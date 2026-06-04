"""Plan Y v1.3 gen-side dispatch tests (Gap 1 + Gap 2).

Covers _expand_items per-item dispatch resolution (BC-G1-2 / BC-G2-2/3/7),
the BC-G0 legacy passthrough reconciliation, and _submit_all caller mapping +
EH-G1-1 / EH-G1-2 gates.

Run: `python3 -m pytest tests/test_plan_y_v13_gen.py` from skill root.

#009 / BC-G9-4: schema.Plan / schema.Item built once as a base, varied via
dataclasses.replace so future fields auto-propagate.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import plan_loader  # noqa: E402
import plan_runner  # noqa: E402

schema = plan_loader._import_plan_schema()
RI = plan_loader.ResolvedItem
LP = plan_loader.LoadedPlan

_BASE_PLAN = schema.Plan(
    id="t", title="t", version=1,
    created="2026-01-01T00:00:00+08:00", updated="2026-01-01T00:00:00+08:00",
    status="ready", workflow="flux_basic",
    size=[512, 512], steps=20, batch_per_item=1,
    seed_strategy={"type": "fixed", "base": 0, "step": 0},
    items=[],
)
_BASE_ITEM = schema.Item(slug="ch1_01_x", prompt="a literal prompt")


def _plan(**ov):
    return replace(_BASE_PLAN, **ov)


def _item(**ov):
    return replace(_BASE_ITEM, **ov)


def _expand_one(plan, item):
    p = replace(plan, items=[item])
    return plan_loader._expand_items(p)[0]


# ---------- BC-G0 legacy passthrough reconciliation ----------


def test_legacy_flux_pulid_passthrough():
    """cards_a11c-like: flux_pulid + face_ref, character_consistency default
    prompt_only, NO v1.3 fields → legacy passthrough (pulid_strength =
    plan.pulid_weight, face_ref = plan.face_ref), NOT force-disabled."""
    plan = _plan(workflow="flux_pulid", pulid_weight=0.9, face_ref="hero.png")
    ri = _expand_one(plan, _item())
    assert ri.pulid_dispatch == "legacy"
    assert ri.pulid_strength == 0.9
    assert ri.pulid_face_ref == "hero.png"
    assert ri.workflow_override is None


def test_legacy_no_pulid_dragon_hunt_like():
    """flux_basic + no face_ref/pulid_weight → legacy, all None (v1.2 behavior)."""
    plan = _plan(workflow="flux_basic")
    ri = _expand_one(plan, _item())
    assert ri.pulid_dispatch == "legacy"
    assert ri.pulid_strength is None
    assert ri.pulid_face_ref is None


# ---------- v13 dispatch resolution ----------


def test_v13_item_pulid_disabled_forces_none():
    """BC-G2-7: item declares pulid.enabled=false + workflow_override=flux_basic
    → strength/face_ref forced None despite plan-level values."""
    plan = _plan(workflow="flux_pulid", pulid_weight=0.8, face_ref="hero.png")
    item = _item(pulid_override={"enabled": False}, workflow_override="flux_basic")
    ri = _expand_one(plan, item)
    assert ri.pulid_dispatch == "v13"
    assert ri.pulid_enabled is False
    assert ri.pulid_strength is None
    assert ri.pulid_face_ref is None
    assert ri.workflow_override == "flux_basic"


def test_v13_panel_taxonomy_enables_pulid():
    """BC-G1-4 / BC-G2-3: panel_type → panel_taxonomy supplies workflow + pulid."""
    plan = _plan(
        panel_taxonomy={
            "hero": schema.PanelTypeConfig(
                workflow="flux_pulid", pulid={"enabled": True, "strength": 1.2}
            )
        },
    )
    ri = _expand_one(plan, _item(panel_type="hero"))
    assert ri.pulid_dispatch == "v13"
    assert ri.workflow_override == "flux_pulid"
    assert ri.pulid_enabled is True
    assert ri.pulid_strength == 1.2


def test_v13_strength_default_end_to_end(monkeypatch):
    """dev-review L10: v13 enabled=true with NO strength anywhere → effective
    strength = default 1.0, and that 1.0 reaches inject's pulid_weight."""
    plan = _plan(
        panel_taxonomy={"hero": schema.PanelTypeConfig(pulid={"enabled": True})},
    )
    ri = _expand_one(plan, _item(panel_type="hero"))
    assert ri.pulid_dispatch == "v13"
    assert ri.pulid_enabled is True
    assert ri.pulid_strength == 1.0  # _DISPATCH_DEFAULTS default
    # end-to-end: 1.0 reaches inject (template has ApplyPulidFlux → alignment ok)
    captured = _capture_inject(monkeypatch)
    plan_runner._submit_all({"none": _pulid_template()}, _loaded([ri]), "run_x",
                            plan_face_ref=None)
    assert captured[0]["pulid_weight"] == 1.0


# ---------- _submit_all caller mapping + gates ----------


def _loaded(items, **kw):
    base = dict(raw=None, items=items, workflow="flux_basic", size=[512, 512],
                steps=20, lora=[], face_ref=None, pulid_weight=None,
                negative="", output_dir="", mode="plan")
    base.update(kw)
    return LP(**base)


def _capture_inject(monkeypatch):
    captured = []
    monkeypatch.setattr(plan_runner, "inject", lambda wf, **kw: captured.append(kw) or wf)
    monkeypatch.setattr(plan_runner.api, "submit_prompt", lambda w, c: ("pid", 0, {}))
    return captured


def test_bcg2_7_caller_mapping_double_none(monkeypatch):
    """Phase 4 fixture (BC-G2-7): item pulid.enabled=false + workflow_override=
    flux_basic + plan.pulid_weight=0.8 + plan.face_ref=hero.png → inject called
    with pulid_weight=None ∧ face_ref_filename=None."""
    captured = _capture_inject(monkeypatch)
    item = RI(index=1, slug="x", final_prompt="p", seed=1, filename_prefix="01_x",
              workflow_override="flux_basic", pulid_enabled=False,
              pulid_strength=None, pulid_face_ref=None, pulid_dispatch="v13")
    plan_runner._submit_all({"none": {}}, _loaded([item]), "run_x",
                            plan_face_ref="hero.png")
    kw = captured[0]
    assert kw["pulid_weight"] is None
    assert kw["face_ref_filename"] is None


def _pulid_template():
    return {"9": {"class_type": "ApplyPulidFlux", "inputs": {"weight": 0.9}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}}}


def test_ehg1_2_enabled_false_but_workflow_has_pulid(monkeypatch):
    """EH-G1-2: v13 item pulid_enabled=false but effective workflow contains
    ApplyPulidFlux → WorkflowParamError → item fails (not the batch)."""
    _capture_inject(monkeypatch)
    item = RI(index=1, slug="x", final_prompt="p", seed=1, filename_prefix="01_x",
              pulid_enabled=False, pulid_dispatch="v13")
    subs = plan_runner._submit_all({"none": _pulid_template()}, _loaded([item]),
                                   "run_x", plan_face_ref=None)
    assert subs[0]["prompt_id"] is None
    assert "ApplyPulidFlux" in subs[0]["error"]


def test_ehg1_2_enabled_true_but_no_pulid_node(monkeypatch):
    """EH-G1-2 reverse: pulid_enabled=true but workflow has no ApplyPulidFlux."""
    _capture_inject(monkeypatch)
    item = RI(index=1, slug="x", final_prompt="p", seed=1, filename_prefix="01_x",
              pulid_enabled=True, pulid_dispatch="v13")
    subs = plan_runner._submit_all({"none": {"3": {"class_type": "CLIPTextEncode",
                                                   "inputs": {"text": ""}}}},
                                   _loaded([item]), "run_x", plan_face_ref=None)
    assert subs[0]["prompt_id"] is None
    assert "no ApplyPulidFlux" in subs[0]["error"]


def test_legacy_pulid_node_workflow_no_gate(monkeypatch):
    """BC-G0: legacy item + workflow with ApplyPulidFlux → NO EH-G1-2 gate;
    inject called normally (cards_a11c flux_pulid keeps working)."""
    captured = _capture_inject(monkeypatch)
    item = RI(index=1, slug="x", final_prompt="p", seed=1, filename_prefix="01_x",
              pulid_strength=0.9, pulid_dispatch="legacy")
    subs = plan_runner._submit_all({"none": _pulid_template()}, _loaded([item]),
                                   "run_x", plan_face_ref="hero.png")
    assert subs[0]["prompt_id"] == "pid"
    assert captured[0]["pulid_weight"] == 0.9


def test_ehg1_1_workflow_override_not_found(monkeypatch):
    """EH-G1-1: workflow_override file missing → item fails, batch continues."""
    _capture_inject(monkeypatch)
    item = RI(index=1, slug="x", final_prompt="p", seed=1, filename_prefix="01_x",
              workflow_override="no_such_workflow_xyz", pulid_dispatch="v13")
    subs = plan_runner._submit_all({"none": {}}, _loaded([item]), "run_x",
                                   plan_face_ref=None)
    assert subs[0]["prompt_id"] is None
    assert "no_such_workflow_xyz" in subs[0]["error"]


def test_bcg1_3_workflow_override_template_cached(monkeypatch):
    """BC-G1-3: consecutive items with same workflow_override → workflow file
    resolved/read once (template cache)."""
    _capture_inject(monkeypatch)
    calls = []
    real_resolve = plan_runner._resolve_workflow

    def counting_resolve(name):
        calls.append(name)
        return real_resolve(name)

    monkeypatch.setattr(plan_runner, "_resolve_workflow", counting_resolve)
    items = [
        RI(index=1, slug="a", final_prompt="p", seed=1, filename_prefix="01_a",
           workflow_override="flux_basic", pulid_enabled=False, pulid_dispatch="v13"),
        RI(index=2, slug="b", final_prompt="p", seed=2, filename_prefix="02_b",
           workflow_override="flux_basic", pulid_enabled=False, pulid_dispatch="v13"),
    ]
    plan_runner._submit_all({"none": {}}, _loaded(items), "run_x", plan_face_ref=None)
    assert calls.count("flux_basic") == 1  # loaded once, cached for item 2
