# core/pipeline.py
import pandas as pd
import math
from pathlib import Path

from core.signals.validation import compute_validation_signals
from core.signals.risk import compute_risk_signals

from core.signals.whale import (
    standardize_columns,
    compute_concentration,
    calc_breadth,
    compute_foreign_local_net,
    build_top15_tables,
    build_breadth_series,
    compute_master_trend,
)
from core.io.price_data import fetch_ohlcv_20d, fetch_price_nd
from core.signals.tv import compute_tv_radar_signals
from core.signals.regime import compute_regime_signals

from core.config import PipelineConfig
from core.aggregate import compute_final_pack
from core.types import Insight
from core.signals.geo import compute_geo_signals, load_company_geo_map as _load_company_geo_map
from core.signals.enhanced import compute_enhanced_signals
from core.signals.distribution import compute_distribution_risk
from core.signals.monitor import compute_monitor_state
from core.signals.whale_extras import compute_turning_points, compute_whale_radar
from core.broker_archetype import apply_broker_archetype
from core.signals.institutional import compute_institutional_and_margin_signals
from core.top6_history import enrich_top6_phase7, update_top6_history
from core.phase8_anomaly import enrich_phase8


# --- Phase 0：whale_layers + headline（藍圖 V1）--------------------------------

TIER3_HEAVY_LOT_THRESHOLD = 500.0
INST_FLOW_LOT_EPS = 50.0


def _daily_net_from_cumulative(cumulative: list) -> list[float]:
    if not cumulative:
        return []
    out = [round(float(cumulative[0]), 1)]
    for i in range(1, len(cumulative)):
        out.append(round(float(cumulative[i]) - float(cumulative[i - 1]), 1))
    return out


def _enrich_top6_daily_net_series(
    top6_details: list[dict], whale_data: list[dict]
) -> None:
    """從 whale_data 累積軌跡差分，寫入 top6_details.daily_net_series。"""
    by_name: dict[str, list] = {}
    by_id: dict[str, list] = {}
    for w in whale_data:
        vals = w.get("values")
        if not vals:
            continue
        name = str(w.get("name", "")).strip()
        bid = str(w.get("broker_id", "")).strip()
        if name:
            by_name[name] = vals
        if bid:
            by_id[bid] = vals

    name_to_id = {
        str(d.get("broker_name", "")).strip(): str(d.get("broker_id", "")).strip()
        for d in top6_details
        if d.get("broker_name") and d.get("broker_id")
    }
    for w in whale_data:
        if w.get("broker_id"):
            continue
        name = str(w.get("name", "")).strip()
        bid = name_to_id.get(name)
        if bid:
            w["broker_id"] = bid

    for broker in top6_details:
        bid = str(broker.get("broker_id", "")).strip()
        bname = str(broker.get("broker_name", "")).strip()
        cumulative = by_id.get(bid) or by_name.get(bname)
        broker["daily_net_series"] = (
            _daily_net_from_cumulative(cumulative) if cumulative else []
        )


def _sign_flow_lot(v: float, eps: float = INST_FLOW_LOT_EPS) -> int:
    if v > eps:
        return 1
    if v < -eps:
        return -1
    return 0


def _compute_chip_arbitration(signals: dict, whale_layers: dict) -> dict:
    """三大法人（股→千張）vs Top6 分點大戶，統一矛盾解讀。"""
    inst_lot = round(float(signals.get("inst_three_net_5d", 0) or 0) / 1000.0, 1)
    s1 = whale_layers.get("tier1_institutional", {}).get("layer_summary", {}) or {}
    s2 = whale_layers.get("tier2_local_major", {}).get("layer_summary", {}) or {}
    t1 = float(s1.get("total_net_5d", 0) or 0)
    t2 = float(s2.get("total_net_5d", 0) or 0)
    top6_net = round(t1 + t2, 1)

    sig_inst = _sign_flow_lot(inst_lot)
    sig_top6 = _sign_flow_lot(top6_net)
    sig_t2 = _sign_flow_lot(t2)
    conflict = sig_inst != 0 and sig_top6 != 0 and sig_inst != sig_top6

    mag = min(abs(inst_lot), abs(top6_net)) if conflict else 0.0
    max_mag = max(abs(inst_lot), abs(top6_net))

    if not conflict:
        level = "ALIGNED"
        index = max(0, int(12 - min(12.0, abs(inst_lot - top6_net) / 80.0)))
        verdict = "三大法人與分點大戶五日方向大致一致，籌碼歸屬較清楚。"
    elif max_mag < 300.0:
        level = "MILD"
        index = 35 + int(min(25.0, mag / 12.0))
        verdict = "法人與分點方向略有分歧，宜觀察哪一邊量能延續。"
    else:
        level = "HIGH"
        index = min(
            100,
            55 + int(min(45.0, mag / 18.0 + max_mag / 45.0)),
        )
        verdict = (
            "三大法人 vs 分點大戶方向相反，籌碼歸屬不明，風險偏高；"
            "不宜單邊重押，以觀望或減碼為宜。"
        )

    detail = (
        f"三大法人 5日約 {inst_lot:+.0f} 千張；"
        f"Top6 外資 {t1:+.0f}、本土 {t2:+.0f} 千張（合計 {top6_net:+.0f}）"
    )
    trust_hint = ""
    if level == "HIGH":
        if sig_inst < 0 and sig_t2 > 0:
            trust_hint = "法人持續賣超、本土 Top6 接盤：中長期宜偏法人；短線勿假設本土能永遠撐盤。"
        elif sig_inst > 0 and sig_t2 < 0:
            trust_hint = "法人買、分點賣：留意分點倒貨是否抵銷法人買盤。"
        else:
            trust_hint = "方向矛盾時，優先參考三大法人＋借券／融資旗標，勿只看單一分層。"

    return {
        "inst_three_net_5d_lot": inst_lot,
        "top6_net_5d_lot": top6_net,
        "tier1_net_5d_lot": round(t1, 1),
        "tier2_net_5d_lot": round(t2, 1),
        "conflict_level": level,
        "conflict_index": index,
        "verdict": verdict,
        "detail": detail,
        "trust_hint": trust_hint,
    }


def _confidence_hint_text(
    confidence: int,
    arbitration: dict,
    diverge_fb: bool,
    signals: dict,
) -> str:
    mon = str(signals.get("monitor_state", "") or "").upper()
    parts: list[str] = []
    if confidence < 45:
        parts.append("信心偏低：多項訊號相互矛盾，不宜重押或追高。")
    if arbitration.get("conflict_level") == "HIGH":
        parts.append(str(arbitration.get("verdict") or ""))
    elif arbitration.get("conflict_level") == "MILD" and confidence < 55:
        parts.append("法人與分點略有分歧，決策宜保守。")
    if diverge_fb:
        parts.append("外資／本土 Top6 五日方向亦相反，訊號抵觸。")
    if mon == "FADING":
        parts.append("Monitor FADING：主力群聚走弱，分數單日快照需搭配走勢圖判斷。")
    elif mon == "DISTRIBUTION":
        parts.append("Monitor DISTRIBUTION：留意倒貨，勿逆勢加碼。")
    elif mon in ("ACCUMULATION", "MARKUP") and confidence >= 58:
        parts.append("監控偏多頭階段，但仍需停損紀律。")
    if not parts:
        if confidence >= 60:
            return "信心尚可：多數訊號同向，維持標準風控即可。"
        return "信心中等：維持標準部位與停損，勿因單日分數過度加碼。"
    return " ".join(p for p in parts if p)


def _tier3_heavy_alerts(members: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in members:
        n5 = float(m.get("net_5d_lot", 0) or 0)
        if abs(n5) < TIER3_HEAVY_LOT_THRESHOLD:
            continue
        out.append(
            {
                "name": m.get("name", ""),
                "net_5d_lot": round(n5, 1),
                "side": "SELL" if n5 < 0 else "BUY",
            }
        )
    out.sort(key=lambda x: abs(float(x.get("net_5d_lot", 0) or 0)), reverse=True)
    return out


def _classify_whale_behavior(n1: float, n5: float, sb: int, ss: int) -> str:
    """ACCUMULATING / REDUCING / HOLDING / FLIPPING"""
    eps = 1e-6
    if (n1 > eps and n5 < -eps) or (n1 < -eps and n5 > eps):
        if abs(n5) > eps and abs(n1) < abs(n5) * 0.10:
            return "HOLDING"
        return "FLIPPING"
    if n5 > eps:
        if sb >= 3 or n1 >= -eps:
            return "ACCUMULATING"
        return "HOLDING"
    if n5 < -eps:
        if ss >= 3 or n1 <= eps:
            return "REDUCING"
        return "HOLDING"
    if abs(n1) > eps and ((n1 > 0 and ss >= 1) or (n1 < 0 and sb >= 1)):
        if abs(n5) > eps and abs(n1) < abs(n5) * 0.10:
            return "HOLDING"
        return "FLIPPING"
    return "HOLDING"


def _position_vs_price(avg_cost: float, close_last: float | None) -> str:
    if close_last is None or avg_cost <= 0 or close_last <= 0:
        return ""
    pct = (close_last - avg_cost) / avg_cost * 100.0
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _is_tier3_day_style(m: dict) -> bool:
    """短線／隔日沖風格：一日與五日淨額反向，且一日翻轉相對五日夠大。"""
    n1 = float(m.get("net_1d_lot", m.get("net_1d", 0)) or 0)
    n5 = float(m.get("net_5d_lot", m.get("net_5d", 0)) or 0)
    if n1 * n5 >= 0:
        return False
    if abs(n1) < 50.0:
        return False
    if abs(n5) > 0 and abs(n1) / abs(n5) < 0.20:
        return False
    return True


def _layer_consensus(members: list[dict]) -> tuple[str, str]:
    """(consensus, direction) direction: BUY / SELL / NEUTRAL"""
    if not members:
        return "UNKNOWN", "NEUTRAL"
    nets = [float(m.get("net_5d_lot", 0) or 0) for m in members]
    pos_c = sum(1 for x in nets if x > 0)
    neg_c = sum(1 for x in nets if x < 0)
    total = sum(nets)
    n = len(members)
    if pos_c == n and neg_c == 0:
        cons = "STRONG_BUY"
    elif neg_c == n and pos_c == 0:
        cons = "STRONG_SELL"
    elif total > 0:
        cons = "WEAK_BUY" if neg_c else "STRONG_BUY"
    elif total < 0:
        cons = "WEAK_SELL" if pos_c else "STRONG_SELL"
    else:
        cons = "MIXED"
    direction = "BUY" if total > 0 else ("SELL" if total < 0 else "NEUTRAL")
    return cons, direction


def _cost_range_from_members(members: list[dict]) -> list[float] | None:
    costs = [float(m["avg_cost"]) for m in members if m.get("avg_cost")]
    if not costs:
        return None
    return [round(min(costs), 2), round(max(costs), 2)]


def _build_whale_layers_phase0(top6_details: list[dict], signals: dict) -> dict:
    enh = signals.get("enhanced") or {}
    close_last: float | None
    try:
        cl = enh.get("close_last")
        close_last = float(cl) if cl is not None else None
    except Exception:
        close_last = None

    enriched: list[dict] = []
    for row in top6_details:
        n5 = float(row.get("net_5d", 0) or 0)
        n1 = float(row.get("net_1d", 0) or 0)
        sb = int(row.get("streak_buy", 0) or 0)
        ss = int(row.get("streak_sell", 0) or 0)
        avg_c = float(row.get("avg_price", 0) or 0)
        org = str(row.get("broker_org_type", "unknown") or "unknown").lower()
        if org not in ("foreign", "local"):
            org = "unknown"
        m = {
            "name": str(row.get("broker_name", "") or ""),
            "broker_id": str(row.get("broker_id", "") or ""),
            "type": org,
            "net_5d_lot": round(n5, 1),
            "net_1d_lot": round(n1, 1),
            "avg_cost": round(avg_c, 2) if avg_c > 0 else None,
            "streak_buy": sb,
            "streak_sell": ss,
            "position_vs_price": _position_vs_price(avg_c, close_last),
            "behavior": _classify_whale_behavior(n1, n5, sb, ss),
        }
        enriched.append(m)

    tier3_ids: set[str] = set()
    for m in enriched:
        if _is_tier3_day_style(m):
            tier3_ids.add(m["broker_id"])

    tier3_members = [m for m in enriched if m["broker_id"] in tier3_ids]
    tier1_members = [m for m in enriched if m["type"] == "foreign" and m["broker_id"] not in tier3_ids]
    tier2_members = [m for m in enriched if m["type"] == "local" and m["broker_id"] not in tier3_ids]
    unk = [m for m in enriched if m["type"] == "unknown" and m["broker_id"] not in tier3_ids]
    tier2_members.extend(unk)

    c1, d1 = _layer_consensus(tier1_members)
    c2, d2 = _layer_consensus(tier2_members)
    rng1 = _cost_range_from_members(tier1_members)
    rng2 = _cost_range_from_members(tier2_members)

    tier3_heavy = _tier3_heavy_alerts(tier3_members)
    if tier3_heavy:
        h0 = tier3_heavy[0]
        n5v = float(h0["net_5d_lot"])
        side_zh = "賣超" if n5v < 0 else "買超"
        tier3_alert = (
            f"⚠ 隔日沖大戶 {h0['name']} 五日淨{side_zh}{abs(n5v):.0f}張"
            f"（≥{TIER3_HEAVY_LOT_THRESHOLD:.0f}張），影響力可能大於外資法人層"
        )
    elif not tier3_members:
        tier3_alert = "未偵測到隔日沖大戶介入"
    else:
        tier3_alert = (
            f"偵測到 {len(tier3_members)} 家分點呈短線翻向特徵，宜搭配量能觀察"
        )

    return {
        "tier1_institutional": {
            "label": "外資法人",
            "members": tier1_members,
            "layer_summary": {
                "total_net_5d": round(sum(float(x.get("net_5d_lot", 0) or 0) for x in tier1_members), 1),
                "direction": d1,
                "avg_cost_range": rng1,
                "consensus": c1,
            },
        },
        "tier2_local_major": {
            "label": "本土主力",
            "members": tier2_members,
            "layer_summary": {
                "total_net_5d": round(sum(float(x.get("net_5d_lot", 0) or 0) for x in tier2_members), 1),
                "direction": d2,
                "avg_cost_range": rng2,
                "consensus": c2,
            },
        },
        "tier3_day_trader": {
            "label": "短線／隔日沖",
            "members": tier3_members,
            "alert": tier3_alert,
            "heavy_alerts": tier3_heavy,
        },
    }


def _derive_action_signal_phase0(
    signals: dict, diverge_fb: bool, whale_layers: dict
) -> str:
    """BUY_ZONE / HOLD_WATCH / EXIT_ALERT / NEUTRAL。EXIT 需配合籌碼面：Top6 外資+本土五日皆買時不因 chip 單獨過低判逃。"""
    grade = str(signals.get("final_grade", "C") or "C").upper()
    try:
        chip = float(signals.get("chip_score", 50) or 50)
    except Exception:
        chip = 50.0
    mon = str(signals.get("monitor_state", "NEUTRAL") or "NEUTRAL").upper()
    trend = str(signals.get("trend", "") or "")

    s1 = whale_layers.get("tier1_institutional", {}).get("layer_summary", {}) or {}
    s2 = whale_layers.get("tier2_local_major", {}).get("layer_summary", {}) or {}
    t1n = float(s1.get("total_net_5d", 0) or 0)
    t2n = float(s2.get("total_net_5d", 0) or 0)
    top6_both_buying = t1n > 0 and t2n > 0

    if mon == "DISTRIBUTION" or grade == "D" or "偏空" in trend:
        return "EXIT_ALERT"
    if chip < 38.0 and not top6_both_buying:
        return "EXIT_ALERT"
    if grade in ("A", "B") and chip >= 58.0 and (not diverge_fb) and mon in (
        "ACCUMULATION",
        "MARKUP",
        "NEUTRAL",
    ):
        return "BUY_ZONE"
    if diverge_fb or grade == "C" or (45.0 <= chip < 58.0):
        return "HOLD_WATCH"
    return "NEUTRAL"


def _dir_zh(code: str) -> str:
    return {"BUY": "買超", "SELL": "賣超", "NEUTRAL": "持平"}.get(
        str(code or "").upper(), str(code or "")
    )


def _any_member_position_vs_price(whale_layers: dict) -> bool:
    for tier in ("tier1_institutional", "tier2_local_major", "tier3_day_trader"):
        for m in (whale_layers.get(tier) or {}).get("members") or []:
            if m.get("position_vs_price"):
                return True
    return False


def _build_headline_phase0(
    stock_id: str,
    whale_layers: dict,
    signals: dict,
) -> dict:
    enh = signals.get("enhanced") or {}
    c_low = enh.get("cost_low")
    c_high = enh.get("cost_high")
    close_l = enh.get("close_last")

    f5 = float(signals.get("foreign_net_5d", 0) or 0)
    l5 = float(signals.get("local_net_5d", 0) or 0)
    diverge_fb = (f5 > 0 and l5 < 0) or (f5 < 0 and l5 > 0)

    t1 = whale_layers["tier1_institutional"]["members"]
    s1 = whale_layers["tier1_institutional"]["layer_summary"]
    t2 = whale_layers["tier2_local_major"]["members"]
    s2 = whale_layers["tier2_local_major"]["layer_summary"]

    d1 = _dir_zh(str(s1.get("direction", "") or ""))
    d2 = _dir_zh(str(s2.get("direction", "") or ""))

    parts: list[str] = []
    if t1:
        lead = "、".join(m["name"] for m in t1[:4])
        if len(t1) > 4:
            lead += f"等{len(t1)}家"
        parts.append(
            f"外資主力共{len(t1)}家（{lead}），五日淨{d1}約{float(s1.get('total_net_5d', 0) or 0):.0f}張"
        )
    else:
        parts.append("外資主力在 Top6 中不明顯")

    if t2:
        parts.append(
            f"本土分點共{len(t2)}家，五日淨{d2}約{float(s2.get('total_net_5d', 0) or 0):.0f}張"
        )

    if (
        c_low is not None
        and c_high is not None
        and close_l is not None
        and _any_member_position_vs_price(whale_layers)
    ):
        try:
            parts.append(
                f"估算大戶成本區 {float(c_low):.0f}~{float(c_high):.0f}，現價 {float(close_l):.0f}"
            )
        except Exception:
            pass

    if diverge_fb:
        parts.append("外資與本土五日方向分歧")

    summary = "；".join(parts) if parts else f"{stock_id} 籌碼摘要資料不足"

    action = _derive_action_signal_phase0(signals, diverge_fb, whale_layers)
    try:
        confidence = int(round(float(signals.get("chip_score", signals.get("final_score", 50) or 50))))
    except Exception:
        confidence = 50
    confidence = max(0, min(100, confidence))

    key_events: list[str] = []
    for m in sorted(t1, key=lambda x: float(x.get("net_5d_lot", 0) or 0), reverse=True)[:3]:
        nm = m.get("name", "")
        nb = float(m.get("net_5d_lot", 0) or 0)
        sb = int(m.get("streak_buy", 0) or 0)
        if nm and nb > 0 and sb >= 2:
            key_events.append(f"{nm} 連買{sb}天，五日累積+{nb:.0f}張")
        elif nm and abs(nb) >= 30:
            key_events.append(f"{nm} 五日淨額 {nb:+.0f} 張")

    if diverge_fb:
        key_events.append("外資／本土五日淨額方向相反")

    arbitration = _compute_chip_arbitration(signals, whale_layers)
    if arbitration.get("conflict_level") == "HIGH":
        key_events.insert(
            0,
            f"法人矛盾指數 {arbitration.get('conflict_index', 0)}：{arbitration.get('verdict', '')}",
        )
    for ha in (whale_layers.get("tier3_day_trader") or {}).get("heavy_alerts") or []:
        side_zh = "賣超" if str(ha.get("side", "")).upper() == "SELL" else "買超"
        key_events.append(
            f"隔日沖大戶 {ha.get('name', '')} 五日淨{side_zh}{abs(float(ha.get('net_5d_lot', 0) or 0)):.0f}張（重倉警示）"
        )

    if (
        c_low is not None
        and c_high is not None
        and close_l is not None
        and _any_member_position_vs_price(whale_layers)
    ):
        try:
            mid = (float(c_low) + float(c_high)) / 2.0
            if mid > 0:
                dev = (float(close_l) - mid) / mid * 100.0
                key_events.append(f"現價相對大戶成本中位 {dev:+.1f}%")
        except Exception:
            pass

    tags = signals.get("tags") or []
    if isinstance(tags, list):
        for t in tags[:2]:
            if isinstance(t, str) and t and t not in key_events:
                key_events.append(t)

    confidence_hint = _confidence_hint_text(confidence, arbitration, diverge_fb, signals)

    return {
        "summary": summary,
        "action_signal": action,
        "confidence": confidence,
        "confidence_hint": confidence_hint,
        "chip_arbitration": arbitration,
        "key_events": key_events[:8],
    }


# -----------------------------------------------------------------------------
def analyze_whale_trajectory(
    frames: list[pd.DataFrame],
    target_dates: list[str],
    broker_map: dict,
    adapter,
    stock_id: str,
    debug_tv: bool = False,
    cfg: PipelineConfig | None = None,
) -> tuple[Insight | None, pd.DataFrame | None]:
    """
    - Top6 軌跡（10日）
    - signals（20日 + 5日 + 廣度序列 + TV radar + Regime + Final aggregation）
    """
    cfg = cfg or PipelineConfig()

    if not frames:
        return None, None

    combined = pd.concat(frames, ignore_index=True)
    combined = standardize_columns(combined)
    if combined.empty:
        return None, None

    combined["date"] = combined["date"].astype(str)

    # 補上 org 欄位：讓 df_1d 可以用 org 分外資/本土
    combined["broker_id"] = combined["broker_id"].astype(str).str.strip()
    combined["org"] = combined["broker_id"].map(
        lambda x: (broker_map.get(x, {}).get("broker_org_type", "unknown") or "unknown")
    )

    date_20d = list(target_dates)
    date_10d = date_20d[-10:] if len(date_20d) >= 10 else date_20d
    date_5d = date_20d[-5:] if len(date_20d) >= 5 else date_20d
    last_1d = date_20d[-1]

    df_20d = combined[combined["date"].isin(date_20d)].copy()
    df_10d = combined[combined["date"].isin(date_10d)].copy()
    df_5d = combined[combined["date"].isin(date_5d)].copy()
    df_1d = combined[combined["date"] == last_1d].copy()

    # Top6（10日用 net 買方）
    agg_10d = df_10d.groupby(["broker_id", "broker_name"], as_index=False).agg(
        buy=("buy", "sum"),
        sell=("sell", "sum"),
        net_buy=("net", "sum"),
    )
    top6 = agg_10d.sort_values("net_buy", ascending=False).head(6).copy()
    top6_ids = top6["broker_id"].astype(str).tolist()

    # 讓 Top6 也有 streak
    from core.signals_whale import compute_streaks

    pivot10 = (
        df_10d.pivot_table(index="date", columns="broker_id", values="net", aggfunc="sum")
        .fillna(0)
        .reindex(date_10d)
        .fillna(0)
    )
    streaks10 = compute_streaks(pivot10)

    # Top6 details
    has_price = "price" in combined.columns
    top6_details: list[dict] = []

    # 先做一次清洗，避免型別/空白造成對不到
    combined["broker_id"] = combined["broker_id"].astype(str).str.strip()

    # 確保 streaks10 一定是 dict（避免 None / 其他型別）
    if not isinstance(streaks10, dict):
        streaks10 = {}

    for _, r in top6.iterrows():
        bid = str(r.get("broker_id", "")).strip()
        if not bid:
            continue

        bname = str(r.get("broker_name", "")).strip()

        # streaks（用 bid 查）
        st = streaks10.get(bid, {}) or {}
        sb = int(st.get("streak_buy", 0) or 0)
        ss = int(st.get("streak_sell", 0) or 0)

        bdata = combined[combined["broker_id"] == bid]

        n10d = float(r.get("net_buy", 0) or 0) / 1000.0
        n5d = float(bdata[bdata["date"].isin(date_5d)]["net"].sum()) / 1000.0
        n1d = float(bdata[bdata["date"] == last_1d]["net"].sum()) / 1000.0

        avg_p = 0.0
        if has_price and not bdata.empty:
            buy_only = bdata[bdata["buy"] > 0]
            if not buy_only.empty and float(buy_only["buy"].sum()) > 0:
                avg_p = float((buy_only["buy"] * buy_only["price"]).sum() / buy_only["buy"].sum())

        meta = broker_map.get(bid, {}) or {}

        top6_details.append(
            {
                "broker_id": bid,
                "broker_name": bname,
                "net_10d": round(n10d, 1),
                "net_5d": round(n5d, 1),
                "net_1d": round(n1d, 1),
                "avg_price": round(avg_p, 2),
                "city": meta.get("city", "") or "",
                "broker_org_type": meta.get("broker_org_type", "unknown") or "unknown",
                "is_proprietary": meta.get("is_proprietary", "") or "",
                "seat_type": meta.get("seat_type", "") or "",
                "streak_buy": sb,
                "streak_sell": ss,
            }
        )

    # 套用 Broker archetype，補上 archetype_wave_score / archetype_label 等欄位
    archetype_pack = apply_broker_archetype(top6_details)
    top6_details = archetype_pack.get("top6_details", top6_details)

    # Top6 軌跡矩陣（累積 net）
    whale_detail = df_10d[df_10d["broker_id"].isin(top6_ids)].copy()
    pivot_net = whale_detail.pivot_table(index="date", columns="broker_name", values="net", aggfunc="sum").fillna(0)
    pivot_cumsum = pivot_net.reindex(date_10d).fillna(0).cumsum()

    colors = ["#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF", "#FF9F40"]
    name_to_id = {
        str(d.get("broker_name", "")).strip(): str(d.get("broker_id", "")).strip()
        for d in top6_details
        if d.get("broker_name") and d.get("broker_id")
    }
    whale_data = []
    for i, name in enumerate(pivot_cumsum.columns):
        col_name = str(name).strip()
        entry: dict = {
            "name": col_name,
            "values": (pivot_cumsum[name] / 1000.0).round(1).tolist(),
            "color": colors[i % len(colors)],
        }
        if col_name in name_to_id:
            entry["broker_id"] = name_to_id[col_name]
        whale_data.append(entry)
    total_whale_values = (pivot_cumsum.sum(axis=1) / 1000.0).round(1).tolist()
    _enrich_top6_daily_net_series(top6_details, whale_data)

    # signals（短期）
    c20 = compute_concentration(df_20d, top_n=15)
    c5 = compute_concentration(df_5d, top_n=15)

    net_1d_lot = round(float(combined[combined["date"] == last_1d]["net"].sum()) / 1000.0, 1)
    net_5d_lot = round(float(df_5d["net"].sum()) / 1000.0, 1)
    net_20d_lot = round(float(df_20d["net"].sum()) / 1000.0, 1)

    b20 = calc_breadth(df_20d)
    b5 = calc_breadth(df_5d)

    fl5 = compute_foreign_local_net(df_5d, broker_map)
    top15_pack = build_top15_tables(df_20d, broker_map, date_20d)
    breadth_series_pack = build_breadth_series(df_20d, date_20d)

    signals: dict = {
        "concentration_5d": c5,
        "concentration_20d": c20,
        "netbuy_1d_lot": net_1d_lot,
        "netbuy_5d_lot": net_5d_lot,
        "netbuy_20d_lot": net_20d_lot,
        "buy_count_5d": b5["buy_count"],
        "sell_count_5d": b5["sell_count"],
        "breadth_5d": b5["breadth"],
        "breadth_ratio_5d": b5["breadth_ratio"],
        "buy_count_20d": b20["buy_count"],
        "sell_count_20d": b20["sell_count"],
        "breadth_20d": b20["breadth"],
        "breadth_ratio_20d": b20["breadth_ratio"],
        "foreign_net_5d": fl5["foreign_net"],
        "local_net_5d": fl5["local_net"],
        "top_buy_15": top15_pack["top_buy_15"],
        "top_sell_15": top15_pack["top_sell_15"],
        **breadth_series_pack,
    }

    # 三大法人 + 融資 cross-check（使用 FinMind 原始資料）
    try:
        inst_margin_pack = compute_institutional_and_margin_signals(
            adapter.client,  # type: ignore[attr-defined]
            stock_id=stock_id,
            last_trade_date=last_1d,
        )
        signals.update(inst_margin_pack)
    except Exception as e:
        # DEBUG：暫時印出錯誤原因，方便查為何 inst_* / sbl_* 沒有寫進 signals
        print(f"⚠ inst/margin signals failed for {stock_id} on {last_1d}: {e!r}")

    # 將 broker archetype 的彙總指標灌入 signals
    signals.update(archetype_pack.get("signals", {}))

    # === A. ΔMajorFlow20：20日買方 Top15 張數 - 賣方 Top15 張數 ===
    buy_sum_20 = 0.0
    sell_sum_20 = 0.0

    if "top_buy_15" in top15_pack and top15_pack["top_buy_15"]:
        buy_sum_20 = sum([float(r["net_lot"]) for r in top15_pack["top_buy_15"]])

    if "top_sell_15" in top15_pack and top15_pack["top_sell_15"]:
        sell_sum_20 = sum([abs(float(r["net_lot"])) for r in top15_pack["top_sell_15"]])

    delta_major_flow_20 = round(buy_sum_20 - sell_sum_20, 1)

    signals["delta_major_flow_20"] = delta_major_flow_20
    signals["top15_buy_sum_20"] = round(buy_sum_20, 1)
    signals["top15_sell_sum_20"] = round(sell_sum_20, 1)

    # === A2. ΔMajorFlow5：5日買方 Top15 - 賣方 Top15 ===
    top15_5 = build_top15_tables(df_5d, broker_map, date_5d)

    buy_sum_5 = 0.0
    sell_sum_5 = 0.0

    if top15_5.get("top_buy_15"):
        buy_sum_5 = sum(float(r.get("net_lot", 0) or 0) for r in top15_5["top_buy_15"])

    if top15_5.get("top_sell_15"):
        sell_sum_5 = sum(abs(float(r.get("net_lot", 0) or 0)) for r in top15_5["top_sell_15"])

    delta_major_flow_5 = round(buy_sum_5 - sell_sum_5, 1)

    signals["delta_major_flow_5"] = delta_major_flow_5
    signals["top15_buy_sum_5"] = round(buy_sum_5, 1)
    signals["top15_sell_sum_5"] = round(sell_sum_5, 1)

    # ---- 壓力比 ----
    def _safe_float(x, default=0.0):
        try:
            return float(x)
        except Exception:
            return default

    buy_sum_20 = _safe_float(signals.get("top15_buy_sum_20", 0.0), 0.0)
    sell_sum_20 = _safe_float(signals.get("top15_sell_sum_20", 0.0), 0.0)
    denom_20 = (buy_sum_20 + sell_sum_20) if (buy_sum_20 + sell_sum_20) > 0 else 0.0
    signals["pressure_ratio_20d"] = round((buy_sum_20 / denom_20), 4) if denom_20 > 0 else None
    signals["net_pressure_20d"] = round(((buy_sum_20 - sell_sum_20) / denom_20), 4) if denom_20 > 0 else None

    buy_sum_5 = _safe_float(signals.get("top15_buy_sum_5", 0.0), 0.0)
    sell_sum_5 = _safe_float(signals.get("top15_sell_sum_5", 0.0), 0.0)
    denom_5 = (buy_sum_5 + sell_sum_5) if (buy_sum_5 + sell_sum_5) > 0 else 0.0
    signals["pressure_ratio_5d"] = round((buy_sum_5 / denom_5), 4) if denom_5 > 0 else None
    signals["net_pressure_5d"] = round(((buy_sum_5 - sell_sum_5) / denom_5), 4) if denom_5 > 0 else None

    # ---- 名單穩定度（Jaccard）----
    def _topn_buy_set_by_day(df, day, top_n=15):
        try:
            dd = df[df["date"] == day].copy()
            if dd.empty:
                return set()
            g = dd.groupby("broker_id", as_index=False)["net"].sum()
            g["net"] = pd.to_numeric(g["net"], errors="coerce").fillna(0.0)
            g = g[g["net"] > 0].sort_values("net", ascending=False).head(top_n)
            return set(g["broker_id"].astype(str).tolist())
        except Exception:
            return set()

    def _jaccard(a: set, b: set):
        if not a and not b:
            return None
        u = a.union(b)
        if not u:
            return None
        return len(a.intersection(b)) / len(u)

    try:
        sets_20 = [_topn_buy_set_by_day(df_20d, d, top_n=15) for d in date_20d]
        jac_20 = []
        for i in range(1, len(sets_20)):
            v = _jaccard(sets_20[i - 1], sets_20[i])
            if v is not None:
                jac_20.append(v)
        signals["top15_buy_stability_20d"] = round(float(sum(jac_20) / len(jac_20)), 4) if jac_20 else None

        date_10 = date_20d[-10:] if len(date_20d) >= 10 else date_20d[:]
        sets_10 = [_topn_buy_set_by_day(df_20d, d, top_n=15) for d in date_10]
        jac_10 = []
        for i in range(1, len(sets_10)):
            v = _jaccard(sets_10[i - 1], sets_10[i])
            if v is not None:
                jac_10.append(v)
        signals["top15_buy_stability_10d"] = round(float(sum(jac_10) / len(jac_10)), 4) if jac_10 else None

        sizes_10 = [len(s) for s in sets_10 if s is not None]
        signals["top15_buy_avg_size_10d"] = round(float(sum(sizes_10) / len(sizes_10)), 2) if sizes_10 else None

    except Exception:
        signals["top15_buy_stability_20d"] = None
        signals["top15_buy_stability_10d"] = None
        signals["top15_buy_avg_size_10d"] = None

    # ----------------------------------------------------------
    # TV Radar（短期價格行為）
    ohlcv_20d = fetch_ohlcv_20d(adapter, stock_id, date_20d, debug=debug_tv)
    price_df = ohlcv_20d if ohlcv_20d is not None else pd.DataFrame()
    price_df_tail = price_df

    # === B. 主力拐點偵測 Turning Points ===
    tp = compute_turning_points(
        df_20d=df_20d,
        df_1d=df_1d,
        fl5=fl5,
        top6_ids=top6_ids,
        top6_details=top6_details,
        date_20d=date_20d,
        last_1d=last_1d,
        price_df_tail=price_df_tail,
    )
    signals["turning_points"] = tp

    # ----------------------------------------------------------
    # Whale Radar (0~100)
    signals["whale_radar"] = compute_whale_radar(signals, debug=debug_tv)

    # ----------------------------------------------------------
    # Enhanced (single source of truth) - coherence + cost zone + stats + streak
    signals = compute_enhanced_signals(
        signals=signals,
        df_20d=df_20d,
        df_5d=df_5d,
        date_20d=date_20d,
        top6_details=top6_details,
        top6_ids=top6_ids,
        ohlcv_20d=ohlcv_20d,
    )

    # ----------------------------------------------------------
    # Regime（中期趨勢底座）
    price_250d = fetch_price_nd(adapter, stock_id, lookback_days=int(cfg.regime.lookback_days))
    regime_pack = compute_regime_signals(price_250d)
    signals.update(regime_pack)

    if debug_tv:
        print("OHLCV rows=", 0 if ohlcv_20d is None else len(ohlcv_20d))
        print("OHLCV cols=", [] if ohlcv_20d is None else list(ohlcv_20d.columns))
        print("OHLCV tail=\n", ohlcv_20d.tail(3) if ohlcv_20d is not None and not ohlcv_20d.empty else None)

    tv_pack = compute_tv_radar_signals(ohlcv_20d, debug=debug_tv)
    if debug_tv:
        print("TV_PACK=", tv_pack)

    signals.update(tv_pack)

    # 最後算主力走向（一次）
    trend_pack = compute_master_trend(signals)
    signals["trend_score"] = float(trend_pack.get("score", 0) or 0)
    signals["trend"] = trend_pack.get("trend", "")
    signals["tags"] = trend_pack.get("tags", [])
    signals["score"] = signals["trend_score"]
    signals["score_unified"] = signals["trend_score"]

    # -------------------------
    # Validation / Risk (MVP) - 使用專用模組
    validation = compute_validation_signals(price_df=ohlcv_20d, signals=signals, cfg=cfg)
    risk = compute_risk_signals(price_df=ohlcv_20d, signals=signals, cfg=cfg)

    signals["validation"] = validation
    signals["risk"] = risk

    signals["breakout_flag"] = validation["breakout_flag"]
    signals["divergence_flag"] = validation["divergence_flag"]
    signals["confirmation_score"] = validation["confirmation_score"]
    signals["atr_pct_20d"] = risk["atr_pct_20d"]
    signals["avg_turnover_20d"] = risk["avg_turnover_20d"]
    signals["invalid_flag"] = risk["invalid_flag"]

    # -------------------------
    # Geo: 分點地緣關聯性（Top5 買超分點 vs 公司總部）
    signals, top6_details = compute_geo_signals(
        signals=signals,
        broker_map=broker_map,
        stock_id=stock_id,
        top6_details=top6_details,
    )

    # -------------------------
    # HHI / Entropy + distribution risk tag
    signals = compute_distribution_risk(signals=signals, df_20d=df_20d)

    # === Whale Trend Monitor (long-term) - 5 states ===
    signals = compute_monitor_state(signals)

    # -------------------------
    signals.update(compute_final_pack(signals, cfg))

    # -------------------------
    # 籌碼總分卡（0-100，跟著大戶走，不含地緣）
    def _safe_float_local(x, default=0.0):
        try:
            if x is None or (isinstance(x, float) and math.isnan(x)):
                return default
            return float(x)
        except Exception:
            return default

    raw_score = _safe_float_local(
        signals.get("score_unified", signals.get("score", 0.0)), 0.0
    )
    # 基礎分：保留原有 Score 的影響，但略放大權重（最高 60 分）
    base_score = max(0.0, min(60.0, raw_score * 0.6))

    monitor_state = str(signals.get("monitor_state", "NEUTRAL") or "NEUTRAL").upper()
    monitor_bonus_map = {
        "ACCUMULATION": 22.0,
        "MARKUP": 18.0,
        "NEUTRAL": 5.0,
        "FADING": 0.0,
        "DISTRIBUTION": -10.0,
    }
    monitor_bonus = monitor_bonus_map.get(monitor_state, 0.0)

    inst_regime = str(signals.get("inst_regime_flag", "OTHER") or "OTHER").upper()
    regime_bonus = 0.0
    if inst_regime == "BULL_NO_SHORT":
        regime_bonus = 12.0
    elif inst_regime == "BEAR_WITH_SHORT":
        regime_bonus = -10.0

    conc20 = _safe_float_local(signals.get("concentration_20d"), 0.0)
    if conc20 >= 30.0:
        conc_bonus = 10.0
    elif conc20 >= 20.0:
        conc_bonus = 7.0
    elif conc20 >= 10.0:
        conc_bonus = 3.0
    else:
        conc_bonus = 0.0

    enh = signals.get("enhanced") or {}
    c_low = _safe_float_local(enh.get("cost_low"), None)
    c_high = _safe_float_local(enh.get("cost_high"), None)
    c_close = _safe_float_local(enh.get("close_last"), None)
    cost_bonus = 0.0
    if c_low is not None and c_high is not None and c_close is not None and c_high > c_low:
        span = c_high - c_low
        pos = (c_close - c_low) / span if span > 0 else 0.0
        if pos < -0.1:
            cost_bonus = -10.0
        elif pos < 0.3:
            cost_bonus = 12.0
        elif pos <= 1.1:
            cost_bonus = 6.0
        elif pos > 1.3:
            cost_bonus = -5.0

    stab20 = signals.get("top15_buy_stability_20d")
    stab_bonus = 0.0
    if stab20 is not None:
        stab20f = _safe_float_local(stab20, 0.0)
        if stab20f >= 0.6:
            stab_bonus = 5.0
        elif stab20f <= 0.3:
            stab_bonus = -5.0

    risk_pack = signals.get("risk") or {}
    atr_pct_20d = risk_pack.get("atr_pct_20d", signals.get("atr_pct_20d"))
    risk_bonus = 0.0
    if atr_pct_20d is not None:
        atrf = _safe_float_local(atr_pct_20d, 0.0)
        if atrf >= 0.10:
            risk_bonus = -5.0
        elif atrf >= 0.07:
            risk_bonus = -3.0

    chip_raw = base_score + monitor_bonus + regime_bonus + conc_bonus + cost_bonus + stab_bonus + risk_bonus
    chip_score = max(0.0, min(100.0, chip_raw))

    # 燈號門檻：以目前市況校正，讓 40~60 分區間視為可觀察帶
    if chip_score >= 60.0:
        chip_light = "green"
        chip_comment = "籌碼明顯偏強，主力環境相對友善，可積極列入主力觀察名單（仍需搭配風險控管）。"
    elif chip_score >= 45.0:
        chip_light = "yellow"
        chip_comment = "籌碼中性偏多，主力並不積極但也沒有明顯倒貨跡象，適合小部位試單或持續關注。"
    else:
        chip_light = "red"
        chip_comment = "目前籌碼較不友善（主力偏保守或資金較分散），建議先當作次要標的或等待型態改善。"

    signals["chip_score"] = round(chip_score, 1)
    signals["chip_light"] = chip_light
    signals["chip_comment"] = chip_comment

    # Phase 7：Top6 駐留／新進大戶歷史 + 集團合併摘要
    trade_date_str = str(last_1d)[:10]
    _data_root = Path(__file__).resolve().parents[1] / "data"
    enrich_top6_phase7(stock_id, top6_details, signals, trade_date_str, _data_root)
    update_top6_history(stock_id, top6_details, trade_date_str, _data_root)

    # Phase 8：異常偵測（爆量、反轉、集團同步、價量背離、大戶佔比、指標 Z-Score）
    enrich_phase8(
        stock_id=stock_id,
        top6_details=top6_details,
        signals=signals,
        df_20d=df_20d,
        df_1d=df_1d,
        date_20d=date_20d,
        ohlcv_20d=ohlcv_20d,
        top6_ids=top6_ids,
        data_dir=_data_root,
    )

    whale_layers = _build_whale_layers_phase0(top6_details, signals)
    headline = _build_headline_phase0(stock_id, whale_layers, signals)
    signals["chip_arbitration"] = headline.get("chip_arbitration") or _compute_chip_arbitration(
        signals, whale_layers
    )

    insight: Insight = {
        "history_labels": [d[5:] for d in date_10d],  # MM-DD
        "whale_data": whale_data,
        "total_whale_values": total_whale_values,
        "top6_details": top6_details,
        "signals": signals,
        "whale_layers": whale_layers,
        "headline": headline,
    }

    boss_list_df = agg_10d.sort_values("net_buy", ascending=False).head(20).reset_index(drop=True)
    boss_list_df.rename(columns={"net_buy": "net"}, inplace=True)
    boss_list_df["net_lot"] = (boss_list_df["net"] / 1000.0).round(1)

    return insight, boss_list_df