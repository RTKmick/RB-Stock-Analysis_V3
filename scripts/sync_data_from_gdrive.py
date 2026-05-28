#!/usr/bin/env python3
"""
將 Google Drive 共用資料夾內的大檔（例如 TDR 快取 CSV）下載到本機專案目錄。

前置條件（Google 端）：
  - 資料夾「共用」設為：知道連結的使用者 → 檢視者（或檢視者以上）
  - 若下載失敗，常見原因是權限未開、或資料夾內有捷徑／捷徑迴圈

本機：
  pip install gdown

環境變數（擇一）：
  RB_GDRIVE_DATA_FOLDER_ID   僅資料夾 ID，例如 1L9H-Suhii63Zur1Md0FbUtA65a5n9UM4
  RB_GDRIVE_DATA_FOLDER_URL 完整網址，例如 https://drive.google.com/drive/folders/...

若 Drive 內目錄結構與本專一致，建議：
  data/cache/tdr/<股票代號>/<YYYY-MM-DD>.csv
則使用 --output 指向專案根下相對路徑 data/cache/tdr ，下載後可直接給 scraper_chip 當快取用。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_folder_id(url_or_id: str) -> str:
    s = (url_or_id or "").strip()
    if not s:
        raise ValueError("空的資料夾 ID／網址")
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", s)
    if m:
        return m.group(1)
    if re.match(r"^[a-zA-Z0-9_-]{15,}$", s):
        return s
    raise ValueError(
        "無法解析 Google Drive 資料夾 ID。請貼完整 folders/... 網址，或僅貼資料夾 ID。"
    )


def _folder_id_from_env() -> str | None:
    u = os.getenv("RB_GDRIVE_DATA_FOLDER_URL", "").strip()
    if u:
        return parse_folder_id(u)
    i = os.getenv("RB_GDRIVE_DATA_FOLDER_ID", "").strip()
    if i:
        return parse_folder_id(i)
    return None


def main() -> int:
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None  # type: ignore[misc, assignment]

    if load_dotenv:
        load_dotenv(_project_root() / ".env", override=False)

    parser = argparse.ArgumentParser(
        description="自 Google Drive 資料夾下載檔案到本機（需 gdown、資料夾須共用）"
    )
    parser.add_argument(
        "--folder-id",
        dest="folder_id",
        default=None,
        help="Drive 資料夾 ID 或完整 URL（預設讀 .env：RB_GDRIVE_DATA_FOLDER_ID / RB_GDRIVE_DATA_FOLDER_URL）",
    )
    parser.add_argument(
        "--output",
        dest="output",
        default="data/_gdrive_sync",
        help="下載目的地（相對專案根目錄），例如 data/cache/tdr",
    )
    args = parser.parse_args()

    raw = args.folder_id or _folder_id_from_env()
    if not raw:
        print(
            "[ERROR] 未指定資料夾。請傳 --folder-id，或在 .env 設定 "
            "RB_GDRIVE_DATA_FOLDER_ID / RB_GDRIVE_DATA_FOLDER_URL",
            file=sys.stderr,
        )
        return 2

    try:
        folder_id = parse_folder_id(raw)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    try:
        import gdown
    except ImportError:
        print("[ERROR] 請先安裝：pip install gdown", file=sys.stderr)
        return 1

    root = _project_root()
    out_dir = (root / args.output).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
    print(f"[INFO] 資料夾：{folder_url}", flush=True)
    print(f"[INFO] 輸出至：{out_dir}", flush=True)

    gdown.download_folder(
        id=folder_id,
        output=str(out_dir),
        quiet=False,
        use_cookies=False,
    )
    print("[INFO] 完成。", flush=True)
    print(
        "[HINT] 若 TDR 快取應在 data/cache/tdr/<股號>/ 下，請確認 Drive 內層級是否一致；"
        "否則可將 --output 設為 data/_gdrive_sync 再手動搬移。",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
