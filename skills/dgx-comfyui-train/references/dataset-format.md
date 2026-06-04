# Dataset 格式規範

`ar2:dgx-comfyui-train` 採 ai-toolkit 標準 dataset 格式（與 kohya 相同）。

## 基本結構

```
datasets/{tag}/                    ← caller 傳給 --dataset 的目錄
├── 01_pose_a.png                  ← 圖檔（支援 .jpg / .jpeg / .png）
├── 01_pose_a.txt                  ← 同名 caption（必有）
├── 02_pose_b.png
├── 02_pose_b.txt
├── ...
```

## 規則

- 圖檔 + 同名 `.txt` 配對（沿用 ai-toolkit / kohya 慣例）
- caption 內容是該圖的描述 + 任何想保留的 tag
- 解析度建議 ≥ 512px（ai-toolkit 內建 bucket，會自動 resize 成 preset 的 `resolution: [512, 768, 1024]` 等）
- 圖檔比例任意（ai-toolkit 自動 bucket）

## trigger_word 處理

`-train` skill 把 caller 的 `--tag` 自動寫入 ai-toolkit preset 的 `trigger_word`。
ai-toolkit 在訓練時會把 trigger_word 自動加到 caption 開頭（若 caption 內沒有）。

所以你的 `.txt` 不一定要寫 trigger word，留純描述即可。例如：

```
# 01_pose_a.txt
front portrait, soft lighting, serene expression, anime style
```

trigger_word（如 `char_xxx`）會由 ai-toolkit 自動 prepend。

## 驗證規則（`-train` 內建）

執行前 `dataset_validator.py` 會檢查：

| 規則 | 嚴格度 |
|------|--------|
| 圖檔 ≥ 5 張 | 必過 — 不夠中止 |
| 每張圖配同名 .txt | 必過 — 缺中止 |
| 圖檔副檔名 ∈ {.jpg, .jpeg, .png} | 必過 — 其他擋 |
| 解析度 ≥ 512px（任一邊） | 警告 — 不擋但提示 |
| caption 非空 | 警告 — 空字串提示 |

## ai-toolkit 自動產的 cache

訓練第一次跑會在 `data/` 內生成：
- `_latent_cache/` — 預編碼的 VAE latents（加速重訓）
- `.aitk_size.json` — ai-toolkit 紀錄各圖實際解析度

這些是 ai-toolkit 自管的、別動。本地上傳前的 `tar` 會略過 `.aitk_size.json` 與 `_latent_cache/`（皆為 DGX 端產的）。

## 範例（從 DGX 既存 Dr_Eilin）

```
data/
├── 01_portrait_soft.png       ← 768x768 角色正面
├── 01_portrait_soft.txt       ← "front portrait, soft lighting, serene expression..."
├── 02_portrait_strong.png
├── 02_portrait_strong.txt
├── ... 共 15 張
├── _latent_cache/             ← 訓練時自動產
└── .aitk_size.json
```

15 張多角度 / 多表情 / 多姿態的描述 caption 是 character LoRA 的標準量級。少於 5 張容易過擬合單一姿態。

## 不在本 skill 範圍

- 自動 captioning（請使用者自備 .txt；未來獨立 skill）
- dataset 預處理（resize / crop / 對比調整 → 使用者自備或未來獨立 skill）
- dataset poison 偵測（重複圖、空 caption → edge case，v1 不擋）
