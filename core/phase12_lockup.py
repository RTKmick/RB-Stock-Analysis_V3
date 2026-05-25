"""
Phase 12：投信/外資鎖碼分數 — 偵測法人實體層的持續性鎖碼意圖。
規格：phase12_lockup_spec.md
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from core.finmind_client import FinMindClient

# ===== 觀察窗 =====
LOCKUP_LOOKBACK_DAYS = 10

# ===== A 因子：連買天數 =====
MIN_CONSECUTIVE_BUY_DAYS = 3
SCORE_CONSEC_PER_DAY = 8
SCORE_CONSEC_CAP = 40

# ===== B 因子：累積買超 / 流通股本比 =====
SCORE_RATIO_BANDS = [
    (0.001, 15),
    (0.003, 25),
    (0.005, 35),
]

# ===== C 因子：股價推升一致性 =====
SCORE_PRICE_LIFT_BANDS = [
    (0.05, 25),
    (0.01, 15),
    (-0.01, 5),
    (float("-inf"), 0),
]

STRONG_LOCKUP_THRESHOLD = 80
MODERATE_LOCKUP_THRESHOLD = 60
WEAK_LOCKUP_THRESHOLD = 30

DUAL_LOCKUP_BOTH_MIN = 70

# FinMind TaiwanStockInstitutionalInvestorsBuySell 之 name 欄位（英文）
TRUST_NAMES = ("Investment_Trust",)
FOREIGN_NAMES = ("Foreign_Investor",)


def _empty_lockup(consecutive_days: int = 0) -> dict[str, Any]:
    return {
        "consecutive_buy_days": consecutive_days,
        "accumulated_net_shares": 0,
        "accumulated_ratio": 0.0,
        "price_lift_pct": 0.0,
        "score": 0,
        "label": "NO_LOCKUP",
        "score_breakdown": {"consecutive": 0, "ratio": 0, "price_lift": 0},
    }


def _label_from_score(score: int) -> str:
    if score >= STRONG_LOCKUP_THRESHOLD:
        return "STRONG_LOCKUP"
    if score >= MODERATE_LOCKUP_THRESHOLD:
        return "MODERATE_LOCKUP"
    if score >= WEAK_LOCKUP_THRESHOLD:
        return "WEAK_LOCKUP"
    return "NO_LOCKUP"


def fetch_share_capital_shares(client: FinMindClient, stock_id: str, end_date: str) -> float | None:
    """
    流通／發行股數（股）。優先 TaiwanStockShareholding.NumberOfSharesIssued；
    TaiwanStockInfo 本專案實測無股本欄位故不採用。
    """
    try:
        end = str(end_date)[:10]
        start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=120)).strftime("%Y-%m-%d")
    except Exception:
        return None

    df = client.request_data(
        "TaiwanStockShareholding",
        data_id=stock_id,
        start_date=start,
        end_date=end,
    )
    if df is None or df.empty or "NumberOfSharesIssued" not in df.columns:
        return None
    d = df.copy()
    d["date"] = d["date"].astype(str)
    d = d.sort_values("date").reset_index(drop=True)
    v = pd.to_numeric(d["NumberOfSharesIssued"].iloc[-1], errors="coerce")
    if v is None or (isinstance(v, float) and v != v):
        return None
    f = float(v)
    return f if f > 0 else None


def _close_by_date(ohlcv: pd.DataFrame | None) -> dict[str, float]:
    if ohlcv is None or ohlcv.empty or "date" not in ohlcv.columns or "close" not in ohlcv.columns:
        return {}
    m: dict[str, float] = {}
    for _, r in ohlcv.iterrows():
        m[str(r["date"])] = float(r.get("close", 0) or 0)
    return m


def build_party_daily_series(
    inst_df: pd.DataFrame | None,
    finmind_party_names: tuple[str, ...],
    close_by_date: dict[str, float],
    lookback: int,
) -> list[dict[str, Any]]:
    """法人單類別：依日加總淨買賣股數，合併收盤價。"""
    if inst_df is None or inst_df.empty:
        return []
    need = {"date", "name", "buy", "sell"}
    if not need.issubset(inst_df.columns):
        return []
    sub = inst_df[inst_df["name"].astype(str).isin(finmind_party_names)].copy()
    if sub.empty:
        return []
    sub["buy"] = pd.to_numeric(sub["buy"], errors="coerce").fillna(0.0)
    sub["sell"] = pd.to_numeric(sub["sell"], errors="coerce").fillna(0.0)
    sub["net_shares"] = sub["buy"] - sub["sell"]
    g = (
        sub.groupby("date", as_index=False)["net_shares"]
        .sum()
        .sort_values("date")
        .reset_index(drop=True)
    )
    g = g.tail(lookback)
    out: list[dict[str, Any]] = []
    for _, row in g.iterrows():
        ds = str(row["date"])
        out.append(
            {
                "date": ds,
                "net_shares": float(row["net_shares"]),
                "close": float(close_by_date.get(ds, 0) or 0),
            }
        )
    return out


def detect_lockup_for_party(
    party_daily: list[dict[str, Any]],
    share_capital_shares: float,
) -> dict[str, Any]:
    if not party_daily or len(party_daily) < MIN_CONSECUTIVE_BUY_DAYS:
        return _empty_lockup()

    consecutive = 0
    for d in reversed(party_daily):
        if d.get("net_shares") is None:
            break
        if float(d["net_shares"]) > 0:
            consecutive += 1
        else:
            break

    if consecutive < MIN_CONSECUTIVE_BUY_DAYS:
        return _empty_lockup(consecutive_days=consecutive)

    recent_period = party_daily[-consecutive:]

    total_net_shares = sum(float(d.get("net_shares", 0) or 0) for d in recent_period)
    ratio = (
        total_net_shares / share_capital_shares
        if share_capital_shares and share_capital_shares > 0
        else 0.0
    )

    try:
        start_close = float(recent_period[0].get("close", 0) or 0)
        end_close = float(recent_period[-1].get("close", 0) or 0)
        price_lift = (end_close / start_close - 1.0) if start_close > 0 else 0.0
    except (TypeError, ValueError):
        price_lift = 0.0

    consec_score = min(float(consecutive * SCORE_CONSEC_PER_DAY), float(SCORE_CONSEC_CAP))

    ratio_score = 0
    for threshold, points in SCORE_RATIO_BANDS:
        if ratio >= threshold:
            ratio_score = points

    lift_score = 0
    for threshold, points in SCORE_PRICE_LIFT_BANDS:
        if price_lift >= threshold:
            lift_score = points
            break

    total_score = int(min(100.0, consec_score + float(ratio_score) + float(lift_score)))

    return {
        "consecutive_buy_days": consecutive,
        "accumulated_net_shares": int(round(total_net_shares)),
        "accumulated_ratio": round(ratio, 5),
        "price_lift_pct": round(price_lift * 100.0, 2),
        "score": total_score,
        "label": _label_from_score(total_score),
        "score_breakdown": {
            "consecutive": int(consec_score),
            "ratio": int(ratio_score),
            "price_lift": int(lift_score),
        },
    }


def enrich_phase12_lockup(
    stock_id: str,
    signals: dict[str, Any],
    institutional_df: pd.DataFrame | None,
    ohlcv_20d: pd.DataFrame | None,
    client: FinMindClient,
    last_trade_date: str,
    lookback: int = LOCKUP_LOOKBACK_DAYS,
) -> None:
    """寫入 signals['lockup']：投信、外資鎖碼分數與雙鎖碼旗標。"""
    close_map = _close_by_date(ohlcv_20d)
    cap = fetch_share_capital_shares(client, stock_id, last_trade_date)

    if institutional_df is None or institutional_df.empty or not cap:
        signals["lockup"] = {
            "investment_trust": _empty_lockup(),
            "foreign": _empty_lockup(),
            "is_dual_lockup": False,
        }
        return

    it_daily = build_party_daily_series(institutional_df, TRUST_NAMES, close_map, lookback)
    fr_daily = build_party_daily_series(institutional_df, FOREIGN_NAMES, close_map, lookback)

    it_lockup = detect_lockup_for_party(it_daily, float(cap))
    fr_lockup = detect_lockup_for_party(fr_daily, float(cap))

    is_dual = bool(
        it_lockup["score"] >= DUAL_LOCKUP_BOTH_MIN and fr_lockup["score"] >= DUAL_LOCKUP_BOTH_MIN
    )

    signals["lockup"] = {
        "investment_trust": it_lockup,
        "foreign": fr_lockup,
        "is_dual_lockup": is_dual,
    }
