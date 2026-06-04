---
display_name: 「DGX 產圖計劃」
emoji: 📋
status: stable
order: 2
category: workflow
upstream: []
downstream: ["ar2:dgx-comfyui-gen"]
---

## 一句話：這 skill 解什麼問題？

設計批次產圖的 plan / preset、管理共享 preset 庫；不負責實際產圖（那是 `ar2:dgx-comfyui-gen` 的事）。

## 什麼時候會想到要用？

- 我有一系列要產的圖（12 生肖、5 章節卡冊、N 張同主題）想一次規劃好
- 我看到別人 promote 的 preset 想 fork 來改
- 我有一份滿意的 working plan 想 promote 進共享 preset 庫
- 我想列現有的 working plans 或看 preset 庫有什麼

## 最簡單的用法

```bash
# 看 preset 庫
python3 ~/.claude/skills/ar2:dgx-comfyui-plan/scripts/plan_main.py --show

# fork 一個 preset 來改
python3 ~/.claude/skills/ar2:dgx-comfyui-plan/scripts/plan_main.py --from-preset cards_a11c

# 列工作中的 plan
python3 ~/.claude/skills/ar2:dgx-comfyui-plan/scripts/plan_main.py --list

# 滿意了就 promote 給家族共用
python3 ~/.claude/skills/ar2:dgx-comfyui-plan/scripts/plan_main.py --promote {working_id} \
    --tags fantasy,pulid --desc "5 章節卡冊"
```

設計完的 plan 用 `ar2:dgx-comfyui-gen --plan {id}` 跑出圖。

## 常用參數

| 參數 | 白話 |
| --- | --- |
| `--show` | 列所有 preset |
| `--show PRESET_ID` | cat 某 preset 的詳細內容 |
| `--list` | 列 `cwd/plans/` 內所有 working plans |
| `--from-preset PRESET_ID` | 從 preset fork 出新 working plan（含 interactive 修改）|
| `--promote WORKING_ID` | 升 working plan 為 preset（自動 sanitize 本機路徑）|
| `--tags x,y` | 跟 `--promote` 一起用、加 tags |
| `--desc "..."` | 跟 `--promote` 一起用、加一行描述 |
| `--overwrite` | 跟 `--promote` 一起用、覆蓋既有 preset（會先 .bak）|

## 跟家族裡其他 skill 怎麼配合？

- **上游**：無（純本機設計、不連 DGX）
- **下游**：`ar2:dgx-comfyui-gen --plan {id}` / `--preset {id}` 把 plan 跑成圖
- **特殊關係**：preset 庫住在這個 skill 的 `presets/` 內、`git push` 後跨機共享

## 容易踩的坑

- **直接跑 `plan_main.py` 不帶 flag（無 args）已 deprecated**：原本是 4-round interactive create、實測 0% 用上（chat-driven 都用 AskUserQuestion simulate 取代）。現在會印提示 + exit 2；建新 plan 請在 chat 環境讓 Claude 直接寫 `plans/{id}_outline.md`、或從 terminal 用 `--from-preset` fork
- **plan 設了 `face_ref` 是本機絕對路徑**：promote 時會自動 sanitize 為 `<set face_ref locally>` placeholder、不洩本機路徑；fork 出新 working plan 後要手動填回本機路徑才能跑 gen
- **想調 PuLID 強度但不知道怎麼做**：plan frontmatter 加 `pulid_weight: 0.7`（範圍 0.0–3.0），跑 `--plan` 時會自動套到 workflow JSON 的 `ApplyPulidFlux` node；非 PuLID workflow 設了會被 gen skill 攔下
- **promote 後 preset 沒在別台機器看到**：preset 寫進 `~/Code/ar2-skills/.../presets/` 後要手動 `git commit && git push`，這個 skill 不自動 push
