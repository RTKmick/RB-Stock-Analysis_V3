"""
Phase 14：過濾型共振 — 排除 Phase 13 標記為 DAY_HOPPER 的分點後，計算真主力共識。
規格：phase14_filtered_resonance_spec.md
"""
from __future__ import annotations

from typing import Any

# ===== 過濾規則 =====
EXCLUDE_BROKER_TYPES: tuple[str, ...] = ("DAY_HOPPER",)

# ===== 最少非短線分點數 =====
MIN_NON_DAYHOP_BROKERS = 3

# ===== 共識門檻 =====
FILTERED_STRONG_RATIO = 0.80
FILTERED_MODERATE_RATIO = 0.60

# ===== 嚴重度（刻意高於 Phase 11 對應等級）=====
SEVERITY_STRONG = 95
SEVERITY_MODERATE = 65


def _empty_filtered_resonance() -> dict[str, Any]:
    return {
        "direction": None,
        "consensus_count": 0,
        "non_dayhop_total": 0,
        "consensus_ratio": 0.0,
        "severity_label": "NONE",
        "severity": 0,
        "excluded_dayhopper_count": 0,
        "is_high_confidence": False,
    }


def detect_filtered_resonance(top6_details: list[dict[str, Any]]) -> dict[str, Any]:
    """
    對 Top6 排除 DAY_HOPPER 後計算共識。
    使用 Phase 13 dayhop.broker_type 過濾，再用 Phase 11 detect_whale_resonance 一致的方向判定。
    """
    if not top6_details:
        return _empty_filtered_resonance()

    excluded = 0
    directions: list[str] = []

    for b in top6_details:
        dayhop = b.get("dayhop") or {}
        broker_type = dayhop.get("broker_type")
        if broker_type in EXCLUDE_BROKER_TYPES:
            excluded += 1
            continue

        anomaly = b.get("anomaly") or {}
        d = anomaly.get("consecutive_direction")
        if d in ("BUY", "SELL"):
            directions.append(str(d))
            continue
        net = float(b.get("net_1d", 0) or b.get("net_lot", 0) or 0)
        if net > 0:
            directions.append("BUY")
        elif net < 0:
            directions.append("SELL")

    non_dayhop_total = len(directions)

    if non_dayhop_total < MIN_NON_DAYHOP_BROKERS:
        return {
            **_empty_filtered_resonance(),
            "non_dayhop_total": non_dayhop_total,
            "excluded_dayhopper_count": excluded,
        }

    buy_count = directions.count("BUY")
    sell_count = directions.count("SELL")

    if buy_count == sell_count:
        return {
            "direction": "MIXED",
            "consensus_count": max(buy_count, sell_count),
            "non_dayhop_total": non_dayhop_total,
            "consensus_ratio": round(max(buy_count, sell_count) / non_dayhop_total, 2),
            "severity_label": "NONE",
            "severity": 0,
            "excluded_dayhopper_count": excluded,
            "is_high_confidence": False,
        }

    direction = "BUY" if buy_count > sell_count else "SELL"
    max_count = max(buy_count, sell_count)
    ratio = max_count / non_dayhop_total

    if ratio >= FILTERED_STRONG_RATIO:
        severity_label = "STRONG"
        severity = SEVERITY_STRONG
    elif ratio >= FILTERED_MODERATE_RATIO:
        severity_label = "MODERATE"
        severity = SEVERITY_MODERATE
    else:
        return {
            "direction": direction,
            "consensus_count": max_count,
            "non_dayhop_total": non_dayhop_total,
            "consensus_ratio": round(ratio, 2),
            "severity_label": "NONE",
            "severity": 0,
            "excluded_dayhopper_count": excluded,
            "is_high_confidence": False,
        }

    return {
        "direction": direction,
        "consensus_count": max_count,
        "non_dayhop_total": non_dayhop_total,
        "consensus_ratio": round(ratio, 2),
        "severity_label": severity_label,
        "severity": severity,
        "excluded_dayhopper_count": excluded,
        "is_high_confidence": True,
    }


def enrich_phase14_filtered_resonance(
    top6_details: list[dict[str, Any]],
    signals: dict[str, Any],
) -> None:
    """須在 Phase 11（whale_resonance / anomaly）與 Phase 13（dayhop）之後執行。"""
    signals["filtered_resonance"] = detect_filtered_resonance(top6_details)


def empty_filtered_resonance_snapshot() -> dict[str, Any]:
    """供 pipeline 例外處理使用，與正常路徑回傳結構一致。"""
    return _empty_filtered_resonance()
