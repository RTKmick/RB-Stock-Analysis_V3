#!/usr/bin/env python3
"""
Phase 19：聚合各檔 *_whale_track.json → data/market_pulse.json（市場大戶熱點）。

用法（專案根目錄）：
  python scripts/generate_market_pulse.py
"""
from __future__ import annotations

import json
from glob import glob
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "data" / "market_pulse.json"


def _lockup_max_score(lockup: dict[str, Any]) -> int:
    it = lockup.get("investment_trust") or {}
    fr = lockup.get("foreign") or {}
    try:
        return max(int(it.get("score") or 0), int(fr.get("score") or 0))
    except (TypeError, ValueError):
        return 0


def _latest_probe_date(stocks: list[dict[str, Any]]) -> str:
    dates = [str(s.get("probe_date") or "").strip() for s in stocks if s.get("probe_date")]
    return max(dates) if dates else ""


def _sort_key_hot(s: dict[str, Any]) -> tuple[float, float, int]:
    return (
        -float(s.get("severity") or 0),
        -float(s.get("filtered_count") or 0),
        -int(s.get("lockup_score") or 0),
    )


def _load_whale_track(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _stock_item(d: dict[str, Any]) -> dict[str, Any]:
    sig = d.get("signals") or {}
    if not isinstance(sig, dict):
        sig = {}
    wr = sig.get("whale_resonance") or {}
    if not isinstance(wr, dict):
        wr = {}
    fr = sig.get("filtered_resonance") or {}
    if not isinstance(fr, dict):
        fr = {}
    lockup = sig.get("lockup") or {}
    if not isinstance(lockup, dict):
        lockup = {}
    headline = d.get("headline") or {}
    if not isinstance(headline, dict):
        headline = {}

    def _i(x: Any) -> int:
        try:
            return int(x or 0)
        except (TypeError, ValueError):
            return 0

    return {
        "stock_id": str(d.get("stock_id") or "").strip(),
        "stock_name": str(d.get("stock_name") or "").strip(),
        "probe_date": str(d.get("probe_date") or "").strip(),
        "consensus_dir": wr.get("direction"),
        "consensus_count": _i(wr.get("consensus_count")),
        "consensus_total": 6,
        "severity_label": str(wr.get("severity_label") or "NONE").strip() or "NONE",
        "severity": _i(wr.get("severity")),
        "filtered_dir": fr.get("direction"),
        "filtered_count": _i(fr.get("consensus_count")),
        "filtered_total": _i(fr.get("non_dayhop_total")),
        "filtered_label": str(fr.get("severity_label") or "NONE").strip() or "NONE",
        "lockup_score": _lockup_max_score(lockup),
        "is_dual_lockup": bool(lockup.get("is_dual_lockup")),
        "score_unified": float(sig.get("score_unified") or 0) or 0.0,
        "action_signal": headline.get("action_signal"),
    }


def _compute_broker_activity(data_dir: Path) -> list[dict[str, Any]]:
    broker_map: dict[str, dict[str, Any]] = {}
    paths = sorted(glob(str(data_dir / "*_whale_track.json")))
    for fpath in paths:
        d = _load_whale_track(Path(fpath))
        if not d:
            continue
        sig = d.get("signals") or {}
        if not isinstance(sig, dict):
            sig = {}
        stock_id = str(d.get("stock_id") or "").strip()
        stock_name = str(d.get("stock_name") or "").strip()

        for b in (sig.get("top_buy_15") or [])[:6]:
            if not isinstance(b, dict):
                continue
            bid = str(b.get("broker_id") or "").strip()
            if not bid:
                continue
            net = float(b.get("net_lot") or 0)
            bm = broker_map.setdefault(
                bid,
                {
                    "broker_id": bid,
                    "broker_name": str(b.get("broker_name") or "").strip(),
                    "buy_stocks": [],
                    "sell_stocks": [],
                    "total_net": 0.0,
                },
            )
            if not bm.get("broker_name") and b.get("broker_name"):
                bm["broker_name"] = str(b.get("broker_name") or "").strip()
            bm["buy_stocks"].append(
                {
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "net_lot": round(net, 1),
                }
            )
            bm["total_net"] += net

        for b in (sig.get("top_sell_15") or [])[:6]:
            if not isinstance(b, dict):
                continue
            bid = str(b.get("broker_id") or "").strip()
            if not bid:
                continue
            net = float(b.get("net_lot") or 0)
            bm = broker_map.setdefault(
                bid,
                {
                    "broker_id": bid,
                    "broker_name": str(b.get("broker_name") or "").strip(),
                    "buy_stocks": [],
                    "sell_stocks": [],
                    "total_net": 0.0,
                },
            )
            if not bm.get("broker_name") and b.get("broker_name"):
                bm["broker_name"] = str(b.get("broker_name") or "").strip()
            bm["sell_stocks"].append(
                {
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "net_lot": round(net, 1),
                }
            )
            bm["total_net"] += net

    activity: list[dict[str, Any]] = []
    for bid, bm in broker_map.items():
        stock_count = len(bm["buy_stocks"]) + len(bm["sell_stocks"])
        if stock_count < 2:
            continue
        buy_c = len(bm["buy_stocks"])
        sell_c = len(bm["sell_stocks"])
        is_rotation = bool(bm["buy_stocks"] and bm["sell_stocks"])
        activity.append(
            {
                "broker_id": bid,
                "broker_name": bm["broker_name"] or bid,
                "stock_count": stock_count,
                "buy_count": buy_c,
                "sell_count": sell_c,
                "is_rotation": is_rotation,
                "total_net_lot": round(float(bm["total_net"]), 1),
                "buy_stocks": bm["buy_stocks"],
                "sell_stocks": bm["sell_stocks"],
            }
        )

    activity.sort(key=lambda x: (-x["stock_count"], -abs(float(x["total_net_lot"]))))
    return activity[:15]


def generate_market_pulse(data_dir: Path | None = None) -> dict[str, Any]:
    base = data_dir or (ROOT / "data")
    stocks: list[dict[str, Any]] = []
    paths = sorted(glob(str(base / "*_whale_track.json")))
    for fpath in paths:
        d = _load_whale_track(Path(fpath))
        if not d:
            continue
        item = _stock_item(d)
        if item["stock_id"]:
            stocks.append(item)

    hot_buy = sorted(
        [
            s
            for s in stocks
            if s.get("consensus_dir") == "BUY"
            and str(s.get("severity_label") or "NONE") != "NONE"
        ],
        key=_sort_key_hot,
    )
    hot_sell = sorted(
        [
            s
            for s in stocks
            if s.get("consensus_dir") == "SELL"
            and str(s.get("severity_label") or "NONE") != "NONE"
        ],
        key=_sort_key_hot,
    )

    return {
        "updated": _latest_probe_date(stocks),
        "stock_count": len(stocks),
        "hot_buy": hot_buy,
        "hot_sell": hot_sell,
        "broker_activity": _compute_broker_activity(base),
    }


def main() -> int:
    out = generate_market_pulse()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    nb = len(out.get("hot_buy") or [])
    ns = len(out.get("hot_sell") or [])
    nk = len(out.get("broker_activity") or [])
    print(f"[OK] market_pulse.json: hot_buy={nb}, hot_sell={ns}, broker_activity={nk}")
    if nb == 0 and ns == 0:
        print(
            "[WARN] hot_buy 與 hot_sell 皆為空：今日追蹤檔無 whale_resonance 共識（NONE 或未分方向）。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
