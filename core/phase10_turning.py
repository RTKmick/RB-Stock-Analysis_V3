"""
Phase 10：大船轉向偵測 — Top6 動量時間線（5 日滾動淨額）。
規格：phase10_turning_signal_spec.md
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.phase9_deep import _cache_csv_paths, _read_tdr_cache_csv

# 與 core/signals_whale.py、pipeline 一致：FinMind 分點 buy/sell 為股數，顯示用千張
SHARES_PER_KLOT = 1000.0


def compute_whale_momentum_timeline(
    stock_id: str,
    broker_ids: list[str],
    data_dir: Path | str,
    lookback: int = 60,
    window: int = 5,
) -> dict[str, Any] | None:
    """
    依 data/cache/tdr/{stock_id}/*.csv 計算各分點每日淨額（千張）與 window 日滾動合計，
    並在最近 lookback 交易日內掃描轉向（滾動由正轉負 / 由負轉正）。
    """
    root = Path(data_dir)
    cache_dir = root / "cache" / "tdr" / str(stock_id)
    paths = _cache_csv_paths(cache_dir)
    if not paths:
        return None

    paths = paths[-lookback:]
    dates: list[str] = []
    broker_daily: dict[str, list[float]] = {str(b).strip(): [] for b in broker_ids if str(b).strip()}
    if not broker_daily:
        return None

    for p in paths:
        dates.append(p.stem)
        df = _read_tdr_cache_csv(p)
        if df is None:
            for bid in broker_daily:
                broker_daily[bid].append(0.0)
            continue
        df = df.copy()
        df["broker_id"] = df["broker_id"].astype(str).str.strip()
        df["buy"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0.0)
        df["sell"] = pd.to_numeric(df["sell"], errors="coerce").fillna(0.0)
        for bid in broker_daily:
            rows = df[df["broker_id"] == bid]
            if rows.empty:
                broker_daily[bid].append(0.0)
            else:
                net_shares = float(rows["buy"].sum()) - float(rows["sell"].sum())
                broker_daily[bid].append(net_shares / SHARES_PER_KLOT)

    result: dict[str, Any] = {"dates": dates, "brokers": {}}

    for bid, daily in broker_daily.items():
        rolling: list[float | None] = []
        for i in range(len(daily)):
            if i < window - 1:
                rolling.append(None)
            else:
                s = sum(daily[i - window + 1 : i + 1])
                rolling.append(round(float(s), 1))

        turn_point: str | None = None
        turn_type: str | None = None
        # 由最近往回找 30 個索引區間內的符號反轉（Phase10 review：慢主力轉向可能較長）
        for i in range(len(rolling) - 1, max(0, len(rolling) - 30), -1):
            a, b = rolling[i - 1], rolling[i]
            if a is None or b is None:
                continue
            if b < 0 < a:
                turn_point = dates[i]
                turn_type = "BEAR_TURN"
                break
            if b > 0 > a:
                turn_point = dates[i]
                turn_type = "BULL_TURN"
                break

        result["brokers"][bid] = {
            "daily_net": [round(x, 2) for x in daily],
            "rolling_5d": rolling,
            "turn_point": turn_point,
            "turn_type": turn_type,
        }

    return result


def enrich_phase10_momentum(
    stock_id: str,
    top6_details: list[dict[str, Any]],
    signals: dict[str, Any],
    data_dir: Path | str,
    lookback: int = 60,
    window: int = 5,
) -> None:
    """寫入 momentum_* 與 momentum_dates；不保留完整 daily_net 於 JSON（節省空間）。"""
    ids = [str(b.get("broker_id", "")).strip() for b in top6_details if str(b.get("broker_id", "")).strip()]
    if not ids:
        signals["momentum_dates"] = []
        return

    timeline = compute_whale_momentum_timeline(
        stock_id, ids, data_dir, lookback=lookback, window=window
    )
    if not timeline:
        signals["momentum_dates"] = []
        for b in top6_details:
            b.pop("momentum_rolling_5d", None)
            b.pop("momentum_turn_point", None)
            b.pop("momentum_turn_type", None)
        return

    signals["momentum_dates"] = list(timeline.get("dates") or [])

    for b in top6_details:
        bid = str(b.get("broker_id", "")).strip()
        if not bid:
            continue
        bt = (timeline.get("brokers") or {}).get(bid)
        if not bt:
            b.pop("momentum_rolling_5d", None)
            b.pop("momentum_turn_point", None)
            b.pop("momentum_turn_type", None)
            continue
        b["momentum_rolling_5d"] = bt.get("rolling_5d")
        b["momentum_turn_point"] = bt.get("turn_point")
        b["momentum_turn_type"] = bt.get("turn_type")
