"""Tests for renderer._topo_levels (DAG layering for pipeline diagram).

Covers BC-1..7 + EH-1..2 from P1-design-spec.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from parser import OverviewData  # noqa: E402
from renderer import _topo_levels  # noqa: E402
from scanner import SkillInfo  # noqa: E402


def _make(name: str, *, order: int, upstream=None, downstream=None) -> OverviewData:
    """Build a minimal OverviewData with the metadata fields _topo_levels reads."""
    skill = SkillInfo(name=name, workspace_path=Path("/tmp"), install_path=None,
                     status="workspace_only")
    return OverviewData(
        skill=skill,
        meta={
            "order": order,
            "upstream": upstream or [],
            "downstream": downstream or [],
        },
        sections={},
        parse_state="ok",
    )


# ---------- BC-1: empty input ----------

def test_empty_input_returns_empty_list():
    assert _topo_levels([]) == []


# ---------- BC-2: single isolated skill ----------

def test_single_skill_single_level():
    a = _make("a", order=1)
    assert _topo_levels([a]) == [[a]]


# ---------- BC-3: realistic 4-node ar2:* graph ----------

def test_ar2_family_three_levels():
    check = _make("ar2:dgx-comfyui-check", order=1,
                  downstream=["ar2:dgx-comfyui-gen", "ar2:dgx-comfyui-train"])
    plan = _make("ar2:dgx-comfyui-plan", order=2,
                 downstream=["ar2:dgx-comfyui-gen"])
    train = _make("ar2:dgx-comfyui-train", order=3,
                  upstream=["ar2:dgx-comfyui-check"],
                  downstream=["ar2:dgx-comfyui-gen"])
    gen = _make("ar2:dgx-comfyui-gen", order=4,
                upstream=["ar2:dgx-comfyui-check", "ar2:dgx-comfyui-plan",
                          "ar2:dgx-comfyui-train"])

    levels = _topo_levels([check, plan, train, gen])
    names = [[d.skill.name for d in lvl] for lvl in levels]
    assert names == [
        ["ar2:dgx-comfyui-check", "ar2:dgx-comfyui-plan"],  # level 0 (N roots)
        ["ar2:dgx-comfyui-train"],                            # level 1
        ["ar2:dgx-comfyui-gen"],                              # level 2
    ]


# ---------- BC-4: within-level order respects (order, name) ----------

def test_level_sorted_by_order_within_level():
    """Two roots at level 0: lower order comes first."""
    b = _make("b", order=5)
    a = _make("a", order=2)
    levels = _topo_levels([b, a])
    assert [d.skill.name for d in levels[0]] == ["a", "b"]


# ---------- BC-5: union of upstream + downstream ----------

def test_edge_declared_only_on_downstream_side():
    """If A says downstream=[B] but B doesn't say upstream=[A], the edge still counts."""
    a = _make("a", order=1, downstream=["b"])
    b = _make("b", order=2)  # missing upstream declaration
    levels = _topo_levels([a, b])
    assert [[d.skill.name for d in lvl] for lvl in levels] == [["a"], ["b"]]


def test_edge_declared_only_on_upstream_side():
    """If B says upstream=[A] but A doesn't say downstream=[B], the edge still counts."""
    a = _make("a", order=1)  # missing downstream declaration
    b = _make("b", order=2, upstream=["a"])
    levels = _topo_levels([a, b])
    assert [[d.skill.name for d in lvl] for lvl in levels] == [["a"], ["b"]]


# ---------- BC-6: unknown skill name in metadata ignored ----------

def test_unknown_upstream_reference_ignored():
    """Typo / cross-batch reference should not crash, just be skipped."""
    a = _make("a", order=1, upstream=["nonexistent_skill"])
    levels = _topo_levels([a])
    assert levels == [[a]]


def test_unknown_downstream_reference_ignored():
    a = _make("a", order=1, downstream=["ghost"])
    levels = _topo_levels([a])
    assert levels == [[a]]


# ---------- EH-1: cycle detection ----------

def test_cycle_raises():
    a = _make("a", order=1, upstream=["b"])
    b = _make("b", order=2, upstream=["a"])
    with pytest.raises(ValueError, match="cycle"):
        _topo_levels([a, b])


def test_self_edge_raises():
    """Self-loop (skill upstream itself) is a special-case cycle, raises clearly."""
    a = _make("a", order=1, upstream=["a"])
    with pytest.raises(ValueError, match="self-edge"):
        _topo_levels([a])
