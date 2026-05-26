"""
Phase 16：共識升級警報 — 比對今天與昨天的 filtered_resonance，偵測狀態跳變。
規格：phase16_consensus_alert_and_cleanup_spec.md
前置：Phase 14（filtered_resonance）、Phase 15（signals_history）
"""
from __future__ import annotations

from typing import Any

from core.phase15_history import get_signals_history

LOOKBACK_DAYS = 5

ALERT_SEVERITY: dict[str, int] = {
    "CONSENSUS_FORMED": 85,
    "CONSENSUS_UPGRADED": 90,
    "CONSENSUS_REVERSED": 95,
    "CONSENSUS_COLLAPSED": 75,
    "CONSENSUS_DOWNGRADED": 60,
}


def _get_level(label: str | None) -> int:
    if label == "STRONG":
        return 3
    if label == "MODERATE":
        return 2
    return 0


def _fr_counts(fr: dict[str, Any]) -> tuple[int, int]:
    """即時 signals 用 consensus_count／non_dayhop_total；歷史快照用 count／total。"""
    c = int(fr.get("consensus_count") or fr.get("count") or 0)
    t = int(fr.get("non_dayhop_total") or fr.get("total") or 0)
    return c, t


def detect_consensus_alert(
    signals: dict[str, Any],
    stock_id: str,
    data_dir: str,
) -> dict[str, Any] | None:
    today_fr = signals.get("filtered_resonance") or {}
    today_label = today_fr.get("severity_label") or "NONE"
    today_dir = today_fr.get("direction")
    today_level = _get_level(str(today_label) if today_label is not None else None)

    history = get_signals_history(stock_id, data_dir, n_days=LOOKBACK_DAYS)
    if len(history) < 1:
        return None

    today_date = str(signals.get("_trade_date", "") or "")[:10] or None

    prev_record = None
    for rec in reversed(history):
        rec_date = str(rec.get("date", ""))[:10]
        if today_date and rec_date == today_date:
            continue
        prev_record = rec
        break

    if prev_record is None:
        return None

    prev_fr = prev_record.get("filtered_resonance") or {}
    # Phase 15 快照用 label；即時 signals 用 severity_label
    prev_label = prev_fr.get("severity_label") or prev_fr.get("label") or "NONE"
    prev_dir = prev_fr.get("direction")
    prev_level = _get_level(str(prev_label) if prev_label is not None else None)
    prev_date = str(prev_record.get("date", ""))[:10]

    alert_type: str | None = None
    alert_emoji = ""
    alert_text = ""

    if (
        today_level >= 2
        and prev_level >= 2
        and today_dir in ("BUY", "SELL")
        and prev_dir in ("BUY", "SELL")
        and today_dir != prev_dir
    ):
        alert_type = "CONSENSUS_REVERSED"
        dir_zh = "買" if today_dir == "BUY" else "賣"
        prev_dir_zh = "買" if prev_dir == "BUY" else "賣"
        alert_emoji = "🔄"
        alert_text = f"真主力共識反轉！{prev_dir_zh}→{dir_zh}"

    elif today_level == 3 and prev_level == 2 and today_dir == prev_dir:
        alert_type = "CONSENSUS_UPGRADED"
        dir_zh = "買" if today_dir == "BUY" else "賣"
        alert_emoji = "⬆️"
        alert_text = f"真主力共識升級 中→強 ({dir_zh})"

    elif today_level >= 2 and prev_level == 0:
        alert_type = "CONSENSUS_FORMED"
        dir_zh = "買" if today_dir == "BUY" else "賣"
        grade = "強" if today_level == 3 else "中"
        alert_emoji = "🔔"
        alert_text = f"真主力共識剛形成！{grade}共識{dir_zh}"

    elif today_level == 0 and prev_level >= 2:
        alert_type = "CONSENSUS_COLLAPSED"
        prev_dir_zh = "買" if prev_dir == "BUY" else "賣"
        alert_emoji = "⚠️"
        alert_text = f"真主力共識瓦解！({prev_dir_zh}共識消失)"

    elif today_level == 2 and prev_level == 3 and today_dir == prev_dir:
        alert_type = "CONSENSUS_DOWNGRADED"
        dir_zh = "買" if today_dir == "BUY" else "賣"
        alert_emoji = "⬇️"
        alert_text = f"真主力共識降級 強→中 ({dir_zh})"

    if alert_type is None:
        return None

    severity = ALERT_SEVERITY.get(alert_type, 50)
    tc, tt = _fr_counts(today_fr)
    pc, pt = _fr_counts(prev_fr)

    return {
        "alert_type": alert_type,
        "alert_emoji": alert_emoji,
        "alert_text": alert_text,
        "severity": severity,
        "today": {
            "label": today_label,
            "direction": today_dir,
            "count": tc,
            "total": tt,
        },
        "previous": {
            "date": prev_date,
            "label": prev_label,
            "direction": prev_dir,
            "count": pc,
            "total": pt,
        },
    }


def enrich_phase16_consensus_alert(
    signals: dict[str, Any],
    stock_id: str,
    data_dir: str,
    trade_date: str | None = None,
) -> None:
    if trade_date:
        signals["_trade_date"] = str(trade_date)[:10]

    alert = detect_consensus_alert(signals, stock_id, data_dir)
    signals["consensus_alert"] = alert
    signals.pop("_trade_date", None)
