"""
Phase 9：大戶深層追蹤 — 快取累積淨額、籌碼沉澱率。
規格：phase9_deep_tracking_spec.md
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


def _cache_csv_paths(cache_dir: Path) -> list[Path]:
    if not cache_dir.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(cache_dir.glob("*.csv")):
        if not p.is_file():
            continue
        # 略過 Windows 複製殘檔 e.g. 2026-05-22 (1).csv
        if re.search(r"\(\d+\)\.csv$", p.name):
            continue
        out.append(p)
    return out


def _read_tdr_cache_csv(path: Path) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError, pd.errors.ParserError):
        return None
    if df.empty:
        return None
    if "broker_id" not in df.columns and "securities_trader_id" in df.columns:
        df = df.rename(columns={"securities_trader_id": "broker_id"})
    need = {"broker_id", "buy", "sell"}
    if not need.issubset(df.columns):
        return None
    return df


def enrich_top6_accumulated_from_cache(
    stock_id: str,
    top6_details: list[dict[str, Any]],
    data_dir: Path | str,
) -> None:
    """
    依 data/cache/tdr/{stock_id}/*.csv 彙總各分點累積淨額與有資料天數。
    快取涵蓋幾天就加總幾天（規格以 60 天為目標，與 scraper --days 一致即可）。
    """
    root = Path(data_dir)
    cache_dir = root / "cache" / "tdr" / str(stock_id)
    acc_net: dict[str, float] = defaultdict(float)
    acc_days: dict[str, int] = defaultdict(int)

    for csv_path in _cache_csv_paths(cache_dir):
        df = _read_tdr_cache_csv(csv_path)
        if df is None:
            continue
        df["broker_id"] = df["broker_id"].astype(str).str.strip()
        df["buy"] = pd.to_numeric(df["buy"], errors="coerce").fillna(0.0)
        df["sell"] = pd.to_numeric(df["sell"], errors="coerce").fillna(0.0)
        for bid, grp in df.groupby("broker_id"):
            b = str(bid).strip()
            if not b:
                continue
            day_net = float(grp["buy"].sum()) - float(grp["sell"].sum())
            acc_net[b] += day_net
            acc_days[b] += 1

    for broker in top6_details:
        bid = str(broker.get("broker_id", "")).strip()
        if not bid:
            broker["accumulated_net"] = 0.0
            broker["active_days"] = 0
            continue
        broker["accumulated_net"] = round(float(acc_net.get(bid, 0.0)), 1)
        broker["active_days"] = int(acc_days.get(bid, 0))


def compute_chip_settlement_rate(df_20d: pd.DataFrame, top6_ids: list[str]) -> float:
    """
    Top6 在 20 日內淨額絕對值合計 / 全市場 20 日買賣量合計（皆來自分點表，單位一致）。
    """
    if df_20d is None or df_20d.empty:
        return 0.0
    ids = {str(x).strip() for x in top6_ids}
    sub = df_20d[df_20d["broker_id"].astype(str).str.strip().isin(ids)]
    top6_net_abs = float(sub["net"].abs().sum()) if not sub.empty else 0.0
    market_vol = float(df_20d["buy"].sum()) + float(df_20d["sell"].sum())
    if market_vol <= 0:
        return 0.0
    return round(min(1.0, top6_net_abs / market_vol), 4)


def enrich_phase9(
    stock_id: str,
    top6_details: list[dict[str, Any]],
    signals: dict[str, Any],
    df_20d: pd.DataFrame,
    top6_ids: list[str],
    data_dir: Path | str,
) -> None:
    """Phase 9：累積部位 + 沉澱率。"""
    dd = Path(data_dir)
    enrich_top6_accumulated_from_cache(stock_id, top6_details, dd)
    signals["chip_settlement_rate"] = compute_chip_settlement_rate(df_20d, top6_ids)
