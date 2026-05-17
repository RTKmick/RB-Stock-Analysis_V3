"""每日訊號記錄、報酬回填、勝率統計（V1.8.0 歷史回測）。"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HISTORY_PATH = ROOT / "data" / "signal_history.json"
STATS_PATH = ROOT / "data" / "signal_stats.json"

_BACKFILL_NULLS = {
    "close_5d_later": None,
    "close_10d_later": None,
    "close_20d_later": None,
    "return_5d_pct": None,
    "return_10d_pct": None,
    "return_20d_pct": None,
}


def _trade_date_from_whale(data: dict[str, Any]) -> str:
    probe = str(data.get("probe_date") or "").strip()
    if probe and len(probe) >= 10:
        return probe[:10]
    lu = str(data.get("last_update") or "").strip()
    if lu and len(lu) >= 10:
        return lu[:10].replace("/", "-")
    return datetime.now().strftime("%Y-%m-%d")


def _close_from_whale(data: dict[str, Any]) -> float | None:
    enh = data.get("enhanced")
    if not isinstance(enh, dict):
        sig = data.get("signals") or {}
        if isinstance(sig, dict):
            enh = sig.get("enhanced") or {}
        else:
            enh = {}
    if not isinstance(enh, dict):
        enh = {}
    close_last = enh.get("close_last")
    if close_last is None:
        sig = data.get("signals") or {}
        if isinstance(sig, dict):
            e2 = sig.get("enhanced") or {}
            if isinstance(e2, dict):
                close_last = e2.get("close_last")
    if close_last is None:
        return None
    try:
        return float(close_last)
    except (TypeError, ValueError):
        return None


def _ensure_record(rec: dict[str, Any]) -> dict[str, Any]:
    for k, v in _BACKFILL_NULLS.items():
        rec.setdefault(k, v)
    for k in ("score_unified", "chip_light", "monitor_state", "final_grade"):
        rec.setdefault(k, None)
    return rec


def _build_record(data: dict[str, Any], stock_id: str, logged_at: str) -> dict[str, Any]:
    hl = data.get("headline") or {}
    sig = data.get("signals") or {}
    if not isinstance(sig, dict):
        sig = {}
    entry: dict[str, Any] = {
        "trade_date": _trade_date_from_whale(data),
        "stock_id": stock_id,
        "stock_name": data.get("stock_name") or stock_id,
        "action_signal": hl.get("action_signal") or "NEUTRAL",
        "close_last": _close_from_whale(data),
        "confidence": hl.get("confidence"),
        "logged_at": logged_at,
        "score_unified": sig.get("score_unified"),
        "chip_light": sig.get("chip_light"),
        "monitor_state": sig.get("monitor_state"),
        "final_grade": sig.get("final_grade"),
        **_BACKFILL_NULLS,
    }
    if entry["close_last"] is not None:
        entry["close_last"] = float(entry["close_last"])
    if entry["score_unified"] is not None:
        try:
            entry["score_unified"] = float(entry["score_unified"])
        except (TypeError, ValueError):
            entry["score_unified"] = None
    return entry


def _load_history() -> dict[str, Any]:
    if HISTORY_PATH.is_file():
        try:
            with open(HISTORY_PATH, encoding="utf-8") as f:
                store = json.load(f)
        except Exception:
            store = {}
    else:
        store = {}
    records = [_ensure_record(dict(r)) for r in (store.get("records") or []) if isinstance(r, dict)]
    store["records"] = records
    return store


def _save_history(store: dict[str, Any]) -> None:
    store["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def current_prices_from_whale_tracks() -> dict[str, float]:
    prices: dict[str, float] = {}
    for path in sorted((ROOT / "data").glob("*_whale_track.json")):
        sid = path.name.replace("_whale_track.json", "")
        if not sid.isdigit():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        close = _close_from_whale(data)
        if close is not None:
            prices[sid] = close
    return prices


def append_signal_history() -> int:
    """從 data/*_whale_track.json 追加當日訊號（同 trade_date+stock_id 去重更新）。"""
    pattern = list((ROOT / "data").glob("*_whale_track.json"))
    if not pattern:
        print("[WARN] no whale_track json; skip signal_history")
        return 0

    store = _load_history()
    records: list[dict[str, Any]] = list(store.get("records") or [])
    index = {
        (str(r.get("trade_date")), str(r.get("stock_id"))): i
        for i, r in enumerate(records)
        if r.get("trade_date") and r.get("stock_id")
    }
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
    added = updated = 0

    for path in pattern:
        sid = path.name.replace("_whale_track.json", "")
        if not sid.isdigit():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            print(f"[WARN] skip {path.name}: {exc}")
            continue

        entry = _build_record(data, sid, now_s)
        key = (entry["trade_date"], sid)
        if key in index:
            old = records[index[key]]
            for bf_key in _BACKFILL_NULLS:
                if old.get(bf_key) is not None:
                    entry[bf_key] = old[bf_key]
            records[index[key]] = entry
            updated += 1
        else:
            index[key] = len(records)
            records.append(entry)
            added += 1

    store["records"] = records
    _save_history(store)
    print(f"[OK] wrote {HISTORY_PATH} (+{added} new, {updated} updated, total {len(records)})")
    return 0


def backfill_returns(
    history_path: Path | None = None,
    current_prices: dict[str, float] | None = None,
) -> int:
    """回填歷史記錄的未來報酬率（日曆日近似交易日）。"""
    path = history_path or HISTORY_PATH
    store = _load_history() if path == HISTORY_PATH else json.loads(path.read_text(encoding="utf-8"))
    records = store.get("records") or []
    today = datetime.now().strftime("%Y-%m-%d")
    prices = current_prices if current_prices is not None else current_prices_from_whale_tracks()
    filled = 0

    for rec in records:
        trade_date = rec.get("trade_date", "")
        stock_id = str(rec.get("stock_id", ""))
        close_then = rec.get("close_last")
        if not trade_date or not stock_id or not close_then:
            continue
        try:
            close_then_f = float(close_then)
            if close_then_f <= 0:
                continue
        except (TypeError, ValueError):
            continue
        try:
            td = datetime.strptime(str(trade_date)[:10], "%Y-%m-%d")
            days_passed = (datetime.strptime(today, "%Y-%m-%d") - td).days
        except ValueError:
            continue

        current_price = prices.get(stock_id)
        if current_price is None:
            continue

        if days_passed >= 7 and rec.get("close_5d_later") is None:
            rec["close_5d_later"] = current_price
            rec["return_5d_pct"] = round((current_price - close_then_f) / close_then_f * 100, 2)
            filled += 1
        if days_passed >= 14 and rec.get("close_10d_later") is None:
            rec["close_10d_later"] = current_price
            rec["return_10d_pct"] = round((current_price - close_then_f) / close_then_f * 100, 2)
            filled += 1
        if days_passed >= 28 and rec.get("close_20d_later") is None:
            rec["close_20d_later"] = current_price
            rec["return_20d_pct"] = round((current_price - close_then_f) / close_then_f * 100, 2)
            filled += 1

    if path == HISTORY_PATH:
        _save_history(store)
    else:
        store["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] backfill_returns: {filled} field(s) filled")
    return filled


def compute_signal_stats(
    history_path: Path | None = None,
    output_path: Path | None = None,
    min_sample: int = 10,
) -> dict[str, Any]:
    """依 signal_history 計算各 action_signal 勝率與平均報酬。"""
    path = history_path or HISTORY_PATH
    out_path = output_path or STATS_PATH
    if path == HISTORY_PATH:
        store = _load_history()
    else:
        store = json.loads(path.read_text(encoding="utf-8"))
    records = store.get("records") or []

    by_signal: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        sig = r.get("action_signal")
        if sig:
            by_signal[str(sig)].append(r)

    stats: dict[str, Any] = {}
    total_with_5d = total_with_20d = 0
    for signal, recs in by_signal.items():
        s: dict[str, Any] = {"count": len(recs)}
        for period in ("5d", "10d", "20d"):
            key = f"return_{period}_pct"
            returns = [float(r[key]) for r in recs if r.get(key) is not None]
            n = len(returns)
            s[f"sample_size_{period}"] = n
            if period == "5d":
                total_with_5d += n
            if period == "20d":
                total_with_20d += n
            if n >= min_sample:
                s[f"avg_return_{period}_pct"] = round(sum(returns) / n, 2)
                wins = sum(1 for x in returns if x > 0)
                s[f"win_rate_{period}"] = round(wins / n, 2)
            else:
                s[f"avg_return_{period}_pct"] = None
                s[f"win_rate_{period}"] = None
        stats[signal] = s

    output = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_records": len(records),
        "total_with_5d_return": total_with_5d,
        "total_with_20d_return": total_with_20d,
        "by_signal": stats,
        "min_sample_size": min_sample,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"[OK] wrote {out_path} ({len(records)} records, {len(stats)} signals)")
    return output


def run_signal_history_pipeline(min_sample: int = 10) -> None:
    """append → backfill → stats（每日 pipeline 呼叫）。"""
    append_signal_history()
    prices = current_prices_from_whale_tracks()
    backfill_returns(current_prices=prices)
    compute_signal_stats(min_sample=min_sample)
