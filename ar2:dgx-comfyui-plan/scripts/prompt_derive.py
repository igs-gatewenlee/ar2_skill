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

Translation strategy (Phase 2 choice, P1 § 七 allowed three options):
This module uses **passthrough** — Layer A values are emitted as-is (in
whatever language the user wrote them). This is the simplest implementation
and avoids maintaining a Chinese ↔ English translation table. Caller agents
(chat-driven Claude) may pre-translate values into English before writing
the outline if a fully-English prompt is desired.
"""

from __future__ import annotations

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


def derive_prompt(plan: Plan, item: Item) -> str:
    """Derive a prompt string from the plan's Design Dimensions.

    Args:
        plan: Plan with non-None `layer_a` (and optionally `layer_b/c`).
        item: Item whose `slug` is parsed for the group key.

    Returns:
        Single-line prompt string (no newlines, no unescaped `|`,
        length ≤ 2000 chars).

    Raises:
        ValueError EH-4: `plan.layer_a` is None.
        ValueError EH-5: result violates BC-18 char boundary or > 2000 chars.
        ValueError EH-6: all dimensions resolve to unspecified (empty result).
    """
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

    # EH-5: BC-18 char boundary (no newline, no unescaped `|`, ≤ 2000 chars).
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

    return result


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
