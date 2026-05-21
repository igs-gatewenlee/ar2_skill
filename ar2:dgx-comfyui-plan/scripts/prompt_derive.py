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
    _LAYER_A_DIMENSION_NAMES,
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
    parts: list[str] = []
    for dim_name in _LAYER_A_DIMENSION_NAMES:
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
    parts: list[str] = []
    # Step 1: locked dims (visual base anchors)
    for dim_name in _STORYBOARD_LOCKED_DIMS:
        dim: Dimension = getattr(plan.layer_a, dim_name)
        if dim.scope == "locked" and dim.value:
            parts.append(dim.value)

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
