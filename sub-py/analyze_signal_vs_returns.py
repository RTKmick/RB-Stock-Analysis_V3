"""
Phase 1：Signal vs 未來報酬 — 分析腳本

讀取 backtest_signals_60d.csv，產出：
- Score 區間（0-40 / 40-60 / 60-80 / 80+）的未來 5/10/20 日報酬統計與分佈（含盈虧比 pl_ratio）
- Monitor state 的報酬統計
- 分數區間 × Monitor state（Confluence）交叉表（樣本數門檻可調）
- 可選流動性濾網：--min-avg-volume-20d-lot（張）、--liquidity-drop-bottom-pct（每日橫截面最低分位剔除）
- HTML 報告（表格 + 圖表 + 策略解讀備註）

使用方式：
  python SubPY/analyze_signal_vs_returns.py
  python SubPY/analyze_signal_vs_returns.py --csv data/backtest_signals_60d.csv --output data/signal_vs_returns_report.html
"""

from __future__ import annotations

import os
import sys
import argparse
from datetime import datetime

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DATA_PATH = os.path.join(PROJECT_ROOT, "data")
DEFAULT_CSV = os.path.join(DATA_PATH, "backtest_signals_60d.csv")
FIG_DIR = os.path.join(DATA_PATH, "signal_vs_returns_figures")

SCORE_BUCKETS = [(0, 40, "0-40"), (40, 60, "40-60"), (60, 80, "60-80"), (80, 101, "80+")]
RET_COLS = ["ret_5d", "ret_10d", "ret_20d"]


def _safe_int(x, default: int = 0) -> int:
    """安全地把值轉成 int，遇到 NaN 或例外時回傳預設值。"""
    try:
        if pd.isna(x):
            return default
        return int(x)
    except Exception:
        return default


def _score_bucket(score_series):
    """將 score 分桶，回傳 bucket 標籤。"""
    def bucket(x):
        if pd.isna(x):
            return None
        x = float(x)
        for lo, hi, label in SCORE_BUCKETS:
            if lo <= x < hi:
                return label
        return "80+"
    return score_series.map(bucket)


def _regime_row(row: pd.Series) -> str:
    """
    根據三大法人 + 融資/借券壓力標記，決定 Inst × Margin × SBL regime：
      - BULL_NO_SHORT: inst_bull_no_short_pressure_flag == 1
      - BEAR_WITH_SHORT: inst_bear_with_short_pressure_flag == 1
      - 其他: OTHER
    """
    b = _safe_int(row.get("inst_bull_no_short_pressure_flag"), 0)
    s = _safe_int(row.get("inst_bear_with_short_pressure_flag"), 0)
    if b == 1 and s == 0:
        return "BULL_NO_SHORT"
    if s == 1:
        return "BEAR_WITH_SHORT"
    return "OTHER"


def load_and_prepare(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype={"stock_id": str}, encoding="utf-8-sig")
    for c in RET_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    score_col = "final_score" if "final_score" in df.columns else "score"
    if score_col in df.columns:
        df["score_bucket"] = _score_bucket(df[score_col])
    else:
        df["score_bucket"] = None
    if "monitor_state" in df.columns:
        df["monitor_state"] = df["monitor_state"].fillna("NEUTRAL").astype(str)
    else:
        df["monitor_state"] = "NEUTRAL"

    if "avg_volume_20d_lot" in df.columns:
        df["avg_volume_20d_lot"] = pd.to_numeric(df["avg_volume_20d_lot"], errors="coerce")

    # Inst × Margin × SBL regime（若有新欄位則用 _regime_row 判斷，否則全部標為 OTHER）
    if (
        "inst_bull_no_short_pressure_flag" in df.columns
        or "inst_bear_with_short_pressure_flag" in df.columns
    ):
        df["inst_regime_flag"] = df.apply(_regime_row, axis=1)
    else:
        df["inst_regime_flag"] = "OTHER"
    return df


def apply_liquidity_filters(
    df: pd.DataFrame,
    min_avg_volume_20d_lot: float | None,
    liquidity_drop_bottom_pct: float | None,
) -> tuple[pd.DataFrame, dict]:
    """
    流動性防呆：剔除均量過低樣本，或依 trade_date 橫截面剔除最低流動性分位（預設關閉）。
    優先使用 avg_volume_20d_lot（backtest 新版欄位）；分位排名欄位優先用張數，否則退回 avg_turnover_20d。
    """
    meta: dict = {
        "initial_rows": int(len(df)),
        "excluded_min_volume": 0,
        "excluded_bottom_quantile": 0,
        "note_min_volume": "",
        "note_quantile": "",
        "liquidity_rank_col": "",
    }
    out = df.copy()
    if min_avg_volume_20d_lot is not None and float(min_avg_volume_20d_lot) > 0:
        thr = float(min_avg_volume_20d_lot)
        if "avg_volume_20d_lot" in out.columns and out["avg_volume_20d_lot"].notna().any():
            ok = out["avg_volume_20d_lot"].fillna(0) >= thr
            meta["excluded_min_volume"] = int((~ok).sum())
            out = out.loc[ok].copy()
        else:
            meta["note_min_volume"] = (
                "CSV 無 avg_volume_20d_lot，略過「最低張數」濾網；請重跑 backtest_signals_60d.py 產出新 CSV。"
            )

    if liquidity_drop_bottom_pct is not None and float(liquidity_drop_bottom_pct) > 0:
        pct = float(liquidity_drop_bottom_pct)
        if "trade_date" not in out.columns:
            meta["note_quantile"] = "無 trade_date，略過橫截面尾端剔除。"
        else:
            col = ""
            if "avg_volume_20d_lot" in out.columns and out["avg_volume_20d_lot"].notna().sum() > 0:
                col = "avg_volume_20d_lot"
            elif "avg_turnover_20d" in out.columns:
                col = "avg_turnover_20d"
            if col:
                rk = out.groupby("trade_date")[col].rank(pct=True, ascending=True, method="first")
                bad = rk <= pct
                meta["excluded_bottom_quantile"] = int(bad.sum())
                meta["liquidity_rank_col"] = col
                out = out.loc[~bad].copy()
            else:
                meta["note_quantile"] = "無 avg_volume_20d_lot / avg_turnover_20d，略過橫截面尾端剔除。"

    meta["final_rows"] = int(len(out))
    return out, meta


def _summarize_return_series(s: pd.Series) -> dict:
    s = pd.to_numeric(s, errors="coerce").dropna()
    if s.empty:
        return {}
    wins = s[s > 0]
    losses = s[s < 0]
    n = int(len(s))
    mean = float(s.mean())
    median = float(s.median())
    std = float(s.std()) if n > 1 else 0.0
    wr = float((s > 0).mean() * 100.0)
    avg_win = float(wins.mean()) if len(wins) else float("nan")
    avg_loss = float(losses.mean()) if len(losses) else float("nan")
    pl_ratio = float("nan")
    if len(wins) and len(losses) and avg_loss != 0:
        pl_ratio = float(avg_win / abs(avg_loss))
    return {
        "n": n,
        "mean": mean,
        "median": median,
        "std": std,
        "win_rate%": wr,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "pl_ratio": pl_ratio,
    }


def stats_by_group(df: pd.DataFrame, group_col: str, value_col: str) -> pd.DataFrame:
    """對 group_col 分組：n, mean, median, std, win_rate%, 平均獲利/平均虧損, 盈虧比。"""
    valid = df[[group_col, value_col]].dropna()
    if valid.empty:
        return pd.DataFrame()
    recs: list[dict] = []
    for name, grp in valid.groupby(group_col, dropna=False):
        st = _summarize_return_series(grp[value_col])
        if not st:
            continue
        row = {"_idx": name, **st}
        recs.append(row)
    out = pd.DataFrame(recs).set_index("_idx")
    out.index.name = group_col
    return out.round(4)


def stats_by_score_state(df: pd.DataFrame, value_col: str, min_cell_n: int) -> pd.DataFrame:
    """Score bucket × monitor_state 交叉統計（樣本數 >= min_cell_n 才列出）。"""
    valid = df.dropna(subset=["score_bucket", "monitor_state", value_col]).copy()
    if valid.empty:
        return pd.DataFrame()
    order_bucket = [lb for _, _, lb in SCORE_BUCKETS]
    order_state = ["ACCUMULATION", "MARKUP", "FADING", "DISTRIBUTION", "NEUTRAL"]
    recs: list[dict] = []
    for sb in order_bucket:
        for ms in order_state:
            sub = valid[(valid["score_bucket"] == sb) & (valid["monitor_state"] == ms)]
            st = _summarize_return_series(sub[value_col])
            if not st or st["n"] < min_cell_n:
                continue
            label = f"{sb} | {ms}"
            recs.append({"_idx": label, **st})
    if not recs:
        return pd.DataFrame()
    out = pd.DataFrame(recs).set_index("_idx")
    out.index.name = "score_x_state"
    return out.round(4)


def run_analysis(df: pd.DataFrame, ret_cols: list, min_cell_n: int = 8) -> dict:
    results = {
        "by_score": {},
        "by_state": {},
        "by_inst_regime": {},
        "by_score_state": {},
        "summary": [],
    }
    df_clean = df.dropna(subset=ret_cols, how="all").copy()
    if df_clean.empty:
        return results

    for col in ret_cols:
        if col not in df_clean.columns:
            continue
        if df_clean["score_bucket"].notna().any():
            by_score = stats_by_group(df_clean.dropna(subset=["score_bucket"]), "score_bucket", col)
            by_score = by_score.reindex([lb for _, _, lb in SCORE_BUCKETS])
            results["by_score"][col] = by_score
        by_state = stats_by_group(df_clean, "monitor_state", col)
        order = ["ACCUMULATION", "MARKUP", "FADING", "DISTRIBUTION", "NEUTRAL"]
        by_state = by_state.reindex([s for s in order if s in by_state.index])
        results["by_state"][col] = by_state

        results["by_score_state"][col] = stats_by_score_state(df_clean, col, min_cell_n=min_cell_n)

        # Inst × Margin × SBL regime（BULL_NO_SHORT / BEAR_WITH_SHORT / OTHER）
        if "inst_regime_flag" in df_clean.columns:
            by_regime = stats_by_group(df_clean, "inst_regime_flag", col)
            order_regime = ["BULL_NO_SHORT", "BEAR_WITH_SHORT", "OTHER"]
            by_regime = by_regime.reindex([s for s in order_regime if s in by_regime.index])
            results["by_inst_regime"][col] = by_regime

    results["n_total"] = len(df_clean)
    results["n_with_returns"] = df_clean[ret_cols].notna().any(axis=1).sum()
    return results


def write_html_report(
    results: dict, output_path: str, figures_dir: str, figure_files: list = None
) -> None:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    os.makedirs(figures_dir, exist_ok=True)
    figure_files = figure_files or []
    out_dir = os.path.dirname(output_path)
    rel_fig = os.path.relpath(figures_dir, out_dir) if out_dir else figures_dir
    rel_fig = rel_fig.replace("\\", "/")

    html = []
    html.append("<!DOCTYPE html><html lang=\"zh-TW\"><head><meta charset=\"UTF-8\">")
    html.append("<title>報酬分析：訊號 vs 未來報酬</title>")
    html.append("<style>body{font-family:Segoe UI,Microsoft JhengHei,sans-serif;background:#1a1a1a;color:#e0e0e0;padding:24px;} h1,h2{color:#f1c40f;} h3{color:#ddd;} table{border-collapse:collapse;margin:12px 0;} th,td{border:1px solid #444;padding:8px 12px;text-align:right;} th{background:#333;color:#f1c40f;} .n{text-align:center;} .meta{color:#888;font-size:0.9em;} .fig{max-width:90%;margin:16px 0;border:1px solid #444;}</style></head><body>")
    html.append("<h1>報酬分析：訊號 vs 未來報酬</h1>")
    html.append(f"<p class=\"meta\">報告產生時間：{datetime.now().strftime('%Y-%m-%d %H:%M')} ｜ 有效樣本數：{results.get('n_total', 0)}</p>")
    fm = results.get("filter_meta") or {}
    if fm and (
        int(fm.get("excluded_min_volume", 0) or 0) > 0
        or int(fm.get("excluded_bottom_quantile", 0) or 0) > 0
        or fm.get("note_min_volume")
        or fm.get("note_quantile")
        or int(fm.get("initial_rows", 0) or 0) != int(fm.get("final_rows", 0) or 0)
    ):
        irows = fm.get("initial_rows", results.get("n_total", 0))
        frows = fm.get("final_rows", results.get("n_total", 0))
        ex_v = fm.get("excluded_min_volume", 0)
        ex_q = fm.get("excluded_bottom_quantile", 0)
        lc = fm.get("liquidity_rank_col", "")
        parts = [
            f"流動性濾網：原始列數 {irows} -> 剩餘 {frows}（剔除均量過低 {ex_v} 筆、橫截面尾端 {ex_q} 筆）。"
        ]
        if lc:
            parts.append(f"橫截面排序欄位：{lc}。")
        if fm.get("note_min_volume"):
            parts.append(str(fm["note_min_volume"]))
        if fm.get("note_quantile"):
            parts.append(str(fm["note_quantile"]))
        html.append(f"<p class=\"meta\">{' '.join(parts)}</p>")

    html.append("<h2>策略檢視說明（Quant Review）</h2>")
    html.append(
        "<ul class=\"meta\">"
        "<li><b>分數區間</b>：特別比較 <code>60-80</code> 與 <code>80+</code>。"
        "若極高分區間的短天期報酬反而較弱，可能反映過熱或主力佈局末期（需搭配量能／大盤驗證）。</li>"
        "<li><b>盈虧比</b>：勝率僅為一維；<code>pl_ratio</code>＝「正報酬樣本平均 / |負報酬樣本平均|」。"
        "勝率不高但 pl_ratio 顯著大於 1 時，仍可能具正期望值。</li>"
        "<li><b>Confluence</b>：交叉表為「分數區間 | monitor_state」；可挑選例如「ACCUMULATION 且分數跨入 60-80」等組合（以樣本數與回測為準）。</li>"
        "<li><b>流動性</b>：建議以 CLI <code>--min-avg-volume-20d-lot 500</code>（張）或"
        "<code>--liquidity-drop-bottom-pct 0.05</code> 降低冷門股極端值扭曲；張數來自 backtest 之 <code>avg_volume_20d_lot</code>。</li>"
        "<li><b>大盤 Regime（未來擴充）</b>：籌碼在系統性空頭常失效；後續可於母體加入大盤相對季線等旗標再分層統計。</li>"
        "<li><b>下一步</b>：於交叉表尋找「ret_10d 中位數高且勝率&gt;55%」組合，作為儀表板 BUY_ZONE 等規則的實證依據。</li>"
        "</ul>"
    )

    # 映射 ret_* 欄位為中文說明
    ret_label = {
        "ret_5d": "5日報酬（ret_5d）",
        "ret_10d": "10日報酬（ret_10d）",
        "ret_20d": "20日報酬（ret_20d）",
    }

    # 欄位名稱中文化（n/mean/median/std/win_rate%）
    col_rename = {
        "n": "樣本數(N)",
        "mean": "平均值(mean)",
        "median": "中位數(median)",
        "std": "標準差(std)",
        "win_rate%": "勝率%(win_rate)",
        "avg_win": "平均獲利(>0)",
        "avg_loss": "平均虧損(<0)",
        "pl_ratio": "盈虧比(pl_ratio)",
    }

    # Monitor state 狀態值中文化
    state_rename = {
        "ACCUMULATION": "ACCUMULATION（吸籌/佈局期）",
        "MARKUP": "MARKUP（推升/趨勢延續）",
        "FADING": "FADING（退潮警戒）",
        "DISTRIBUTION": "DISTRIBUTION（派發警戒）",
        "NEUTRAL": "NEUTRAL（中性觀察）",
    }

    # Inst × Margin × SBL regime 狀態值中文化
    regime_rename = {
        "BULL_NO_SHORT": "BULL_NO_SHORT（偏多、空方壓力小）",
        "BEAR_WITH_SHORT": "BEAR_WITH_SHORT（偏空＋借券/空單壓力）",
        "OTHER": "OTHER（訊號混雜／方向不明）",
    }

    def _to_html_renamed(tb: pd.DataFrame, index_name: str | None = None) -> str:
        if tb is None or tb.empty:
            return "<p class=\"meta\">此區間暫無樣本。</p>"
        tb2 = tb.copy()
        # 重新命名欄位
        tb2.rename(columns=col_rename, inplace=True)
        # 重新命名 index（例如 monitor_state / inst_regime_flag）
        if index_name and tb2.index.name == index_name:
            if index_name == "monitor_state":
                tb2 = tb2.rename(index=state_rename)
            elif index_name == "inst_regime_flag":
                tb2 = tb2.rename(index=regime_rename)
        return (
            tb2.to_html(classes="n", float_format="%.4f")
            .replace("<th>", "<th class=\"n\">")
        )

    # By Score
    html.append("<h2>一、依分數區間看未來報酬</h2>")
    for col in RET_COLS:
        if col not in results.get("by_score", {}):
            continue
        tb = results["by_score"][col]
        if tb.empty:
            continue
        title = ret_label.get(col, col)
        html.append(f"<h3>{title}（依分數區間）</h3>")
        html.append(_to_html_renamed(tb))
        html.append("<br/>")
    html.append(
        "<p class=\"meta\">解讀：平均值 / 中位數代表該分數區間的平均 / 典型報酬；勝率% 為報酬&gt;0 的比例；"
        "盈虧比為正報酬子樣本均值除以負報酬子樣本均值的絕對值（兩側皆須有樣本）。"
        "請一併檢視 <code>80+</code> 是否出現「過熱反轉」（短天期不如 <code>60-80</code>）。</p>"
    )
    for fn in figure_files:
        if "ret_by_score_" in fn:
            name = os.path.basename(fn)
            html.append(f"<p><img class=\"fig\" src=\"{rel_fig}/{name}\" alt=\"{name}\"/></p>")

    # By Monitor state
    html.append("<h2>二、依主力監測狀態看報酬（Whale Trend Monitor）</h2>")
    for col in RET_COLS:
        if col not in results.get("by_state", {}):
            continue
        tb = results["by_state"][col]
        if tb.empty:
            continue
        title = ret_label.get(col, col)
        html.append(f"<h3>{title}（不同狀態）</h3>")
        html.append(_to_html_renamed(tb, index_name="monitor_state"))
        html.append("<br/>")
    html.append(
        "<p class=\"meta\">解讀：比較 ACCUMULATION / MARKUP 與 NEUTRAL / DISTRIBUTION 的報酬差異；"
        "可與「三、分數×狀態」交叉表併讀，尋找 Confluence。</p>"
    )
    for fn in figure_files:
        if "ret_by_state_" in fn:
            name = os.path.basename(fn)
            html.append(f"<p><img class=\"fig\" src=\"{rel_fig}/{name}\" alt=\"{name}\"/></p>")

    # By Score × Monitor state (Confluence)
    html.append("<h2>三、分數區間 × 主力狀態（Confluence）</h2>")
    html.append(
        "<p class=\"meta\">僅列出樣本數達門檻之組合；列名格式「分數區間 | monitor_state」。</p>"
    )
    for col in RET_COLS:
        if col not in results.get("by_score_state", {}):
            continue
        tb = results["by_score_state"][col]
        if tb is None or tb.empty:
            continue
        title = ret_label.get(col, col)
        html.append(f"<h3>{title}（交叉表）</h3>")
        html.append(_to_html_renamed(tb))
        html.append("<br/>")

    # By Inst × Margin × SBL Regime
    html.append("<h2>四、三大法人 × 融資 × 借券 狀態下的報酬</h2>")
    for col in RET_COLS:
        if col not in results.get("by_inst_regime", {}):
            continue
        tb = results["by_inst_regime"][col]
        if tb.empty:
            continue
        title = ret_label.get(col, col)
        html.append(f"<h3>{title}（不同資金壓力組合）</h3>")
        html.append(
            _to_html_renamed(tb, index_name="inst_regime_flag")
        )
        html.append("<br/>")
    html.append(
        "<p class=\"meta\">解讀："
        "樣本數(N)＝這種狀態在歷史上出現了多少個交易日；"
        "BULL_NO_SHORT（偏多、空方壓力小）＝三大法人 20 日合計偏多，且融資 / 借券壓力都不明顯；"
        "BEAR_WITH_SHORT（偏空＋借券/空單壓力）＝三大法人 20 日偏空，且借券 / 空單壓力放大；"
        "OTHER（訊號混雜／方向不明）＝多空訊號互相抵銷或不明顯。"
        "可用來設計多頭候選池（只挑 BULL_NO_SHORT），或避開高風險區（BEAR_WITH_SHORT）。</p>"
    )

    html.append("</body></html>")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html))
    print(f"[INFO] HTML 報告已寫入：{output_path}")


def try_plot_figures(df: pd.DataFrame, figures_dir: str, ret_cols: list) -> list:
    """若 matplotlib 可用，產出分佈圖並回傳檔名列表。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[WARN] 未安裝 matplotlib，略過圖表。可執行：pip install matplotlib")
        return []

    os.makedirs(figures_dir, exist_ok=True)
    plt.rcParams["figure.facecolor"] = "#1a1a1a"
    plt.rcParams["axes.facecolor"] = "#252525"
    plt.rcParams["axes.edgecolor"] = "#444"
    plt.rcParams["axes.labelcolor"] = "#e0e0e0"
    plt.rcParams["xtick.color"] = "#aaa"
    plt.rcParams["ytick.color"] = "#aaa"
    plt.rcParams["font.family"] = ["Microsoft JhengHei", "sans-serif"]
    files = []

    df_clean = df.dropna(subset=ret_cols, how="all").copy()
    if df_clean.empty or not df_clean["score_bucket"].notna().any():
        return files

    order_bucket = [lb for _, _, lb in SCORE_BUCKETS]
    order_state = ["ACCUMULATION", "MARKUP", "FADING", "DISTRIBUTION", "NEUTRAL"]

    for col in ret_cols:
        if col not in df_clean.columns:
            continue
        sub = df_clean[["score_bucket", col]].dropna()
        sub = sub[sub["score_bucket"].isin(order_bucket)]
        if sub.empty:
            continue
        pairs = [(lb, sub[sub["score_bucket"] == lb][col].values) for lb in order_bucket]
        data_by_bucket = [a for _, a in pairs if len(a) > 0]
        labels_bucket = [lb for lb, a in pairs if len(a) > 0]
        if not data_by_bucket:
            continue
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.boxplot(data_by_bucket, tick_labels=labels_bucket, patch_artist=True)
        ax.set_xlabel("Score 區間")
        ax.set_ylabel(col + " (報酬)")
        ax.axhline(0, color="#666", linestyle="--")
        ax.set_title(f"{col} 依 Score 區間分佈")
        fpath = os.path.join(figures_dir, f"ret_by_score_{col}.png")
        plt.savefig(fpath, bbox_inches="tight")
        plt.close()
        files.append(fpath)

    for col in ret_cols:
        if col not in df_clean.columns:
            continue
        sub = df_clean[["monitor_state", col]].dropna()
        sub = sub[sub["monitor_state"].isin(order_state)]
        if sub.empty:
            continue
        pairs = [(s, sub[sub["monitor_state"] == s][col].values) for s in order_state]
        data_by_state = [a for _, a in pairs if len(a) > 0]
        labels_used = [s for s, a in pairs if len(a) > 0]
        if not data_by_state:
            continue
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.boxplot(data_by_state, tick_labels=labels_used, patch_artist=True)
        ax.set_xlabel("Monitor state")
        ax.set_ylabel(col + " (報酬)")
        ax.axhline(0, color="#666", linestyle="--")
        ax.set_title(f"{col} 依 Monitor state 分佈")
        fpath = os.path.join(figures_dir, f"ret_by_state_{col}.png")
        plt.savefig(fpath, bbox_inches="tight")
        plt.close()
        files.append(fpath)

    if files:
        print(f"[INFO] 圖表已儲存至：{figures_dir}")
    return files


def main():
    parser = argparse.ArgumentParser(description="Phase 1: Signal vs 未來報酬分析")
    parser.add_argument("--csv", type=str, default=DEFAULT_CSV, help="backtest CSV 路徑")
    parser.add_argument("--output", type=str, default=os.path.join(DATA_PATH, "signal_vs_returns_report.html"), help="HTML 報告輸出路徑")
    parser.add_argument("--figures", type=str, default=FIG_DIR, help="圖表輸出目錄")
    parser.add_argument("--no-plot", action="store_true", help="不產出圖表（僅表格）")
    parser.add_argument(
        "--min-avg-volume-20d-lot",
        type=float,
        default=None,
        metavar="N",
        help="剔除 20 日均量（張）低於 N 的樣本；需 CSV 含 avg_volume_20d_lot（請重跑 backtest）",
    )
    parser.add_argument(
        "--liquidity-drop-bottom-pct",
        type=float,
        default=None,
        metavar="P",
        help="每個 trade_date 橫截面，剔除流動性最低 P 比例列（0~1，例如 0.05）",
    )
    parser.add_argument(
        "--min-score-state-n",
        type=int,
        default=8,
        metavar="K",
        help="分數×狀態交叉表最小樣本數（預設 8）",
    )
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        print(f"[ERR] 找不到 CSV：{args.csv}")
        print("請先執行：python SubPY/backtest_signals_60d.py --stock_ids 2317,2454,6239 --days 60")
        sys.exit(1)

    df = load_and_prepare(args.csv)
    df, filter_meta = apply_liquidity_filters(
        df,
        args.min_avg_volume_20d_lot,
        args.liquidity_drop_bottom_pct,
    )
    ret_cols = [c for c in RET_COLS if c in df.columns]
    if not ret_cols:
        print("[ERR] CSV 中沒有 ret_5d / ret_10d / ret_20d 欄位。")
        sys.exit(1)

    results = run_analysis(df, ret_cols, min_cell_n=args.min_score_state_n)
    results["filter_meta"] = filter_meta
    if results["n_total"] == 0:
        print("[WARN] 沒有同時具備 signals 與未來報酬的樣本。")
        sys.exit(0)

    # Console 簡表
    print("\n===== Score 區間 vs 未來報酬（摘要）=====")
    for col in ret_cols:
        if col in results.get("by_score", {}):
            print(f"\n{col}:")
            print(results["by_score"][col].to_string())
    print("\n===== Monitor state vs 未來報酬（摘要）=====")
    for col in ret_cols:
        if col in results.get("by_state", {}):
            print(f"\n{col}:")
            print(results["by_state"][col].to_string())
    print("\n===== Score x State (Confluence) 摘要 =====")
    for col in ret_cols:
        if col in results.get("by_score_state", {}):
            tb = results["by_score_state"][col]
            if tb is not None and not tb.empty:
                print(f"\n{col}:")
                print(tb.to_string())

    fig_files = []
    if not args.no_plot:
        fig_files = try_plot_figures(df, args.figures, ret_cols)
    write_html_report(results, args.output, args.figures, figure_files=fig_files)

    print("\n[OK] Phase 1 分析完成。請開啟 HTML 報告檢視：")
    print(f"   {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
