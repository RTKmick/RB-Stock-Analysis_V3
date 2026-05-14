import os

def fix_file(filepath, replacements):
    if not os.path.exists(filepath):
        print(f"找不到檔案：{filepath}，請確保你在專案根目錄執行此腳本。")
        return

    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    changed = False
    for i, line in enumerate(lines):
        for bad_line, good_line in replacements:
            if line.startswith(bad_line[:5]) and line.strip() == bad_line.strip() and not line.startswith(" "):
                lines[i] = good_line + '\n'
                changed = True
                print(f"🔧 已修復 {filepath} 第 {i+1} 行")
    
    if changed:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        print(f"✅ {filepath} 儲存成功！")
    else:
        print(f"👍 {filepath} 裡面沒有發現錯誤的縮排，可能已經修好了。")

institutional_fixes = [
    ('out["inst_foreign_net_5d"] = _last_n_sum(foreign, 5)', '            out["inst_foreign_net_5d"] = _last_n_sum(foreign, 5)'),
    ('out["margin_balance_20d_change"] = 0.0', '        out["margin_balance_20d_change"] = 0.0')
]

pipeline_fixes = [
    ('rng2 = _cost_range_from_members(tier2_members)', '    rng2 = _cost_range_from_members(tier2_members)'),
    ('f"估算大戶成本區 {float(c_low):.0f}~{float(c_high):.0f}，現價 {float(close_l):.0f}"', '                f"估算大戶成本區 {float(c_low):.0f}~{float(c_high):.0f}，現價 {float(close_l):.0f}"'),
    ('pivot_cumsum = pivot_net.reindex(date_10d).fillna(0).cumsum()', '    pivot_cumsum = pivot_net.reindex(date_10d).fillna(0).cumsum()'),
    ('buy_sum_5 = _safe_float(signals.get("top15_buy_sum_5", 0.0), 0.0)', '    buy_sum_5 = _safe_float(signals.get("top15_buy_sum_5", 0.0), 0.0)'),
    ('signals["score"] = signals["trend_score"]', '    signals["score"] = signals["trend_score"]'),
    ('chip_light = "yellow"', '        chip_light = "yellow"')
]

print("開始自動修復縮排...")
fix_file('core/signals/institutional.py', institutional_fixes)
fix_file('core/pipeline.py', pipeline_fixes)
print("修復完成！請執行 python -m py_compile core/pipeline.py 測試。")
