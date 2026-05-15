---
display_name: 「DGX 產圖」
emoji: 🎨
status: stable
order: 2
category: workflow
upstream: ["ar2:dgx-comfyui-check"]
downstream: []
---

## 一句話：這 skill 解什麼問題？

在 DGX 上用 ComfyUI workflow 產圖，再把成品拉回本機。

## 什麼時候會想到要用？

- 我想用 DGX 的 GPU 跑 ComfyUI 產圖
- 我有 prompt 想批次出圖
- 我剛訓好 LoRA 想試試效果
- 我有自己準備的 workflow JSON 想跑

## 最簡單的用法

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-gen/scripts/generate.py \
  --prompt "a serene mountain at sunset" --batch 4 --tag test
```

產出的圖會在本機 `./outputs/ar2-dgx-comfyui-gen/{date}_test/` 內。

## 常用參數

| 參數 | 白話 |
| --- | --- |
| `--prompt` | 想出什麼圖、用文字描述 |
| `--batch` | 一次出幾張 |
| `--tag` | 給這次產圖一個標籤（會做為輸出目錄名）|
| `--workflow` | 用哪個 workflow（預設 `flux_basic`，可選 `flux_pulid`）|
| `--check` | 跑前先做 pre-flight（VRAM / API / 模型存在性）|

## 跟家族裡其他 skill 怎麼配合？

- **上游**：常先用 `ar2:dgx-comfyui-check` 確認 DGX 環境健康（產圖前用 `--check` 也能順手做 pre-flight）
- **下游**：圖檔留在本機，無 skill 自動下游
- **配合 train**：用 `ar2:dgx-comfyui-train` 訓完的 LoRA 通常會用本 skill 試效果

## 容易踩的坑

- **VRAM 不夠**：用 `--check` pre-flight 會擋（不會白白送 workflow 出去再失敗）
- **workflow JSON 找不到對應模型**：先用 `ar2:dgx-comfyui-check` 看看 DGX 上是否有那個模型
- **SSH tunnel 沒關**：本 skill 用完**不主動 kill tunnel**，讓家族其他 skill 共用同條通道。想徹底斷線手動 `pkill -f ssh.*5.27`
- **產圖過久沒完成**：可能是 prompt 太複雜或 batch 太大、卡在 ComfyUI queue。打開 DGX 的 ComfyUI web UI 看 queue 狀態
