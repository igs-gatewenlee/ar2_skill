"""Tests for pulid_weight propagation (issue #4).

Covers BC-4..9, EH-4 from P1-design-spec.md.
- BC-4 LoadedPlan mirrors plan_schema.Plan.pulid_weight (covered by
  plan-skill schema tests + the propagation here)
- BC-5 inject(None) leaves ApplyPulidFlux.weight untouched (default 0.9)
- BC-6 inject(1.2) writes node.inputs.weight = 1.2
- BC-7 inject(0.0) writes 0.0 (value-write assertion only, no upstream claim)
- BC-8 _submit_all forwards loaded.pulid_weight to inject
- BC-9 inject(None) on a workflow without ApplyPulidFlux is a no-op (flux_basic)
- EH-4 inject(1.2) on a workflow without ApplyPulidFlux raises WorkflowParamError
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
WORKFLOWS_DIR = Path(__file__).resolve().parent.parent / "workflows"
sys.path.insert(0, str(SCRIPTS_DIR))

import workflow_params  # noqa: E402
import plan_runner  # noqa: E402


@pytest.fixture
def flux_pulid_workflow() -> dict:
    return json.loads((WORKFLOWS_DIR / "flux_pulid.json").read_text())


@pytest.fixture
def flux_basic_workflow() -> dict:
    return json.loads((WORKFLOWS_DIR / "flux_basic.json").read_text())


def _apply_pulid_node(wf: dict) -> dict | None:
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") == "ApplyPulidFlux":
            return node
    return None


# ---------- BC-5: None leaves ApplyPulidFlux untouched ----------

def test_inject_none_leaves_apply_pulid_weight_at_default(flux_pulid_workflow):
    """BC-5: pulid_weight=None → ApplyPulidFlux.weight unchanged (default 0.9)."""
    original = _apply_pulid_node(flux_pulid_workflow)["inputs"]["weight"]
    patched = workflow_params.inject(flux_pulid_workflow, pulid_weight=None)
    node = _apply_pulid_node(patched)
    assert node["inputs"]["weight"] == original
    assert node["inputs"]["weight"] == 0.9  # ground truth confirms default


# ---------- BC-6: in-range float written ----------

def test_inject_writes_weight_value(flux_pulid_workflow):
    """BC-6: pulid_weight=1.2 → node.inputs.weight=1.2."""
    patched = workflow_params.inject(flux_pulid_workflow, pulid_weight=1.2)
    node = _apply_pulid_node(patched)
    assert node["inputs"]["weight"] == 1.2


# ---------- BC-7: 0.0 also writes (no upstream claim) ----------

def test_inject_writes_zero_as_value(flux_pulid_workflow):
    """BC-7 (DR-4): pulid_weight=0.0 → 0.0 is written; we don't claim PuLID
    is "off", only that the value reached the node input."""
    patched = workflow_params.inject(flux_pulid_workflow, pulid_weight=0.0)
    node = _apply_pulid_node(patched)
    assert node["inputs"]["weight"] == 0.0


# ---------- BC-9 (DR-5): None on basic workflow is a no-op ----------

def test_inject_none_on_basic_workflow_is_noop(flux_basic_workflow):
    """BC-9: workflow without ApplyPulidFlux + pulid_weight=None → no error,
    workflow unchanged. Backward-compat for flux_basic (which has no PuLID)."""
    snapshot = copy.deepcopy(flux_basic_workflow)
    patched = workflow_params.inject(flux_basic_workflow, pulid_weight=None)
    assert patched == snapshot  # unchanged


# ---------- EH-4: explicit weight + no node raises ----------

def test_inject_weight_on_basic_workflow_raises(flux_basic_workflow):
    """EH-4: pulid_weight=1.2 on workflow without ApplyPulidFlux →
    WorkflowParamError, same pattern as face_ref/LoadImage."""
    with pytest.raises(workflow_params.WorkflowParamError) as exc_info:
        workflow_params.inject(flux_basic_workflow, pulid_weight=1.2)
    assert "ApplyPulidFlux" in str(exc_info.value)


# ---------- Type coercion: float() applied internally ----------

def test_inject_int_weight_coerced_to_float(flux_pulid_workflow):
    """Defensive: int 1 should still write 1.0 (float coercion inside inject)."""
    patched = workflow_params.inject(flux_pulid_workflow, pulid_weight=1)
    node = _apply_pulid_node(patched)
    assert node["inputs"]["weight"] == 1.0
    assert isinstance(node["inputs"]["weight"], float)


# ---------- BC-8: _submit_all forwards loaded.pulid_weight to inject ----------

def test_submit_all_forwards_pulid_weight_to_inject(monkeypatch):
    """BC-G2-7 (Plan Y v1.3): _submit_all forwards ResolvedItem.pulid_strength
    as inject's pulid_weight (dispatch strength → runtime weight), NOT
    loaded.pulid_weight. For a legacy item, _expand_items sets pulid_strength =
    plan.pulid_weight, so the effective value stays byte-equivalent to v1.2."""
    captured: dict = {}

    def fake_inject(workflow_template, **kwargs):
        captured.update(kwargs)
        return workflow_template

    def fake_submit_prompt(_workflow, _client_id):
        return "fake-prompt-id", 0, {}

    monkeypatch.setattr(plan_runner, "inject", fake_inject)
    monkeypatch.setattr(plan_runner.api, "submit_prompt", fake_submit_prompt)

    # Minimal LoadedPlan + one ResolvedItem (legacy: pulid_strength carries the
    # plan-level pulid_weight as _expand_items would have set it).
    item = plan_runner.plan_loader.ResolvedItem(
        index=1,
        slug="x",
        final_prompt="p",
        seed=42,
        filename_prefix="01_x",
        pulid_strength=1.5,
    )
    loaded = plan_runner.plan_loader.LoadedPlan(
        raw=None,
        items=[item],
        workflow="flux_pulid",
        size=[1024, 1024],
        steps=20,
        lora=[],
        face_ref=None,
        pulid_weight=1.5,
        negative="",
        output_dir="",
        mode="plan",
    )

    # T3：_submit_all 改收 per-route templates dict（route=none item → templates["none"]）
    plan_runner._submit_all({"none": {}}, loaded, "run_x", plan_face_ref=None)

    assert captured.get("pulid_weight") == 1.5
