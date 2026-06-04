"""Derive prompt strings from Plan's Design Dimensions.

IF-1 contract (P1 design spec):
    derive_prompt(plan: Plan, item: Item) -> str

Pure function — no IO, no side effects. Caller (gen side, M2) detects the
`"<derived>"` sentinel in `item.prompt` and replaces it with this output.

Coverage:
- BC-7: pure function, plan + item → string
- BC-8: slug → group_key parsing (pattern `{group_id}_{NN}_{name}`)
- BC-9: locked → literal; per_group → cross_group_progression lookup; fallback unspecified (DR-7)
- BC-10: unspecified dims contribute nothing to prompt
- BC-11/15: caller responsibility — sentinel detection happens outside this module
- EH-4: missing layer_a → ValueError
- EH-5: result violates BC-18 char boundary or exceeds 2000 chars → ValueError
- EH-6: all dims unspecified → empty result → ValueError

Plan Y v1.2 — Mode dispatch (album / storyboard):
- BC-DR1: album mode 行為與 v1.1 byte-equivalent（重構提取為 _derive_album、不變邏輯）
- BC-DR2: storyboard mode 順序「locked → beat → per_group」、rationale=視覺基底+主敘事+章節過渡
- BC-DR4/5/6: storyboard beat==None 行為（軟 fallback 用 cgp / 雙缺 abort）
- BC-DR7: 兩 mode 皆只讀 en `value`、不讀 `value_zh`
- IF-2: dict-based dispatch 對齊 M1 BC-S0 SSoT 精神（#009 prevention）

Translation strategy (Phase 2 choice, P1 § 七 allowed three options):
This module uses **passthrough** — Layer A values are emitted as-is (in
whatever language the user wrote them).
"""

from __future__ import annotations

import sys
from typing import Callable

from plan_schema import (
    _CAST_VISUAL_BUDGET_PER_PLAN,
    _LAYER_A_DIMENSION_NAMES,
    _resolve_per_item_config,
    Dimension,
    Item,
    LayerB,
    Plan,
    layer_a_is_empty,
)


# Length cap for derived prompt strings (IF-1 contract).
_MAX_PROMPT_LEN = 2000
# Sentinel that triggers derive (caller detects this in item.prompt).
DERIVED_SENTINEL = "<derived>"
# Locked dims that storyboard mode always emits up-front (visual base anchors).
# Per BC-DR2 rationale: visual anchors precede narrative beat.
_STORYBOARD_LOCKED_DIMS = (
    "hair", "outfit", "expression", "style_intensity",
    "view_angle", "color_palette",
)
# Per-group dims that may follow the narrative beat (scene transitions).
_STORYBOARD_PER_GROUP_DIMS = ("composition", "background", "lighting")


def derive_prompt(plan: Plan, item: Item) -> str:
    """Derive a prompt string from the plan's Design Dimensions.

    Plan Y v1.2 — dispatches on `plan.mode`:
    - "album"     → `_derive_album` (v1.1 byte-equivalent)
    - "storyboard" → `_derive_storyboard` (Layer D-driven narrative beat)

    Args:
        plan: Plan with non-None `layer_a` (and optionally `layer_b/c`).
        item: Item whose `slug` is parsed for the group key (album) or whose
              `beat_description` is consumed (storyboard).

    Returns:
        Single-line prompt string (IF-1 contract — see _validate_postcondition).

    Raises:
        ValueError EH-DR3: unsupported `plan.mode`.
        ValueError EH-4/5/6/EH-DR1/2: per-mode failures.
    """
    handler = _DERIVE_DISPATCH.get(plan.mode)
    if handler is None:
        raise ValueError(
            f"EH-DR3: derive_prompt: unsupported mode {plan.mode!r}; "
            f"expected one of {tuple(_DERIVE_DISPATCH)}"
        )
    return handler(plan, item)


def _derive_album(plan: Plan, item: Item) -> str:
    """BC-DR1: album mode — v1.1 byte-equivalent (locked + per_group)."""
    # R-2 fix: BC-3a behavior equivalence — layer_a is None and
    # LayerA(all unspecified) are equivalent "missing Design Dimensions"
    # states; both raise EH-4 (not EH-6) per design spec § 九 BC-3a.
    if plan.layer_a is None or layer_a_is_empty(plan.layer_a):
        raise ValueError(
            f"EH-4: missing Design Dimensions, cannot derive prompt for "
            f"item {item.slug!r}"
        )

    group_key = _extract_group_key(item.slug)
    # BC-G4-3: cast visual prepend (order: cast → locked → per_group).
    parts: list[str] = _cast_prefix_parts(plan, item)
    overridden = _protagonist_overrides(plan, item)  # BC-G4-4
    for dim_name in _LAYER_A_DIMENSION_NAMES:
        if dim_name in overridden:
            continue  # cast.protagonist.visual.{key} > visual_lock.{key}
        dim: Dimension = getattr(plan.layer_a, dim_name)
        value = _resolve_dimension(dim, dim_name, plan.layer_b, group_key)
        if value:
            parts.append(value)

    if not parts:
        raise ValueError(
            f"EH-6: all dimensions unspecified, derived prompt would be empty "
            f"for item {item.slug!r}"
        )

    result = ", ".join(parts)
    _validate_postcondition(result, item)
    return result


def _derive_storyboard(plan: Plan, item: Item) -> str:
    """BC-DR2: storyboard mode — order: locked → beat → per_group.

    Rationale: locked dims provide visual base anchors → beat provides
    main narrative action → per_group adds chapter scene transitions.
    """
    if plan.layer_a is None:
        raise ValueError(
            f"EH-4: missing Design Dimensions, cannot derive prompt for "
            f"item {item.slug!r}"
        )

    group_key = _extract_group_key(item.slug)
    # BC-G4-3 order: cast → locked → [beat_prefix] → beat → per_group → [beat_suffix].
    parts: list[str] = _cast_prefix_parts(plan, item)
    overridden = _protagonist_overrides(plan, item)  # BC-G4-4
    # Step 1: locked dims (visual base anchors)
    for dim_name in _STORYBOARD_LOCKED_DIMS:
        if dim_name in overridden:
            continue  # cast.protagonist.visual.{key} > visual_lock.{key}
        dim: Dimension = getattr(plan.layer_a, dim_name)
        if dim.scope == "locked" and dim.value:
            parts.append(dim.value)

    # BC-G6-2/3: beat_prefix before beat (storyboard only, use_template gate).
    beat_prefix, beat_suffix = _beat_templates(plan, item)
    if beat_prefix:
        parts.append(beat_prefix)

    # Step 2: item.beat_description OR fallback to cross_group_progression
    has_beat = item.beat_description is not None
    has_cgp = (
        plan.layer_b is not None
        and plan.layer_b.cross_group_progression is not None
    )
    if has_beat:
        # BC-DR4: use the beat verbatim (already in en per BC-DR7)
        parts.append(item.beat_description)
        # BC-DR2: per_group dims follow beat as scene transitions
        if has_cgp:
            _append_per_group_dims(parts, plan.layer_b, group_key)
    elif has_cgp:
        # BC-DR5: 軟 fallback — emit per_group dims as scene only, with warning
        sys.stdout.write(
            f"derive_prompt: item {item.slug!r} has no beat_description in "
            f"storyboard mode; falling back to cross_group_progression "
            f"group scene\n"
        )
        _append_per_group_dims(parts, plan.layer_b, group_key)
    else:
        # BC-DR6: beat==None + cgp empty/None → EH-DR1 abort
        raise ValueError(
            f"EH-DR1: storyboard mode requires either item {item.slug!r} to "
            f"have beat_description, or plan to define cross_group_progression"
        )

    # BC-G6-2: beat_suffix after per_group dims.
    if beat_suffix:
        parts.append(beat_suffix)

    if not parts:
        raise ValueError(
            f"EH-6: derived prompt would be empty for item {item.slug!r}"
        )

    result = ", ".join(parts)
    _validate_postcondition(result, item)
    return result


def _append_per_group_dims(
    parts: list[str],
    layer_b: LayerB,
    group_key: str,
) -> None:
    """Helper: append cross_group_progression values for storyboard scene dims."""
    cgp = layer_b.cross_group_progression
    if cgp is None:
        return
    for dim_name in _STORYBOARD_PER_GROUP_DIMS:
        per_dim = cgp.get(dim_name)
        if per_dim is None:
            continue
        value = per_dim.get(group_key)
        if value:
            parts.append(value)


def _cast_prefix_parts(plan: Plan, item: Item) -> list[str]:
    """BC-G4-3 + EH-G4-4 (per-plan budget): cast visual fragments to prepend.

    Returns [] when item.cast_in_panel empty or plan.cast absent. Per-value
    char boundaries are already enforced input-side (BC-G4-6); here we enforce
    the cumulative per-plan budget (≤ 1500) and name the offending cast list.
    """
    if not item.cast_in_panel or not plan.cast:
        return []
    parts: list[str] = []
    total = 0
    for cid in item.cast_in_panel:
        entry = plan.cast.get(cid)
        if entry is None:
            # parse-time EH-G4-1 should prevent this; defensive.
            raise ValueError(
                f"EH-G4-1: unknown character {cid!r} in cast_in_panel for "
                f"item {item.slug!r}"
            )
        for value in entry.visual.values():
            parts.append(value)
            total += len(value)
    if total > _CAST_VISUAL_BUDGET_PER_PLAN:
        raise ValueError(
            f"EH-G4-4: item {item.slug!r} cast prepend 累加 {total} chars > "
            f"{_CAST_VISUAL_BUDGET_PER_PLAN} budget（cast_in_panel="
            f"{item.cast_in_panel}）；derive 後會超 IF-G2 2000 chars 上限"
        )
    return parts


def _protagonist_overrides(plan: Plan, item: Item) -> set[str]:
    """BC-G4-4: cast.protagonist.visual.{key} > visual_lock.{key}.value.

    Returns the set of visual_lock dimension names that the protagonist entry
    (when present in cast_in_panel) overrides — caller skips those locked dims
    so the protagonist's value (already in the cast prepend) wins. The third
    tier (narrative_direction.character_seed) is moot in derive: character_seed
    is chat-guidance only and never enters the prompt (DR-6).
    """
    if not plan.cast or "protagonist" not in (item.cast_in_panel or []):
        return set()
    prot = plan.cast.get("protagonist")
    if prot is None:
        return set()
    return set(prot.visual.keys()) & set(_LAYER_A_DIMENSION_NAMES)


def _beat_templates(plan: Plan, item: Item) -> tuple[str | None, str | None]:
    """BC-G6-2/3/4: resolve (beat_prefix, beat_suffix) for storyboard mode.

    Gated by use_template (BC-G6-3). beat_prefix/suffix only ever resolve from
    the panel_type layer (None when item.panel_type absent or not in taxonomy).
    Album mode never calls this (BC-G6-4). Goes through the shared dispatch
    helper (DR-4) — no raw panel_taxonomy access here.
    """
    if not item.use_template or not item.panel_type:
        return None, None
    prefix, _ = _resolve_per_item_config(plan, item, "beat_prefix")
    suffix, _ = _resolve_per_item_config(plan, item, "beat_suffix")
    return prefix, suffix


def _validate_postcondition(result: str, item: Item) -> None:
    """IF-1 後置條件硬約束（兩 mode 共用）— BC-DR8/9/10。"""
    if "\n" in result:
        raise ValueError(
            f"EH-5: derived prompt contains newline for item {item.slug!r}"
        )
    if _has_unescaped_pipe(result):
        raise ValueError(
            f"EH-5: derived prompt contains unescaped `|` for item "
            f"{item.slug!r}"
        )
    if len(result) > _MAX_PROMPT_LEN:
        raise ValueError(
            f"EH-5: derived prompt too long ({len(result)} > {_MAX_PROMPT_LEN}) "
            f"for item {item.slug!r}"
        )


# IF-2 (Plan Y v1.2) — dict-based dispatch (DR-3 採納、對齊 M1 BC-S0 SSoT 精神).
# Defined AFTER the handler functions so they're resolvable.
# R-1 fix: strict typing — Callable[[Plan, Item], str] instead of builtin callable.
_DERIVE_DISPATCH: dict[str, Callable[[Plan, Item], str]] = {
    "album": _derive_album,
    "storyboard": _derive_storyboard,
}


def _extract_group_key(slug: str) -> str:
    """BC-8: parse group_id from slug.

    Expected slug pattern: `{group_id}_{NN}_{name}` where NN is 1-4 digits.
    Examples:
        "ch1_03_letter_arrival" → "ch1"
        "sr_01_pose"            → "sr"
        "n_99_card"             → "n"
    Fallback (no group structure):
        "single_token"          → "__single__"
        "two_word"              → "__single__"  (second token not numeric)
    """
    parts = slug.split("_")
    if len(parts) < 3:
        return "__single__"
    if not parts[1].isdigit():
        return "__single__"
    return parts[0]


def _resolve_dimension(
    dim: Dimension,
    dim_name: str,
    layer_b: LayerB | None,
    group_key: str,
) -> str | None:
    """Return the prompt fragment for one dimension, or None if unspecified.

    BC-9 logic:
    - scope=locked → return dim.value (literal)
    - scope=per_group → look up layer_b.cross_group_progression[dim_name][group_key]
    - scope=unspecified → return None (BC-10: contributes nothing)

    DR-7: per_group lookup falls back to None (not error) when:
    - layer_b is None
    - layer_b.cross_group_progression is None
    - dim_name not in cross_group_progression
    - group_key not in cross_group_progression[dim_name]
    """
    if dim.scope == "unspecified":
        return None
    if dim.scope == "locked":
        return dim.value if dim.value else None
    if dim.scope == "per_group":
        if layer_b is None or layer_b.cross_group_progression is None:
            return None
        per_dim = layer_b.cross_group_progression.get(dim_name)
        if per_dim is None:
            return None
        return per_dim.get(group_key)
    # Defensive: unknown scope (parse-time EH-2 should prevent this).
    return None


def _has_unescaped_pipe(s: str) -> bool:
    """True if `s` contains a `|` that isn't preceded by `\\`."""
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            i += 2
            continue
        if s[i] == "|":
            return True
        i += 1
    return False
