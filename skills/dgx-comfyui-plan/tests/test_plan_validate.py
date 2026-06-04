"""Plan Y v1.3 — plan_main --validate warnings (BC-G5-4 A/B/C groups)."""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import plan_schema as ps  # noqa: E402
import plan_validate as pv  # noqa: E402

_BASE_PLAN = ps.Plan(
    id="t", title="t", version=1,
    created="2026-01-01T00:00:00+08:00", updated="2026-01-01T00:00:00+08:00",
    status="ready", workflow="flux_basic",
    size=[512, 512], steps=20, batch_per_item=1,
    seed_strategy={"type": "fixed", "base": 0, "step": 0},
    items=[],
)


def _plan(**ov):
    return replace(_BASE_PLAN, **ov)


def _item(slug, **ov):
    return replace(ps.Item(slug=slug, prompt="p"), **ov)


def _layer_a_hair_locked():
    dims = {n: ps.Dimension(None, "unspecified") for n in ps._LAYER_A_DIMENSION_NAMES}
    dims["hair"] = ps.Dimension("blonde", "locked")
    return ps.LayerA(**dims)


class TestEventWarnings(unittest.TestCase):

    def test_a1_low_event_density(self):
        items = [
            _item("ch1_01_a", event_type="mood", event_description="quiet morning"),
            _item("ch1_02_b", event_type="transition", event_description="walking on"),
            _item("ch1_03_c", event_type="action", event_description="draws the sword"),
        ]
        ws = pv.collect_warnings(_plan(items=items))
        self.assertTrue(any(w.startswith("[A1]") for w in ws))

    def test_a2_consecutive_same_type(self):
        items = [
            _item("ch1_01_a", event_type="action", event_description="charges ahead"),
            _item("ch1_02_b", event_type="action", event_description="strikes hard"),
        ]
        ws = pv.collect_warnings(_plan(items=items))
        self.assertTrue(any(w.startswith("[A2]") for w in ws))

    def test_density_threshold_respects_plan_quality(self):
        # event_density_warning=0.9 → threshold 0.1; 1/3 weak → 33% > 10% → A1
        items = [
            _item("ch1_01_a", event_type="mood", event_description="quiet morning"),
            _item("ch1_02_b", event_type="action", event_description="draws the sword"),
            _item("ch1_03_c", event_type="discovery", event_description="finds the map"),
        ]
        plan = _plan(items=items,
                     plan_quality={"event_density_warning": 0.9,
                                   "cast_in_panel_warning": True})
        ws = pv.collect_warnings(plan)
        self.assertTrue(any(w.startswith("[A1]") for w in ws))


class TestCastWarnings(unittest.TestCase):

    def test_b1_cast_pulid_conflict(self):
        plan = _plan(
            character_consistency="both",  # → effective pulid_enabled=true
            cast={
                "hero": ps.CastEntry(name="H", type="human"),
                "mage": ps.CastEntry(name="M", type="human"),
            },
            items=[_item("ch1_01_a", cast_in_panel=["hero", "mage"])],
        )
        ws = pv.collect_warnings(plan)
        self.assertTrue(any(w.startswith("[B1]") for w in ws))

    def test_b1_no_conflict_when_pulid_off(self):
        plan = _plan(
            character_consistency="prompt_only",  # enabled=false
            cast={
                "hero": ps.CastEntry(name="H", type="human"),
                "mage": ps.CastEntry(name="M", type="human"),
            },
            items=[_item("ch1_01_a", cast_in_panel=["hero", "mage"])],
        )
        ws = pv.collect_warnings(plan)
        self.assertFalse(any(w.startswith("[B1]") for w in ws))

    def test_b2_visual_lock_protagonist_overlap(self):
        plan = _plan(
            layer_a=_layer_a_hair_locked(),
            cast={"protagonist": ps.CastEntry(name="P", visual={"hair": "silver"})},
            items=[_item("ch1_01_a")],
        )
        ws = pv.collect_warnings(plan)
        self.assertTrue(any(w.startswith("[B2]") for w in ws))


class TestDispatchWarnings(unittest.TestCase):

    def test_c1_panel_type_not_in_taxonomy(self):
        plan = _plan(
            panel_taxonomy={"hero": ps.PanelTypeConfig(workflow="x")},
            items=[_item("ch1_01_a", panel_type="ghost")],
        )
        ws = pv.collect_warnings(plan)
        self.assertTrue(any(w.startswith("[C1]") for w in ws))

    def test_c2_double_write(self):
        plan = _plan(
            panel_taxonomy={"hero": ps.PanelTypeConfig(workflow="pt_wf")},
            items=[_item("ch1_01_a", panel_type="hero", workflow_override="item_wf")],
        )
        ws = pv.collect_warnings(plan)
        self.assertTrue(any(w.startswith("[C2]") for w in ws))

    def test_no_warnings_clean_plan(self):
        plan = _plan(items=[_item("ch1_01_a")])
        self.assertEqual(pv.collect_warnings(plan), [])


class TestValidateCLI(unittest.TestCase):

    def test_validate_missing_plan_exit_1(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(pv.validate(Path(td), "nope"), 1)


if __name__ == "__main__":
    unittest.main()
