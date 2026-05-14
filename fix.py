# 🚨 V1.6.9 縮排錯誤修復指令 (給 AI)

> **注意 (To the AI Assistant applying this)**: 
> 你在前一次修改時，**把要修改的該行程式碼前面的空格（縮排）全部清空了**，導致原本正確的區塊現在出現了嚴重的 `IndentationError`。
> **請在執行以下的 Search/Replace 時，務必、絕對要保留程式碼前面的空格！不要把縮排吃掉！**
> Python 對縮排極度敏感，少一個空格程式就會崩潰。

---

## 檔案 1：`core/signals/institutional.py` (2 處錯誤)

### 錯誤 1：約第 130 行

**目前錯誤代碼（縮排被吃掉，跑到最左邊）**：
```python
out["inst_foreign_net_5d"] = _last_n_sum(foreign, 5)
            out["inst_trust_net_5d"] = _last_n_sum(trust, 5)
```

**✅ 修正為（請確保 `out["inst_foreign_net_5d"]` 前面有 12 個空格）**：
```python
            out["inst_foreign_net_5d"] = _last_n_sum(foreign, 5)
            out["inst_trust_net_5d"] = _last_n_sum(trust, 5)
```

### 錯誤 2：約第 257 行

**目前錯誤代碼**：
```python
    else:

out["margin_balance_20d_change"] = 0.0
        out["margin_risk_flag"] = 0
```

**✅ 修正為（請確保前面有 8 個空格）**：
```python
    else:
        out["margin_balance_20d_change"] = 0.0
        out["margin_risk_flag"] = 0
```

---

## 檔案 2：`core/pipeline.py` (6 處錯誤)

### 錯誤 1：約第 156 行

**目前錯誤代碼**：
```python
    c1, d1 = _layer_consensus(tier1_members)
    c2, d2 = _layer_consensus(tier2_members)
    rng1 = _cost_range_from_members(tier1_members)

rng2 = _cost_range_from_members(tier2_members)
```

**✅ 修正為（請確保 `rng2` 前面有 4 個空格）**：
```python
    c1, d1 = _layer_consensus(tier1_members)
    c2, d2 = _layer_consensus(tier2_members)
    rng1 = _cost_range_from_members(tier1_members)
    rng2 = _cost_range_from_members(tier2_members)
```

### 錯誤 2：約第 286-288 行

**目前錯誤代碼**：
```python
        try:
            parts.append(

f"估算大戶成本區 {float(c_low):.0f}~{float(c_high):.0f}，現價 {float(close_l):.0f}"
            )
```

**✅ 修正為（請確保 `f"估算...` 前面有 16 個空格）**：
```python
        try:
            parts.append(
                f"估算大戶成本區 {float(c_low):.0f}~{float(c_high):.0f}，現價 {float(close_l):.0f}"
            )
```

### 錯誤 3：約第 467 行

**目前錯誤代碼**：
```python
    # Top6 軌跡矩陣（累積 net）
    whale_detail = df_10d[df_10d["broker_id"].isin(top6_ids)].copy()
    pivot_net = whale_detail.pivot_table(index="date", columns="broker_name", values="net", aggfunc="sum").fillna(0)

pivot_cumsum = pivot_net.reindex(date_10d).fillna(0).cumsum()
```

**✅ 修正為（請確保 `pivot_cumsum` 前面有 4 個空格）**：
```python
    # Top6 軌跡矩陣（累積 net）
    whale_detail = df_10d[df_10d["broker_id"].isin(top6_ids)].copy()
    pivot_net = whale_detail.pivot_table(index="date", columns="broker_name", values="net", aggfunc="sum").fillna(0)

    pivot_cumsum = pivot_net.reindex(date_10d).fillna(0).cumsum()
```

### 錯誤 4：約第 579 行

**目前錯誤代碼**：
```python
    signals["pressure_ratio_20d"] = round((buy_sum_20 / denom_20), 4) if denom_20 > 0 else None
    signals["net_pressure_20d"] = round(((buy_sum_20 - sell_sum_20) / denom_20), 4) if denom_20 > 0 else None

buy_sum_5 = _safe_float(signals.get("top15_buy_sum_5", 0.0), 0.0)
    sell_sum_5 = _safe_float(signals.get("top15_sell_sum_5", 0.0), 0.0)
```

**✅ 修正為（請確保 `buy_sum_5` 前面有 4 個空格）**：
```python
    signals["pressure_ratio_20d"] = round((buy_sum_20 / denom_20), 4) if denom_20 > 0 else None
    signals["net_pressure_20d"] = round(((buy_sum_20 - sell_sum_20) / denom_20), 4) if denom_20 > 0 else None

    buy_sum_5 = _safe_float(signals.get("top15_buy_sum_5", 0.0), 0.0)
    sell_sum_5 = _safe_float(signals.get("top15_sell_sum_5", 0.0), 0.0)
```

### 錯誤 5：約第 690 行

**目前錯誤代碼**：
```python
    signals["trend_score"] = float(trend_pack.get("score", 0) or 0)
    signals["trend"] = trend_pack.get("trend", "")
    signals["tags"] = trend_pack.get("tags", [])

signals["score"] = signals["trend_score"]
    signals["score_unified"] = signals["trend_score"]
```

**✅ 修正為（請確保 `signals["score"]` 前面有 4 個空格）**：
```python
    signals["trend_score"] = float(trend_pack.get("score", 0) or 0)
    signals["trend"] = trend_pack.get("trend", "")
    signals["tags"] = trend_pack.get("tags", [])

    signals["score"] = signals["trend_score"]
    signals["score_unified"] = signals["trend_score"]
```

### 錯誤 6：約第 815 行

**目前錯誤代碼**：
```python
    elif chip_score >= 45.0:

chip_light = "yellow"
        chip_comment = "籌碼中性偏多，主力並不積極但也沒有明顯倒貨跡象，適合小部位試單或持續關注。"
```

**✅ 修正為（請確保 `chip_light` 前面有 8 個空格）**：
```python
    elif chip_score >= 45.0:
        chip_light = "yellow"
        chip_comment = "籌碼中性偏多，主力並不積極但也沒有明顯倒貨跡象，適合小部位試單或持續關注。"
```

---

## 給 AI 的最終驗證

在套用完這些變更後，請在終端機執行以下檢查：
```bash
python -m py_compile core/signals/institutional.py
python -m py_compile core/pipeline.py
```
如果沒有吐出任何錯誤（特別是 `IndentationError`），代表你成功保留了縮排。
