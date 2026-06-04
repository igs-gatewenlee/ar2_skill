# flux_basic.json — Required Models

純 text-to-image Flux 工作流。必備模型清單（對應 `ar2:dgx-comfyui-check` 的核心必備項目）。

## 必備模型

| ComfyUI 分類 | 檔名 | 用途 |
|--------------|------|------|
| `diffusion_models/` | `flux1-dev.safetensors` | Flux dev 主模型 |
| `clip/` | `clip_l.safetensors` | Text encoder 1 |
| `clip/` | `t5xxl_fp8_e4m3fn.safetensors` | Text encoder 2 |
| `vae/` | `flux_ae.safetensors` | VAE |

## 必備 custom_nodes

無（純官方節點：`UNETLoader` / `DualCLIPLoader` / `CLIPTextEncode` / `EmptySD3LatentImage` / `RandomNoise` / `KSamplerSelect` / `BasicScheduler` / `BasicGuider` / `FluxGuidance` / `SamplerCustomAdvanced` / `VAELoader` / `VAEDecode` / `SaveImage`）。

## 注入點（給 workflow_params.py 用）

| 參數 | 對應節點 | class_type | 寫入欄位 |
|------|---------|-----------|---------|
| `prompt` | node `3` | `CLIPTextEncode` | `inputs.text` |
| `seed` | node `6` | `RandomNoise` | `inputs.noise_seed` |
| `steps` | node `8` | `BasicScheduler` | `inputs.steps` |
| `batch_size` | node `4` | `EmptySD3LatentImage` | `inputs.batch_size` |
| `output_subdir` (auto) | node `13` | `SaveImage` | `inputs.filename_prefix` = `{subdir}/img` |

## 驗證命令

執行 `-check` 確認 DGX 端模型齊全：

```bash
python3 ~/.claude/skills/ar2:dgx-comfyui-check/scripts/inspect.py
```

清單上若有 ❌ 標記到上述任一模型，本 workflow 跑不了。
