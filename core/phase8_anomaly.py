"""
Phase 8：大戶異常偵測（爆量、方向反轉、集團同步、價量背離、大戶成交佔比、指標 Z-Score）。
規格：phase8_anomaly_detection_spec.md
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.broker_groups import get_broker_group
from core.metric_history import append_metric_snapshot, history_records_before_date


def compute_broker_volume_spike(broker_daily_data: list[float], lookback: int = 20) -> float:
    if len(broker_daily_data) < 2:
        return 1.0
    today_vol = abs(float(broker_daily_data[-1]))
    hist = broker_daily_data[:-1][-lookback:]
    if not hist or sum(hist) == 0:
        return 1.0
    avg = sum(hist) / len(hist)
    if avg == 0:
        return 1.0
    return round(today_vol / avg, 2)


def detect_direction_reversal(daily_net_series: list[float]) -> tuple[str | None, float]:
    if len(daily_net_series) < 3:
        return None, 0.0
    today = float(daily_net_series[-1])
    prev_5 = daily_net_series[-6:-1] if len(daily_net_series) >= 6 else daily_net_series[:-1]
    if not prev_5:
        return None, 0.0
    buy_days = sum(1 for x in prev_5 if float(x) > 0)
    sell_days = sum(1 for x in prev_5 if float(x) < 0)
    prev_avg = sum(float(x) for x in prev_5) / len(prev_5)
    pa = abs(prev_avg) if prev_avg != 0 else 1e-9

    if buy_days >= 3 and today < 0 and abs(today) > pa * 1.5:
        return "DUMP_AFTER_BUY", round(today, 1)
    if sell_days >= 3 and today > 0 and abs(today) > pa * 1.5:
        return "SCOOP_AFTER_SELL", round(today, 1)
    return None, 0.0


def detect_group_sync_from_df(df_1d: pd.DataFrame) -> list[dict[str, Any]]:
    """依當日各分點淨額，檢查同一集團是否 ≥2 分點且 ≥2/3 同向。"""
    if df_1d is None or df_1d.empty:
        return []
    sync_alerts: list[dict[str, Any]] = []
    gdf = (
        df_1d.groupby(["broker_id", "broker_name"], as_index=False)["net"]
        .sum()
        .assign(
            broker_id=lambda x: x["broker_id"].astype(str).str.strip(),
            broker_name=lambda x: x["broker_name"].astype(str),
        )
    )
    group_nets: dict[str, list[float]] = {}
    for _, row in gdf.iterrows():
        bid = str(row["broker_id"]).strip()
        net = float(row.get("net", 0) or 0)
        if net == 0:
            continue
        gname = get_broker_group(bid, str(row.get("broker_name") or ""))
        if not gname:
            continue
        group_nets.setdefault(gname, []).append(net)

    for group_name, active in group_nets.items():
        if len(active) < 2:
            continue
        buy_count = sum(1 for x in active if x > 0)
        sell_count = sum(1 for x in active if x < 0)
        total = float(sum(active))
        n = len(active)
        if buy_count >= n * 0.67:
            sync_alerts.append(
                {
                    "group": group_name,
                    "direction": "BUY",
                    "branch_count": buy_count,
                    "total_branches": n,
                    "total_net": round(total, 1),
                }
            )
        elif sell_count >= n * 0.67:
            sync_alerts.append(
                {
                    "group": group_name,
                    "direction": "SELL",
                    "branch_count": sell_count,
                    "total_branches": n,
                    "total_net": round(total, 1),
                }
            )
    return sync_alerts


def detect_price_volume_divergence(
    close_series: list[float],
    top6_net_series: list[float],
    lookback: int = 5,
) -> dict[str, Any] | None:
    if len(close_series) < 2 or len(top6_net_series) < 2:
        return None
    lb = min(lookback, len(close_series), len(top6_net_series))
    if lb < 2:
        return None
    base_i = -lb
    price_chg = float(close_series[-1]) - float(close_series[base_i])
    net_sum = sum(float(x) for x in top6_net_series[-lb:])
    base_close = float(close_series[base_i])
    price_chg_pct = round(price_chg / base_close * 100, 2) if base_close else None

    if price_chg > 0 and net_sum < 0:
        return {
            "type": "PRICE_UP_WHALE_SELL",
            "label": "⚠️ 散戶追漲、大戶出貨",
            "price_chg_pct": price_chg_pct,
            "whale_net_5d": round(net_sum, 1),
        }
    if price_chg < 0 and net_sum > 0:
        return {
            "type": "PRICE_DOWN_WHALE_BUY",
            "label": "🔍 股價下跌、大戶吃貨",
            "price_chg_pct": price_chg_pct,
            "whale_net_5d": round(net_sum, 1),
        }
    return None


def compute_whale_turnover_share(top6_total_volume: float, market_total_volume: float) -> float:
    if not market_total_volume or market_total_volume == 0:
        return 0.0
    return round(float(top6_total_volume) / float(market_total_volume), 4)


def compute_anomaly_flags(
    signals: dict[str, Any],
    enhanced: dict[str, Any],
    history_20d: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    checks: list[tuple[str, Any, str, bool | None]] = [
        ("concentration_5d", signals.get("concentration_5d"), "集中度", True),
        ("pressure_ratio_5d", signals.get("pressure_ratio_5d"), "壓力比", None),
        ("coherence_slope_5d", enhanced.get("coherence_slope_5d"), "凝聚度斜率", None),
        ("top15_buy_stability_10d", signals.get("top15_buy_stability_10d"), "大戶穩定度", False),
    ]

    for key, current, label, _unused_high_is_good in checks:
        hist = []
        for h in history_20d:
            v = h.get(key)
            if v is not None:
                try:
                    hist.append(float(v))
                except (TypeError, ValueError):
                    continue
        if len(hist) < 5 or current is None:
            continue
        try:
            cur = float(current)
        except (TypeError, ValueError):
            continue
        mean = sum(hist) / len(hist)
        var = sum((x - mean) ** 2 for x in hist) / len(hist)
        std = var**0.5
        if std == 0:
            continue
        z = (cur - mean) / std
        if abs(z) >= 2.0:
            direction = "異常偏高" if z > 0 else "異常偏低"
            anomalies.append(
                {
                    "metric": label,
                    "key": key,
                    "current": round(cur, 4),
                    "mean_20d": round(mean, 4),
                    "z_score": round(z, 2),
                    "direction": direction,
                }
            )
    return anomalies


def _broker_abs_daily_volumes(df: pd.DataFrame, broker_id: str, dates: list[str]) -> list[float]:
    bid = str(broker_id).strip()
    out: list[float] = []
    sub = df[(df["broker_id"].astype(str).str.strip() == bid) & (df["date"].isin(dates))]
    for d in dates:
        day = sub[sub["date"] == d]
        if day.empty:
            out.append(0.0)
        else:
            out.append(float(day["buy"].sum()) + float(day["sell"].sum()))
    return out


def _market_volume_lots(ohlcv: pd.DataFrame | None, date_str: str) -> float:
    if ohlcv is None or ohlcv.empty or "volume" not in ohlcv.columns:
        return 0.0
    row = ohlcv[ohlcv["date"].astype(str) == str(date_str)]
    if row.empty:
        return 0.0
    vol = float(row.iloc[-1]["volume"])
    return vol / 1000.0


def _aligned_close_and_top6_net(
    df_20d: pd.DataFrame,
    ohlcv: pd.DataFrame | None,
    date_20d: list[str],
    top6_ids: list[str],
    lookback: int = 5,
) -> tuple[list[float], list[float]]:
    if ohlcv is None or ohlcv.empty:
        return [], []
    dc = {str(r["date"]): float(r["close"]) for _, r in ohlcv.iterrows()}
    dates = date_20d[-lookback:]
    closes: list[float] = []
    nets: list[float] = []
    ids_set = set(str(x).strip() for x in top6_ids)
    for d in dates:
        c = dc.get(str(d))
        if c is None:
            return [], []
        sub = df_20d[(df_20d["date"] == d) & (df_20d["broker_id"].astype(str).str.strip().isin(ids_set))]
        nets.append(float(sub["net"].sum()) if not sub.empty else 0.0)
        closes.append(c)
    return closes, nets


def enrich_phase8(
    stock_id: str,
    top6_details: list[dict[str, Any]],
    signals: dict[str, Any],
    df_20d: pd.DataFrame,
    df_1d: pd.DataFrame,
    date_20d: list[str],
    ohlcv_20d: pd.DataFrame | None,
    top6_ids: list[str],
    data_dir: Path | str,
) -> None:
    """寫入 signals / top6_details；更新 metric_history。"""
    dd = Path(data_dir)
    last_1d = str(date_20d[-1])[:10]

    # --- A1 爆量 ---
    ratios: list[float] = []
    alert_cnt = 0
    for broker in top6_details:
        bid = str(broker.get("broker_id", "")).strip()
        if not bid:
            broker["volume_spike_ratio"] = 1.0
            broker["volume_spike_alert"] = False
            continue
        vols = _broker_abs_daily_volumes(df_20d, bid, date_20d)
        spike = compute_broker_volume_spike(vols, lookback=20)
        broker["volume_spike_ratio"] = spike
        broker["volume_spike_alert"] = spike >= 3.0
        ratios.append(spike)
        if broker["volume_spike_alert"]:
            alert_cnt += 1
    signals["max_broker_spike"] = max(ratios) if ratios else 1.0
    signals["spike_alert_count"] = alert_cnt

    # --- A2 方向反轉 ---
    for broker in top6_details:
        series = broker.get("daily_net_series") or []
        if isinstance(series, list) and series:
            floats = [float(x) for x in series]
        else:
            floats = []
        rev_type, rev_mag = detect_direction_reversal(floats)
        broker["reversal_type"] = rev_type
        broker["reversal_magnitude"] = rev_mag

    # --- A3 集團同步 ---
    signals["group_sync_alerts"] = detect_group_sync_from_df(df_1d)

    # --- A4 價量背離 ---
    closes, nets = _aligned_close_and_top6_net(df_20d, ohlcv_20d, date_20d, top6_ids, lookback=5)
    signals["divergence_detail"] = detect_price_volume_divergence(closes, nets, lookback=5)

    # --- A5 大戶成交佔比 ---
    sub1 = df_1d[df_1d["broker_id"].astype(str).str.strip().isin(set(str(x).strip() for x in top6_ids))]
    top6_vol = float(sub1["buy"].sum()) + float(sub1["sell"].sum()) if not sub1.empty else 0.0
    mkt = _market_volume_lots(ohlcv_20d, last_1d)
    signals["whale_turnover_share"] = compute_whale_turnover_share(top6_vol, mkt)
    shares_5d: list[float] = []
    for d in date_20d[-5:]:
        sd = df_20d[df_20d["date"] == d]
        s6 = sd[sd["broker_id"].astype(str).str.strip().isin(set(str(x).strip() for x in top6_ids))]
        t6v = float(s6["buy"].sum()) + float(s6["sell"].sum()) if not s6.empty else 0.0
        mv = _market_volume_lots(ohlcv_20d, str(d))
        if mv > 0:
            shares_5d.append(compute_whale_turnover_share(t6v, mv))
    signals["whale_turnover_share_5d_avg"] = (
        round(sum(shares_5d) / len(shares_5d), 4) if shares_5d else None
    )

    # --- A6 指標歷史 + Z-Score ---
    enh = signals.get("enhanced") or {}
    if not isinstance(enh, dict):
        enh = {}
    hist_for_z = history_records_before_date(stock_id, last_1d, dd, max_n=25)
    signals["metric_anomalies"] = compute_anomaly_flags(signals, enh, hist_for_z[-20:])

    snap = {
        "concentration_5d": signals.get("concentration_5d"),
        "pressure_ratio_5d": signals.get("pressure_ratio_5d"),
        "coherence_slope_5d": enh.get("coherence_slope_5d"),
        "top15_buy_stability_10d": signals.get("top15_buy_stability_10d"),
    }
    append_metric_snapshot(stock_id, last_1d, snap, dd)
