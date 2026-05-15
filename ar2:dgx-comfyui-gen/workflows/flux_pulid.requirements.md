# flux_pulid.json — Required Models

Flux + PuLID 臉部一致性工作流。必備模型多於 `flux_basic`，覆蓋臉部 embedding + Redux 風格遷移。

## 必備模型（在 flux_basic 之上額外加）

| ComfyUI 分類 | 檔名 | 用途 |
|--------------|------|------|
| `diffusion_models/` | `flux1-dev.safetensors` | （同 flux_basic） |
| `clip/` | `clip_l.safetensors` | （同） |
| `clip/` | `t5xxl_fp8_e4m3fn.safetensors` | （同） |
| `vae/` | `flux_ae.safetensors` | （同） |
| **`pulid/`** | `pulid_flux_v0.9.1.safetensors` | PuLID Flux 模型 |
| **`clip_vision/`** | `EVA02_CLIP_L_336_psz14_s6B.safetensors` | PuLID 視覺 encoder |
| **`clip_vision/`** | `sigclip_vision_patch14_384.safetensors` | Redux 視覺 encoder |
| **`style_models/`** | `flux1-redux-dev.safetensors` | Redux 風格模型 |
| **`insightface/models/antelopev2/`** | 5 個 `.onnx` 檔 | InsightFace 臉部偵測 |

## 必備 custom_nodes

| custom_node | 必備 |
|-------------|------|
| `ComfyUI-PuLID-Flux-Enhanced` | ✅ 提供 `ApplyPulidFlux` / `PulidFluxModelLoader` / `PulidFluxEvaClipLoader` / `PulidFluxInsightFaceLoader` |

## 注入點（給 workflow_params.py 用）

| 參數 | 對應節點 | class_type | 寫入欄位 |
|------|---------|-----------|---------|
| `prompt` | node `4` | `CLIPTextEncode` | `inputs.text` |
| `seed` | node `6` | `RandomNoise` | `inputs.noise_seed` |
| `steps` | node `8` | `BasicScheduler` | `inputs.steps` |
| `batch_size` | node `40` | `EmptySD3LatentImage` | `inputs.batch_size` |
| `face_ref_filename` (auto) | node `20` | `LoadImage` | `inputs.image` = `{subdir}/{filename}` |
| `output_subdir` (auto) | node `13` | `SaveImage` | `inputs.filename_prefix` = `{subdir}/img` |

## 使用須知

- `--face-ref ./path/to/face.png` **必填**（PuLID 需要 face reference）
- `-gen` 會把 face_ref 上傳到 `/root/ComfyUI/input/{subdir}/{filename}`、再把 workflow 內 LoadImage 路徑對齊
- `-gen` 對所有 LoadImage 套用同一個 face_ref（v1 限制）

## 驗證命令

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-check/scripts/inspect.py
```

`-check` 報告中 `pulid`、`clip_vision`、`style_models`、`insightface` 任一 ❌ → 本 workflow 跑不了。
