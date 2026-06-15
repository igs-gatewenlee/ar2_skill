"""spine QC 閾值常數（集中管理）。

所有數值標「暫定·tunable·待多角色樣本校準」(P1 設計規格 R-2)——目前只有 1 個 PoC
角色的數據基礎，首批跑真資料後再調。
"""

# 部件齊全（B-2 拍板 + R-1 實測否證後：legs 移出 v1 → v2，v1=上肢 4 件）
EXPECTED_PARTS = ("head", "torso", "upper_arm_l", "upper_arm_r")

# 切件中間檔前綴（BC-8：QC bijection 不把這些當部件）
INTERMEDIATE_PREFIXES = (
    "hint", "sam", "refmask", "legmask", "mask", "source",
    "viz", "composite", "reference", "starpose", "poc",
)

# 預設 draw_order（小=底層先畫；沿用 PoC manifest 語意：torso 底 / head / arm 前）
DEFAULT_DRAW_ORDER = {"torso": 0, "head": 1, "upper_arm_l": 2, "upper_arm_r": 2}

# --- QC 閾值（全部暫定·tunable）---
ALPHA_OPAQUE_THRESH = 10        # part alpha > 此 = 不透明（content_bbox / 覆蓋 / 重疊用）
ARM_SEPARATION_MAX = 0.05       # 閘4 上肢左右件重疊/較小件面積 ≤ 此（PoC 實證 0%，門檻暫定）
SYMMETRY_AREA_RATIO_MIN = 0.6   # 閘5 min(area_l,area_r)/max ≥ 此
SYMMETRY_CENTER_Y_TOL = 0.10    # 閘5 兩件中心 y 差 / ref_h ≤ 此
HOLE_AREA_MAX = 0.02            # 閘6 部件內封閉透明洞面積 / 部件 bbox 面積 > 此 → warn
REASSEMBLY_SSIM_MIN = 0.95      # 閘7 可組回 masked-SSIM ≥ 此
# 閘8 兩段式（R-2 首批真實樣本校準：raw 切件無 dilate 天生 ~16% seam/邊緣 loss，0.97 是
# 加 joint-dilate(v2) 才達的目標；故 0.97 降為 warning 線、只在 gross 漏抓硬 fail）：
COVERAGE_GROSS_FAIL = 0.70      # < 此 = gross 漏抓（整部件/大塊缺，如 PoC 尿布63%/腿缺）→ fail
COVERAGE_TARGET = 0.97          # ≥ 此 = 乾淨 pass；GROSS~此 = seam loss → warning（需 dilate/更緊 hints）

# is_fg 白底前景判定（PoC inspect_starpose/viz_legs 同法）。非白底 reference → 閘8 降 warn
WHITE_BG_FG_DELTA = 24          # (255-r)+(255-g)+(255-b) > 此 = 前景像素
WHITE_BG_BORDER_MAX_FG = 0.02   # reference 邊框前景比例 > 此 → 判定非白底（閘8 降 warn）
