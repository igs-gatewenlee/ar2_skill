---
display_name: 「DGX 體檢」
emoji: 🩺
status: stable
order: 1
category: workflow
upstream: []
downstream: ["ar2:dgx-comfyui-gen", "ar2:dgx-comfyui-train"]
---

## 一句話：這 skill 解什麼問題？

檢查 DGX 機器狀態 + 盤點 ComfyUI 的 13 類模型。

## 什麼時候會想到要用？

- 我想連 DGX 但不確定機器有沒有開
- 我要產圖或訓練前，想確認需要的模型都在
- 我想看 DGX 上現有的 LoRA / Checkpoint 有哪些
- 我發現 ComfyUI 不能用，想快速診斷哪一塊出問題

## 最簡單的用法

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-check/scripts/inspect.py
```

連 DGX → 三項健康檢查（GPU / process / API）→ 列出 13 個模型分類 → 環境摘要（含 PuLID dtype patch 狀態 ✅/❌）。

## 常用參數

| 參數 | 白話 |
| --- | --- |
| （無）| 跑完整 inventory（健康檢查 + 模型盤點 + PuLID patch 狀態）|
| `--apply-pulid-patch` | 套 PuLID-Flux-Enhanced 的 dtype-cast patch（idempotent、自動建 dated backup）— 解 PuLID weight bf16/fp16 mismatch、且 `git pull` 會覆蓋這個 fix 故需要重套機制 |

## 跟家族裡其他 skill 怎麼配合？

- **上游**：無（這是家族的第一站）
- **下游**：
  - → `ar2:dgx-comfyui-gen`（產圖前建議先 check 一次）
  - → `ar2:dgx-comfyui-train`（訓練前建議先 check 一次）

## 容易踩的坑

- **第一次跑缺 `sshpass`**：用 `brew install esolitos/ipa/sshpass` 補上
- **連不上 DGX**：通常是私網不通（不是 skill 的 bug），檢查 VPN 或機器是否在線
- **API 健康檢查紅燈**：通常是 ComfyUI 剛重啟還沒 ready，等 30 秒再跑
- **VRAM 顯示「Free 29G」但實際只能用 ~27G**：host 上有其他 container 吃約 2GB，不影響使用
- **PuLID patch 狀態顯示 ❌ unpatched**：跑 `--apply-pulid-patch` 一次即可；上游 ComfyUI-PuLID-Flux-Enhanced custom node 若 `git pull` 過會洗掉 patch、再跑一次就好
