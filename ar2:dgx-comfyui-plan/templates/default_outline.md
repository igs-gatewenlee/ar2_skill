---
id: PLACEHOLDER_ID
title: PLACEHOLDER_TITLE
version: 1
created: PLACEHOLDER_CREATED
updated: PLACEHOLDER_UPDATED
status: ready
workflow: flux_basic
size: [1024, 1024]
steps: 20
batch_per_item: 1
seed_strategy:
  type: incremental
  base: 1000
  step: 137
lora: []
face_ref: null
---

# Story / Vision
(用一段話描述這批圖的整體故事、氛圍、想表達什麼。

例：12 個東方生肖的擬人化人物，每張一個生肖 + 對應動物。
強調溫暖光線、和諧構圖、童話氛圍。)

# Style anchor
**Prefix**: (none)
**Suffix**: , anime style illustration, soft lighting, high quality, detailed character art
**Negative**: (none)

# Output
- dir: outputs/ar2-dgx-comfyui-gen/PLACEHOLDER_ID/
- naming: {NN}_{slug}_{n}.png

# Items
| # | slug | prompt | full? |
|---|------|--------|-------|
| 1 | example_slug | replace this prompt | |

# Open notes
(自由空間：寫不確定的點、未來變奏想法、與上次跑的差異等)
