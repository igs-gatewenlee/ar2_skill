---
id: bilingual_sb
title: Bilingual Storyboard fixture for M2 P4
version: 1
created: '2026-05-21T00:00:00+08:00'
updated: '2026-05-21T00:00:00+08:00'
status: ready
workflow: flux_pulid
size: [1280, 720]
size_aspect: landscape_16_9
steps: 20
batch_per_item: 1
seed_strategy:
  type: fixed
  base: 42
lora: []
mode: storyboard
character_consistency: pulid_face_ref
---

# Story / Vision
M2 P4 fixture covering Plan Y v1.2 storyboard mode with bilingual.

# Style anchor
**Prefix**: masterpiece
**Prefix_zh**: 傑作
**Suffix**: cinematic lighting
**Suffix_zh**: 電影感打光
**Negative**: deformed hands, blurry
**Negative_zh**: 變形的手、模糊

# Output
- dir: outputs/bilingual_sb/
- naming: {NN}_{slug}.png

# Items
| # | slug | prompt | full? |
|---|------|--------|-------|
| 1 | ch1_01_arrival | <derived> |  |
| 2 | ch1_02_decision | <derived> |  |
| 3 | ch1_03_no_beat | <derived> |  |

# Design Dimensions

```yaml
season_structure:
  theme: storyboard sample
  grouping_axis: chapter
  groups:
    ch1:
      count: 3
      label: opening
  cross_group_progression:
    composition:
      ch1: dynamic full body shot
    background:
      ch1: ancient village square
    lighting:
      ch1: warm golden hour
visual_lock:
  hair:
    value: medium brown hair
    value_zh: 棕色中長髮
    scope: locked
  outfit:
    value: leather travel armor
    value_zh: 皮製旅行護甲
    scope: locked
  composition:
    value: null
    scope: per_group
  background:
    value: null
    scope: per_group
  lighting:
    value: null
    scope: per_group
  expression:
    value: resolute and determined
    value_zh: 堅決決心
    scope: locked
  style_intensity:
    value: anime illustration
    value_zh: 動畫插畫風
    scope: locked
  view_angle:
    value: eye-level
    value_zh: 視線水平
    scope: locked
  color_palette:
    value: gold and deep blue
    value_zh: 金與深藍
    scope: locked
per_item_beats:
  ch1_01_arrival:
    description: hero walking into the village at sunset
    description_zh: 主角夕陽下走進村莊
  ch1_02_decision:
    description: hero accepting the quest scroll
    description_zh: 主角接過任務卷軸
```

# Open notes
DR-5 採納：所有 value_zh 字面與 value 不同（避免 byte 比對假陰性）。
ch1_03_no_beat 故意無 beat、用於 BC-DR5 軟 fallback 測試。
