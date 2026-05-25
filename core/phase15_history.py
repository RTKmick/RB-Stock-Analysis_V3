"""
Phase 15：訊號歷史追蹤 — 每日 append 一筆 signals 快照到 {stock_id}_signals_history.json
規格：phase15_history_spec.md
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

# ===== 保留天數 =====
HISTORY_RETENTION_DAYS = 60


def _safe_get(d: dict | None, *keys: str, default: Any = None) -> Any:
    """巢狀安全取值。"""
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def extract_signal_snapshot(
    signals: dict[str, Any],
    top6_details: list[dict[str, Any]],
    trade_date: str,
) -> dict[str, Any]:
    """從 pipeline 產出物中抽取 history 用的最小快照。"""
    chip_score_raw = _safe_get(signals, "chip_score", default=None)
    chip_score: int | None
    if chip_score_raw is None:
        chip_score = None
    else:
        try:
            chip_score = int(round(float(chip_score_raw)))
        except (TypeError, ValueError):
            chip_score = None

    monitor_state = _safe_get(signals, "monitor_state", default=None)

    wr = signals.get("whale_resonance") or {}
    wr_snapshot = {
        "direction": wr.get("direction"),
        "count": int(wr.get("consensus_count") or 0),
        "label": wr.get("severity_label") or "NONE",
        "severity": int(wr.get("severity") or 0),
    }

    pv = signals.get("pv_divergence") or {}
    pv_snapshot = {
        "type": pv.get("type"),
        "strength": float(pv.get("divergence_strength") or 0.0),
        "severity": int(pv.get("severity") or 0),
    }

    lk = signals.get("lockup") or {}
    it = lk.get("investment_trust") or {}
    fr = lk.get("foreign") or {}
    lockup_snapshot = {
        "trust": int(it.get("score") or 0),
        "trust_label": it.get("label") or "NO_LOCKUP",
        "foreign": int(fr.get("score") or 0),
        "foreign_label": fr.get("label") or "NO_LOCKUP",
        "dual": bool(lk.get("is_dual_lockup") or False),
    }

    fres = signals.get("filtered_resonance") or {}
    filtered_snapshot = {
        "direction": fres.get("direction"),
        "count": int(fres.get("consensus_count") or 0),
        "total": int(fres.get("non_dayhop_total") or 0),
        "label": fres.get("severity_label") or "NONE",
        "severity": int(fres.get("severity") or 0),
        "high_confidence": bool(fres.get("is_high_confidence") or False),
    }

    bear_turn_count = 0
    bull_turn_count = 0
    dayhopper = 0
    swing = 0
    holder = 0
    spike_count = 0
    accelerating_count = 0

    for b in top6_details or []:
        tt = b.get("momentum_turn_type")
        if tt == "BEAR_TURN":
            bear_turn_count += 1
        elif tt == "BULL_TURN":
            bull_turn_count += 1

        btype = (b.get("dayhop") or {}).get("broker_type")
        if btype == "DAY_HOPPER":
            dayhopper += 1
        elif btype == "SWING_TRADER":
            swing += 1
        elif btype == "POSITION_HOLDER":
            holder += 1

        an = b.get("anomaly") or {}
        if an.get("is_spike"):
            spike_count += 1
        if an.get("is_accelerating"):
            accelerating_count += 1

    turn_summary = {
        "bear_turn_count": bear_turn_count,
        "bull_turn_count": bull_turn_count,
    }
    top6_summary = {
        "dayhopper": dayhopper,
        "swing": swing,
        "holder": holder,
        "spike": spike_count,
        "accelerating": accelerating_count,
    }

    composite_severity = max(
        wr_snapshot["severity"],
        pv_snapshot["severity"],
        filtered_snapshot["severity"],
        100 if lockup_snapshot["dual"] else 0,
    )

    trap_signal = bool(
        wr_snapshot["direction"] in ("BUY", "SELL")
        and filtered_snapshot["direction"] in ("BUY", "SELL")
        and wr_snapshot["direction"] != filtered_snapshot["direction"]
    )

    return {
        "date": str(trade_date)[:10],
        "chip_score": chip_score,
        "monitor_state": monitor_state,
        "whale_resonance": wr_snapshot,
        "pv_divergence": pv_snapshot,
        "lockup": lockup_snapshot,
        "filtered_resonance": filtered_snapshot,
        "turn_summary": turn_summary,
        "top6_summary": top6_summary,
        "composite_severity": int(composite_severity),
        "trap_signal": trap_signal,
    }


def append_signals_history(
    stock_id: str,
    stock_name: str,
    signals: dict[str, Any],
    top6_details: list[dict[str, Any]],
    trade_date: str,
    data_dir: Path | str,
    lookback: int = HISTORY_RETENTION_DAYS,
) -> None:
    """
    將今日 signals 快照 append 至 data/{stock_id}_signals_history.json。
    同日去重（重跑 pipeline 時覆寫當日）；保留 lookback 天滾動。
    """
    root = Path(data_dir)
    history_path = root / f"{stock_id}_signals_history.json"

    history: dict[str, Any] = {
        "stock_id": str(stock_id),
        "stock_name": str(stock_name or ""),
        "records": [],
    }

    if history_path.is_file():
        try:
            with open(history_path, encoding="utf-8") as f:
                history = json.load(f)
        except (OSError, json.JSONDecodeError):
            history = {
                "stock_id": str(stock_id),
                "stock_name": str(stock_name or ""),
                "records": [],
            }

    if not isinstance(history.get("records"), list):
        history["records"] = []

    today = str(trade_date)[:10]

    existing_dates = {str(r.get("date", "")) for r in history["records"]}
    if today in existing_dates:
        history["records"] = [r for r in history["records"] if str(r.get("date", "")) != today]

    record = extract_signal_snapshot(signals, top6_details, today)
    history["records"].append(record)

    history["records"].sort(key=lambda r: str(r.get("date", "")))
    history["records"] = history["records"][-lookback:]

    history["stock_name"] = str(stock_name or history.get("stock_name", ""))
    history["updated_at"] = datetime.now().isoformat(timespec="seconds")

    history_path.parent.mkdir(parents=True, exist_ok=True)
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def get_signals_history(
    stock_id: str,
    data_dir: Path | str,
    n_days: int = 10,
) -> list[dict[str, Any]]:
    """
    讀取 {stock_id}_signals_history.json 最近 N 天記錄。
    供 Phase 16+ 變化型訊號使用。
    """
    root = Path(data_dir)
    history_path = root / f"{stock_id}_signals_history.json"
    if not history_path.is_file():
        return []

    try:
        with open(history_path, encoding="utf-8") as f:
            history = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    records = history.get("records") or []
    if not isinstance(records, list):
        return []

    records.sort(key=lambda r: str(r.get("date", "")))
    return records[-n_days:]
