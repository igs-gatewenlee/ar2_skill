---
id: typo_slug_test
title: Negative fixture for EH-D1 (typo slug in per_item_beats)
version: 1
created: '2026-05-21T00:00:00+08:00'
updated: '2026-05-21T00:00:00+08:00'
status: ready
workflow: flux_basic
size: [1024, 1024]
size_aspect: square
steps: 20
batch_per_item: 1
seed_strategy:
  type: fixed
  base: 42
lora: []
mode: storyboard
character_consistency: prompt_only
---

# Story / Vision
Negative fixture: per_item_beats contains a slug that's NOT in the Items table.
Expected behavior: parse should raise ValueError EH-D1 with valid slugs listed.

# Style anchor
**Prefix**: (none)
**Suffix**: (none)
**Negative**: (none)

# Output
- dir: outputs/typo_test/
- naming: {NN}_{slug}.png

# Items
| # | slug | prompt | full? |
|---|------|--------|-------|
| 1 | ch1_01_arrival | <derived> |  |
| 2 | ch1_02_decision | <derived> |  |

# Design Dimensions

```yaml
visual_lock:
  hair:
    value: brown hair
    scope: locked
per_item_beats:
  ch1_01_arrival:
    description: hero arrives
  ch1_99_typo_slug:
    description: this slug is NOT in the Items table — EH-D1 should fire
```

# Open notes
Negative test fixture (DR-9 採納、Plan Y v1.2).
