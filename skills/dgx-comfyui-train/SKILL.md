---
name: dgx-comfyui-train
description: Use when the user asks to "訓練 LoRA", "train LoRA", "用 dataset Y 訓練 char_xxx", or wants to run a LoRA training on DGX (192.168.5.27) via ai-toolkit (Ostris). Validates local dataset, uploads, generates ai-toolkit YAML config, launches background training, streams log with live loss progress, runs sanity check, auto-deploys passed LoRA to /root/ComfyUI/models/loras/{tag}_{date}.safetensors. Long-running (30min~3h). Ctrl-C detaches; status query via `train.py --status [run_id]`. NOT for: image generation (use ar2:dgx-comfyui-gen), model inventory (use ar2:dgx-comfyui-check), dataset captioning.
---

# ar2:dgx-comfyui-train

DGX LoRA 訓練 skill。家族 `ar2:dgx-*` 第三個 skill。

**訓練工具**：ai-toolkit (Ostris) — DGX 已驗證安裝於 `/root/ai-toolkit/`。

## 這個 skill 做什麼

1. 驗證本地 dataset（≥ 5 張、配 .txt caption、≥ 512px 警告）
2. 強制 pre-flight：ai-toolkit 存在 / Flux base 存在 / VRAM ≥ 22 GB / 磁碟 ≥ 10 GB
3. （opt-in `--check`）家族通用 pre-flight via `-check`
4. 處理同 tag 同天衝突（自動加 `_v2/v3/...` 後綴）
5. 打包 + SCP + DGX 端 untar dataset 到 `/root/lora_training/{date}_{tag}/data/`
6. 從 preset (`character_flux.yaml`) 渲染 ai-toolkit YAML config 並上傳
7. DGX 端 `nohup python /root/ai-toolkit/run.py config.yaml` 背景啟動
8. 本地 polling log，即時解析 loss / step（解耦：Ctrl-C 不殺 DGX 訓練）
9. 完成後 sanity check（檔案 / 最後 K loss / 趨勢 / log 錯誤）
10. 通過 → atomic mv 到 `/root/ComfyUI/models/loras/{tag}_{date}.safetensors`
11. （opt-in `--backup`）SCP LoRA 回本地
12. 寫 cache `~/.cache/ar2-dgx-comfyui-train/{run_id}.json`

## 何時觸發

- 「訓練 X 角色 LoRA」「用 ./datasets/char_xxx/ 跑訓練」
- 「train LoRA, tag = char_xxx, dataset = ...」
- 「查上次訓練狀態」（→ `--status`）

## 何時 **不** 觸發

- 產圖 → `ar2:dgx-comfyui-gen`
- 模型盤點 → `ar2:dgx-comfyui-check`
- captioning（dataset 的 `.txt` 必須使用者準備好）→ 本 skill 不做
- 自動產訓練圖（PuLID 那種）→ 不在 v1 範圍

## 如何執行

### 訓練

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-train/scripts/train.py \
  --dataset ./datasets/char_xxx \
  --tag char_xxx
```

### 帶 pre-flight 環境檢查

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-train/scripts/train.py \
  --dataset ./datasets/char_xxx \
  --tag char_xxx \
  --check
```

### 訓練後備份 LoRA 回本機

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-train/scripts/train.py \
  --dataset ./datasets/char_xxx \
  --tag char_xxx \
  --backup
```

### 查狀態

```bash
# 最近一次 run
python3 ~/.claude/skills/ar2:dgx-comfyui-train/scripts/train.py --status

# 指定 run_id
python3 ~/.claude/skills/ar2:dgx-comfyui-train/scripts/train.py --status 1a2b3c...
```

### 中途 Ctrl-C

訓練在 DGX 上**繼續跑**（解耦設計）。本地只是停止 log polling。重新 attach：

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-train/scripts/train.py --status {run_id}
```

## CLI 參數

| Flag | 預設 | 說明 |
|------|------|------|
| `--dataset` | **必填**（train 模式） | 本地 dataset 目錄（含 image + .txt） |
| `--tag` | `{HHMMSS}_{4hex}` | run tag；同天衝突自動加 `_v2/v3/...` |
| `--preset` | `character_flux` | preset 名（不含 .yaml） |
| `--check` | off | pre-flight 跑 `-check` |
| `--backup` | off | deploy 後 SCP LoRA 回本機 `./outputs/...` |
| `--poll-interval` | 5.0 | log 拉 tail 間隔（秒） |
| `--status [run_id]` | (none) | 查狀態模式；run_id 省略 = 最近一次 |

## Exit codes

- `0` 訓練成功 + deploy 完成（或 status 顯示完成）
- `1` 連線 / dataset / pre-flight / launch 失敗
- `2` 訓練完成但 sanity check 失敗或 deploy 失敗

## State lifecycle

```
pending  → running → finished → deployed (成功)
                              ↘ failed   (sanity 失敗)
running → crashed (PID 死、cache 沒更新；--status 時自動修正)
```

## 預期輸出（成功案例）

```
Validating dataset: /Users/.../datasets/char_xxx
  ✅ 15 images, captions paired

== ar2:dgx-comfyui-train @ 192.168.5.27 ==
  preset: character_flux
  dataset: ... (15 images)
  tag (initial): char_xxx
  date: 20260515
[pre-flight] checking DGX training environment...
  GPU: used 0 MiB, free 32510 MiB
  disk: 734 GB free on /root
  ✅ train pre-flight passed
  final tag: char_xxx
  workspace: /root/lora_training/20260515_char_xxx
  run_id: a1b2c3d4-...

Packaging dataset ...
Uploading dataset → /tmp/{run_id}.tar.gz ...
Extracting to /root/lora_training/20260515_char_xxx/data ...
  config: /root/lora_training/20260515_char_xxx/config.yaml

Launching training (background)...
  PID: 12345
  log: /root/lora_training/20260515_char_xxx/train.log

Polling log every 5.0s. Ctrl-C to detach (training will continue on DGX).

  [12.3s] step 1/1500, loss=0.4521, lr=1.00e-04
  [30.1s] step 10/1500, loss=0.3214, lr=1.00e-04
  ...
  [42m 18s] step 1500/1500, loss=0.0421, lr=1.00e-04
  [done] training complete

Training process ended. Running sanity check...
  total steps logged: 1500
  final loss: 0.0421
  min loss: 0.0421 @ step 1500

✅ sanity check passed; deploying...
  deployed: /root/ComfyUI/models/loras/char_xxx_20260515.safetensors

✅ Done in 42m 18s
  LoRA: /root/ComfyUI/models/loras/char_xxx_20260515.safetensors
  run_id: a1b2c3d4-...
```

## 檔案結構

```
ar2:dgx-comfyui-train/
├── SKILL.md
├── config.py                     ← 連線 + ai-toolkit / Flux 路徑 + VRAM/disk 門檻
├── .gitignore
├── hooks/pre-commit
├── scripts/
│   ├── ssh_client.py             ← 移植自 -check
│   ├── trainer.py                ← ai-toolkit YAML 渲染 + nohup 啟動 + PID 管理
│   ├── dataset_validator.py      ← 本地 dataset 驗證
│   ├── log_parser.py             ← ai-toolkit log step/loss/error 解析
│   ├── sanity_check.py           ← 完整 sanity check + atomic mv 部署
│   ├── state_cache.py            ← ~/.cache/ar2-dgx-comfyui-train/{run_id}.json
│   └── train.py                  ← 主入口（--train / --status）
├── references/
│   ├── connection.md             ← 故障診斷（移植自 -check）
│   ├── training-config.md        ← ai-toolkit YAML 結構說明
│   ├── dataset-format.md         ← image + .txt 規範
│   └── deployment.md             ← auto-deploy 規約 / mv / 失敗處置
└── presets/
    └── character_flux.yaml       ← v1 唯一 preset（mirror Dr_Eilin，已驗證可跑）
```

## 家族 ar2:dgx-*

| Skill | 對本 skill 的關係 |
|-------|-------------------|
| `ar2:dgx-comfyui-check` | 觀察者 — 訓練中可看 lora_training/ 增長；完訓後 LoRA 進 inventory |
| `ar2:dgx-comfyui-gen` | 黑盒消費者 — 訓練好的 LoRA 直接可用，引用 `{tag}_{date}` 即可 |
| `ar2:dgx-comfyui-train` | 本 skill — 黑盒生產者 |

## 安全約束

⛔ **不可 publish / push 到任何公開 / 共享 repo**。`config.py` 含明文密碼。
- `.gitignore` 排除 config.py
- `hooks/pre-commit` 攔 PASSWORD literal commit
- 安裝後 `chmod 600 config.py`

訓練特有提醒：
- Dataset 可能含個資 / 版權 → 上傳前審
- LoRA 反映 dataset 特徵 → 受限 dataset → 受限 LoRA
- log + sample 圖可能含 dataset 特徵 → 本地落地時注意
- `~/.cache/ar2-dgx-comfyui-train/` 含 run metadata，建議 `chmod 700`

## 故障排除

- DGX 連不上 → `references/connection.md`
- VRAM 不足 → 重啟 DGX 上的 ComfyUI 釋出（lazy load）
- Dataset 驗證失敗 → 看錯誤訊息；`references/dataset-format.md`
- ai-toolkit 找不到 → 確認 `/root/ai-toolkit/` 存在（plan v1 Section 13 已驗證）
- Sanity check 失敗 → 看 `references/deployment.md` 對照失敗類型
- 訓練中 process 死 → `--status` 自動偵測為 `crashed`；看 log

## v1 已知限制

| 項目 | 影響 | 未來修法 |
|------|------|---------|
| 訓練工具鎖 ai-toolkit | 切其他 trainer 要新 plan | 加 adapter |
| 不做 captioning | 需自備 .txt | future skill |
| 不做 dataset 預處理 | 需自備 ≥ 512px | future flag |
| 無 `train cancel` | 想殺要 SSH `kill {pid}` | 加 `--cancel` |
| 無 resume | 中斷只能從頭 | 加 `--resume {run_id}` |
| 只 1 個 preset | character 用 | 加 style 等 |
| 單 trainer adapter (ai-toolkit only) | 不認識其他 trainer log | 多 adapter |
