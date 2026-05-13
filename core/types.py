# core/types.py
from typing import Any, Dict, List, Literal, Optional, TypedDict


class TVDebug(TypedDict, total=False):
    close_last: float
    vwap_last: Optional[float]
    slope_vwap10: float
    z_vol20: float
    body_pct_last: float
    med_body_pct20: float
    obv_slope20: float
    ad_slope20: float
    atr10: float
    atr20: float
    compression: bool
    hvn_low: Optional[float]
    hvn_high: Optional[float]
    near_hvn: bool
    vol_shrink: bool
    hl_shrink: bool
    reason: str


class TVPack(TypedDict, total=False):
    sig_vwap: int
    sig_accumulation: int
    sig_rotation: int
    sig_profile_zone: int
    sig_structure_break: int
    tv_score: int
    tv_grade: Literal["weak", "watch", "strong"]
    tv_debug: TVDebug


class RegimePack(TypedDict, total=False):
    regime_score: float
    regime_trend: str
    regime_tags: List[str]


class TopRow(TypedDict, total=False):
    broker_id: str
    broker_name: str
    net_lot: float
    city: str
    broker_org_type: str
    streak_buy: int
    streak_sell: int


class WhaleSignals(TypedDict, total=False):
    concentration_5d: float
    concentration_20d: float

    netbuy_1d_lot: float
    netbuy_5d_lot: float
    netbuy_20d_lot: float

    buy_count_5d: int
    sell_count_5d: int
    breadth_5d: int
    breadth_ratio_5d: float

    buy_count_20d: int
    sell_count_20d: int
    breadth_20d: int
    breadth_ratio_20d: float

    foreign_net_5d: float
    local_net_5d: float

    top_buy_15: List[TopRow]
    top_sell_15: List[TopRow]

    labels_20d: List[str]
    buy_count_series_20d: List[int]
    sell_count_series_20d: List[int]
    breadth_series_20d: List[int]
    breadth_ratio_series_20d: List[float]


class FinalPack(TypedDict, total=False):
    score: float
    trend: str
    tags: List[str]

    final_score: float
    final_grade: Literal["A", "B", "C", "D"]
    weights: Dict[str, float]


class Signals(WhaleSignals, TVPack, RegimePack, FinalPack, total=False):
    # 允許未列出的 key 先存在（total=False + Any）
    # 若你要更嚴格，可移除這行並逐步補齊所有 signals keys
    pass


class Insight(TypedDict, total=False):
    history_labels: List[str]
    whale_data: List[Dict[str, Any]]
    total_whale_values: List[float]
    top6_details: List[Dict[str, Any]]
    signals: Signals
    whale_layers: Dict[str, Any]
    headline: Dict[str, Any]
