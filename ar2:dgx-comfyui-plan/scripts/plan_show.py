"""Plan list / show (BC-6, BC-7, BC-8).

BC-6: `--list` → working plans in plans/
BC-7: `--show` (no args) → presets in ar2-skills/.../presets/
BC-8: `--show {id}` → cat preset detail
"""

from __future__ import annotations

import sys
from pathlib import Path

import plan_schema as ps


def list_plans(plans_dir: Path) -> int:
    """BC-6: list working plans in plans_dir."""
    if not plans_dir.exists():
        print("(no plans directory)")
        return 0
    files = sorted(plans_dir.glob("*_outline.md"))
    if not files:
        print("(no working plans)")
        return 0
    print(f"Working plans ({len(files)}):")
    for f, plan in _iter_parsed(files):
        if plan is None:
            continue
        print(
            f"  {plan.id:32s}  {plan.title:30s}  "
            f"{plan.status:10s}  "
            f"({len(plan.items)} items)"
        )
    return 0


def show_presets(presets_dir: Path, preset_id: str | None) -> int:
    """BC-7 (no args) / BC-8 (with id)."""
    if not presets_dir.exists():
        print(f"(no presets directory: {presets_dir})")
        return 0
    if preset_id is None:
        return _list_presets(presets_dir)
    return _show_preset(presets_dir, preset_id)


def _list_presets(presets_dir: Path) -> int:
    files = sorted(presets_dir.glob("*_outline.md"))
    if not files:
        print("(no presets)")
        return 0
    print(f"Available presets ({len(files)}):")
    for f, plan in _iter_parsed(files):
        if plan is None:
            continue
        desc = plan.description or plan.title
        tags = ",".join(plan.tags) if plan.tags else "-"
        print(
            f"  {plan.id:32s}  {desc:35s}  tags:{tags:20s}  "
            f"({len(plan.items)} items)"
        )
    return 0


def _show_preset(presets_dir: Path, preset_id: str) -> int:
    try:
        ps.validate_id(preset_id)
    except ValueError as e:
        sys.stderr.write(f"❌ {e}\n")
        return 1
    path = presets_dir / f"{preset_id}_outline.md"
    if not path.exists():
        sys.stderr.write(f"❌ preset not found: {path}\n")
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def _iter_parsed(files):
    """Yield (path, Plan|None). Prints a warning + None for unparseable files."""
    for f in files:
        try:
            yield f, ps.parse(f)
        except ValueError as e:
            print(f"  ⚠️  {f.name}: parse failed: {e}")
            yield f, None
