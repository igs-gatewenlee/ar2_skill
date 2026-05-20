"""Tests for plan_loader sentinel detection + derive integration.

Covers M2-P1 design spec:
- BC-G1: _import_prompt_derive returns module with derive_prompt + DERIVED_SENTINEL
- BC-G2: exact match only — variants (trailing space, uppercase, empty) go non-derive path
- BC-G3: sentinel hit → derive result IS final_prompt (no _join_prompt wrap, no item.full branch)
- BC-G4: regression — outline without sentinel produces identical ResolvedItem list
- BC-G5: mixed items — sentinel + manual coexist in order
- BC-G6: eager import — _import_prompt_derive called at _expand_items entry
- EH-G2: derive ValueError wrapped with item index + slug + remediation hint
- EH-G3: layer_a None + sentinel item → fail-fast on first failing item
- DR-1 char boundary defence: style_prefix containing `|` does NOT pollute derived final_prompt
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import plan_loader  # noqa: E402

schema = plan_loader._import_plan_schema()
prompt_derive = plan_loader._import_prompt_derive()


# ---------- Helpers: build minimal Plan / Item / Layer for tests ----------

def _make_dim(value=None, scope="unspecified"):
    return schema.Dimension(value=value, scope=scope)


def _make_layer_a(**dims):
    """Build LayerA with all 9 dims defaulting to unspecified; override via kwargs."""
    defaults = {
        name: _make_dim() for name in (
            "hair", "outfit", "composition", "background", "lighting",
            "expression", "style_intensity", "view_angle", "color_palette",
        )
    }
    defaults.update(dims)
    return schema.LayerA(**defaults)


def _make_layer_b(**kwargs):
    return schema.LayerB(
        theme=kwargs.get("theme", "test theme"),
        grouping_axis=kwargs.get("grouping_axis", "rarity"),
        groups=kwargs.get("groups", {"common": {"count": 6, "label": "Common"}}),
        cross_group_progression=kwargs.get("cross_group_progression"),
    )


def _make_plan(items, layer_a=None, layer_b=None,
               style_prefix="(none)", style_suffix="(none)"):
    return schema.Plan(
        id="testplan_abcd",
        title="Test Plan",
        version=1,
        created="2026-05-20T00:00:00+08:00",
        updated="2026-05-20T00:00:00+08:00",
        status="working",
        workflow="flux_basic",
        size=[1024, 1024],
        steps=20,
        batch_per_item=1,
        seed_strategy={"type": "fixed", "base": 42},
        style_prefix=style_prefix,
        style_suffix=style_suffix,
        style_negative="(none)",
        output_dir="out",
        items=items,
        layer_a=layer_a,
        layer_b=layer_b,
    )


def _make_derivable_plan(items, hair_value="long hair", **kwargs):
    """Build a plan with locked hair dim + default layer_b — derive_prompt-ready."""
    return _make_plan(
        items=items,
        layer_a=_make_layer_a(hair=_make_dim(hair_value, "locked")),
        layer_b=_make_layer_b(),
        **kwargs,
    )


# ---------- BC-G1: sibling import returns expected module ----------

def test_import_prompt_derive_returns_module_with_contract():
    """BC-G1: _import_prompt_derive returns a module exposing the IF-1 contract."""
    mod = plan_loader._import_prompt_derive()
    assert callable(getattr(mod, "derive_prompt", None))
    assert getattr(mod, "DERIVED_SENTINEL", None) == "<derived>"


def test_import_prompt_derive_is_cached():
    """BC-G1 cache: repeated calls return the same module object (sys.modules cache)."""
    first = plan_loader._import_prompt_derive()
    second = plan_loader._import_prompt_derive()
    assert first is second


# ---------- BC-G2: sentinel exact match only ----------

@pytest.mark.parametrize("not_sentinel", [
    "<derived> ",       # trailing space
    " <derived>",       # leading space
    "<DERIVED>",        # uppercase
    "<derive>",         # missing 'd'
    "",                 # empty
    "<derived>x",       # extra suffix
])
def test_sentinel_variants_treated_as_manual(not_sentinel):
    """BC-G2: only exact equality with DERIVED_SENTINEL triggers derive path.

    Variants must go through _join_prompt with prefix/suffix (or pass through
    when item.full=True) — never invoke derive_prompt.
    """
    plan = _make_plan(
        items=[schema.Item(slug="x", prompt=not_sentinel, full=False)],
        style_prefix="comic style", style_suffix="dramatic",
        layer_a=None,  # would trigger EH-4 if derive were called
    )
    resolved = plan_loader._expand_items(plan)
    # Did not raise (layer_a None) → confirms derive not invoked.
    # Final prompt includes prefix + body + suffix (per _join_prompt rules).
    assert resolved[0].final_prompt != ""


# ---------- BC-G3 + DR-1: derive result IS final_prompt, no wrap ----------

def test_sentinel_hit_returns_derive_result_unwrapped():
    """BC-G3: sentinel hit → final_prompt is exactly the derive result.

    No _join_prompt wrap — even when style_prefix / style_suffix are set,
    they MUST NOT appear in the derived item's final_prompt.
    """
    plan = _make_derivable_plan(
        items=[schema.Item(slug="ch1_01_hero", prompt="<derived>", full=False)],
        hair_value="long red hair",
        style_prefix="comic style", style_suffix="cinematic",
    )
    derive_result = prompt_derive.derive_prompt(plan, plan.items[0])
    resolved = plan_loader._expand_items(plan)
    assert resolved[0].final_prompt == derive_result.strip()
    # Neither prefix nor suffix appears in derived final_prompt.
    assert "comic style" not in resolved[0].final_prompt
    assert "cinematic" not in resolved[0].final_prompt


def test_dr1_pipe_in_style_anchor_does_not_pollute_derived():
    """DR-1 defence: style_prefix containing `|` MUST NOT leak into derived
    final_prompt. This guards M1 IF-1's "no unescaped `|`" post-condition
    against caller-side wrap silently breaking it.
    """
    plan = _make_derivable_plan(
        items=[schema.Item(slug="ch1_01_hero", prompt="<derived>", full=False)],
        hair_value="blue hair",
        style_prefix="anime style | studio ghibli",  # pipe in prefix
        style_suffix="dramatic | dark",               # pipe in suffix
    )
    resolved = plan_loader._expand_items(plan)
    assert "|" not in resolved[0].final_prompt


def test_sentinel_hit_ignores_item_full_flag():
    """BC-G3: item.full is ignored for sentinel items (derive is the SSoT).

    Both full=True and full=False produce the same final_prompt.
    """
    def _expand_with_full(full_flag: bool):
        plan = _make_derivable_plan(
            items=[schema.Item(slug="ch1_01_x", prompt="<derived>", full=full_flag)],
            hair_value="short",
            style_prefix="comic", style_suffix="hd",
        )
        return plan_loader._expand_items(plan)

    out_a = _expand_with_full(True)
    out_b = _expand_with_full(False)
    assert out_a[0].final_prompt == out_b[0].final_prompt


# ---------- BC-G4: backward-compat regression ----------

def test_no_sentinel_outline_unchanged_full_false():
    """BC-G4: outline without sentinel + full=False → prefix + body + suffix."""
    plan = _make_plan(
        items=[schema.Item(slug="ch1_01_a", prompt="a brave knight", full=False)],
        style_prefix="comic style", style_suffix="cinematic",
    )
    resolved = plan_loader._expand_items(plan)
    # _join_prompt with comma-free anchors uses ", " separator.
    assert resolved[0].final_prompt == "comic style, a brave knight, cinematic"


def test_no_sentinel_outline_unchanged_full_true():
    """BC-G4: outline without sentinel + full=True → prompt as-is, no wrap."""
    plan = _make_plan(
        items=[schema.Item(slug="ch1_01_a", prompt="self contained prompt", full=True)],
        style_prefix="comic style", style_suffix="cinematic",
    )
    resolved = plan_loader._expand_items(plan)
    assert resolved[0].final_prompt == "self contained prompt"


# ---------- BC-G5: mixed sentinel + manual items ----------

def test_mixed_items_order_preserved_each_takes_its_path():
    """BC-G5: sentinel and manual items coexist; each follows its own path
    and the output preserves plan.items order.
    """
    plan = _make_derivable_plan(
        items=[
            schema.Item(slug="ch1_01_a", prompt="manual one", full=False),
            schema.Item(slug="ch1_02_b", prompt="<derived>", full=False),
            schema.Item(slug="ch1_03_c", prompt="manual two", full=True),
        ],
        style_prefix="prefix", style_suffix="suffix",
    )
    resolved = plan_loader._expand_items(plan)
    assert [r.slug for r in resolved] == ["ch1_01_a", "ch1_02_b", "ch1_03_c"]
    # Manual full=False got wrapped, derived item did not, manual full=True did not.
    assert "prefix" in resolved[0].final_prompt and "suffix" in resolved[0].final_prompt
    assert "prefix" not in resolved[1].final_prompt
    assert resolved[2].final_prompt == "manual two"


# ---------- BC-G6: eager import ----------

def test_import_called_even_when_no_sentinel_items(monkeypatch):
    """BC-G6: _import_prompt_derive is invoked at _expand_items entry
    regardless of whether any item uses the sentinel.
    """
    calls = {"n": 0}
    original = plan_loader._import_prompt_derive

    def counting():
        calls["n"] += 1
        return original()

    monkeypatch.setattr(plan_loader, "_import_prompt_derive", counting)
    plan = _make_plan(items=[
        schema.Item(slug="x", prompt="no sentinel here", full=False),
    ])
    plan_loader._expand_items(plan)
    assert calls["n"] == 1


# ---------- EH-G2: derive ValueError wrapped with item context ----------

def test_eh_g2_wraps_derive_error_with_item_context():
    """EH-G2: derive_prompt ValueError → re-raised with item index + slug
    + remediation hint, original exception preserved in __cause__.
    """
    plan = _make_plan(
        items=[schema.Item(slug="ch1_01_x", prompt="<derived>", full=False)],
        layer_a=None,  # triggers EH-4 in derive_prompt
    )
    with pytest.raises(ValueError) as exc_info:
        plan_loader._expand_items(plan)
    msg = str(exc_info.value)
    assert "item 1" in msg
    assert "ch1_01_x" in msg
    assert "<derived>" in msg
    assert "Fill Design Dimensions" in msg
    # Exception chain preserved.
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, ValueError)


# ---------- EH-G3: fail-fast on first failing item ----------

def test_eh_g3_fail_fast_on_first_sentinel_failure():
    """EH-G3: first sentinel item that fails triggers ValueError; subsequent
    items are not processed (no leakage of partial state).
    """
    plan = _make_plan(
        items=[
            schema.Item(slug="ch1_01_first", prompt="<derived>", full=False),
            schema.Item(slug="ch1_02_second", prompt="<derived>", full=False),
        ],
        layer_a=None,
    )
    with pytest.raises(ValueError) as exc_info:
        plan_loader._expand_items(plan)
    # Identifies the FIRST failing item, not the second.
    assert "item 1" in str(exc_info.value)
    assert "ch1_01_first" in str(exc_info.value)
    assert "ch1_02_second" not in str(exc_info.value)


# ---------- EH-G1: RuntimeError when sibling module not found ----------

def test_eh_g1_runtime_error_with_install_hint_and_searched_paths():
    """EH-G1 (R-4 fix): _import_sibling_module raises RuntimeError with the
    install hint and the list of searched candidate paths when the target
    file does not exist in any candidate location.

    Triggered by asking for a file_name that is guaranteed not to exist
    anywhere — verifies the failure path without mocking the file system.
    """
    with pytest.raises(RuntimeError) as exc_info:
        plan_loader._import_sibling_module(
            "test_fake_module_for_eh_g1", "nonexistent_module_xyz.py"
        )
    msg = str(exc_info.value)
    assert "nonexistent_module_xyz not found" in msg
    assert "Install ar2:dgx-comfyui-plan skill" in msg
    assert "searched:" in msg
    # Searched paths include the deployed-skills and source-repo candidates.
    assert "ar2:dgx-comfyui-plan" in msg


# ---------- Integration: real cards_a11c regression (R-2 arch-risk addressed) ----------

def test_real_cards_a11c_outline_regression():
    """R-2 / BC-G4: real production cards_a11c outline (no Design Dimensions,
    all manual prompts) loads successfully and produces ResolvedItem list
    with all items going through _join_prompt path (no derive invocation).

    Skipped if cards_a11c is not present in this environment.
    """
    plans_dir = Path.home() / "Code" / "ai_cards" / "plans"
    outline_path = plans_dir / "cards_a11c_outline.md"
    if not outline_path.exists():
        pytest.skip("cards_a11c outline not present in this environment")

    loaded = plan_loader.load_working(plans_dir, "cards_a11c")
    plan_obj = loaded.raw

    # Sanity: outline has items and they all loaded.
    assert len(loaded.items) > 0
    assert len(loaded.items) == len(plan_obj.items)

    # BC-G4: no item uses the sentinel — all went through manual path.
    sentinel = prompt_derive.DERIVED_SENTINEL
    assert all(item.prompt != sentinel for item in plan_obj.items)

    # BC-G4: every resolved item has a non-empty final_prompt with the style
    # suffix applied (cards_a11c uses Disney Pixar suffix on all items).
    expected_suffix_fragment = "Disney Pixar"
    for r in loaded.items:
        assert isinstance(r.final_prompt, str) and r.final_prompt
        # cards_a11c sets all items full=False (no field in table) — suffix applies.
        assert expected_suffix_fragment in r.final_prompt


# ---------- Integration: mock outline with Design Dimensions (#008 + BC-G3) ----------

def test_integration_mock_outline_derives_against_ground_truth():
    """#008 / R-2 / BC-G3: fixture outline with Design Dimensions + a sentinel
    item. After load_working, the sentinel item's final_prompt MUST equal
    the derive_prompt ground-truth (no _join_prompt wrap, no anchor pollution).

    This is the closest pre-ComfyUI integration check we can run without
    real generation. ComfyUI end-to-end real-run is tracked separately.
    """
    fixture_path = Path(__file__).parent / "fixtures" / "derived_mock_outline.md"
    assert fixture_path.exists(), f"fixture missing: {fixture_path}"

    loaded = plan_loader._load(fixture_path, mode="plan")
    plan_obj = loaded.raw

    # Find the sentinel item (rare_02_phoenix in the fixture).
    sentinel = prompt_derive.DERIVED_SENTINEL
    sentinel_idx, sentinel_item = next(
        (i, it) for i, it in enumerate(plan_obj.items, start=1)
        if it.prompt == sentinel
    )
    sentinel_resolved = loaded.items[sentinel_idx - 1]

    # Ground truth: call derive_prompt directly on the parsed plan + item.
    ground_truth = prompt_derive.derive_prompt(plan_obj, sentinel_item).strip()

    # BC-G3: final_prompt is the derive ground truth verbatim.
    assert sentinel_resolved.final_prompt == ground_truth

    # BC-G5: surrounding manual items still produce their own final_prompt.
    manual_resolved = [
        r for i, r in enumerate(loaded.items, start=1)
        if plan_obj.items[i - 1].prompt != sentinel
    ]
    assert all(r.final_prompt for r in manual_resolved)

    # Sanity: derive ground truth pulls in locked Layer A dims.
    assert "long flowing red hair" in ground_truth


def test_integration_mock_outline_per_group_dims_resolve_via_slug():
    """BC-G8 (derive_prompt slug parsing) + BC-G3: rare_02_phoenix's slug
    parses to group_key='rare'; per_group `background` dim should resolve
    via cross_group_progression['background']['rare'] = 'golden palace interior'.
    """
    fixture_path = Path(__file__).parent / "fixtures" / "derived_mock_outline.md"
    loaded = plan_loader._load(fixture_path, mode="plan")
    plan_obj = loaded.raw
    sentinel_resolved = next(
        r for i, r in enumerate(loaded.items, start=1)
        if plan_obj.items[i - 1].prompt == prompt_derive.DERIVED_SENTINEL
    )
    # per_group resolution proves the integration touches Layer B + slug parsing.
    assert "golden palace interior" in sentinel_resolved.final_prompt
    assert "dramatic spotlight" in sentinel_resolved.final_prompt
