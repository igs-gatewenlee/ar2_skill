# ai-toolkit Training Config 解讀

`presets/character_flux.yaml` 是 v1 唯一 preset，mirror 自 DGX 上 `/root/lora_training/Dr_Eilin/config.yaml`（已驗證可跑）。本檔解釋每個欄位、何時要 override。

## ai-toolkit YAML 結構

```yaml
---
job: extension                      # 固定，告訴 ai-toolkit 用 extension 系統跑
config:
  name: "{config_name}"             # 由 -train 注入：{tag}_{YYYYMMDD}
  process:
    - type: 'sd_trainer'            # 用 SD Trainer extension
      training_folder: "{path}"     # 由 -train 注入：訓練工作區 output 子目錄
      device: cuda:0                # 鎖 GPU 0
      trigger_word: "{tag}"         # 由 -train 注入：tag 自動 prepend 到 caption

      network:
        type: "lora"                # LoRA 訓練（不是 full fine-tune）
        linear: 32                  # LoRA rank（network_dim）
        linear_alpha: 32            # LoRA alpha（通常 = rank）

      save:
        dtype: float16              # 儲存精度
        save_every: 500             # 每 500 step 存一次 checkpoint
        max_step_saves_to_keep: 2   # 只留最後 2 個 checkpoint
        push_to_hub: false

      datasets:
        - folder_path: "{path}"     # 由 -train 注入：dataset 子目錄
          caption_ext: "txt"
          caption_dropout_rate: 0.05  # 5% 機率訓練時 caption 被丟棄
          shuffle_tokens: false
          cache_latents_to_disk: true  # 預編碼 latents 到磁碟（加速）
          resolution: [512, 768]    # 多解析度 bucket

      train:
        batch_size: 1               # V100 32GB Flux 一次只能 1
        steps: 1500                 # 總訓練步數（safety net）
        gradient_accumulation_steps: 1
        train_unet: true
        train_text_encoder: false   # Flux 通常不訓 text encoder
        gradient_checkpointing: true  # 省 VRAM
        noise_scheduler: "flowmatch"
        optimizer: "adamw8bit"      # 8-bit AdamW，省 VRAM
        lr: 1e-4                    # 典型 character LoRA lr
        ema_config:
          use_ema: true
          ema_decay: 0.99
        dtype: bf16                 # bfloat16 訓練（V100 支援）

      model:
        name_or_path: "/root/flux-dev"  # 鎖 DGX 上的 Flux base
        is_flux: true
        quantize: true              # V100 32GB 必開（不開會 OOM）

      sample:
        sampler: "flowmatch"
        sample_every: 500           # 每 500 step 產 sample 圖
        width: 768
        height: 768
        prompts:                    # 由 -train 注入：含 {tag} 的範例 prompts
          - "{tag}, portrait, anime style"
          - "{tag}, full body, anime style"
        neg: ""
        seed: 42
        walk_seed: true
        guidance_scale: 3.5
        sample_steps: 20

meta:
  name: "{config_name}"
  version: '1.0'
```

## 由 `-train` 自動注入的欄位

| 欄位 | 替換為 |
|------|--------|
| `config.name` | `{tag}_{YYYYMMDD}` |
| `config.process[0].training_folder` | `/root/lora_training/{date}_{tag}/output` |
| `config.process[0].trigger_word` | `{tag}` |
| `config.process[0].datasets[0].folder_path` | `/root/lora_training/{date}_{tag}/data` |
| `config.process[0].sample.prompts[*]` | `{tag}` 替換到字串內 |
| `meta.name` | 同 `config.name` |

CLI override 可改：`--steps`、`--lr`、`--rank`、`--batch-size`（會覆蓋 preset 對應欄位）。

## Hyperparameter 速查

| 欄位 | character LoRA 典型 | 何時要動 |
|------|-------------------|---------|
| `network.linear` (rank) | 32 | 想更輕量 → 16；更強表現 → 64（VRAM 變高） |
| `train.steps` | 1500 | dataset 大 → 2000-3000；dataset 小 → 500-1000 |
| `train.lr` | 1e-4 | 多數 character LoRA 通用；不收斂 → 試 5e-5 或 2e-4 |
| `train.optimizer` | `adamw8bit` | VRAM 充足可改 `adamw`（不省 VRAM 但稍精準） |
| `save.save_every` | 500 | 短訓練 → 100-200；長訓練 → 1000 |
| `datasets[0].resolution` | `[512, 768]` | 想學細節 → 加 1024 |
| `model.quantize` | `true` | V100 32GB **不可改 false**（會 OOM） |

## safety net：max_train_steps + max_train_time

ai-toolkit 內建 `train.steps`（上限）。`-train` 額外規約：

- preset 必含 `steps` 欄位（v1 鎖 1500）
- v1 不額外加 wall-clock timeout（ai-toolkit 沒這個欄位，需 skill 端 monitor）
- 異常情況（NaN loss / diverge）由 sanity_check 偵測；訓練不會主動中止但 deploy 會擋

## 訓練步數估算

每 step 約 1.5-3s（V100 + Flux LoRA + batch=1 + quantize）。

- 500 step ≈ 12-25 分鐘
- 1500 step ≈ 40-75 分鐘（character LoRA 典型）
- 3000 step ≈ 80-150 分鐘
