"""Phase 4 tests — Plan Y v1.3 schema (panel_taxonomy / cast / dispatch / events).

Covers testable BC-G0/G2/G3/G4/G5/G6 + EH-G3/G4/G5 from
P1-design-spec-PlanY_v1.3.md (round 4 final).

Run: `python3 -m pytest tests/test_plan_y_v13.py` from skill root.

#009 / BC-G9-4: fixtures use dataclasses.replace(_base_*, ...) so future
dataclass fields auto-propagate (no manual keyword drift).
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import plan_schema as ps  # noqa: E402
import prompt_derive as pd  # noqa: E402

_FIXDIR = ROOT / "tests" / "fixtures" / "v12_regression"


# ---------- #009-safe base fixtures (replace pattern) ----------

_BASE_PLAN = ps.Plan(
    id="t", title="t", version=1,
    created="2026-01-01T00:00:00+08:00", updated="2026-01-01T00:00:00+08:00",
    status="ready", workflow="flux_basic",
    size=[512, 512], steps=20, batch_per_item=1,
    seed_strategy={"type": "fixed", "base": 0, "step": 0},
    items=[],
)
_BASE_ITEM = ps.Item(slug="ch1_01_x", prompt="<derived>")


def _plan(**overrides) -> ps.Plan:
    return replace(_BASE_PLAN, **overrides)


def _item(**overrides) -> ps.Item:
    return replace(_BASE_ITEM, **overrides)


# ---------- outline writer (parse-path tests) ----------

_REQUIRED_SECTIONS = """# Story / Vision
v1.3 test

# Style anchor
**Prefix**: (none)
**Suffix**: (none)
**Negative**: (none)

# Output
- dir: out/
- naming: {NN}_{slug}.png

# Items
| # | slug | prompt | full? |
|---|------|--------|-------|
{items}

# Open notes
(none)
"""


def _write_outline(
    tmp: Path, *, frontmatter_extra: str = "", dd_yaml: str | None = None,
    items_rows: str = "| 1 | ch1_01_hero | a hero |  |",
    mode: str = "album",
) -> Path:
    fm = (
        "---\n"
        "id: t\ntitle: t\nversion: 1\n"
        "created: '2026-01-01T00:00:00+08:00'\n"
        "updated: '2026-01-01T00:00:00+08:00'\n"
        f"status: ready\nworkflow: flux_basic\nmode: {mode}\n"
        "size:\n- 512\n- 512\nsteps: 20\nbatch_per_item: 1\n"
        "seed_strategy:\n  type: fixed\n  base: 0\n  step: 0\n"
        f"{frontmatter_extra}"
        "---\n\n"
    )
    body = _REQUIRED_SECTIONS.replace("{items}", items_rows)
    if dd_yaml is not None:
        dd = f"# Design Dimensions\n\n```yaml\n{dd_yaml}```\n\n"
        body = dd + body
    path = tmp / "t_outline.md"
    path.write_text(fm + body, encoding="utf-8")
    return path


# ============================================================
# BC-G0: backward compat + frozen baseline regression
# ============================================================


class TestBCG0Backward(unittest.TestCase):

    def test_bcg0_4_frozen_baseline_byte_equal(self):
        """BC-G0-4/0-6: v1.3 parser+derive byte-equal to frozen v1.2 baseline."""
        spec = importlib.util.spec_from_file_location(
            "_v12_baseline", _FIXDIR / "dragon_hunt_ensemble_baseline.py"
        )
        bl = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bl)
        plan = ps.parse(_FIXDIR / "dragon_hunt_ensemble_outline.md")
        by_slug = {it.slug: it for it in plan.items}
        for slug, expected in bl.EXPECTED_DERIVE.items():
            got = pd.derive_prompt(plan, by_slug[slug])
            self.assertEqual(got, expected, f"derive drift for {slug}")

    def test_bcg0_2_3_v12_outline_new_fields_default(self):
        """BC-G0-2/3: v1.2 outline (no v1.3 keys) → new fields default None/[]."""
        with tempfile.TemporaryDirectory() as td:
            p = ps.parse(_write_outline(Path(td)))
        self.assertIsNone(p.panel_taxonomy)
        self.assertIsNone(p.cast)
        self.assertIsNone(p.plan_quality)
        self.assertEqual(p.items[0].cast_in_panel, [])
        self.assertIsNone(p.items[0].panel_type)
        self.assertTrue(p.items[0].use_template)

    def test_bcg0_5_v12_roundtrip_byte_equivalent(self):
        """BC-G0-5: serialize(parse(v1.2)) round-trips with no v1.3 noise."""
        plan = ps.parse(_FIXDIR / "dragon_hunt_ensemble_outline.md")
        ser = ps.serialize(plan)
        self.assertNotIn("panel_taxonomy", ser)
        self.assertNotIn("cast:", ser)
        self.assertNotIn("plan_quality", ser)
        # idempotent re-parse → re-serialize
        with tempfile.TemporaryDirectory() as td:
            p2 = Path(td) / "rt_outline.md"
            p2.write_text(ser, encoding="utf-8")
            self.assertEqual(ps.serialize(ps.parse(p2)), ser)


# ============================================================
# BC-G3: panel_taxonomy + dispatch
# ============================================================


class TestBCG3PanelTaxonomy(unittest.TestCase):

    def test_bcg3_1_5_parse_panel_taxonomy(self):
        dd = (
            "panel_taxonomy:\n"
            "  hero_closeup:\n"
            "    workflow: flux_pulid\n"
            "    pulid: {enabled: true, strength: 1.2}\n"
            "    beat_prefix: 'close-up'\n"
            "  multi_character_ensemble:\n"
            "    workflow: flux_basic\n"
            "    pulid: {enabled: false}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            p = ps.parse(_write_outline(Path(td), dd_yaml=dd))
        self.assertIn("hero_closeup", p.panel_taxonomy)
        cfg = p.panel_taxonomy["hero_closeup"]
        self.assertEqual(cfg.workflow, "flux_pulid")
        self.assertEqual(cfg.pulid, {"enabled": True, "strength": 1.2})
        self.assertEqual(cfg.beat_prefix, "close-up")

    def test_bcg3_2_panel_type_regex_reject_digit_start(self):
        dd = "panel_taxonomy:\n  1bad: {workflow: x}\n"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"a-z"):
                ps.parse(_write_outline(Path(td), dd_yaml=dd))

    def test_bcg3_2_panel_type_reserved_rejected(self):
        dd = "panel_taxonomy:\n  default: {workflow: x}\n"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"保留字"):
                ps.parse(_write_outline(Path(td), dd_yaml=dd))

    def test_ehg3_2_unknown_key_in_taxonomy_entry(self):
        dd = "panel_taxonomy:\n  hero: {workflow: x, bogus: 1}\n"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"EH-G3-2"):
                ps.parse(_write_outline(Path(td), dd_yaml=dd))

    def test_bcg3_3_item_panel_type_regex(self):
        dd = (
            "panel_taxonomy:\n  hero: {workflow: x}\n"
            "per_item_beats:\n  ch1_01_hero:\n    panel_type: 'BAD CAPS'\n"
        )
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"a-z"):
                ps.parse(_write_outline(Path(td), dd_yaml=dd))


# ============================================================
# BC-G3-4 / DR-4: _resolve_per_item_config 3-layer dispatch
# ============================================================


class TestDispatchHelper(unittest.TestCase):

    def test_workflow_layer1_item_wins(self):
        plan = _plan(
            workflow="plan_wf",
            panel_taxonomy={"hero": ps.PanelTypeConfig(workflow="pt_wf")},
        )
        item = _item(panel_type="hero", workflow_override="item_wf")
        val, src = ps._resolve_per_item_config(plan, item, "workflow")
        self.assertEqual((val, src), ("item_wf", "item"))

    def test_workflow_layer2_panel_type(self):
        plan = _plan(
            workflow="plan_wf",
            panel_taxonomy={"hero": ps.PanelTypeConfig(workflow="pt_wf")},
        )
        item = _item(panel_type="hero")
        val, src = ps._resolve_per_item_config(plan, item, "workflow")
        self.assertEqual((val, src), ("pt_wf", "panel_type"))

    def test_workflow_layer3_plan_level(self):
        plan = _plan(workflow="plan_wf")
        item = _item()
        val, src = ps._resolve_per_item_config(plan, item, "workflow")
        self.assertEqual((val, src), ("plan_wf", "plan_level"))

    def test_pulid_enabled_from_consistency(self):
        plan = _plan(character_consistency="both")
        val, src = ps._resolve_per_item_config(plan, _item(), "pulid.enabled")
        self.assertEqual((val, src), (True, "plan_level"))
        plan2 = _plan(character_consistency="prompt_only")
        val2, _ = ps._resolve_per_item_config(plan2, _item(), "pulid.enabled")
        self.assertFalse(val2)

    def test_pulid_strength_default(self):
        plan = _plan()  # no pulid_weight
        val, src = ps._resolve_per_item_config(plan, _item(), "pulid.strength")
        self.assertEqual((val, src), (1.0, "default"))

    def test_pulid_partial_override_per_key_fallback(self):
        """BC-G2-1: partial dict → missing key falls through, not short-circuit."""
        plan = _plan(
            pulid_weight=0.8, face_ref="hero.png",
            character_consistency="both",
        )
        item = _item(pulid_override={"strength": 1.5})
        s, _ = ps._resolve_per_item_config(plan, item, "pulid.strength")
        f, _ = ps._resolve_per_item_config(plan, item, "pulid.face_ref")
        self.assertEqual(s, 1.5)             # from item
        self.assertEqual(f, "hero.png")      # fell through to plan_level

    def test_double_written_detection(self):
        """BC-G5-4 C2 helper: both item + panel_type supply workflow."""
        plan = _plan(panel_taxonomy={"hero": ps.PanelTypeConfig(workflow="pt_wf")})
        item = _item(panel_type="hero", workflow_override="item_wf")
        self.assertTrue(ps._dispatch_double_written(plan, item, "workflow"))
        item2 = _item(panel_type="hero")
        self.assertFalse(ps._dispatch_double_written(plan, item2, "workflow"))


# ============================================================
# BC-G2: pulid override validation
# ============================================================


class TestBCG2PulidOverride(unittest.TestCase):

    def test_unknown_pulid_key_rejected(self):
        dd = "per_item_beats:\n  ch1_01_hero:\n    pulid: {bogus: 1}\n"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"unknown key"):
                ps.parse(_write_outline(Path(td), dd_yaml=dd))

    def test_strength_out_of_range_rejected(self):
        dd = "per_item_beats:\n  ch1_01_hero:\n    pulid: {strength: 9.0}\n"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"out of range"):
                ps.parse(_write_outline(Path(td), dd_yaml=dd))


# ============================================================
# BC-G5 / EH-G5: event validation
# ============================================================


class TestBCG5Events(unittest.TestCase):

    def test_ehg5_1_bad_event_type(self):
        dd = (
            "per_item_beats:\n  ch1_01_hero:\n"
            "    event_type: explosion\n    event_description: big boom happens\n"
        )
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"EH-G5-1"):
                ps.parse(_write_outline(Path(td), dd_yaml=dd))

    def test_ehg5_2_asymmetric_event(self):
        dd = "per_item_beats:\n  ch1_01_hero:\n    event_type: action\n"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"EH-G5-2"):
                ps.parse(_write_outline(Path(td), dd_yaml=dd))

    def test_ehg5_3_short_description(self):
        dd = (
            "per_item_beats:\n  ch1_01_hero:\n"
            "    event_type: action\n    event_description: short\n"
        )
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"EH-G5-3"):
                ps.parse(_write_outline(Path(td), dd_yaml=dd))

    def test_ehg5_4_density_out_of_range(self):
        fm = "plan_quality:\n  event_density_warning: 1.5\n"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"EH-G5-4"):
                ps.parse(_write_outline(Path(td), frontmatter_extra=fm))

    def test_plan_quality_defaults_filled(self):
        fm = "plan_quality:\n  event_density_warning: 0.5\n"
        with tempfile.TemporaryDirectory() as td:
            p = ps.parse(_write_outline(Path(td), frontmatter_extra=fm))
        self.assertEqual(p.plan_quality["event_density_warning"], 0.5)
        self.assertTrue(p.plan_quality["cast_in_panel_warning"])


# ============================================================
# BC-G4 / EH-G4: cast schema + budget
# ============================================================


class TestBCG4Cast(unittest.TestCase):

    def test_parse_cast(self):
        dd = (
            "cast:\n"
            "  protagonist:\n    name: Aria\n    type: human\n"
            "    visual: {hair: brown, outfit: blue cape}\n"
            "  dragon:\n    name: Scarwing\n    type: creature\n"
            "    visual: {color: red scales}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            p = ps.parse(_write_outline(Path(td), dd_yaml=dd))
        self.assertEqual(p.cast["protagonist"].name, "Aria")
        self.assertEqual(p.cast["dragon"].type, "creature")
        self.assertEqual(p.cast["protagonist"].visual["hair"], "brown")

    def test_ehg4_1_unknown_cast_ref(self):
        dd = (
            "cast:\n  protagonist:\n    name: Aria\n    visual: {hair: brown}\n"
            "per_item_beats:\n  ch1_01_hero:\n    cast_in_panel: [ghost]\n"
        )
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"EH-G4-1"):
                ps.parse(_write_outline(Path(td), dd_yaml=dd))

    def test_bcg4_6_single_value_too_long(self):
        long_val = "x" * 600
        dd = (
            f"cast:\n  p:\n    name: P\n    visual: {{hair: '{long_val}'}}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"visual.*過長"):
                ps.parse(_write_outline(Path(td), dd_yaml=dd))

    def test_bcg4_6_unescaped_pipe_in_visual(self):
        dd = "cast:\n  p:\n    name: P\n    visual: {hair: 'a | b'}\n"
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"未跳脫"):
                ps.parse(_write_outline(Path(td), dd_yaml=dd))

    def test_ehg4_4_per_entry_budget(self):
        v1 = "a" * 400
        v2 = "b" * 450
        dd = (
            f"cast:\n  p:\n    name: P\n    visual: {{hair: '{v1}', outfit: '{v2}'}}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, r"EH-G4-4"):
                ps.parse(_write_outline(Path(td), dd_yaml=dd))


# ============================================================
# round-trip for a full v1.3 outline
# ============================================================


class TestV13RoundTrip(unittest.TestCase):

    def test_v13_outline_roundtrip(self):
        dd = (
            "panel_taxonomy:\n"
            "  hero_closeup: {workflow: flux_pulid, beat_prefix: 'close-up'}\n"
            "cast:\n"
            "  protagonist:\n    name: Aria\n    visual: {hair: brown}\n"
            "per_item_beats:\n"
            "  ch1_01_hero:\n"
            "    panel_type: hero_closeup\n"
            "    cast_in_panel: [protagonist]\n"
            "    event_type: action\n    event_description: hero draws sword\n"
            "    use_template: false\n"
        )
        with tempfile.TemporaryDirectory() as td:
            path = _write_outline(Path(td), dd_yaml=dd)
            p1 = ps.parse(path)
            ser = ps.serialize(p1)
            p2 = Path(td) / "rt.md"
            p2.write_text(ser, encoding="utf-8")
            self.assertEqual(ps.serialize(ps.parse(p2)), ser)
        # spot-check fields survived
        it = p1.items[0]
        self.assertEqual(it.panel_type, "hero_closeup")
        self.assertEqual(it.cast_in_panel, ["protagonist"])
        self.assertEqual(it.event_type, "action")
        self.assertFalse(it.use_template)


# ============================================================
# Gap 4 + Gap 6 derive (cast prepend / beat templates / overrides)
# ============================================================


def _layer_a_hair_locked() -> ps.LayerA:
    dims = {n: ps.Dimension(None, "unspecified") for n in ps._LAYER_A_DIMENSION_NAMES}
    dims["hair"] = ps.Dimension("blonde curls", "locked")
    dims["outfit"] = ps.Dimension("red armor", "locked")
    return ps.LayerA(**dims)


class TestDeriveCastAndBeat(unittest.TestCase):

    def test_bcg4_3_cast_prepend_order_storyboard(self):
        plan = _plan(
            mode="storyboard", layer_a=_layer_a_hair_locked(),
            cast={"mage": ps.CastEntry(name="M", visual={"hair": "indigo hair"})},
        )
        item = _item(beat_description="casts a spell", cast_in_panel=["mage"])
        out = pd.derive_prompt(plan, item)
        # cast fragment precedes locked dims, which precede beat
        self.assertLess(out.index("indigo hair"), out.index("blonde curls"))
        self.assertLess(out.index("blonde curls"), out.index("casts a spell"))

    def test_bcg4_4_protagonist_overrides_visual_lock(self):
        plan = _plan(
            mode="storyboard", layer_a=_layer_a_hair_locked(),
            cast={"protagonist": ps.CastEntry(name="Hero", visual={"hair": "silver mane"})},
        )
        item = _item(beat_description="leads the charge", cast_in_panel=["protagonist"])
        out = pd.derive_prompt(plan, item)
        self.assertIn("silver mane", out)
        self.assertNotIn("blonde curls", out)  # protagonist hair wins
        self.assertIn("red armor", out)         # non-overridden locked dim stays

    def test_bcg6_2_beat_prefix_suffix_position(self):
        plan = _plan(
            mode="storyboard", layer_a=_layer_a_hair_locked(),
            panel_taxonomy={
                "hero": ps.PanelTypeConfig(beat_prefix="PFX", beat_suffix="SFX")
            },
        )
        item = _item(panel_type="hero", beat_description="the beat")
        out = pd.derive_prompt(plan, item)
        self.assertLess(out.index("blonde curls"), out.index("PFX"))
        self.assertLess(out.index("PFX"), out.index("the beat"))
        self.assertLess(out.index("the beat"), out.index("SFX"))

    def test_bcg6_3_use_template_false_skips(self):
        plan = _plan(
            mode="storyboard", layer_a=_layer_a_hair_locked(),
            panel_taxonomy={
                "hero": ps.PanelTypeConfig(beat_prefix="PFX", beat_suffix="SFX")
            },
        )
        item = _item(panel_type="hero", beat_description="the beat", use_template=False)
        out = pd.derive_prompt(plan, item)
        self.assertNotIn("PFX", out)
        self.assertNotIn("SFX", out)

    def test_bcg6_4_album_no_beat_templates(self):
        """Album mode applies cast prepend but NOT beat_prefix/suffix."""
        plan = _plan(
            mode="album", layer_a=_layer_a_hair_locked(),
            panel_taxonomy={
                "hero": ps.PanelTypeConfig(beat_prefix="PFX", beat_suffix="SFX")
            },
            cast={"mage": ps.CastEntry(name="M", visual={"hair": "indigo hair"})},
        )
        item = _item(slug="ch1_01_x", panel_type="hero", cast_in_panel=["mage"])
        out = pd.derive_prompt(plan, item)
        self.assertIn("indigo hair", out)  # cast dispatch works in album
        self.assertNotIn("PFX", out)        # beat templates do not
        self.assertNotIn("SFX", out)

    def test_ehg4_4_derive_per_plan_budget(self):
        big = "x" * 400  # 4 keys * 400 = 1600 > 1500 per-plan (each ≤500 ok input-side)
        plan = _plan(
            mode="storyboard", layer_a=_layer_a_hair_locked(),
            cast={"a": ps.CastEntry(name="A", visual={
                "k1": big, "k2": big, "k3": big, "k4": big})},
        )
        item = _item(beat_description="does a thing", cast_in_panel=["a"])
        with self.assertRaisesRegex(ValueError, r"EH-G4-4"):
            pd.derive_prompt(plan, item)


if __name__ == "__main__":
    unittest.main()
