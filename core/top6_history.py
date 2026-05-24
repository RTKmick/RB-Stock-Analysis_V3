"""
Phase 7：Top6 歷史（駐留天數、新進大戶）。
寫入 data/{stock_id}_top6_history.json，供下次 pipeline 計算連續出現天數。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.broker_groups import compute_group_summary, get_broker_group


def _history_path(stock_id: str, data_dir: Path) -> Path:
    return data_dir / f"{stock_id}_top6_history.json"


def _load_history(stock_id: str, data_dir: Path) -> dict[str, Any]:
    path = _history_path(stock_id, data_dir)
    try:
        with open(path, encoding="utf-8") as f:
            h = json.load(f)
        if isinstance(h, dict) and isinstance(h.get("records"), list):
            return h
    except (OSError, json.JSONDecodeError):
        pass
    return {"stock_id": stock_id, "records": []}


def _save_history(stock_id: str, history: dict[str, Any], data_dir: Path) -> None:
    path = _history_path(stock_id, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def update_top6_history(
    stock_id: str,
    top6_details: list[dict[str, Any]],
    trade_date: str,
    data_dir: Path | str | None = None,
) -> None:
    """記錄當日 Top6 broker_id（最多 6 筆），同日不重複；保留最近 60 筆。"""
    root = Path(__file__).resolve().parents[1]
    dd = Path(data_dir) if data_dir else root / "data"
    history = _load_history(stock_id, dd)
    records: list[dict[str, Any]] = list(history.get("records") or [])

    existing_dates = {str(r.get("date", "")) for r in records}
    if trade_date in existing_dates:
        return

    today_ids = [str(t.get("broker_id", "")).strip() for t in top6_details[:6] if t.get("broker_id")]
    records.append({"date": trade_date, "top6_ids": today_ids})
    records = records[-60:]
    history["stock_id"] = stock_id
    history["records"] = records
    _save_history(stock_id, history, dd)


def compute_stability(
    stock_id: str,
    top6_details: list[dict[str, Any]],
    data_dir: Path | str | None = None,
) -> dict[str, int]:
    """由歷史紀錄計算各 broker_id 連續出現在 Top6 的天數（僅看已存檔紀錄，不含本次尚未寫入之日）。"""
    root = Path(__file__).resolve().parents[1]
    dd = Path(data_dir) if data_dir else root / "data"
    history = _load_history(stock_id, dd)
    records = sorted(history.get("records") or [], key=lambda x: str(x.get("date", "")), reverse=True)

    stability: dict[str, int] = {}
    for broker in top6_details:
        bid = str(broker.get("broker_id", "")).strip()
        if not bid:
            continue
        streak = 0
        for r in records:
            ids = r.get("top6_ids") or []
            if bid in ids:
                streak += 1
            else:
                break
        stability[bid] = streak
    return stability


def detect_newcomers(
    stock_id: str,
    top6_details: list[dict[str, Any]],
    data_dir: Path | str | None = None,
) -> dict[str, bool]:
    """
    相對「上一筆歷史快照」不在 Top6、且今日淨額 > 200 張者視為新進大戶。
    """
    root = Path(__file__).resolve().parents[1]
    dd = Path(data_dir) if data_dir else root / "data"
    history = _load_history(stock_id, dd)
    records = sorted(history.get("records") or [], key=lambda x: str(x.get("date", "")), reverse=True)

    if not records:
        return {}

    yesterday_ids = set(str(x) for x in (records[0].get("top6_ids") or []))

    newcomers: dict[str, bool] = {}
    for broker in top6_details:
        bid = str(broker.get("broker_id", "")).strip()
        if not bid:
            continue
        n1d = float(broker.get("net_1d") or 0)
        is_new = bid not in yesterday_ids and n1d > 200.0
        newcomers[bid] = is_new
    return newcomers


def enrich_top6_phase7(
    stock_id: str,
    top6_details: list[dict[str, Any]],
    signals: dict[str, Any],
    trade_date: str,
    data_dir: Path | str | None = None,
) -> None:
    """
    在寫入歷史檔之前：補 consecutive_days、is_newcomer、group_name；
    signals 補 group_summary。
    """
    stability = compute_stability(stock_id, top6_details, data_dir)
    newcomers = detect_newcomers(stock_id, top6_details, data_dir)

    for broker in top6_details:
        bid = str(broker.get("broker_id", "")).strip()
        streak_hist = stability.get(bid, 0)
        broker["consecutive_days"] = max(1, streak_hist + 1)
        broker["is_newcomer"] = bool(newcomers.get(bid, False))
        broker["group_name"] = get_broker_group(bid, str(broker.get("broker_name") or ""))

    signals["group_summary"] = compute_group_summary(
        signals.get("top_buy_15"),
        signals.get("top_sell_15"),
    )
