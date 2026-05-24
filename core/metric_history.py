"""
Phase 8：每日關鍵指標快照，供 Z-Score 異常偵測（data/{stock_id}_metric_history.json）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _path(stock_id: str, data_dir: Path) -> Path:
    return data_dir / f"{stock_id}_metric_history.json"


def load_metric_history(stock_id: str, data_dir: Path) -> dict[str, Any]:
    p = _path(stock_id, data_dir)
    try:
        with open(p, encoding="utf-8") as f:
            h = json.load(f)
        if isinstance(h, dict) and isinstance(h.get("records"), list):
            return h
    except (OSError, json.JSONDecodeError):
        pass
    return {"stock_id": stock_id, "records": []}


def history_records_before_date(stock_id: str, trade_date: str, data_dir: Path, max_n: int = 25) -> list[dict[str, Any]]:
    """取得嚴格早於 trade_date 的紀錄，由舊到新（最多 max_n 筆）。"""
    h = load_metric_history(stock_id, data_dir)
    recs = [r for r in (h.get("records") or []) if str(r.get("date", "")) < str(trade_date)[:10]]
    recs = sorted(recs, key=lambda x: str(x.get("date", "")))
    return recs[-max_n:]


def append_metric_snapshot(
    stock_id: str,
    trade_date: str,
    snapshot: dict[str, Any],
    data_dir: Path,
) -> None:
    """同日只寫入一次；保留最近 90 筆。"""
    h = load_metric_history(stock_id, data_dir)
    records: list[dict[str, Any]] = list(h.get("records") or [])
    d0 = str(trade_date)[:10]
    if any(str(r.get("date", ""))[:10] == d0 for r in records):
        return
    row = {"date": d0, **snapshot}
    records.append(row)
    records = records[-90:]
    h["stock_id"] = stock_id
    h["records"] = records
    p = _path(stock_id, data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=2)
