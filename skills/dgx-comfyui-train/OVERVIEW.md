---
display_name: 「DGX 訓 LoRA」
emoji: 🎓
status: beta
order: 3
category: workflow
upstream: ["ar2:dgx-comfyui-check"]
downstream: ["ar2:dgx-comfyui-gen"]
---

## 一句話：這 skill 解什麼問題？

在 DGX 上訓練 Flux LoRA，訓完自動部署到 ComfyUI 可用位置。

## 什麼時候會想到要用？

- 我有一組 dataset（圖片 + 同名 .txt 描述）想訓自己的角色 LoRA
- 我想試 Flux base model 的 LoRA 微調
- 我訓到一半 SSH 斷線，想重連看訓練進度

## 最簡單的用法

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-train/scripts/train.py \
  --dataset ./datasets/your_char --tag your_char
```

驗證 dataset → 上傳到 DGX → 啟動訓練 → loss 即時回報 → 完成 → auto-deploy 到 `models/loras/{tag}_{date}.safetensors`。

## 常用參數

| 參數 | 白話 |
| --- | --- |
| `--dataset` | dataset 目錄（內含 image + 同名 `.txt`）|
| `--tag` | 訓練任務標籤（會用在輸出 LoRA 檔名）|
| `--status` | 重連已啟動的訓練、不啟新的（適用 SSH 斷掉後）|
| `--preset` | 用哪份訓練 config（預設 `character_lora`）|

## 跟家族裡其他 skill 怎麼配合？

- **上游**：常先用 `ar2:dgx-comfyui-check` 確認 DGX 環境 + base model 完整
- **下游**：訓完 sanity check 通過 → 自動 `mv` 到 `models/loras/`，下次用 `ar2:dgx-comfyui-gen` 可直接 reference 該 LoRA

## 容易踩的坑

- **dataset 結構錯**（image / .txt 對不上）：skill 啟動前會驗證、擋下來
- **訓練解耦設計**：Ctrl-C **不會**殺 DGX 端訓練、訓練仍會在 DGX 上繼續跑。用 `--status` 可以重新 attach 看進度
- **本 skill 還在 beta**：log 解析 regex 還沒對真實訓練輸出 100% 驗過。如果看到「無法解析 log」這類錯，請回報
- **訓完的 LoRA 檔名格式**：預期是 `{tag}_{date}.safetensors`，但 ai-toolkit 實際可能加 step 後綴。首次跑完用 `ls /root/lora_training/{date}_{tag}/output/` 確認實際檔名
