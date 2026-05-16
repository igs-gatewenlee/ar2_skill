---
name: ar2:dgx-comfyui-plan
description: Use when the user asks to "建立 plan", "批量產圖計劃", "from-preset", "show presets", "promote 滿意的 plan", or wants to design a structured outline.md plan for batch image generation via ar2:dgx-comfyui-gen. Conducts a 4-round interactive dialogue (高層意圖 → items → 技術 anchor → review), writes plans/{id}_outline.md (YAML frontmatter + Markdown body + items table), and supports preset library (promote / from-preset / show) for cross-machine sharing via git. Pure local (no SSH to DGX). NOT for: actual image generation (use ar2:dgx-comfyui-gen --plan), LoRA training (use ar2:dgx-comfyui-train).
---

# ar2:dgx-comfyui-plan

DGX ComfyUI 計劃設計 + 共享 preset 庫 skill。家族 `ar2:dgx-*` 第四個 skill。

## 這個 skill 做什麼

1. **Interactive create**：4-round 對話收集主題 / items / 技術 anchor / review，產出 `plans/{id}_outline.md`
2. **From-preset**：從共享 preset 庫 fork 出新 working plan（preset 內容為起始值、進入 interactive 改）
3. **List / Show**：列出 working plans (`--list`) 或 presets (`--show` / `--show {id}`)
4. **Promote**：滿意的 working plan → `ar2-skills/.../presets/{id}_outline.md`（含 sanitize：清本機路徑、加 description/tags/provenance），git push 共享

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

### 建新 plan（interactive）

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-plan/scripts/plan_main.py
```

進入 4-round 對話、完成後寫入 `plans/{id}_outline.md`。

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
| (no args) | Interactive create new working plan |
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

- ✅ Interactive create / from-preset / list / show / promote
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
