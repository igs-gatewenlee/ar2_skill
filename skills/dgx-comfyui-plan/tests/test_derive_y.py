"""M2 P4 tests — Plan Y v1.2 prompt_derive BC-DR + EH-DR coverage.

Tests the 12 BC-DR + 3 EH-DR + 2 IF defined in M2 P1 design spec v1.1:
- BC-DR1: album mode byte-equivalent regression
- BC-DR2/4: storyboard order locked → beat → per_group + beat usage
- BC-DR3: mode default
- BC-DR5: soft fallback + stdout warning (DR-2 採納)
- BC-DR6/EH-DR1: 雙缺 abort
- BC-DR7: 不讀 value_zh (#009 prevention)
- BC-DR8/9/10/EH-DR2: IF-1 後置條件 (single line / ≤2000 / no unescaped |)
- BC-DR11: byte-equivalent baseline (DR-4 採納 物理 baseline)
- BC-DR12: new bilingual_storyboard_mock.md fixture
- EH-DR3: invalid mode
"""

from __future__ import annotations

import contextlib
import io
import sys
from dataclasses import replace
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import plan_schema as ps  # noqa: E402
import prompt_derive as pd  # noqa: E402


# Paths to fixtures
_FIX_DIR = Path(__file__).resolve().parent / "fixtures"
# sibling gen-skill fixtures, relative to this file (plan/tests → skills/).
_GEN_FIX = (
    Path(__file__).resolve().parent.parent.parent
    / "dgx-comfyui-gen" / "tests" / "fixtures"
)
_DERIVED_MOCK = _GEN_FIX / "derived_mock_outline.md"
_BASELINE = _GEN_FIX / "derived_mock_baseline.txt"
_BILINGUAL = _FIX_DIR / "bilingual_storyboard_mock.md"


# ---------- BC-DR1 album mode byte-equivalent regression ----------


def test_bc_dr1_album_byte_equivalent_baseline():
    """BC-DR1: album mode behavior is byte-equivalent to v1.1 baseline.

    BC-DR11: against the physical baseline file (DR-4 採納 物理機制).
    """
    plan = ps.parse(_DERIVED_MOCK)
    assert plan.mode == "album"
    sentinel = [it for it in plan.items if it.prompt == pd.DERIVED_SENTINEL][0]
    result = pd.derive_prompt(plan, sentinel)
    baseline = _BASELINE.read_text(encoding="utf-8").rstrip("\n")
    assert result == baseline, (
        f"BC-DR1/11 byte-equivalent FAIL:\n  got={result!r}\n  exp={baseline!r}"
    )


def test_bc_dr1_album_dispatch_via_dict():
    """BC-DR1 + IF-2: derive_prompt dispatches via _DERIVE_DISPATCH dict."""
    assert "album" in pd._DERIVE_DISPATCH
    assert "storyboard" in pd._DERIVE_DISPATCH
    assert pd._DERIVE_DISPATCH["album"] is pd._derive_album
    assert pd._DERIVE_DISPATCH["storyboard"] is pd._derive_storyboard


# ---------- BC-DR2/4 storyboard order + beat usage ----------


def test_bc_dr2_storyboard_order_locked_beat_per_group():
    """BC-DR2: order is locked → beat → per_group (rationale per spec)."""
    plan = ps.parse(_BILINGUAL)
    items_by_slug = {it.slug: it for it in plan.items}
    result = pd.derive_prompt(plan, items_by_slug["ch1_01_arrival"])

    # Locked dims (visual base anchors) come first
    locked_pos = result.index("medium brown hair")
    # Beat (narrative) comes after locked
    beat_pos = result.index("hero walking into the village")
    # per_group (scene transition) comes after beat
    pg_pos = result.index("ancient village square")
    assert locked_pos < beat_pos < pg_pos, (
        f"BC-DR2 order violated: locked={locked_pos} beat={beat_pos} pg={pg_pos}"
    )


def test_bc_dr4_storyboard_beat_used_verbatim():
    """BC-DR4: item.beat_description (en) emitted verbatim."""
    plan = ps.parse(_BILINGUAL)
    items_by_slug = {it.slug: it for it in plan.items}
    result = pd.derive_prompt(plan, items_by_slug["ch1_02_decision"])
    assert "hero accepting the quest scroll" in result


# ---------- BC-DR3 mode default ----------


def test_bc_dr3_album_dispatch_when_mode_default():
    """BC-DR3: mode default 'album' (from plan_schema Plan dataclass)."""
    plan = ps.parse(_DERIVED_MOCK)  # legacy outline, no `mode:` frontmatter
    assert plan.mode == "album"
    # Should dispatch successfully to _derive_album
    sentinel = [it for it in plan.items if it.prompt == pd.DERIVED_SENTINEL][0]
    pd.derive_prompt(plan, sentinel)  # no exception


# ---------- BC-DR5 軟 fallback + stdout warning (DR-2 採納) ----------


def test_bc_dr5_soft_fallback_emits_stdout_warning(capsys):
    """BC-DR5: beat==None + cgp 非空 → 軟 fallback + stdout warning."""
    plan = ps.parse(_BILINGUAL)
    items_by_slug = {it.slug: it for it in plan.items}
    nobeat = items_by_slug["ch1_03_no_beat"]
    assert nobeat.beat_description is None
    result = pd.derive_prompt(plan, nobeat)
    captured = capsys.readouterr()

    # Warning emitted with required format markers
    assert "falling back" in captured.out
    assert "ch1_03_no_beat" in captured.out
    assert "cross_group_progression" in captured.out

    # Result has locked + per_group, no beat
    assert "medium brown hair" in result
    assert "ancient village square" in result
    assert "hero walking" not in result


# ---------- BC-DR6 / EH-DR1 雙缺 abort ----------


def test_bc_dr6_eh_dr1_double_missing_aborts():
    """BC-DR6: beat==None + cgp == None → EH-DR1 ValueError."""
    plan = ps.parse(_BILINGUAL)
    items_by_slug = {it.slug: it for it in plan.items}
    nobeat = items_by_slug["ch1_03_no_beat"]
    # Remove cgp
    plan.layer_b.cross_group_progression = None
    with pytest.raises(ValueError, match="EH-DR1"):
        pd.derive_prompt(plan, nobeat)


# ---------- BC-DR7 不讀 value_zh (#009 prevention) ----------


def test_bc_dr7_derive_never_emits_value_zh():
    """BC-DR7: derive result must NOT contain any value_zh literal."""
    plan = ps.parse(_BILINGUAL)
    items_by_slug = {it.slug: it for it in plan.items}
    result = pd.derive_prompt(plan, items_by_slug["ch1_01_arrival"])

    # All Chinese value_zh should not appear in derive result
    for zh in [
        "棕色中長髮", "皮製旅行護甲", "堅決決心",
        "動畫插畫風", "視線水平", "金與深藍",
        "主角夕陽下走進村莊", "主角接過任務卷軸",
    ]:
        assert zh not in result, f"BC-DR7 violated: {zh!r} leaked to derive result"


# ---------- BC-DR8/9/10 IF-1 後置條件守住 ----------


def test_bc_dr8_result_under_2000_chars():
    plan = ps.parse(_BILINGUAL)
    items_by_slug = {it.slug: it for it in plan.items}
    result = pd.derive_prompt(plan, items_by_slug["ch1_01_arrival"])
    assert len(result) <= 2000


def test_bc_dr9_result_single_line():
    plan = ps.parse(_BILINGUAL)
    items_by_slug = {it.slug: it for it in plan.items}
    result = pd.derive_prompt(plan, items_by_slug["ch1_01_arrival"])
    assert "\n" not in result
    assert "\r" not in result


def test_bc_dr10_result_no_unescaped_pipe():
    plan = ps.parse(_BILINGUAL)
    items_by_slug = {it.slug: it for it in plan.items}
    result = pd.derive_prompt(plan, items_by_slug["ch1_01_arrival"])
    # _has_unescaped_pipe is the helper used internally
    assert not pd._has_unescaped_pipe(result)


# ---------- EH-DR2 IF-1 違反 (synthetic 2000+ chars) ----------


def test_eh_dr2_too_long_aborts():
    """EH-DR2: derive result > 2000 chars → ValueError."""
    plan = ps.parse(_BILINGUAL)
    # Build a giant beat_description
    giant_beat = "x" * 2001
    items_by_slug = {it.slug: it for it in plan.items}
    item = items_by_slug["ch1_01_arrival"]
    # Mutate item.beat_description
    item.beat_description = giant_beat
    with pytest.raises(ValueError, match="too long|>"):
        pd.derive_prompt(plan, item)


def test_eh_dr2_unescaped_pipe_aborts():
    """EH-DR2: beat_description containing unescaped | → ValueError."""
    plan = ps.parse(_BILINGUAL)
    items_by_slug = {it.slug: it for it in plan.items}
    item = items_by_slug["ch1_01_arrival"]
    item.beat_description = "bad | content"
    with pytest.raises(ValueError, match="unescaped"):
        pd.derive_prompt(plan, item)


# ---------- BC-DR11 baseline.txt physical mechanism (DR-4 採納) ----------


def test_bc_dr11_baseline_file_exists():
    """BC-DR11: baseline.txt must be on disk for mechanical verification."""
    assert _BASELINE.exists(), f"baseline not frozen at {_BASELINE}"
    content = _BASELINE.read_text(encoding="utf-8").rstrip("\n")
    assert len(content) > 0
    # Sanity: baseline should contain known M2-P4 5/20 strings
    assert "long flowing red hair" in content


# ---------- BC-DR12 new bilingual_storyboard_mock.md fixture ----------


def test_bc_dr12_bilingual_fixture_parses():
    """BC-DR12: new fixture parses with mode=storyboard + bilingual + Layer D."""
    plan = ps.parse(_BILINGUAL)
    assert plan.mode == "storyboard"
    assert plan.size_aspect == "landscape_16_9"
    assert plan.character_consistency == "pulid_face_ref"
    # Bilingual present
    assert plan.layer_a.hair.value_zh == "棕色中長髮"
    assert plan.style_prefix_zh == "傑作"
    # Layer D present
    items_by_slug = {it.slug: it for it in plan.items}
    assert items_by_slug["ch1_01_arrival"].beat_description_zh == (
        "主角夕陽下走進村莊"
    )


# ---------- EH-DR3 invalid mode ----------


def test_eh_dr3_invalid_mode_aborts():
    plan = ps.parse(_BILINGUAL)
    plan_bad = replace(plan, mode="invalid_mode")
    items_by_slug = {it.slug: it for it in plan.items}
    with pytest.raises(ValueError, match="EH-DR3"):
        pd.derive_prompt(plan_bad, items_by_slug["ch1_01_arrival"])


# ---------- Robustness: pre-existing derive_mock_outline.md fixture full sweep ----------


def test_derive_mock_outline_still_works_via_album_dispatch():
    """Smoke: 5/20 derived_mock_outline.md (3 items, 1 sentinel) works as expected."""
    plan = ps.parse(_DERIVED_MOCK)
    for item in plan.items:
        if item.prompt == pd.DERIVED_SENTINEL:
            result = pd.derive_prompt(plan, item)
            assert len(result) > 0
            assert "\n" not in result
