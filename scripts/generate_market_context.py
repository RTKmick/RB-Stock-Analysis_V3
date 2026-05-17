#!/usr/bin/env python3
"""
產出 data/market_context.json（TWSE 加權指數、三大法人、融資融券 + 市場狀態）。
用法：python scripts/generate_market_context.py [--date YYYYMMDD]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ROOT = Path(__file__).resolve().parents[1]
SESSION = requests.Session()
SESSION.headers.update(TWSE_HEADERS := {
    "User-Agent": "Mozilla/5.0 (compatible; RB-Stock-Analysis/1.0)",
    "Accept": "application/json",
})
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_PATH = ROOT / "data" / "market_context.json"


def _fetch_twse(url: str, date_yyyymmdd: str) -> dict[str, Any] | None:
    try:
        r = SESSION.get(
            url,
            params={"response": "json", "date": date_yyyymmdd},
            timeout=25,
            verify=False,
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            return None
        if data.get("stat") and str(data.get("stat")).upper() not in ("OK", ""):
            return None
        return data
    except Exception as exc:
        print(f"[WARN] TWSE fetch failed {url} {date_yyyymmdd}: {exc}")
        return None


def _fetch_twse_on_date(url: str, date_yyyymmdd: str) -> dict[str, Any] | None:
    """僅在 API 回傳 date 與請求日一致時採用（避免假日重複最近交易日）。"""
    payload = _fetch_twse(url, date_yyyymmdd)
    if not payload:
        return None
    api_date = str(payload.get("date") or "").strip()
    if api_date and api_date != date_yyyymmdd:
        return None
    return payload


def _table_rows(payload: dict[str, Any] | None) -> list[list[Any]]:
    if not payload:
        return []
    rows = payload.get("data")
    if isinstance(rows, list) and rows:
        return [r for r in rows if isinstance(r, list) and r]
    tables = payload.get("tables")
    if not isinstance(tables, list):
        return []
    out: list[list[Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        data = table.get("data")
        if isinstance(data, list):
            out.extend(r for r in data if isinstance(r, list) and r)
    return out


def _parse_num(v: Any) -> float:
    if v is None:
        return 0.0
    s = str(v).strip().replace(",", "").replace("--", "0")
    if not s or s in ("-", "X", "x"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _find_latest_trading_date(max_back: int = 14) -> datetime:
    d = datetime.now()
    for _ in range(max_back):
        ymd = d.strftime("%Y%m%d")
        payload = _fetch_twse(
            "https://www.twse.com.tw/exchangeReport/FMTQIK", ymd
        )
        rows = _table_rows(payload)
        if len(rows) >= 2:
            return d
        d -= timedelta(days=1)
    return datetime.now()


def _fetch_taiex_series(end: datetime, n: int = 25) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    d = end
    tries = 0
    while len(out) < n and tries < n + 30:
        ymd = d.strftime("%Y%m%d")
        payload = _fetch_twse(
            "https://www.twse.com.tw/exchangeReport/FMTQIK", ymd
        )
        for row in _table_rows(payload):
            if len(row) < 6:
                continue
            # 欄位：日期, 成交股數, 成交金額, 成交筆數, 收盤指數, ...
            close = _parse_num(row[4])
            if close <= 0:
                continue
            date_key = str(row[0]).strip()
            if not any(t[0] == date_key for t in out):
                out.append((date_key, close))
        d -= timedelta(days=1)
        tries += 1
    out.sort(key=lambda x: x[0])
    return out[-n:]


def _row_net_amount(row: list[Any]) -> float:
    """BFI82U 欄位：名稱, 買進, 賣出, 買賣差額（元）。"""
    if len(row) >= 4:
        net = _parse_num(row[3])
        if net != 0.0:
            return net
    if len(row) >= 3:
        return _parse_num(row[1]) - _parse_num(row[2])
    return 0.0


def _fetch_institutional_day(date_yyyymmdd: str) -> dict[str, float] | None:
    payload = _fetch_twse_on_date(
        "https://www.twse.com.tw/fund/BFI82U", date_yyyymmdd
    )
    if not payload:
        return None
    rows = _table_rows(payload)
    foreign = trust = dealer = 0.0
    for row in rows:
        name = str(row[0]).strip()
        if not name or "合計" in name:
            continue
        net = _row_net_amount(row)
        if "外資及陸資" in name or "外陸資" in name:
            foreign += net
        elif name == "投信":
            trust = net
        elif "自營商" in name:
            dealer += net
    three = foreign + trust + dealer
    return {
        "foreign": foreign,
        "trust": trust,
        "dealer": dealer,
        "three": three,
    }


def _fetch_margin_day(date_yyyymmdd: str) -> dict[str, float] | None:
    payload = _fetch_twse_on_date(
        "https://www.twse.com.tw/exchangeReport/MI_MARGN", date_yyyymmdd
    )
    if not payload:
        return None
    rows = _table_rows(payload)
    margin_bal = 0.0
    short_bal = 0.0
    for row in rows:
        if len(row) < 6:
            continue
        name = str(row[0]).strip()
        today = _parse_num(row[5])
        if "融資金額" in name:
            margin_bal = today * 1000.0
        elif name.startswith("融券") and "交易單位" in name:
            short_bal = today
    return {"margin_balance": margin_bal, "short_balance": short_bal}


def _foreign_momentum_label(net_5d: float, net_20d: float) -> str:
    speed_5 = net_5d / 5.0
    speed_20 = net_20d / 20.0
    if speed_20 != 0:
        ratio = speed_5 / speed_20
        if ratio >= 1.3:
            momentum = "ACCELERATING"
        elif ratio <= 0.7:
            momentum = "DECELERATING"
        else:
            momentum = "STABLE"
    else:
        momentum = "NEUTRAL"
    if net_20d > 0:
        base = "BUY"
    elif net_20d < 0:
        base = "SELL"
    else:
        base = "NEUTRAL"
    return f"{base}_{momentum}"


def _foreign_streak_sell(daily_foreign: list[float]) -> int:
    streak = 0
    for v in reversed(daily_foreign):
        if v < 0:
            streak += 1
        else:
            break
    return streak


def compute_market_state(
    taiex: dict[str, Any],
    institutional: dict[str, Any],
    margin: dict[str, Any],
) -> tuple[str, str]:
    score = 0
    t20 = float(taiex.get("trend_20d_pct") or 0)
    if t20 > 3:
        score += 2
    elif t20 > 0:
        score += 1
    elif t20 < -3:
        score -= 2
    else:
        score -= 1

    if float(institutional.get("foreign_net_5d") or 0) > 0:
        score += 1
    elif int(institutional.get("foreign_streak_sell") or 0) >= 3:
        score -= 2
    else:
        score -= 1

    if float(institutional.get("trust_net_5d") or 0) > 0:
        score += 1

    if float(margin.get("margin_balance_change_5d_pct") or 0) > 5:
        score -= 1

    if score >= 3:
        return "RISK_ON", "市場多頭格局，法人資金積極流入"
    if score >= 1:
        return "CAUTIOUS", "市場偏多但有分歧訊號，留意風險"
    if score >= -1:
        return "NEUTRAL", "市場方向不明，觀望為宜"
    return "RISK_OFF", "市場偏空，法人資金持續流出"


def build_market_context(as_of: datetime | None = None) -> dict[str, Any]:
    end = as_of or _find_latest_trading_date()
    series = _fetch_taiex_series(end, 25)
    if len(series) < 2:
        raise RuntimeError("無法取得加權指數序列，請稍後再試或確認 TWSE API。")

    closes = [c for _, c in series]
    dates = [d for d, _ in series]
    close = closes[-1]
    prev = closes[-2] if len(closes) >= 2 else close
    change = close - prev
    change_pct = (change / prev * 100.0) if prev else 0.0
    close_5d = closes[-6] if len(closes) >= 6 else closes[0]
    close_20d = closes[-21] if len(closes) >= 21 else closes[0]
    trend_5d = ((close - close_5d) / close_5d * 100.0) if close_5d else 0.0
    trend_20d = ((close - close_20d) / close_20d * 100.0) if close_20d else 0.0
    series_20d = closes[-20:]

    inst_days: list[dict[str, float]] = []
    d = end
    tries = 0
    while len(inst_days) < 20 and tries < 50:
        ymd = d.strftime("%Y%m%d")
        day = _fetch_institutional_day(ymd)
        if day is not None:
            inst_days.append(day)
        d -= timedelta(days=1)
        tries += 1
    inst_days = list(reversed(inst_days))

    foreign_daily = [x["foreign"] for x in inst_days]
    trust_daily = [x["trust"] for x in inst_days]
    dealer_daily = [x["dealer"] for x in inst_days]
    three_daily = [x["three"] for x in inst_days]

    def _sum_last(arr: list[float], n: int) -> float:
        if not arr:
            return 0.0
        return float(sum(arr[-n:]))

    foreign_1d = foreign_daily[-1] if foreign_daily else 0.0
    foreign_5d = _sum_last(foreign_daily, 5)
    foreign_20d = _sum_last(foreign_daily, 20)
    trust_1d = trust_daily[-1] if trust_daily else 0.0
    trust_5d = _sum_last(trust_daily, 5)
    trust_20d = _sum_last(trust_daily, 20)
    dealer_1d = dealer_daily[-1] if dealer_daily else 0.0
    three_1d = three_daily[-1] if three_daily else 0.0
    three_5d = _sum_last(three_daily, 5)

    margin_series: list[dict[str, float]] = []
    d = end
    tries = 0
    while len(margin_series) < 6 and tries < 30:
        ymd = d.strftime("%Y%m%d")
        mday = _fetch_margin_day(ymd)
        if mday is not None and mday["margin_balance"] > 0:
            margin_series.append(mday)
        d -= timedelta(days=1)
        tries += 1
    margin_series = list(reversed(margin_series))
    margin_bal = margin_series[-1]["margin_balance"] if margin_series else 0.0
    margin_5d_ago = margin_series[-6]["margin_balance"] if len(margin_series) >= 6 else margin_bal
    short_bal = margin_series[-1]["short_balance"] if margin_series else 0.0
    short_5d_ago = margin_series[-6]["short_balance"] if len(margin_series) >= 6 else short_bal
    margin_chg_5d = (
        ((margin_bal - margin_5d_ago) / margin_5d_ago * 100.0) if margin_5d_ago else 0.0
    )
    short_chg_5d = (
        ((short_bal - short_5d_ago) / short_5d_ago * 100.0) if short_5d_ago else 0.0
    )

    institutional = {
        "foreign_net_1d": foreign_1d,
        "foreign_net_5d": foreign_5d,
        "foreign_net_20d": foreign_20d,
        "foreign_streak_sell": _foreign_streak_sell(foreign_daily),
        "trust_net_1d": trust_1d,
        "trust_net_5d": trust_5d,
        "trust_net_20d": trust_20d,
        "dealer_net_1d": dealer_1d,
        "three_net_1d": three_1d,
        "three_net_5d": three_5d,
        "foreign_momentum": _foreign_momentum_label(foreign_5d, foreign_20d),
    }
    margin = {
        "margin_balance": margin_bal,
        "margin_balance_change_5d_pct": round(margin_chg_5d, 2),
        "short_balance": short_bal,
        "short_balance_change_5d_pct": round(short_chg_5d, 2),
    }
    taiex = {
        "close": round(close, 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "close_5d_ago": round(close_5d, 2),
        "close_20d_ago": round(close_20d, 2),
        "trend_5d_pct": round(trend_5d, 2),
        "trend_20d_pct": round(trend_20d, 2),
        "series_20d": [round(x, 2) for x in series_20d],
        "as_of_date": dates[-1] if dates else end.strftime("%Y/%m/%d"),
    }
    state, reason = compute_market_state(taiex, institutional, margin)
    return {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "taiex": taiex,
        "institutional": institutional,
        "margin": margin,
        "market_state": state,
        "market_state_reason": reason,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate data/market_context.json")
    parser.add_argument(
        "--date",
        help="參考交易日 YYYYMMDD（預設：自動找最近有資料之日）",
    )
    parser.add_argument(
        "--keep-on-fail",
        action="store_true",
        help="TWSE 失敗時保留既有 market_context.json（若存在）",
    )
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="不更新 data/signal_history.json",
    )
    args = parser.parse_args()
    as_of = None
    if args.date:
        as_of = datetime.strptime(args.date, "%Y%m%d")

    try:
        ctx = build_market_context(as_of)
    except Exception as exc:
        if args.keep_on_fail and OUT_PATH.is_file():
            print(f"[WARN] {exc}")
            print(f"[OK] kept existing {OUT_PATH}")
            return 0
        raise

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(ctx, f, ensure_ascii=False, indent=2)
    print(f"[OK] wrote {OUT_PATH}")
    inst = ctx.get("institutional") or {}
    margin = ctx.get("margin") or {}
    print(
        f"     market_state={ctx['market_state']} | {ctx['market_state_reason']}"
    )
    print(
        f"     外資1d={inst.get('foreign_net_1d', 0)/1e8:.1f}億 "
        f"外資5d={inst.get('foreign_net_5d', 0)/1e8:.1f}億 "
        f"融資餘額={margin.get('margin_balance', 0)/1e8:.0f}億"
    )
    if not args.no_history:
        from core.signal_history import run_signal_history_pipeline

        run_signal_history_pipeline()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
