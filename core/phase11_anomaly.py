"""
Phase 11：大戶異常走向偵測 — 爆量／加速／共振／量價背離。
規格：phase11_anomaly_spec.md
"""
from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

import pandas as pd

from core.phase10_turning import compute_whale_momentum_timeline

# ===== T1 閾值 =====
SPIKE_Z_THRESHOLD = 3.0
SPIKE_MIN_ABS_KLOT = 50.0
ACCEL_MIN_DAYS = 3
ACCEL_GROWTH_RATIO = 1.5

# ===== T2 閾值 =====
RESONANCE_STRONG_COUNT = 5
RESONANCE_MODERATE_COUNT = 4

# ===== T3 閾值 =====
DIVERGENCE_NET_THRESHOLD = 500.0
DIVERGENCE_PRICE_THRESHOLD = 0.5


def _empty_volume_anomaly() -> dict[str, Any]:
    return {
        "z_score": 0.0,
        "is_spike": False,
        "spike_direction": None,
        "consecutive_days": 0,
        "consecutive_direction": None,
        "is_accelerating": False,
        "severity": 0,
    }


def price_change_pct_from_ohlcv(ohlcv: pd.DataFrame | None) -> float | None:
    """最近一個交易日收盤相對前一交易日之漲跌幅（%）。"""
    if ohlcv is None or ohlcv.empty or len(ohlcv) < 2:
        return None
    try:
        prev = float(ohlcv.iloc[-2]["close"])
        last = float(ohlcv.iloc[-1]["close"])
    except (KeyError, TypeError, ValueError):
        return None
    if prev <= 0:
        return None
    return round((last / prev - 1.0) * 100.0, 4)


def detect_volume_anomaly(daily_net: list[float]) -> dict[str, Any]:
    """
    對單一分點的 daily_net 序列（與 pipeline 相同口徑：股加總後／1000），判斷今日是否爆量、是否連續加速。
    """
    if not daily_net or len(daily_net) < 10:
        return _empty_volume_anomaly()

    raw_last = daily_net[-1]
    if raw_last is None:
        return _empty_volume_anomaly()
    today = float(raw_last)

    history: list[float] = []
    for x in daily_net[:-1]:
        if x is None:
            continue
        history.append(float(x))
    if len(history) < 5:
        return _empty_volume_anomaly()

    mu = statistics.mean(history)
    try:
        sigma = statistics.pstdev(history)
    except statistics.StatisticsError:
        sigma = 0.0

    if sigma > 0:
        z = (today - mu) / sigma
    else:
        z = 0.0

    is_spike = abs(z) >= SPIKE_Z_THRESHOLD and abs(today) >= SPIKE_MIN_ABS_KLOT
    spike_direction: str | None = None
    if is_spike:
        spike_direction = "BUY" if today > 0 else "SELL"

    consecutive = 0
    direction: str | None = None
    if today > 0:
        direction = "BUY"
        for v in reversed(daily_net):
            if v is not None and float(v) > 0:
                consecutive += 1
            else:
                break
    elif today < 0:
        direction = "SELL"
        for v in reversed(daily_net):
            if v is not None and float(v) < 0:
                consecutive += 1
            else:
                break

    is_accelerating = False
    if consecutive >= ACCEL_MIN_DAYS:
        recent = [abs(float(x)) for x in daily_net[-consecutive:] if x is not None]
        if len(recent) >= ACCEL_MIN_DAYS:
            third = max(1, len(recent) // 3)
            early_avg = sum(recent[:third]) / third
            late_avg = sum(recent[-third:]) / third
            if early_avg > 0 and late_avg / early_avg >= ACCEL_GROWTH_RATIO:
                is_accelerating = True

    sev = min(60.0, abs(z) * 15.0)
    sev += min(30.0, float(consecutive * 5))
    if is_accelerating:
        sev += 10.0
    severity = int(min(100.0, sev))

    return {
        "z_score": round(float(z), 2),
        "is_spike": bool(is_spike),
        "spike_direction": spike_direction,
        "consecutive_days": consecutive,
        "consecutive_direction": direction,
        "is_accelerating": bool(is_accelerating),
        "severity": severity,
    }


def detect_whale_resonance(top6_details: list[dict[str, Any]]) -> dict[str, Any]:
    """Top6 當日方向統計（優先 anomaly.consecutive_direction，否則 net_1d）。"""
    if not top6_details:
        return {
            "direction": None,
            "consensus_count": 0,
            "consensus_ratio": 0.0,
            "severity_label": "NONE",
            "severity": 0,
        }

    directions: list[str] = []
    for b in top6_details:
        an = b.get("anomaly") or {}
        d = an.get("consecutive_direction")
        if d in ("BUY", "SELL"):
            directions.append(str(d))
            continue
        net = float(b.get("net_1d", 0) or b.get("net_lot", 0) or 0)
        if net > 0:
            directions.append("BUY")
        elif net < 0:
            directions.append("SELL")

    buy_count = directions.count("BUY")
    sell_count = directions.count("SELL")
    total = len(top6_details)

    if buy_count >= RESONANCE_STRONG_COUNT:
        return {
            "direction": "BUY",
            "consensus_count": buy_count,
            "consensus_ratio": round(buy_count / total, 2),
            "severity_label": "STRONG",
            "severity": 90,
        }
    if sell_count >= RESONANCE_STRONG_COUNT:
        return {
            "direction": "SELL",
            "consensus_count": sell_count,
            "consensus_ratio": round(sell_count / total, 2),
            "severity_label": "STRONG",
            "severity": 90,
        }
    if buy_count >= RESONANCE_MODERATE_COUNT:
        return {
            "direction": "BUY",
            "consensus_count": buy_count,
            "consensus_ratio": round(buy_count / total, 2),
            "severity_label": "MODERATE",
            "severity": 60,
        }
    if sell_count >= RESONANCE_MODERATE_COUNT:
        return {
            "direction": "SELL",
            "consensus_count": sell_count,
            "consensus_ratio": round(sell_count / total, 2),
            "severity_label": "MODERATE",
            "severity": 60,
        }

    return {
        "direction": "MIXED" if buy_count > 0 and sell_count > 0 else None,
        "consensus_count": max(buy_count, sell_count),
        "consensus_ratio": round(max(buy_count, sell_count) / total, 2) if total else 0.0,
        "severity_label": "NONE",
        "severity": 0,
    }


def detect_pv_divergence(
    top6_details: list[dict[str, Any]],
    price_change_pct: float | None,
) -> dict[str, Any]:
    """量價背離：Top6 合計 net_1d（千張口徑）vs 當日股價漲跌幅（%）。"""
    if price_change_pct is None:
        return {
            "type": "UNKNOWN",
            "severity": 0,
            "description": "無股價資料",
            "top6_net_klot": 0.0,
            "price_change_pct": None,
            "divergence_strength": 0.0,
        }

    net_sum = sum(float(b.get("net_1d", 0) or b.get("net_lot", 0) or 0) for b in top6_details)
    p = float(price_change_pct)

    is_stealth_buy = net_sum >= DIVERGENCE_NET_THRESHOLD and -DIVERGENCE_PRICE_THRESHOLD <= p <= DIVERGENCE_PRICE_THRESHOLD
    is_stealth_sell = net_sum <= -DIVERGENCE_NET_THRESHOLD and -DIVERGENCE_PRICE_THRESHOLD <= p <= DIVERGENCE_PRICE_THRESHOLD

    denom = DIVERGENCE_PRICE_THRESHOLD
    price_factor = max(0.0, 1.0 - abs(p) / denom) if denom > 0 else 0.0

    if is_stealth_buy:
        strength = min(
            1.0,
            (net_sum / DIVERGENCE_NET_THRESHOLD) * price_factor,
        )
        return {
            "type": "STEALTH_BUY",
            "top6_net_klot": round(net_sum, 1),
            "price_change_pct": round(p, 2),
            "divergence_strength": round(strength, 2),
            "severity": int(min(100, strength * 80)),
            "description": f"Top6 淨買 {net_sum:.0f} 千張，但股價僅 {p:+.2f}% — 可能在吸籌",
        }

    if is_stealth_sell:
        strength = min(
            1.0,
            (abs(net_sum) / DIVERGENCE_NET_THRESHOLD) * price_factor,
        )
        return {
            "type": "STEALTH_SELL",
            "top6_net_klot": round(net_sum, 1),
            "price_change_pct": round(p, 2),
            "divergence_strength": round(strength, 2),
            "severity": int(min(100, strength * 80)),
            "description": f"Top6 淨賣 {abs(net_sum):.0f} 千張，但股價僅 {p:+.2f}% — 可能在派發",
        }

    return {
        "type": "NORMAL",
        "top6_net_klot": round(net_sum, 1),
        "price_change_pct": round(p, 2),
        "divergence_strength": 0.0,
        "severity": 0,
        "description": "量價同步",
    }


def enrich_phase11_anomaly(
    stock_id: str,
    top6_details: list[dict[str, Any]],
    signals: dict[str, Any],
    data_dir: Path | str,
    ohlcv_20d: pd.DataFrame | None = None,
) -> None:
    """
    Top6 每分點 T1 異常徽章；signals 寫入 whale_resonance、pv_divergence、price_change_pct。
    """
    pc = signals.get("price_change_pct")
    if pc is None and ohlcv_20d is not None:
        pc = price_change_pct_from_ohlcv(ohlcv_20d)
    if pc is not None:
        signals["price_change_pct"] = float(pc)

    ids = [str(b.get("broker_id", "")).strip() for b in top6_details if str(b.get("broker_id", "")).strip()]
    timeline = None
    if ids:
        timeline = compute_whale_momentum_timeline(stock_id, ids, data_dir, lookback=60, window=5)

    brokers = (timeline or {}).get("brokers") or {}
    for b in top6_details:
        bid = str(b.get("broker_id", "")).strip()
        bt = brokers.get(bid) if bid else None
        if bt:
            daily_net = list(bt.get("daily_net") or [])
            b["anomaly"] = detect_volume_anomaly(daily_net)
        else:
            b["anomaly"] = _empty_volume_anomaly()

    signals["whale_resonance"] = detect_whale_resonance(top6_details)
    signals["pv_divergence"] = detect_pv_divergence(
        top6_details,
        float(pc) if pc is not None else None,
    )
