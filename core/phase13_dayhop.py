"""
Phase 13：隔日沖分點識別 — 用 60 天 daily_net 行為對每個 Top6 分點打身分標籤。
規格：phase13_dayhop_spec.md
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.phase10_turning import compute_whale_momentum_timeline

# ===== 觀察窗 =====
DAYHOP_LOOKBACK = 60

# ===== A 因子：翻轉頻率 =====
FLIP_HIGH_THRESHOLD = 0.30
FLIP_MED_THRESHOLD = 0.15

# ===== B 因子：平均持有天數 =====
HOLD_SHORT_THRESHOLD = 2.0
HOLD_MED_THRESHOLD = 5.0

# ===== C 因子：大量短期比例 =====
BIG_DAY_QUANTILE = 0.7
QUICK_REVERSE_DAYS = 2
QUICK_REVERSE_HIGH = 0.50
QUICK_REVERSE_MED = 0.25

# ===== 等級閾值 =====
DAY_HOPPER_THRESHOLD = 70
SWING_TRADER_THRESHOLD = 30

# ===== 最小資料量 =====
MIN_VALID_DAYS = 20


def _empty_dayhop() -> dict[str, Any]:
    return {
        "day_hop_score": 0,
        "broker_type": "UNKNOWN",
        "broker_type_label": "資料不足",
        "score_breakdown": {"flip": 0, "hold": 0, "quick_reverse": 0},
        "stats": {
            "flip_count": 0,
            "flip_rate": 0.0,
            "avg_hold_days": 0.0,
            "big_day_count": 0,
            "quick_reverse_rate": 0.0,
        },
    }


def _type_label(broker_type: str) -> str:
    if broker_type == "DAY_HOPPER":
        return "隔日沖型"
    if broker_type == "SWING_TRADER":
        return "短線型"
    if broker_type == "POSITION_HOLDER":
        return "長線持有"
    return "資料不足"


def detect_dayhop_for_broker(daily_net: list[float | None]) -> dict[str, Any]:
    """
    對單一分點的 daily_net 序列做行為分類。

    daily_net 從 phase10_turning 取得（千張；None 為缺漏日，實務上多為連續 float）。
    """
    valid = [float(x) for x in daily_net if x is not None]
    if len(valid) < MIN_VALID_DAYS:
        return _empty_dayhop()

    n = len(valid)

    flip_count = 0
    for i in range(1, n):
        prev = valid[i - 1]
        curr = valid[i]
        if (prev > 0 and curr < 0) or (prev < 0 and curr > 0):
            flip_count += 1
    flip_rate = flip_count / (n - 1) if n > 1 else 0.0

    runs: list[int] = []
    current_run = 0
    prev_sign = 0
    for v in valid:
        sign = 1 if v > 0 else (-1 if v < 0 else 0)
        if sign == 0:
            if current_run > 0:
                runs.append(current_run)
            current_run = 0
            prev_sign = 0
            continue
        if sign == prev_sign:
            current_run += 1
        else:
            if current_run > 0:
                runs.append(current_run)
            current_run = 1
            prev_sign = sign
    if current_run > 0:
        runs.append(current_run)
    avg_hold_days = sum(runs) / len(runs) if runs else float(n)

    abs_vals = sorted([abs(v) for v in valid], reverse=True)
    cutoff_idx = max(1, int(n * (1 - BIG_DAY_QUANTILE)))
    big_threshold = abs_vals[cutoff_idx - 1] if cutoff_idx <= len(abs_vals) else 0.0
    big_day_count = 0
    quick_reverse_count = 0
    for i, v in enumerate(valid):
        if abs(v) < big_threshold or v == 0:
            continue
        big_day_count += 1
        sign = 1 if v > 0 else -1
        end = min(n, i + QUICK_REVERSE_DAYS + 1)
        for j in range(i + 1, end):
            other = valid[j]
            if sign * other < 0:
                quick_reverse_count += 1
                break
    quick_reverse_rate = quick_reverse_count / big_day_count if big_day_count > 0 else 0.0

    flip_score = 0
    if flip_rate >= FLIP_HIGH_THRESHOLD:
        flip_score = 33
    elif flip_rate >= FLIP_MED_THRESHOLD:
        flip_score = 20

    hold_score = 0
    if avg_hold_days <= HOLD_SHORT_THRESHOLD:
        hold_score = 33
    elif avg_hold_days <= HOLD_MED_THRESHOLD:
        hold_score = 20

    quick_score = 0
    if quick_reverse_rate >= QUICK_REVERSE_HIGH:
        quick_score = 34
    elif quick_reverse_rate >= QUICK_REVERSE_MED:
        quick_score = 20

    day_hop_score = flip_score + hold_score + quick_score

    if day_hop_score >= DAY_HOPPER_THRESHOLD:
        broker_type = "DAY_HOPPER"
    elif day_hop_score >= SWING_TRADER_THRESHOLD:
        broker_type = "SWING_TRADER"
    else:
        broker_type = "POSITION_HOLDER"

    return {
        "day_hop_score": int(min(100, day_hop_score)),
        "broker_type": broker_type,
        "broker_type_label": _type_label(broker_type),
        "score_breakdown": {
            "flip": int(flip_score),
            "hold": int(hold_score),
            "quick_reverse": int(quick_score),
        },
        "stats": {
            "flip_count": int(flip_count),
            "flip_rate": round(flip_rate, 3),
            "avg_hold_days": round(avg_hold_days, 1),
            "big_day_count": int(big_day_count),
            "quick_reverse_rate": round(quick_reverse_rate, 3),
        },
    }


def enrich_phase13_dayhop(
    stock_id: str,
    top6_details: list[dict[str, Any]],
    data_dir: Path | str,
    lookback: int = DAYHOP_LOOKBACK,
) -> None:
    """
    對 Top6 每分點計算隔日沖傾向。
    依賴：Phase 10 的 compute_whale_momentum_timeline 取得 daily_net。
    """
    ids = [str(b.get("broker_id", "")).strip() for b in top6_details if str(b.get("broker_id", "")).strip()]
    if not ids:
        for b in top6_details:
            b["dayhop"] = _empty_dayhop()
        return

    timeline = compute_whale_momentum_timeline(stock_id, ids, data_dir, lookback=lookback, window=5)
    if not timeline:
        for b in top6_details:
            b["dayhop"] = _empty_dayhop()
        return

    brokers = (timeline or {}).get("brokers") or {}
    for b in top6_details:
        bid = str(b.get("broker_id", "")).strip()
        bt = brokers.get(bid) if bid else None
        if not bt:
            b["dayhop"] = _empty_dayhop()
            continue
        daily_net = list(bt.get("daily_net") or [])
        b["dayhop"] = detect_dayhop_for_broker(daily_net)


def empty_dayhop_snapshot() -> dict[str, Any]:
    """供 pipeline 例外處理：與資料不足／無快取時之 top6 dayhop 結構一致。"""
    return _empty_dayhop()
