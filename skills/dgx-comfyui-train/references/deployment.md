# Auto-Deploy 規約

訓練完成後 `-train` 把 LoRA 自動 deploy 到 ComfyUI `models/loras/`。本檔說明規約與失敗處理。

## 自動 deploy 條件

`sanity_check.py` 全部過才 deploy：

```
sanity_pass = all([
  file_exists,              # output 檔案存在
  last_k_loss_not_nan,      # 最後 K=20 step 的 loss 非 NaN
  loss_trend_descending,    # 最後 K step linear fit slope < 0
  no_critical_error,        # log 內無 ERROR / CUDA out of memory / NaN / Inf
])
```

警告但 **不** 擋 deploy：

```
warnings_only = [
  loss_plateau,                # 平緩但無 NaN
  final_loss_above_threshold,  # final_loss > 0.5
  no_sample_generated,         # samples/ 為空
]
```

## LoRA 檔案路徑

### 訓練工作區（source）

```
/root/lora_training/{YYYYMMDD}_{tag}/output/{tag}_{YYYYMMDD}/{tag}_{YYYYMMDD}.safetensors
```

ai-toolkit 用 `config.name` 命名輸出資料夾與檔名。`-train` 在生成 config 時把 `config.name` 設為 `{tag}_{YYYYMMDD}`，所以最終檔名一致。

若 ai-toolkit 留多 checkpoint（`save_every` + `max_step_saves_to_keep`）：
- 中間 checkpoint：`{config_name}_000000500.safetensors`（含 step 後綴）
- final（最後 step）：`{config_name}.safetensors`（無後綴）—— 取這個 deploy

### 部署目標（dest）

```
/root/ComfyUI/models/loras/{tag}_{YYYYMMDD}.safetensors
```

## mv 是 atomic 的

source 與 dest 都在 `/root/` 下（同 filesystem），Linux `mv` 在同 fs 上是 `rename(2)`，atomic。
意外中斷不會留半個檔。

## 同 tag 同天衝突

預期情境：使用者同一天用同 tag 訓練第 2 次。

`-train` 在啟動前（步驟 3）就**先**檢查 `{tag}_{YYYYMMDD}.safetensors` 是否存在，已存在則自動把 tag 改為 `{tag}_v2`、再不行 `_v3`、`_v4`...

→ 對使用者透明（不會覆寫舊 LoRA，但會在報告中提示「tag 自動改為 X」）。

→ 工作區跟目標檔名都會跟著改：
- workspace: `/root/lora_training/{YYYYMMDD}_{tag}_v2/`
- final LoRA: `models/loras/{tag}_v2_{YYYYMMDD}.safetensors`

## 失敗後的處置

| sanity check 失敗項 | 處置 |
|---------------------|------|
| `file_exists` = False | 訓練可能 OOM / crash 中斷 → 看 log + nvidia-smi |
| `last_k_loss_not_nan` 失敗（出現 NaN） | lr 太大 / dtype 不穩 → 降 lr 或改 fp32 |
| `loss_trend_descending` 失敗（loss 上升） | dataset 問題 / lr 太大 → 檢查 dataset / 降 lr |
| `no_critical_error` 失敗 | log 內有 CUDA OOM / ERROR → 釋 VRAM 或減 batch |

失敗時 LoRA 留在工作區 `/root/lora_training/{date}_{tag}/output/`，不刪。使用者可：
1. SSH 進去手動檢查
2. 跑 `train.py --status {run_id}` 看細節
3. 修改 config 重訓（記得改 tag 或讓自動 `_v2`）

## --no-deploy（v1 未實作）

Plan 提到的 `--no-deploy` flag v1 暫不實作（用不到）。若使用者真的需要「訓練但不 deploy」→ 修改 sanity_check.py 跳過 mv 即可。Future enhancement。

## 取消已 deploy 的 LoRA

ComfyUI 不主動 reload `models/loras/`，新 LoRA 進去後要：
- 重啟 ComfyUI（清 RAM 緩存）
- 或下次 `-gen` 引用該 LoRA 時 ComfyUI 會 lazy load

要「取消」一個已 deploy 的 LoRA：
```bash
ssh ... 'rm /root/ComfyUI/models/loras/{tag}_{date}.safetensors'
```

`-gen` 引用不存在的 LoRA 會由 ComfyUI 報錯，可從錯誤訊息 debug。
