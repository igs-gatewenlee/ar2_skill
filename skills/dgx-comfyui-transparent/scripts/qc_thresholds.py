"""QC 閾值常數（集中管理）。

PRD 未指定數值者標「暫定」——日後依實際素材調校。
midtone_alpha_ratio 定義見 qc.midtone_alpha_ratio（分母=非全透明像素）。
"""

# --- midtone alpha (1~254) 佔「非全透明像素 (α>0)」的比例 ---
OPAQUE_MIDTONE_MAX = 0.15   # opaque：midtone > 此 → warning（疑似沒去乾淨/誤抓半透明）
SEMI_MIDTONE_MIN = 0.05     # semi：midtone < 此 → fail（被二值化、失去半透明意義）

# --- 構圖 / 殘留 ---
CONTENT_BBOX_MIN = 0.50     # 有效像素 bbox 佔全圖 < 此 → warning（多餘透明、建議重 trim）
CORNER_N = 16               # 邊角 N×N 區域檢查殘留背景（暫定）
CORNER_ALPHA_MAX = 0        # 邊角 alpha 應為 0；> 此（任一角有不透明）→ warning

# --- ⚠️ v1 未實作（R-2）---
# design §5.4 提及的 opaque 白/黑邊（fringe）與 semi 邊緣硬切（gradient）warning 在 v1
# **未實作**（無 BC 契約、run_qc 無對應邏輯）。先前預埋的 FRINGE_*/GRADIENT_* 常數已移除
# ——避免「定義閾值但邏輯不在」誤導為已交付（踩 spec §11 R-a / #001 反模式）。需要時連同
# run_qc 檢查 + fixture 測試一併補上。

# --- trim / alpha-fix 預設 ---
TRIM_ALPHA_THRESH = 10      # trim getbbox：alpha > 此算有效像素
DEFAULT_SHRINK = 1          # Route A 預設內縮 1px（去白邊）
DEFAULT_BLUR = 1.0          # Route A 預設邊緣羽化
DEFAULT_PADDING = 8         # trim 後保留透明邊界
