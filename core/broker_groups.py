"""
Phase 7：主力集團合併（分點代號前綴 + 名稱前綴）。
TWSE 分點代號規則可再擴充；名稱前綴補強未涵蓋代號。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

# 明確對照（代號不分大小寫）
BROKER_GROUPS: dict[str, list[str]] = {
    "元大": ["989G", "989H", "9846", "9859", "985A"],
    "富邦": ["6020", "6030", "6040", "6050"],
    "凱基": ["9200", "9230", "9268", "9270"],
    "國泰": ["6960", "6970"],
    "統一": ["5850", "5857", "5860"],
    "玉山": ["8840", "884B", "884C"],
    "台新": ["8150", "8160", "8180", "8200"],
    "群益": ["9100", "918E", "918e"],
    "永豐": ["9A00", "9A81"],
    "兆豐": ["7000", "700V"],
}

_NAME_PREFIX_GROUPS: list[tuple[str, str]] = [
    ("元大證券", "元大"),
    ("元大", "元大"),
    ("富邦證券", "富邦"),
    ("富邦", "富邦"),
    ("凱基證券", "凱基"),
    ("凱基", "凱基"),
    ("國泰證券", "國泰"),
    ("國泰", "國泰"),
    ("統一證券", "統一"),
    ("統一", "統一"),
    ("玉山證券", "玉山"),
    ("玉山", "玉山"),
    ("中信證券", "中信"),
    ("中國信託", "中信"),
    ("中信", "中信"),
    ("台新證券", "台新"),
    ("台新", "台新"),
    ("群益證券", "群益"),
    ("群益", "群益"),
    ("永豐證券", "永豐"),
    ("永豐", "永豐"),
    ("兆豐證券", "兆豐"),
    ("兆豐", "兆豐"),
    ("華南證券", "華南"),
    ("華南", "華南"),
    ("第一金證券", "第一金"),
    ("第一金", "第一金"),
]


def _norm_broker_id(broker_id: str) -> str:
    return str(broker_id or "").strip().upper()


def _group_by_id_prefix(bid: str) -> str | None:
    """常見券商代號區間（TWSE 習慣配置，可再微調）。"""
    if not bid:
        return None
    b = bid.upper()
    if b.startswith("980") or b.startswith("981") or b.startswith("982") or b.startswith("983"):
        return "元大"
    if b.startswith("602") or b.startswith("603") or b.startswith("604") or b.startswith("605"):
        return "富邦"
    if b.startswith("920") or b.startswith("921") or b.startswith("922") or b.startswith("923") or b.startswith("924") or b.startswith("925") or b.startswith("926") or b.startswith("927") or b.startswith("928") or b.startswith("929"):
        return "凱基"
    if b.startswith("696") or b.startswith("697") or b.startswith("698") or b.startswith("699"):
        return "國泰"
    if b.startswith("585") or b.startswith("586"):
        return "統一"
    if b.startswith("884"):
        return "玉山"
    if b.startswith("778") or b.startswith("779"):
        return "中信"
    if b.startswith("815") or b.startswith("816") or b.startswith("817") or b.startswith("818") or b.startswith("819") or b.startswith("820") or b.startswith("821") or b.startswith("822") or b.startswith("823") or b.startswith("824") or b.startswith("825"):
        return "台新"
    if b.startswith("910") or b.startswith("918"):
        return "群益"
    if b.startswith("9A0") or b.startswith("9A8"):
        return "永豐"
    if b.startswith("700") or b.startswith("701"):
        return "兆豐"
    return None


def get_broker_group(broker_id: str, broker_name: str | None = None) -> str | None:
    """回傳集團名稱；無則 None。"""
    bid = _norm_broker_id(broker_id)
    for gname, ids in BROKER_GROUPS.items():
        for x in ids:
            if bid == str(x).strip().upper():
                return gname
    g = _group_by_id_prefix(bid)
    if g:
        return g
    name = str(broker_name or "").strip()
    for prefix, gname in _NAME_PREFIX_GROUPS:
        if name.startswith(prefix):
            return gname
    return None


def compute_group_summary(
    top_buy_15: list[dict[str, Any]] | None,
    top_sell_15: list[dict[str, Any]] | None,
) -> list[list[Any]]:
    """合併集團淨額，回傳 [[名稱, 淨額張數], ...] 前 8 名（依絕對值）。"""
    group_net: dict[str, float] = defaultdict(float)
    for b in list(top_buy_15 or []) + list(top_sell_15 or []):
        bid = str(b.get("broker_id") or "")
        g = get_broker_group(bid, str(b.get("broker_name") or ""))
        key = g if g else str(b.get("broker_name") or bid or "other")
        group_net[key] += float(b.get("net_lot") or 0.0)
    sorted_groups = sorted(group_net.items(), key=lambda x: abs(x[1]), reverse=True)
    return [[k, round(v, 1)] for k, v in sorted_groups[:8]]
