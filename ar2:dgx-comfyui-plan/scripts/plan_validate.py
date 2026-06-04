"""Plan Y v1.3 — `--validate` subcommand (BC-G5-4 / IF-G5).

Statistical, non-blocking lint over Plan.items: event-density / dispatch /
cast warnings. Always exits 0 on a parsed plan (warnings never block); a parse
failure exits 1 (stderr). Delegated from plan_main.py for testability.

Warning groups (BC-G5-4):
  A. event validation — A1 event density, A2 consecutive same event_type
  B. cast validation  — B1 cast↔PuLID conflict (EH-G4-2), B2 visual_lock ↔
     cast.protagonist overlap (EH-G4-3)
  C. dispatch validation — C1 panel_type not in taxonomy (EH-G3-1),
     C2 item ↔ panel_taxonomy double-write (DR-4 helper SSoT)

B3 (cast_in_panel undefined ref) is enforced earlier at PARSE time (EH-G4-1,
ValueError) — a successfully parsed plan cannot reach validate with an unknown
ref, so it is surfaced via the parse-failure path (exit 1), not as a dead
in-validate check.
"""

from __future__ import annotations

import sys
from pathlib import Path

import plan_schema as ps

# event_type groups (BC-G5-4 A1: mood + transition = 弱事件).
_WEAK_EVENT_TYPES = ("mood", "transition")
# dispatch dims checked for item ↔ panel_taxonomy double-write (BC-G5-4 C2).
# beat_prefix/suffix have no item-layer source → never double-written; omitted.
_C2_DIMS = ("workflow", "pulid.enabled", "pulid.strength", "pulid.face_ref")


def collect_warnings(plan: ps.Plan) -> list[str]:
    """Return ordered list of warning strings (testable, no IO)."""
    out: list[str] = []
    out.extend(_event_warnings(plan))    # A
    out.extend(_cast_warnings(plan))     # B
    out.extend(_dispatch_warnings(plan)) # C
    return out


# ---------- A. event validation ----------


def _event_warnings(plan: ps.Plan) -> list[str]:
    out: list[str] = []
    items = plan.items
    density = (
        plan.plan_quality["event_density_warning"]
        if plan.plan_quality else 0.7
    )
    threshold = 1.0 - density  # default 0.3
    typed = [it for it in items if it.event_type]
    if typed:
        weak = sum(1 for it in items if it.event_type in _WEAK_EVENT_TYPES)
        ratio = weak / len(items)
        if ratio > threshold:
            out.append(
                f"[A1] 事件密度低：{ratio:.0%} panels 為 mood/transition、"
                f"建議 ≥ {1 - threshold:.0%} strong event "
                f"(event_density_warning={density})"
            )
    # A2: consecutive same event_type
    for i in range(len(items) - 1):
        a, b = items[i], items[i + 1]
        if a.event_type and a.event_type == b.event_type:
            out.append(
                f"[A2] item {i + 1} ({a.slug}) 與 {i + 2} ({b.slug}) 同為 "
                f"{a.event_type}、視覺敘事可能重複"
            )
    return out


# ---------- B. cast validation ----------


def _cast_warnings(plan: ps.Plan) -> list[str]:
    out: list[str] = []
    # B1: cast_in_panel ≥ 2 type=human + effective pulid_enabled=true (EH-G4-2).
    if plan.cast:
        for item in plan.items:
            humans = [
                c for c in item.cast_in_panel
                if c in plan.cast and plan.cast[c].type == "human"
            ]
            if len(humans) < 2:
                continue
            enabled, _ = ps._resolve_per_item_config(plan, item, "pulid.enabled")
            if enabled:
                out.append(
                    f"[B1] item {item.slug}：PuLID 與多角色衝突、cast={humans}、"
                    f"建議 panel_type=multi_character_ensemble 或顯式設 "
                    f"pulid.enabled=false"
                )
    # B2: visual_lock.{key}.value + cast.protagonist.visual.{key} both set (EH-G4-3).
    if plan.cast and "protagonist" in plan.cast and plan.layer_a is not None:
        prot = plan.cast["protagonist"]
        for key in prot.visual:
            if key not in ps._LAYER_A_DIMENSION_NAMES:
                continue
            dim = getattr(plan.layer_a, key)
            if dim.scope != "unspecified" and dim.value:
                out.append(
                    f"[B2] 重複定義 {key}：visual_lock 與 cast.protagonist 皆設、"
                    f"以 cast.protagonist 為準"
                )
    return out


# ---------- C. dispatch validation ----------


def _dispatch_warnings(plan: ps.Plan) -> list[str]:
    out: list[str] = []
    for item in plan.items:
        # C1: panel_type referenced but not defined in panel_taxonomy (EH-G3-1).
        if item.panel_type and (
            not plan.panel_taxonomy or item.panel_type not in plan.panel_taxonomy
        ):
            out.append(
                f"[C1] item {item.slug} panel_type={item.panel_type} 未在 "
                f"panel_taxonomy 定義、會 fallback 到 plan-level default"
            )
        # C2: item ↔ panel_taxonomy double-write (uses DR-4 helper SSoT, DR-R2-7).
        for dim in _C2_DIMS:
            if ps._dispatch_double_written(plan, item, dim):
                out.append(
                    f"[C2] item {item.slug} 同時雙寫 item 與 "
                    f"panel_taxonomy[{item.panel_type}] 的 {dim}、以 item 為準"
                    f"（per BC-G3-4 Layer 1）"
                )
    return out


# ---------- CLI entry ----------


def validate(plans_dir: Path, plan_id: str) -> int:
    """IF-G5: validate plans/{id}_outline.md → stdout warnings, exit 0.

    Parse failure (incl. EH-G4-1 undefined cast ref / B3) → exit 1 + stderr.
    """
    ps.validate_id(plan_id)
    path = plans_dir / f"{plan_id}_outline.md"
    if not path.exists():
        sys.stderr.write(f"❌ plan not found: {path}\n")
        return 1
    try:
        plan = ps.parse(path)
    except ValueError as e:
        sys.stderr.write(f"❌ plan parse failed (plan-stage block): {e}\n")
        return 1
    warnings = collect_warnings(plan)
    if not warnings:
        print(f"✅ {plan_id}: no validation warnings ({len(plan.items)} items)")
        return 0
    print(f"⚠️  {plan_id}: {len(warnings)} validation warning(s) "
          f"({len(plan.items)} items) — non-blocking:")
    for w in warnings:
        print(f"   {w}")
    return 0
