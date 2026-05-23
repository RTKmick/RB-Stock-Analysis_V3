#!/usr/bin/env python3
"""
RB-Stock-Analysis 每日策略日報（Phase 6）
Pipeline 跑完後執行：讀取 data/*_whale_track.json 與 market_context.json，摘要後推 Telegram。

憑證請設於環境變數（建議 .env）：
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
未設定時僅列印摘要並以 exit code 0 結束，不視為錯誤。
"""
from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime
from typing import Any

try:
    import requests
except ImportError:
    print("[ERR] 請安裝 requests：pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore[misc, assignment]


ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
DASHBOARD_URL = os.getenv("RB_DASHBOARD_URL", "https://rtkmick.github.io/RB-Stock-Analysis_V3/").strip()


def _load_dotenv() -> None:
    if load_dotenv:
        load_dotenv()


def send_telegram(text: str) -> bool:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        print("[INFO] 未設定 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，略過發送。")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            print("[OK] Telegram 發送成功")
            return True
        print(f"[ERR] Telegram 回應: {r.status_code} {r.text}")
        return False
    except Exception as e:
        print(f"[ERR] Telegram 發送失敗: {e}")
        return False


def load_all_stocks() -> dict[str, dict[str, Any]]:
    stocks: dict[str, dict[str, Any]] = {}
    pattern = os.path.join(DATA_DIR, "*_whale_track.json")
    for path in glob.glob(pattern):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if not isinstance(data, dict):
                continue
            sid = str(data.get("stock_id") or os.path.basename(path).split("_")[0])
            stocks[sid] = data
        except Exception:
            continue
    return stocks


def load_market_context() -> dict[str, Any] | None:
    path = os.path.join(DATA_DIR, "market_context.json")
    try:
        with open(path, encoding="utf-8") as f:
            out = json.load(f)
        return out if isinstance(out, dict) else None
    except Exception:
        return None


def _score_unified(sig: dict[str, Any]) -> Any:
    if sig.get("score_unified") is not None:
        return sig.get("score_unified")
    if sig.get("final_score") is not None:
        return sig.get("final_score")
    return sig.get("score", "-")


def build_report() -> str:
    stocks = load_all_stocks()
    market = load_market_context()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines: list[str] = []
    lines.append(f"📊 RB 籌碼日報 ({now})")
    lines.append("=" * 30)

    if market:
        t = market.get("taiex") or {}
        ms = market.get("market_state") or "NEUTRAL"
        ms_map = {
            "RISK_ON": "🟢 多頭格局",
            "CAUTIOUS": "🟡 留意風險",
            "NEUTRAL": "⚫ 方向不明",
            "RISK_OFF": "🔴 偏空警戒",
        }
        ms_text = ms_map.get(str(ms), "⚫ 觀察中")
        pct = float(t.get("change_pct") or 0)
        sign = "+" if pct >= 0 else ""
        lines.append("")
        lines.append(f"【大盤】 {ms_text}")
        lines.append(f"加權指數 {t.get('close', '-')} ({sign}{pct}%)")
        reason = market.get("market_state_reason") or ""
        if reason:
            lines.append(str(reason))
    else:
        lines.append("")
        lines.append("【大盤】 （無 market_context.json）")

    lines.append("")
    lines.append(f"【個股摘要】 ({len(stocks)} 檔)")
    lines.append("")

    priority = {"EXIT_ALERT": 0, "HOLD_WATCH": 1, "BUY_ZONE": 2, "NEUTRAL": 3}

    def sort_key(sid: str) -> tuple[int, str]:
        hl = (stocks[sid].get("headline") or {}) if isinstance(stocks[sid], dict) else {}
        act = str(hl.get("action_signal") or "NEUTRAL")
        return (priority.get(act, 3), sid)

    sorted_ids = sorted(stocks.keys(), key=sort_key)

    for sid in sorted_ids:
        d = stocks[sid]
        sig = d.get("signals") or {}
        if not isinstance(sig, dict):
            sig = {}
        hl = d.get("headline") or {}
        if not isinstance(hl, dict):
            hl = {}
        name = d.get("stock_name") or sid
        action = str(hl.get("action_signal") or "NEUTRAL")
        conf = hl.get("confidence", "-")
        score = _score_unified(sig)
        grade = sig.get("final_grade", "-")
        chip = sig.get("chip_light", "-")

        action_map = {
            "BUY_ZONE": "🟢買入",
            "HOLD_WATCH": "🟡觀望",
            "EXIT_ALERT": "🔴退出",
            "NEUTRAL": "⚫中性",
        }
        action_text = action_map.get(action, "⚫" + action)

        chip_map = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
        chip_icon = chip_map.get(str(chip), "⚫")

        f5 = float(sig.get("inst_foreign_net_5d") or 0)
        f5_val = f5 / 10000.0
        f5_sign = "+" if f5_val > 0 else ""
        f5_text = f"外資5D:{f5_sign}{f5_val:.0f}萬"

        lines.append(f"{name}({sid}) {action_text}")
        lines.append(f"  評分:{score} 評級:{grade} 信心:{conf} 籌碼:{chip_icon}")
        lines.append(f"  {f5_text}")
        lines.append("")

    alerts: list[str] = []
    exit_count = sum(
        1
        for d in stocks.values()
        if isinstance(d, dict) and (d.get("headline") or {}).get("action_signal") == "EXIT_ALERT"
    )
    if exit_count >= 2:
        alerts.append(f"🚨 {exit_count}/{len(stocks)} 檔觸發 EXIT_ALERT！")

    if market and market.get("market_state") == "RISK_OFF":
        alerts.append("🚨 大盤偏空警戒！")

    low_conf = 0
    for d in stocks.values():
        if not isinstance(d, dict):
            continue
        c = float((d.get("headline") or {}).get("confidence") or 50)
        if c < 40:
            low_conf += 1
    if stocks and low_conf > len(stocks) // 2:
        alerts.append(f"⚠️ {low_conf}/{len(stocks)} 檔信心度低於40")

    if alerts:
        lines.append("【⚠️ 警報】")
        for a in alerts:
            lines.append(a)
        lines.append("")

    lines.append("─" * 20)
    lines.append(f"Dashboard: {DASHBOARD_URL}")

    return "\n".join(lines)


def main() -> int:
    _load_dotenv()
    report = build_report()
    print(report)
    print("\n" + "=" * 40)
    send_telegram(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
