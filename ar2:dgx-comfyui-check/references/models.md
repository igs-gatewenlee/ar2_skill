# ComfyUI Models — 分類與核心必備清單

13 個 models 子分類，存放於 DGX 的 `/root/ComfyUI/models/`。

`inspect.py` 的 `EXPECTED` dict 與本檔內容必須保持一致。修改其一時務必同步另一個。

---

## 全部 13 分類

| 分類 | 路徑 | 用途 |
|------|------|------|
| `checkpoints` | `/root/ComfyUI/models/checkpoints/` | 通用主模型（SD1.5 / SDXL / SD3 等） |
| `diffusion_models` | `/root/ComfyUI/models/diffusion_models/` | Flux 系列主模型 |
| `clip` | `/root/ComfyUI/models/clip/` | Text encoders（clip_l / t5xxl） |
| `vae` | `/root/ComfyUI/models/vae/` | VAE 模型 |
| `loras` | `/root/ComfyUI/models/loras/` | LoRA（含 -train 部署產出） |
| `controlnet` | `/root/ComfyUI/models/controlnet/` | ControlNet |
| `embeddings` | `/root/ComfyUI/models/embeddings/` | Textual Inversion |
| `upscale_models` | `/root/ComfyUI/models/upscale_models/` | 放大模型 |
| `pulid` | `/root/ComfyUI/models/pulid/` | PuLID 臉部一致性 |
| `clip_vision` | `/root/ComfyUI/models/clip_vision/` | Vision encoders |
| `style_models` | `/root/ComfyUI/models/style_models/` | Flux Redux 等風格模型 |
| `insightface` | `/root/ComfyUI/models/insightface/` | 臉部偵測（antelopev2 / inswapper） |
| `facerestore_models` | `/root/ComfyUI/models/facerestore_models/` | 臉部修復（CodeFormer / GFPGAN） |

---

## 核心必備模型（對照盤點用）

`inspect.py` 比對下列清單與實際盤點結果，缺失標 ❌、多餘只在已定義必備的分類才標 ⚠️。

| 分類 | 必備檔名 |
|------|---------|
| `diffusion_models` | `flux1-dev.safetensors` |
| `clip` | `clip_l.safetensors`, `t5xxl_fp8_e4m3fn.safetensors` |
| `vae` | `flux_ae.safetensors` |
| `pulid` | `pulid_flux_v0.9.1.safetensors` |
| `clip_vision` | `EVA02_CLIP_L_336_psz14_s6B.safetensors`, `sigclip_vision_patch14_384.safetensors` |
| `style_models` | `flux1-redux-dev.safetensors` |
| 其餘 7 個分類 | (無強制必備，盤點時純列數量與大小) |

---

## 不在這份清單

刻意排除的東西：

- **模型下載 URL**：這個 skill 只盤點，不負責下載。需要下載時走別的 skill 或手動處理。
- **嵌套目錄詳列**（如 `insightface/models/antelopev2/*.onnx` 5 個檔）：v1 只列 top-level 檔案，不遞迴展開。
- **磁碟需求**：訪 DGX 端 `df` 取實際剩餘，不依賴預估值。

修改本檔時：同步更新 `scripts/inspect.py` 的 `EXPECTED` dict。
