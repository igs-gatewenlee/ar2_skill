"""Phase 4 tests for prompt_derive module.

Covers BC-7/8/9/10/11/15 + EH-4/5/6 from P1 spec.
Run: `python3 -m unittest tests.test_derive -v` from skill root.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import plan_schema as ps  # noqa: E402
import prompt_derive as pd  # noqa: E402


def _make_plan(
    layer_a: ps.LayerA | None = None,
    layer_b: ps.LayerB | None = None,
) -> ps.Plan:
    return ps.Plan(
        id="t", title="t", version=1,
        created=ps.now_iso(), updated=ps.now_iso(),
        status="ready", workflow="flux_basic",
        size=[512, 512], steps=20, batch_per_item=1,
        seed_strategy={"type": "fixed", "base": 0, "step": 0},
        items=[],
        layer_a=layer_a, layer_b=layer_b,
    )


def _full_layer_a(
    *,
    hair="brown braids",
    outfit_scope: tuple[str | None, str] = ("leather cloak", "locked"),
    composition_scope: tuple[str | None, str] = (None, "per_group"),
    background_scope: tuple[str | None, str] = (None, "per_group"),
    lighting="daylight",
    expression_scope: tuple[str | None, str] = (None, "unspecified"),
    style_intensity="Pixar 3D",
    view_angle_scope: tuple[str | None, str] = (None, "unspecified"),
    color_palette="warm tones",
) -> ps.LayerA:
    """Build a Layer A with sensible defaults — locked unless overridden."""
    return ps.LayerA(
        hair=ps.Dimension(hair, "locked"),
        outfit=ps.Dimension(outfit_scope[0], outfit_scope[1]),
        composition=ps.Dimension(composition_scope[0], composition_scope[1]),
        background=ps.Dimension(background_scope[0], background_scope[1]),
        lighting=ps.Dimension(lighting, "locked"),
        expression=ps.Dimension(expression_scope[0], expression_scope[1]),
        style_intensity=ps.Dimension(style_intensity, "locked"),
        view_angle=ps.Dimension(view_angle_scope[0], view_angle_scope[1]),
        color_palette=ps.Dimension(color_palette, "locked"),
    )


def _empty_layer_a() -> ps.LayerA:
    """All 9 dims unspecified."""
    return ps.LayerA(**{
        n: ps.Dimension(None, "unspecified")
        for n in ps._LAYER_A_DIMENSION_NAMES
    })


# ============================================================
# BC-7: basic derive
# ============================================================


class TestBC7BasicDerive(unittest.TestCase):

    def test_derive_with_only_locked(self):
        """BC-7: plan with all-locked layer_a + simple slug → ordered prompt."""
        plan = _make_plan(layer_a=_full_layer_a())
        item = ps.Item(slug="card_01", prompt="<derived>")
        result = pd.derive_prompt(plan, item)
        self.assertIn("brown braids", result)
        self.assertIn("leather cloak", result)
        self.assertIn("daylight", result)
        self.assertIn("Pixar 3D", result)
        self.assertIn("warm tones", result)
        # Order: dims listed in _LAYER_A_DIMENSION_NAMES order.
        self.assertLess(
            result.index("brown braids"),  # hair (1st)
            result.index("leather cloak"),  # outfit (2nd)
        )


# ============================================================
# BC-8: slug → group_key parsing
# ============================================================


class TestBC8SlugParsing(unittest.TestCase):

    def test_chapter_slug(self):
        self.assertEqual(pd._extract_group_key("ch1_03_letter_arrival"), "ch1")

    def test_rarity_slug(self):
        self.assertEqual(pd._extract_group_key("sr_01_pose"), "sr")

    def test_n_rarity_slug(self):
        self.assertEqual(pd._extract_group_key("n_99_card"), "n")

    def test_no_number_fallback(self):
        """slug without numeric second token → __single__."""
        self.assertEqual(pd._extract_group_key("alpha_beta_gamma"), "__single__")

    def test_two_token_fallback(self):
        self.assertEqual(pd._extract_group_key("just_two"), "__single__")

    def test_single_token_fallback(self):
        self.assertEqual(pd._extract_group_key("single"), "__single__")


# ============================================================
# BC-9: locked / per_group resolution
# ============================================================


class TestBC9Resolution(unittest.TestCase):

    def test_locked_returns_literal(self):
        plan = _make_plan(layer_a=_full_layer_a(hair="black short"))
        result = pd.derive_prompt(plan, ps.Item("x_01_y", "<derived>"))
        self.assertIn("black short", result)

    def test_per_group_lookup_success(self):
        """BC-9: per_group dim resolved via cross_group_progression[dim][group_key]."""
        layer_b = ps.LayerB(
            theme="x", grouping_axis="chapter",
            groups={"ch1": {"count": 12, "label": "啟程"}},
            cross_group_progression={
                "composition": {"ch1": "wide shot", "ch2": "close up"},
                "background": {"ch1": "cottage", "ch2": "forest"},
            },
        )
        plan = _make_plan(layer_a=_full_layer_a(), layer_b=layer_b)
        result = pd.derive_prompt(plan, ps.Item("ch1_01_morning", "<derived>"))
        self.assertIn("wide shot", result)  # composition for ch1
        self.assertIn("cottage", result)    # background for ch1

    def test_dr7_per_group_no_layer_b(self):
        """DR-7: per_group dim + layer_b is None → fallback to unspecified (no error)."""
        plan = _make_plan(layer_a=_full_layer_a(), layer_b=None)
        # composition is per_group but layer_b is None → composition skipped
        result = pd.derive_prompt(plan, ps.Item("ch1_01_x", "<derived>"))
        # locked dims still appear
        self.assertIn("brown braids", result)
        # per_group dims (composition, background) silently absent
        self.assertNotIn("wide shot", result)

    def test_dr7_per_group_progression_none(self):
        """DR-7: per_group dim + cross_group_progression is None → fallback."""
        layer_b = ps.LayerB(
            theme="x", grouping_axis="chapter", groups={"ch1": {}},
            cross_group_progression=None,
        )
        plan = _make_plan(layer_a=_full_layer_a(), layer_b=layer_b)
        result = pd.derive_prompt(plan, ps.Item("ch1_01_x", "<derived>"))
        self.assertIn("brown braids", result)  # locked still works

    def test_dr7_per_group_dim_missing_from_progression(self):
        """DR-7: per_group dim not in cross_group_progression → fallback."""
        layer_b = ps.LayerB(
            theme="x", grouping_axis="chapter", groups={"ch1": {}},
            cross_group_progression={"lighting": {"ch1": "noon"}},  # no composition
        )
        plan = _make_plan(layer_a=_full_layer_a(), layer_b=layer_b)
        result = pd.derive_prompt(plan, ps.Item("ch1_01_x", "<derived>"))
        # composition skipped (not in progression), lighting still uses locked value
        self.assertIn("daylight", result)
        self.assertNotIn("noon", result)  # lighting is locked, not per_group here

    def test_dr7_per_group_group_missing_from_progression(self):
        """DR-7: group_key missing from cross_group_progression[dim] → fallback."""
        layer_b = ps.LayerB(
            theme="x", grouping_axis="chapter", groups={"ch1": {}, "ch9": {}},
            cross_group_progression={
                "composition": {"ch1": "wide", "ch2": "close"},  # ch9 missing
            },
        )
        plan = _make_plan(layer_a=_full_layer_a(), layer_b=layer_b)
        # ch9 not in composition map → fallback (no error)
        result = pd.derive_prompt(plan, ps.Item("ch9_01_x", "<derived>"))
        self.assertIn("brown braids", result)
        self.assertNotIn("wide", result)
        self.assertNotIn("close", result)


# ============================================================
# BC-10: unspecified contributes nothing
# ============================================================


class TestBC10Unspecified(unittest.TestCase):

    def test_unspecified_skipped(self):
        """expression scope=unspecified → not in prompt."""
        layer_a = _full_layer_a(
            expression_scope=(None, "unspecified"),
        )
        plan = _make_plan(layer_a=layer_a)
        result = pd.derive_prompt(plan, ps.Item("card_01", "<derived>"))
        # expression dim has no value emitted (just confirm locked dims appear)
        self.assertIn("brown braids", result)
        # Result is comma-separated; no empty slot between commas
        self.assertNotIn(",,", result)
        self.assertNotIn(", ,", result)


# ============================================================
# EH-4: missing layer_a
# ============================================================


class TestEH4MissingLayerA(unittest.TestCase):

    def test_eh4_layer_a_none(self):
        plan = _make_plan(layer_a=None)
        with self.assertRaisesRegex(ValueError, "EH-4"):
            pd.derive_prompt(plan, ps.Item("card_01", "<derived>"))


# ============================================================
# EH-5: BC-18 char boundary
# ============================================================


class TestEH5CharBoundary(unittest.TestCase):

    def test_eh5_newline_in_value(self):
        """A locked dim with newline → EH-5."""
        layer_a = _full_layer_a(hair="line1\nline2")
        plan = _make_plan(layer_a=layer_a)
        with self.assertRaisesRegex(ValueError, "EH-5.*newline"):
            pd.derive_prompt(plan, ps.Item("card_01", "<derived>"))

    def test_eh5_unescaped_pipe(self):
        layer_a = _full_layer_a(hair="a | b")
        plan = _make_plan(layer_a=layer_a)
        with self.assertRaisesRegex(ValueError, "EH-5.*unescaped"):
            pd.derive_prompt(plan, ps.Item("card_01", "<derived>"))

    def test_eh5_escaped_pipe_ok(self):
        """\\| is properly escaped → no EH-5."""
        layer_a = _full_layer_a(hair=r"a \| b")
        plan = _make_plan(layer_a=layer_a)
        result = pd.derive_prompt(plan, ps.Item("card_01", "<derived>"))
        self.assertIn(r"a \| b", result)

    def test_eh5_length_cap(self):
        """Result > 2000 chars → EH-5."""
        layer_a = _full_layer_a(hair="x" * 3000)
        plan = _make_plan(layer_a=layer_a)
        with self.assertRaisesRegex(ValueError, "EH-5.*too long"):
            pd.derive_prompt(plan, ps.Item("card_01", "<derived>"))


# ============================================================
# EH-6: all unspecified → empty
# ============================================================


class TestEH6EmptyResult(unittest.TestCase):

    def test_eh4_all_unspecified_treated_as_empty(self):
        """R-2 fix: BC-3a — LayerA(全 unspecified) 等價於 layer_a is None → 走 EH-4 (not EH-6)."""
        plan = _make_plan(layer_a=_empty_layer_a())
        with self.assertRaisesRegex(ValueError, "EH-4"):
            pd.derive_prompt(plan, ps.Item("card_01", "<derived>"))

    def test_eh6_layer_a_all_per_group_no_layer_b(self):
        """All per_group dims + no layer_b → all fallback to unspecified → EH-6."""
        layer_a = ps.LayerA(**{
            n: ps.Dimension(None, "per_group") if n in {"composition", "background"}
            else ps.Dimension(None, "unspecified")
            for n in ps._LAYER_A_DIMENSION_NAMES
        })
        plan = _make_plan(layer_a=layer_a, layer_b=None)
        with self.assertRaisesRegex(ValueError, "EH-6"):
            pd.derive_prompt(plan, ps.Item("ch1_01_x", "<derived>"))


# ============================================================
# Sentinel constant
# ============================================================


class TestSentinel(unittest.TestCase):

    def test_sentinel_value(self):
        """Sentinel is the literal string `<derived>` (BC-11 contract)."""
        self.assertEqual(pd.DERIVED_SENTINEL, "<derived>")


if __name__ == "__main__":
    unittest.main(verbosity=2)
