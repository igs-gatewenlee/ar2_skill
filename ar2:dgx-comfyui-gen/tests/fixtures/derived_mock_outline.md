---
id: derived_mock
title: Derived mock outline for M2-P4 integration test
version: 1
created: '2026-05-20T00:00:00+08:00'
updated: '2026-05-20T00:00:00+08:00'
status: ready
workflow: flux_basic
size:
- 512
- 512
steps: 20
batch_per_item: 1
seed_strategy:
  type: fixed
  base: 42
lora: []
---

# Story / Vision
M2-P4 integration fixture. Covers BC-G3 (derived final_prompt is derive ground-truth)
and BC-G5 (mixed sentinel + manual items). Uses 3 locked dims + 2 per_group dims +
1 sentinel item interleaved with manual items.

# Style anchor
**Prefix**: (none)
**Suffix**: (none)
**Negative**: (none)

# Output
- dir: outputs/derived_mock/
- naming: {NN}_{slug}.png

# Items
| # | slug | prompt | full? |
|---|------|--------|-------|
| 1 | rare_01_dragon | a manual prompt for the dragon card |  |
| 2 | rare_02_phoenix | <derived> |  |
| 3 | common_01_squire | a manual common-rarity squire card |  |

# Design Dimensions

```yaml
season_structure:
  theme: fantasy rarity tiers
  grouping_axis: rarity
  groups:
    rare:
      count: 2
      label: Rare
    common:
      count: 1
      label: Common
  cross_group_progression:
    background:
      rare: golden palace interior
      common: modest village square
    lighting:
      rare: dramatic spotlight
      common: soft daylight
narrative_direction:
  character_seed: heroic figures from a fantasy realm
  group_arc:
    rare: legendary characters in their power moment
    common: everyday characters in quiet moments
visual_lock:
  hair:
    value: long flowing red hair
    scope: locked
  outfit:
    value: ornate armor with crimson cloak
    scope: locked
  composition:
    value: portrait centered
    scope: locked
  background:
    value: null
    scope: per_group
  lighting:
    value: null
    scope: per_group
```

# Open notes
M2-P4 fixture only. Not for production use.
