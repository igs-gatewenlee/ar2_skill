"""Fork preset → new working plan (BC-4, BC-5).

Loads preset, drops promote-only metadata (provenance becomes from_preset
forwarding), invokes plan_create with preload arg.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import plan_create
import plan_schema as ps


def from_preset(
    presets_dir: Path,
    plans_dir: Path,
    preset_id: str,
) -> int:
    """BC-4: read preset, run interactive Round 2/3/4 with preload."""
    try:
        ps.validate_id(preset_id)
    except ValueError as e:
        sys.stderr.write(f"❌ {e}\n")
        return 1
    src = presets_dir / f"{preset_id}_outline.md"
    if not src.exists():
        sys.stderr.write(f"❌ preset not found: {src}\n")
        return 1
    preset = ps.parse(src)
    # Detach from preset identity so plan_create can assign a new id +
    # provenance.forked_at. Identity / timestamp fields use sentinel
    # "(pending)" so any accidental write before plan_create overwrites them
    # is easy to spot.
    seed = replace(
        preset,
        id="(pending)",
        created="(pending)",
        updated="(pending)",
        status="ready",
        provenance={"from_preset": preset.id},
    )
    new_id = plan_create.create_plan(plans_dir, preload=seed)
    print(f"\n  forked from preset: {preset_id}")
    print(f"  new working id: {new_id}")
    return 0
