---
display_name: 「DGX 產圖」
emoji: 🎨
status: stable
order: 4
category: workflow
upstream: ["ar2:dgx-comfyui-check", "ar2:dgx-comfyui-plan", "ar2:dgx-comfyui-train"]
downstream: []
---

## 一句話：這 skill 解什麼問題？

在 DGX 上用 ComfyUI workflow 產圖，再把成品拉回本機；支援單張即興、也支援 plan-driven 批次。

## 什麼時候會想到要用？

- 我想用 DGX 的 GPU 跑 ComfyUI 產圖
- 我有 prompt 想批次出圖（用 `--plan` / `--preset`、看 `ar2:dgx-comfyui-plan`）
- 我剛訓好 LoRA 想試試效果
- 我有自己準備的 workflow JSON 想跑

## 最簡單的用法

```bash
# 單張即興
python3 ~/.claude/skills/ar2:dgx-comfyui-gen/scripts/generate.py \
  --prompt "a serene mountain at sunset" --batch 4 --tag test

# Plan-driven 批次（plan / preset 由 ar2:dgx-comfyui-plan 設計）
python3 ~/.claude/skills/ar2:dgx-comfyui-gen/scripts/plan_runner.py --plan cards_a11c
python3 ~/.claude/skills/ar2:dgx-comfyui-gen/scripts/plan_runner.py --preset cards_a11c --items 1-5
```

單張產出在 `./outputs/ar2-dgx-comfyui-gen/{date}_test/`；plan-driven 產出在 `./outputs/ar2-dgx-comfyui-gen/{plan_id}/`。

## 常用參數

**單張 (`generate.py`)**：

| 參數 | 白話 |
| --- | --- |
| `--prompt` | 想出什麼圖、用文字描述 |
| `--batch` | 一次出幾張 |
| `--tag` | 給這次產圖一個標籤（會做為輸出目錄名）|
| `--workflow` | 用哪個 workflow（預設 `flux_basic`，可選 `flux_pulid`）|
| `--check` | 跑前先做 pre-flight（VRAM / API / 模型存在性）|

**Plan-driven (`plan_runner.py`)**：

| 參數 | 白話 |
| --- | --- |
| `--plan PLAN_ID` | 跑 `./plans/{id}_outline.md` 工作版 |
| `--preset PRESET_ID` | 跑 skill 內 preset 庫（不污染 working plan）|
| `--items SPEC` | 子集執行：`1-5` / `1,3,5-7` / `1` |

## 跟家族裡其他 skill 怎麼配合？

- **上游**：
  - `ar2:dgx-comfyui-check`（產圖前確認 DGX 環境、含 PuLID patch 狀態）
  - `ar2:dgx-comfyui-plan`（設計 plan / preset、給 `--plan / --preset` 吃）
- **下游**：圖檔留在本機，無 skill 自動下游
- **配合 train**：用 `ar2:dgx-comfyui-train` 訓完的 LoRA 通常會用本 skill 試效果

## 容易踩的坑

- **VRAM 不夠**：用 `--check` pre-flight 會擋（不會白白送 workflow 出去再失敗）
- **workflow JSON 找不到對應模型**：先用 `ar2:dgx-comfyui-check` 看看 DGX 上是否有那個模型
- **SSH tunnel 沒關**：本 skill 用完**不主動 kill tunnel**，讓家族其他 skill 共用同條通道。想徹底斷線手動 `pkill -f ssh.*5.27`
- **SCP transient fail**：`scp_get/scp_put` 內建 3 次 linear-backoff retry（1s/2s），偶發網路抖動會自己救回、不必手動補。3 次都失敗才報錯
- **ComfyUI queue 累積導致 hang**：`plan_runner` 開跑前自動清舊 queue（best-effort）並印 `⚠️  Found N stale queue items, clearing...` warning。若 queue API 掛了會降級為 warning + 繼續
- **用 `flux_pulid` workflow 想調 PuLID 強度**：plan frontmatter 加 `pulid_weight: 0.7`（範圍 0.0–3.0），不必手改 workflow JSON；非 PuLID workflow 設了會 raise `WorkflowParamError`
