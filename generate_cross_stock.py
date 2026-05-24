#!/usr/bin/env python3
"""
Phase 9 R1：掃描所有 *_whale_track.json，產出 data/cross_stock_flow.json（跨股資金流向）。
規格：phase9_deep_tracking_spec.md
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from glob import glob
from pathlib import Path
from typing import Any


def _broker_key(row: dict[str, Any]) -> str:
    bid = str(row.get("broker_id") or "").strip()
    if bid:
        return bid
    nm = str(row.get("broker_name") or "").strip()
    return f"name:{nm}" if nm else ""


def generate_cross_stock_flow(data_dir: str | Path = "data") -> dict[str, Any]:
    data_dir = Path(data_dir)
    stocks: dict[str, dict[str, Any]] = {}

    pattern = str(data_dir / "*_whale_track.json")
    for fpath in sorted(glob(pattern)):
        fname = os.path.basename(fpath)
        try:
            with open(fpath, encoding="utf-8") as fp:
                d = json.load(fp)
        except (OSError, json.JSONDecodeError):
            continue
        sid = str(d.get("stock_id") or fname.split("_")[0]).strip()
        if not sid:
            continue
        stocks[sid] = d

    # (broker_key, stock_id) -> 累加淨額、顯示欄位
    cell: dict[tuple[str, str], dict[str, Any]] = {}

    for sid, d in stocks.items():
        sname = str(d.get("stock_name") or sid)
        sig = d.get("signals") or {}
        if not isinstance(sig, dict):
            sig = {}

        def _ingest(rows: list[Any], side: str) -> None:
            for b in rows or []:
                if not isinstance(b, dict):
                    continue
                bk = _broker_key(b)
                if not bk:
                    continue
                net = float(b.get("net_lot", 0) or 0)
                sk = (bk, sid)
                if sk not in cell:
                    cell[sk] = {
                        "stock_id": sid,
                        "stock_name": sname,
                        "net_lot": 0.0,
                        "side": side,
                        "broker_name": str(b.get("broker_name") or "").strip(),
                    }
                cell[sk]["net_lot"] = round(float(cell[sk]["net_lot"]) + net, 1)
                cell[sk]["side"] = side
                if b.get("broker_name"):
                    cell[sk]["broker_name"] = str(b.get("broker_name") or "").strip()

        _ingest(list(sig.get("top_buy_15") or []), "BUY")
        _ingest(list(sig.get("top_sell_15") or []), "SELL")

    broker_map: dict[str, list[dict[str, Any]]] = {}
    for (bk, _sid), pos in cell.items():
        broker_map.setdefault(bk, []).append(
            {
                "stock_id": pos["stock_id"],
                "stock_name": pos["stock_name"],
                "net_lot": pos["net_lot"],
                "side": pos["side"],
            }
        )

    cross_flows: list[dict[str, Any]] = []
    for broker_key, positions in broker_map.items():
        stock_set = {p["stock_id"] for p in positions}
        if len(stock_set) < 2:
            continue
        has_buy = any(float(p.get("net_lot", 0) or 0) > 0 for p in positions)
        has_sell = any(float(p.get("net_lot", 0) or 0) < 0 for p in positions)
        is_rotation = bool(has_buy and has_sell)
        total_net = sum(float(p.get("net_lot", 0) or 0) for p in positions)
        label = positions[0].get("broker_name") or ""
        if not label and broker_key.startswith("name:"):
            label = broker_key[5:]
        if not label:
            label = broker_key
        cross_flows.append(
            {
                "broker_id": broker_key if not broker_key.startswith("name:") else "",
                "broker_name": label,
                "stock_count": len(stock_set),
                "is_rotation": is_rotation,
                "total_net": round(total_net, 1),
                "positions": sorted(
                    positions,
                    key=lambda x: float(x.get("net_lot", 0) or 0),
                    reverse=True,
                ),
            }
        )

    cross_flows.sort(key=lambda x: (not x["is_rotation"], -x["stock_count"], -abs(x["total_net"])))

    updated = ""
    for d in stocks.values():
        pd = str(d.get("probe_date") or "")
        if pd > updated:
            updated = pd

    result: dict[str, Any] = {
        "updated": updated,
        "total_brokers_tracked": len(cross_flows),
        "rotation_count": sum(1 for c in cross_flows if c["is_rotation"]),
        "flows": cross_flows[:20],
    }

    out_path = data_dir / "cross_stock_flow.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(
        f"[OK] cross_stock_flow.json: {len(cross_flows)} brokers, "
        f"{result['rotation_count']} rotations, top flows={len(result['flows'])}"
    )
    return result


def append_cross_flow_history(data_dir: str | Path = "data") -> None:
    """將當日跨股流向摘要 append 至 data/cross_flow_history.json（最多保留 60 筆）。"""
    data_dir = Path(data_dir)
    today = datetime.now().strftime("%Y-%m-%d")
    history_path = data_dir / "cross_flow_history.json"

    history: dict[str, Any] = {"records": []}
    if history_path.is_file():
        try:
            with open(history_path, encoding="utf-8") as f:
                history = json.load(f)
        except (OSError, json.JSONDecodeError):
            history = {"records": []}

    if not isinstance(history.get("records"), list):
        history["records"] = []

    existing_dates = {str(r.get("date", "")) for r in history["records"]}
    if today in existing_dates:
        print(f"[skip] cross_flow_history: {today} already recorded")
        return

    flow_path = data_dir / "cross_stock_flow.json"
    if not flow_path.is_file():
        print("[warn] cross_stock_flow.json missing; skip history append")
        return

    try:
        with open(flow_path, encoding="utf-8") as f:
            flow = json.load(f)
    except (OSError, json.JSONDecodeError):
        print("[warn] cross_stock_flow.json unreadable; skip history append")
        return

    snapshot: dict[str, Any] = {
        "date": today,
        "rotation_count": int(flow.get("rotation_count", 0) or 0),
        "top_rotators": [],
    }

    for item in (flow.get("flows") or [])[:10]:
        if not isinstance(item, dict) or not item.get("is_rotation"):
            continue
        positions = list(item.get("positions") or [])
        top_buy = max(positions, key=lambda x: float(x.get("net_lot", 0) or 0)) if positions else None
        top_sell = min(positions, key=lambda x: float(x.get("net_lot", 0) or 0)) if positions else None

        snapshot["top_rotators"].append(
            {
                "broker": str(item.get("broker_name") or item.get("broker_id") or ""),
                "stock_count": int(item.get("stock_count", 0) or 0),
                "buying": str(top_buy.get("stock_name", "")) if top_buy else "",
                "buying_net": round(float(top_buy.get("net_lot", 0) or 0), 1) if top_buy else 0.0,
                "selling": str(top_sell.get("stock_name", "")) if top_sell else "",
                "selling_net": round(float(top_sell.get("net_lot", 0) or 0), 1) if top_sell else 0.0,
            }
        )

    history["records"].append(snapshot)
    history["records"] = history["records"][-60:]

    history_path.parent.mkdir(parents=True, exist_ok=True)
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"[OK] cross_flow_history: appended {today} ({len(snapshot['top_rotators'])} rotators)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 9：產出跨股資金流向 JSON")
    ap.add_argument(
        "--data-dir",
        default="data",
        help="資料目錄（預設 data）",
    )
    args = ap.parse_args()
    generate_cross_stock_flow(args.data_dir)
    append_cross_flow_history(args.data_dir)


if __name__ == "__main__":
    main()
