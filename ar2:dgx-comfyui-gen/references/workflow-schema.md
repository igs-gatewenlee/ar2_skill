# Workflow JSON Schema 與參數注入慣例

`workflow_params.py` 用 **class_type convention** 自動找節點注入參數。本檔說明完整對照表。

## 為什麼用 class_type convention

ComfyUI workflow JSON 沒有「這是 prompt」「這是 seed」的標籤 —— 只有 node IDs 與 class_type。要把 caller 傳的 `--prompt "..."`、`--seed 42` 注入到正確節點，必須靠**慣例**。

## 注入 API

```python
from workflow_params import inject

new_wf = inject(
    workflow,           # caller-deep-copied dict
    prompt=...,
    negative_prompt=...,
    seed=...,
    steps=...,
    batch_size=...,
    face_ref_filename=...,
    output_subdir=...,
)
```

- 找不到對應 class_type → 拋 `WorkflowParamError`
- 多個候選 → 用「**最低 node id**」作 fallback、log 警告
- 缺對應節點時的處理：若 caller **沒傳該參數** → skip；**有傳但找不到節點** → 報錯

## class_type 對照表（v1 支援 Flux + legacy SD）

| 參數 | 主要 class_type（Flux） | 後援 class_type（legacy） | 寫入欄位 |
|------|------------------------|--------------------------|---------|
| `prompt` | `CLIPTextEncode`（第一個按 node id） | 同 | `inputs.text` |
| `negative_prompt` | `CLIPTextEncode`（第二個） | 同 | `inputs.text` |
| `seed` | `RandomNoise.noise_seed` | `KSampler.seed` / `KSamplerAdvanced.seed` / `KSamplerAdvanced.noise_seed` | `inputs.{seed,noise_seed}` |
| `steps` | `BasicScheduler.steps` | `KSampler.steps` / `KSamplerAdvanced.steps` | `inputs.steps` |
| `batch_size` | `EmptySD3LatentImage.batch_size` | `EmptyLatentImage.batch_size` / `EmptyLatentImageFlux.batch_size` | `inputs.batch_size` |
| `width` / `height` | `EmptySD3LatentImage.{width,height}` | `EmptyLatentImage.{width,height}` / `EmptyLatentImageFlux.{width,height}` | `inputs.width` / `inputs.height` |
| `face_ref_filename`（含路徑） | 所有 `LoadImage` | 同 | `inputs.image` |
| `output_subdir`（自動） | 所有 `SaveImage` | 同 | `inputs.filename_prefix = "{output_subdir}/img"` |

**注入順序**：seed → steps → batch_size → width/height → prompt → negative_prompt → face_ref → output_subdir。

## Flux 與 Legacy 的關鍵差異

Flux 工作流不是 KSampler 而是 SamplerCustomAdvanced 連鎖：

```
RandomNoise ──(noise)──┐
                       ↓
KSamplerSelect ───(sampler)──→ SamplerCustomAdvanced ──→ VAEDecode ──→ SaveImage
BasicScheduler ──(sigmas)─────↗
BasicGuider ────(guider)─────↗
```

所以「seed」要找 `RandomNoise.noise_seed`，「steps」要找 `BasicScheduler.steps`。

Legacy SD（SDXL / 1.5）用 `KSampler` 或 `KSamplerAdvanced`，seed/steps 都在同一個節點。

## 範例：flux_basic.json 注入過程

原始（簡化）：

```json
{
  "3": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
  "4": {"class_type": "EmptySD3LatentImage", "inputs": {"batch_size": 1}},
  "6": {"class_type": "RandomNoise", "inputs": {"noise_seed": 0}},
  "8": {"class_type": "BasicScheduler", "inputs": {"steps": 20}},
  "13": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI"}}
}
```

`inject(wf, prompt="A cat", seed=42, steps=30, batch_size=4, output_subdir="20260514_test")` 後：

```json
{
  "3": {"inputs": {"text": "A cat"}},
  "4": {"inputs": {"batch_size": 4}},
  "6": {"inputs": {"noise_seed": 42}},
  "8": {"inputs": {"steps": 30}},
  "13": {"inputs": {"filename_prefix": "20260514_test/img"}}
}
```

`SaveImage.filename_prefix = "{output_subdir}/img"` 規約讓 ComfyUI 把圖寫到 `output/20260514_test/img_00001_.png` 等。SCP 整個 `output/20260514_test/` 拉回即可。

## 多 LoadImage（face_ref）

當 `face_ref_filename = "20260514_test/face.png"` 時，**所有** LoadImage 節點 inputs.image 都會被覆寫成同一個值。
若工作流有多個 LoadImage 需要不同檔案，v1 不支援；未來可加 `face_ref_map = {node_id: filename}`。

## 失敗模式

| 錯誤 | 原因 | 修法 |
|---|---|---|
| `WorkflowParamError: no CLIPTextEncode found` | workflow JSON 沒有 prompt encoder | workflow 不對 |
| `WorkflowParamError: no seed-bearing node found` | 沒 RandomNoise / KSampler / KSamplerAdvanced | workflow 不對 |
| 多個 CLIPTextEncode 但只想填正向 | inject 預設第一個給 prompt | 暫不能精確指定；可加 `--node-id-map` (future) |
