"""M1 P4 tests — Plan Y v1.2 BC-x + EH-x coverage.

Tests for the 19 BC + 8 EH defined in P1 design spec v1.3:
- BC-S0/S1/S2/S3/S4/S5: new enum fields + SSoT
- BC-B1/B2/B3/B4: bilingual value_zh + StyleAnchor _zh
- BC-C1/C2/C2.5/C3: backward compat + round-trip
- BC-D1/D2/D3/D4/D5: Layer D per_item_beats
- EH-S1/S2/S3/S4: enum validation
- EH-B1/B2: bilingual type check
- EH-D1/D2: per_item_beats validation
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

# Add scripts/ to path so we can import plan_schema directly
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import plan_schema as ps  # noqa: E402


# ---------- helpers ----------


def _minimal_outline(
    *, mode="album", size_aspect=None, character_consistency=None,
    add_layer_a=False, add_per_item_beats=False, add_style_zh=False,
    extra_items=False,
) -> str:
    """Build a minimal outline.md text for parametric testing."""
    fm_lines = [
        "---",
        "id: test_a1b2",
        "title: Test",
        "version: 1",
        "created: '2026-05-21T00:00:00+08:00'",
        "updated: '2026-05-21T00:00:00+08:00'",
        "status: ready",
        "workflow: flux_basic",
        "size: [1024, 1024]",
        "steps: 20",
        "batch_per_item: 1",
        "seed_strategy:",
        "  type: fixed",
        "  base: 42",
        "lora: []",
        f"mode: {mode}",
    ]
    if size_aspect is not None:
        fm_lines.append(f"size_aspect: {size_aspect}")
    if character_consistency is not None:
        fm_lines.append(f"character_consistency: {character_consistency}")
    fm_lines.append("---")
    body = ["", "# Story / Vision", "test", "", "# Style anchor"]
    if add_style_zh:
        body.extend([
            "**Prefix**: masterpiece",
            "**Prefix_zh**: 傑作",
            "**Suffix**: (none)",
            "**Negative**: deformed",
            "**Negative_zh**: 殘缺",
        ])
    else:
        body.extend([
            "**Prefix**: (none)",
            "**Suffix**: (none)",
            "**Negative**: (none)",
        ])
    body.extend([
        "",
        "# Output",
        "- dir: outputs/test/",
        "- naming: {NN}_{slug}.png",
        "",
        "# Items",
        "| # | slug | prompt | full? |",
        "|---|------|--------|-------|",
        "| 1 | ch1_01_arr | <derived> |  |",
    ])
    if extra_items:
        body.append("| 2 | ch1_02_dec | <derived> |  |")
    if add_layer_a or add_per_item_beats:
        body.extend(["", "# Design Dimensions", "", "```yaml"])
        if add_layer_a:
            body.extend([
                "visual_lock:",
                "  hair:",
                "    value: brown hair",
                "    value_zh: 棕色頭髮",
                "    scope: locked",
            ])
        if add_per_item_beats:
            body.extend([
                "per_item_beats:",
                "  ch1_01_arr:",
                "    description: hero arriving",
                "    description_zh: 主角抵達",
            ])
        body.append("```")
    body.extend(["", "# Open notes", "test"])
    return "\n".join(fm_lines + body) + "\n"


def _parse_text(text: str) -> ps.Plan:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(text)
        tmp = Path(f.name)
    try:
        return ps.parse(tmp)
    finally:
        tmp.unlink()


# ---------- BC-S0 module constants ----------


def test_bc_s0_module_constants():
    """BC-S0: module-level enum constants exist as SSoT."""
    assert ps.MODE_ENUM == ("album", "storyboard")
    assert "square" in ps.SIZE_ASPECT_ENUM
    assert "landscape_16_9" in ps.SIZE_ASPECT_ENUM
    assert "portrait_2_3" in ps.SIZE_ASPECT_ENUM
    assert "prompt_only" in ps.CHARACTER_CONSISTENCY_ENUM
    assert "pulid_face_ref" in ps.CHARACTER_CONSISTENCY_ENUM
    assert "both" in ps.CHARACTER_CONSISTENCY_ENUM
    assert ps.SIZE_ASPECT_TO_SIZE["square"] == (1024, 1024)
    assert ps.SIZE_ASPECT_TO_SIZE["landscape_16_9"] == (1280, 720)


# ---------- BC-S1/S2/S3 enum + default ----------


def test_bc_s1_mode_default_album_when_missing():
    """BC-S1: frontmatter omits mode → default 'album'."""
    # Build text without `mode:` line
    text = _minimal_outline(mode="album").replace("mode: album\n", "")
    plan = _parse_text(text)
    assert plan.mode == "album"


def test_bc_s1_mode_storyboard_explicit():
    plan = _parse_text(_minimal_outline(mode="storyboard"))
    assert plan.mode == "storyboard"


def test_bc_s2_size_aspect_default_none_legacy(tmp_path):
    """BC-S2 v1.3 + BC-C2.5: legacy preset (no size_aspect) → Plan.size_aspect = None."""
    plan = _parse_text(_minimal_outline())  # no size_aspect
    assert plan.size_aspect is None


def test_bc_s3_character_consistency_default():
    """BC-S3: missing → 'prompt_only'."""
    plan = _parse_text(_minimal_outline())
    assert plan.character_consistency == "prompt_only"


def test_bc_s3_character_consistency_pulid():
    plan = _parse_text(_minimal_outline(character_consistency="pulid_face_ref"))
    assert plan.character_consistency == "pulid_face_ref"


# ---------- BC-S4/S5 size_aspect ↔ size SSoT ----------


def test_bc_s4_serialize_writes_size_aspect():
    """BC-S4: serialize writes size_aspect when present."""
    plan = _parse_text(_minimal_outline(size_aspect="landscape_16_9"))
    assert plan.size_aspect == "landscape_16_9"
    assert plan.size == [1280, 720]  # auto from SIZE_ASPECT_TO_SIZE
    text = ps.serialize(plan)
    assert "size_aspect: landscape_16_9" in text
    assert "size:" in text


def test_bc_s5_size_aspect_ssot_override(capsys):
    """BC-S5: size + size_aspect mismatch → warn + override size."""
    # Construct outline with mismatched size and size_aspect
    text = _minimal_outline(size_aspect="landscape_16_9")
    text = text.replace("size: [1024, 1024]", "size: [999, 999]")
    plan = _parse_text(text)
    captured = capsys.readouterr()
    # Warning emitted: contains 'size_aspect' and indicates override
    assert "size_aspect" in captured.out
    assert "999" in captured.out  # mentions the original bad value
    assert plan.size == [1280, 720]  # overridden by size_aspect SSoT
    assert plan.size_aspect == "landscape_16_9"


# ---------- BC-B1/B2 Dimension.value_zh ----------


def test_bc_b1_dimension_value_zh_default_none():
    """BC-B1: missing value_zh → Dimension.value_zh = None."""
    plan = _parse_text(_minimal_outline(add_layer_a=False))
    # No layer_a in this outline → Plan.layer_a is None, skip
    plan_la = _parse_text(_minimal_outline(add_layer_a=True))
    assert plan_la.layer_a.hair.value == "brown hair"
    assert plan_la.layer_a.hair.value_zh == "棕色頭髮"


def test_bc_b2_dimension_value_zh_round_trip():
    """BC-B2: serialize → re-parse preserves value_zh."""
    plan = _parse_text(_minimal_outline(add_layer_a=True))
    text = ps.serialize(plan)
    plan2 = _parse_text(text)
    assert plan2.layer_a.hair.value_zh == "棕色頭髮"
    assert plan == plan2


# ---------- BC-B4 StyleAnchor _zh dataclass fields ----------


def test_bc_b4_style_zh_round_trip():
    """BC-B4: style_*_zh fields parse + serialize round-trip."""
    plan = _parse_text(_minimal_outline(add_style_zh=True))
    assert plan.style_prefix == "masterpiece"
    assert plan.style_prefix_zh == "傑作"
    assert plan.style_negative == "deformed"
    assert plan.style_negative_zh == "殘缺"
    assert plan.style_suffix_zh is None  # not provided

    # Round-trip
    text = ps.serialize(plan)
    plan2 = _parse_text(text)
    assert plan == plan2


# ---------- BC-C2.5 legacy preset + BC-C3 semantic equivalence ----------


def test_bc_c2_5_legacy_preset_no_size_aspect():
    """BC-C2.5: legacy outline with only `size` no `size_aspect`.

    Plan.size_aspect = None; serialize does NOT emit size_aspect key.
    """
    plan = _parse_text(_minimal_outline())  # no size_aspect
    assert plan.size_aspect is None
    text = ps.serialize(plan)
    assert "size_aspect:" not in text


def test_bc_c3_round_trip_semantic_equiv_legacy_fixture():
    """BC-C3: 5/20 derived_mock_outline.md round-trip semantic-equivalent."""
    # sibling gen-skill fixture, relative to this file (plan/tests → skills/).
    legacy = (
        Path(__file__).resolve().parent.parent.parent
        / "dgx-comfyui-gen" / "tests" / "fixtures" / "derived_mock_outline.md"
    )
    plan = ps.parse(legacy)
    text = ps.serialize(plan)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(text)
        tmp = Path(f.name)
    plan2 = ps.parse(tmp)
    tmp.unlink()
    assert plan == plan2


# ---------- BC-D1/D2/D3/D5 Layer D per_item_beats ----------


def test_bc_d1_item_beat_default_none():
    """BC-D1: Item.beat_description default None."""
    plan = _parse_text(_minimal_outline())  # no per_item_beats
    assert plan.items[0].beat_description is None
    assert plan.items[0].beat_description_zh is None


def test_bc_d2_per_item_beats_apply():
    """BC-D2: per_item_beats YAML block applies to matching items by slug."""
    plan = _parse_text(_minimal_outline(add_per_item_beats=True))
    item = plan.items[0]
    assert item.beat_description == "hero arriving"
    assert item.beat_description_zh == "主角抵達"


def test_bc_d3_per_item_beats_round_trip():
    """BC-D3: serialize emits per_item_beats block + round-trip."""
    plan = _parse_text(_minimal_outline(add_per_item_beats=True))
    text = ps.serialize(plan)
    assert "per_item_beats" in text
    plan2 = _parse_text(text)
    assert plan == plan2


def test_bc_d4_legacy_no_per_item_beats():
    """BC-D4: legacy outline (no per_item_beats) → all item.beat = None."""
    plan = _parse_text(_minimal_outline())  # no per_item_beats
    assert all(it.beat_description is None for it in plan.items)


def test_bc_d5_item_no_entry_keeps_none():
    """BC-D5: item present in Items table but not in per_item_beats → None (normal)."""
    plan = _parse_text(
        _minimal_outline(add_per_item_beats=True, extra_items=True)
    )
    items_by_slug = {it.slug: it for it in plan.items}
    assert items_by_slug["ch1_01_arr"].beat_description == "hero arriving"
    # ch1_02_dec has no entry in per_item_beats → None (BC-D5)
    assert items_by_slug["ch1_02_dec"].beat_description is None


# ---------- EH-S1/S2/S3 enum validation ----------


def test_eh_s1_invalid_mode_aborts():
    """EH-S1: mode not in MODE_ENUM → ValueError."""
    text = _minimal_outline().replace("mode: album", "mode: invalid_mode")
    with pytest.raises(ValueError, match="mode"):
        _parse_text(text)


def test_eh_s2_invalid_size_aspect_aborts():
    text = _minimal_outline(size_aspect="invalid_aspect")
    with pytest.raises(ValueError, match="size_aspect"):
        _parse_text(text)


def test_eh_s3_invalid_character_consistency_aborts():
    text = _minimal_outline(character_consistency="invalid_cc")
    with pytest.raises(ValueError, match="character_consistency"):
        _parse_text(text)


# ---------- EH-B1 Dimension.value_zh type check ----------


def test_eh_b1_value_zh_non_string_aborts():
    """EH-B1: Dimension.value_zh must be str, not list/dict."""
    text = _minimal_outline(add_layer_a=True).replace(
        "value_zh: 棕色頭髮",
        "value_zh:\n      - bad\n      - list",
    )
    with pytest.raises(ValueError, match="value_zh"):
        _parse_text(text)


# ---------- EH-D1/D2 per_item_beats validation ----------


def test_eh_d1_typo_slug_aborts_with_valid_slugs_in_message():
    """EH-D1: per_item_beats contains slug not in Items table → ValueError with valid slugs."""
    fixture = Path(__file__).parent / "fixtures" / "typo_slug_storyboard_mock.md"
    assert fixture.exists(), f"Negative fixture missing: {fixture}"
    with pytest.raises(ValueError) as excinfo:
        ps.parse(fixture)
    msg = str(excinfo.value)
    assert "EH-D1" in msg
    assert "ch1_99_typo_slug" in msg  # the typo slug
    assert "ch1_01_arrival" in msg  # valid slugs list
    assert "ch1_02_decision" in msg  # valid slugs list


def test_eh_d2_per_item_beats_non_mapping_aborts():
    """EH-D2: per_item_beats entry must be a mapping, not a scalar/list."""
    text = _minimal_outline(add_per_item_beats=True).replace(
        "  ch1_01_arr:\n    description: hero arriving\n    description_zh: 主角抵達",
        "  ch1_01_arr: just_a_string_not_a_mapping",
    )
    with pytest.raises(ValueError, match="EH-D2|must be a mapping"):
        _parse_text(text)


# ---------- IF-3 fork + clone preservation ----------


def test_if3_fork_preserves_all_v12_fields():
    """IF-3: dataclasses.replace pattern propagates all new fields (R-1 fix)."""
    plan = _parse_text(_minimal_outline(
        mode="storyboard",
        size_aspect="landscape_16_9",
        character_consistency="pulid_face_ref",
        add_layer_a=True,
        add_style_zh=True,
        add_per_item_beats=True,
    ))
    forked = replace(plan, id="fork_x9y8", title="Fork test")
    assert forked.mode == "storyboard"
    assert forked.size_aspect == "landscape_16_9"
    assert forked.character_consistency == "pulid_face_ref"
    assert forked.layer_a.hair.value_zh == "棕色頭髮"
    assert forked.style_prefix_zh == "傑作"
    # Items are not deep-copied here, but fork itself preserves the list
    assert forked.items[0].beat_description == "hero arriving"


def test_if3_clone_item_preserves_layer_d():
    """IF-3 + R-2 fix: _clone_item via replace(it) propagates beat_description."""
    import plan_create as pc
    plan = _parse_text(_minimal_outline(add_per_item_beats=True))
    orig = plan.items[0]
    cloned = pc._clone_item(orig)
    assert cloned.slug == orig.slug
    assert cloned.beat_description == "hero arriving"
    assert cloned.beat_description_zh == "主角抵達"
    # Mutation of cloned shouldn't affect orig
    cloned.prompt = "MODIFIED"
    assert orig.prompt != "MODIFIED"
