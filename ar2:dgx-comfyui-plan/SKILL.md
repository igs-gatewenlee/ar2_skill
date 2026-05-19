---
name: ar2:dgx-comfyui-plan
description: Use when the user asks to "建立 plan", "批量產圖計劃", "from-preset", "show presets", "promote 滿意的 plan", or wants to design a structured outline.md plan for batch image generation via ar2:dgx-comfyui-gen. Plans are authored either by forking a preset (`--from-preset`) or by Claude composing outline.md directly in chat; writes plans/{id}_outline.md (YAML frontmatter + Markdown body + items table). Supports preset library (promote / from-preset / show) for cross-machine sharing via git. Pure local (no SSH to DGX). NOT for: actual image generation (use ar2:dgx-comfyui-gen --plan), LoRA training (use ar2:dgx-comfyui-train).
---

# ar2:dgx-comfyui-plan

DGX ComfyUI 計劃設計 + 共享 preset 庫 skill。家族 `ar2:dgx-*` 第四個 skill。

## 這個 skill 做什麼

1. **From-preset**：從共享 preset 庫 fork 出新 working plan（preset 內容為起始值、進入 interactive 改）
2. **List / Show**：列出 working plans (`--list`) 或 presets (`--show` / `--show {id}`)
3. **Promote**：滿意的 working plan → `ar2-skills/.../presets/{id}_outline.md`（含 sanitize：清本機路徑、加 description/tags/provenance），git push 共享

> ⚠️ **No-args interactive create 已 deprecated**（issue #2）：直接跑 `plan_main.py` 不帶 flag 會印 deprecation 提示並 exit 2。在 chat 環境 Claude 直接寫 `plans/{id}_outline.md`；在 terminal 用 `--from-preset` 開新 plan。原 4-round `input()` 流程程式碼保留供 `--from-preset` 重用。

## 何時觸發

- 「我要做 12 張同主題的圖」「建立 plan」「批量產圖計劃」
- 「show 看 preset 有什麼」「from-preset zodiac_a1b2」
- 「這個 plan 滿意、promote 變預設」

## 何時 **不** 觸發

- 想 single-shot 產 1 張 → 直接 `ar2:dgx-comfyui-gen --prompt "..."`
- 想實際跑 plan → `ar2:dgx-comfyui-gen --plan {id}` 或 `--preset {id}`
- 想訓練 LoRA → `ar2:dgx-comfyui-train`
- 想 captioning → 不在 ar2:dgx-* 家族範圍

## 如何執行

### 建新 plan

在 chat 環境直接請 Claude 撰寫 `plans/{id}_outline.md`（沿用 outline schema：見下方「Outline.md 結構」）。
在 terminal 環境用 `--from-preset` 從既有 preset fork（見下方）。

> ⚠️ 直接跑 `plan_main.py`（無 flag）的 4-round interactive 流程已 deprecated（issue #2）：0% 真實 exercise、chat-driven 都用 AskUserQuestion simulate。

### Chat-driven flow（樣版引導）

當用戶在 chat 環境請求新建 plan、且需要產出**精確的圖**（不只是隨手批量），Claude 按以下 **17 題藍本** 漸進問用戶——順序固定為 **Layer B → Layer C → Layer A**（B 的策略決定約束 C 的敘事，C 的敘事約束 A 的視覺）。用戶可隨時說「跳過」或「不指定」——所有題目皆 optional。

#### Layer B — 季結構（5 題，先問）

1. **季主題是什麼**？一句話描述（例：「奇幻冒險 hero's journey」「賽馬奪冠」「12 生肖」）
2. **分組軸用哪種**？`rarity`（N/R/SR/SSR 稀有度）/ `chapter`（章節）/ `custom`（自定義）
3. **每組多少 item + label 是什麼**？（例：`ch1: 12 張啟程 / ch2: 12 張試煉 ...`）
4. **跨組進階軸有哪些**？哪些維度跨組演進（例：「構圖從半身到動態」「光效從寫實到魔法」），可空
5. **角色連續性 + 驗收標準**？角色是否跨組一致、什麼樣的卡才算合格

#### Layer C — 敘事方向（3 題，再問）

6. **角色背景種子**：一句話描述角色（例：「12 歲女孩，棕髮辮子，皮製旅行斗篷」），AI 會展開細節
7. **跨組敘事弧**：每個 group 對應的敘事節點（例：`ch1: 離家啟程 / ch2: 森林精靈導師 ...`）
8. **整體情緒色調**：一句話描述（例：「希望 + 冒險 + 治癒感」），可空

#### Layer A — 視覺鎖定（9 題，最後問）

每個維度問：value（用人類語言描述，可中可英）+ scope（locked = 全 season 一致 / per_group = 跨組變化 / unspecified = 不指定，讓 model 自由）

> 提醒：**per-item 變化（每張卡都不同）不在這層樣版內**——個別 item 在 outline `# Items` table 將 `prompt` 寫成具體字串（不寫 `<derived>`）作為 manual override 逃生口（BC-11/15）。

9.  **hair**：髮型 / 髮色（scope: locked）
10. **outfit**：服裝（scope: locked / per_group）
11. **composition**：構圖（scope: locked / per_group）
12. **background**：背景（scope: locked / per_group）
13. **lighting**：光線（scope: locked / per_group）
14. **expression**：表情（scope: locked）
15. **style_intensity**：風格濃度（含 LoRA 強度）（scope: locked）
16. **view_angle**：視角 / 鏡頭距離（scope: locked / per_group）
17. **color_palette**：色調 / 色盤（scope: locked）

#### 產出格式

收齊用戶答案後，Claude 寫入 `plans/{id}_outline.md`，在 `# Story / Vision` 之後、`# Style anchor` 之前插入 `# Design Dimensions` section（YAML 內含 `season_structure` / `narrative_direction` / `visual_lock` 三 top-level key）。`# Items` table 的 `prompt` 欄填 `<derived>`（除非個別 item 用 manual override）。

由 `ar2:dgx-comfyui-gen --plan {id}` 執行時，gen 偵測 `<derived>` sentinel → 呼叫 `prompt_derive.derive_prompt(plan, item)` 從維度推導 prompt。改一處（譬如 hair 改色）所有 derived item 自動連動（**單一來源、derived not stored**）。

### 列工作中的 plan

```bash
python3 .../plan_main.py --list
```

### 看 preset 庫

```bash
python3 .../plan_main.py --show               # 列所有 preset
python3 .../plan_main.py --show zodiac_a1b2   # cat 一個 preset 詳細
```

### 從 preset fork（含 interactive 修改）

```bash
python3 .../plan_main.py --from-preset zodiac_a1b2
```

跳過 Round 1（主題繼承）、進入 Round 2/3/4 修改、寫新 working plan。

### Promote working plan → preset

```bash
python3 .../plan_main.py --promote {working_id} \
    --tags anime,zodiac,character \
    --desc "12 生肖動漫風 / 人物+動物"

# 已存在同名 preset 時加 --overwrite （會先 .bak）
python3 .../plan_main.py --promote {id} --overwrite
```

Promote 後手動 `cd ~/Code/ar2-skills && git add ... && git commit && git push` 跨機共享。

### 之後執行 plan（給 gen skill 用）

```bash
# 工作版
python3 ~/.claude/skills/ar2:dgx-comfyui-gen/scripts/generate.py --plan {working_id}

# Preset（不修改 preset 內容）
python3 ~/.claude/skills/ar2:dgx-comfyui-gen/scripts/generate.py --preset {preset_id}
```

## CLI 參數摘要

| Flag | 用途 |
|------|------|
| (no args) | ⚠️ DEPRECATED — prints notice, exits 2. Use --from-preset or chat. |
| `--from-preset PRESET_ID` | Fork preset → new working plan（含 interactive 改） |
| `--list` | 列 cwd/plans/ 內所有 working plans |
| `--show` | 列所有 presets |
| `--show PRESET_ID` | Cat 一個 preset 內容 |
| `--promote WORKING_ID` | 升 working plan 為 preset |
| `--tags x,y` | （with --promote）逗號分隔 tags |
| `--desc "..."` | （with --promote）一行描述 |
| `--overwrite` | （with --promote）覆蓋既有 preset（含 .bak） |

## Outline.md 結構

```markdown
---
id: zodiac_a1b2
title: 12 生肖動漫風
version: 1
created: 2026-05-16T14:30:00+08:00
updated: 2026-05-16T14:30:00+08:00
status: ready
workflow: flux_basic
size: [1024, 1024]
steps: 20
batch_per_item: 1
seed_strategy:
  type: incremental
  base: 1000
  step: 137
lora: []
face_ref: null
---

# Story / Vision
...

# Style anchor
**Prefix**: (none)
**Suffix**: , anime style illustration, soft lighting
**Negative**: (none)

# Output
- dir: outputs/ar2-dgx-comfyui-gen/zodiac_a1b2/
- naming: {NN}_{slug}_{n}.png

# Items
| # | slug | prompt | full? |
|---|------|--------|-------|
| 1 | rat  | young girl with white mouse | |
| 2 | ox   | farmer boy with brown ox in pastoral field | |
... 

# Open notes
...
```

### Items table 規則

- `slug`：`[a-z0-9_]+`、檔名安全
- `prompt`：單行、含 `|` 須 escape 為 `\|`、全形 `｜` 視為正常字元保留
- `full?`：`✓`/`yes`/`y` = self-contained（gen 不 inject prefix/suffix）；空 = auto inject

## 共享機制

```
~/Code/ar2-skills/ar2:dgx-comfyui-plan/presets/   ← git-tracked、push 即共享
├── zodiac_a1b2_outline.md
├── tarot_arcana_c3d4_outline.md
└── ...

~/Code/ai_cards/plans/                              ← 個人 working plans
├── {id}_outline.md
├── {id}.history.jsonl                              ← 執行記錄（gen 自動 append）
└── preset_runs/
    └── {preset_id}_{ts}.history.jsonl
```

## Phase 2 (MVP) 範圍

- ✅ From-preset / list / show / promote（no-args interactive create deprecated in issue #2）
- ✅ Sanitize（最小化：face_ref / output dir 本機路徑）
- ✅ Schema v1 with PyYAML
- 🔜 SSH validate workflow + LoRA 存在性（推 Phase 2 加 BC-12）
- 🔜 Plan tags 搜尋 / preset version bump / variations per item

## 安全約束

⛔ **Preset 內容是共享資料**、promote 前確認：
- Prompts 不含 NSFW / 版權問題（skill 不做 content moderation、用戶責任）
- LoRA name reference 用戶自選的 LoRA、不洩本機路徑（已 sanitize）

## 故障排除

- Parse error → 對照 Outline.md 結構章節 / `_outline.md` 的 frontmatter + 5 個 sections 是否齊全
- `pip install pyyaml` 失敗 → MVP 依賴 PyYAML 6.x
- Promote 後 git push 失敗 → ar2-skills repo 需設好 remote
