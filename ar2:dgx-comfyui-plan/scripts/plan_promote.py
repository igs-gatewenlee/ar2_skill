"""Promote working plan → preset (BC-9, BC-10, BC-11, EH-6).

Sanitize rules (BC-10, minimal per Q14):
- face_ref containing / or ~ → "<set face_ref locally>"
- output.dir starting with / → "outputs/{id}/"
- strip "# Run history" section (not present in MVP yet, future-proof)
- inject: promoted, provenance, optional description, tags
"""

from __future__ import annotations

import re
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import plan_schema as ps


def promote(
    plans_dir: Path,
    presets_dir: Path,
    working_id: str,
    description: str | None = None,
    tags: list[str] | None = None,
    overwrite: bool = False,
) -> int:
    """BC-9: working plan → preset, with sanitize (BC-10) and overwrite handling (BC-11/EH-6)."""
    try:
        ps.validate_id(working_id)
    except ValueError as e:
        sys.stderr.write(f"❌ {e}\n")
        return 1
    src = plans_dir / f"{working_id}_outline.md"
    if not src.exists():
        sys.stderr.write(f"❌ working plan not found: {src}\n")
        return 1
    presets_dir.mkdir(parents=True, exist_ok=True)
    dst = presets_dir / f"{working_id}_outline.md"

    if dst.exists() and not overwrite:
        sys.stderr.write(
            f"⚠️  preset already exists: {dst}\n"
            "    re-run with --overwrite to replace, or use a different id.\n"
        )
        return 2

    plan = ps.parse(src)

    # R-4 sec: scan free-text fields for local-path leaks before promote.
    leak_warnings = _scan_free_text_leaks(plan)
    if leak_warnings:
        sys.stderr.write(
            "⚠️  free-text fields contain possible local-path leaks:\n"
        )
        for w in leak_warnings:
            sys.stderr.write(f"     - {w}\n")
        sys.stderr.write(
            "    review your plan before promoting (these are NOT auto-stripped — "
            "they may be intentional). Re-run after editing, or proceed knowingly.\n"
        )

    sanitized = _sanitize(plan, working_id, description, tags)

    if dst.exists() and overwrite:
        backup = dst.with_suffix(dst.suffix + ".bak")
        shutil.copy2(dst, backup)
        sys.stderr.write(f"ℹ️  backed up existing preset → {backup}\n")

    ps.atomic_write(dst, ps.serialize(sanitized))
    print(f"✅ promoted: {dst}")
    print("\n--- preview (first 30 lines) ---")
    text = dst.read_text(encoding="utf-8")
    for line in text.splitlines()[:30]:
        print(line)
    print("\n--- next steps ---")
    print(f"cd {presets_dir.parent.parent}")
    print(f"git add ar2:dgx-comfyui-plan/presets/{working_id}_outline.md")
    print(f"git commit -m 'feat(presets): add {working_id}'")
    print("git push  # share across machines / users")
    return 0


def _sanitize(
    plan: ps.Plan,
    working_id: str,
    description: str | None,
    tags: list[str] | None,
) -> ps.Plan:
    """BC-10 sanitize rules — copy plan with sanitized fields + preset metadata."""
    now = ps.now_iso()
    return replace(
        plan,
        updated=now,
        status="ready",
        face_ref=_sanitize_face_ref(plan.face_ref),
        output_dir=_sanitize_output_dir(plan.output_dir, plan.id),
        description=description,
        tags=tags or [],
        provenance={"original_id": working_id},
        promoted=now,
    )


_FACE_REF_LEAK_PATTERNS = (
    "/", "\\", "~",            # POSIX path / Windows backslash / home
    "$HOME", "%USERPROFILE%",  # env vars
    "%HOME%", "$USER",
)
_OUTPUT_DIR_FORBIDDEN_CONTAINS = (
    "\\", "~", "..",           # win backslash / home / traversal anywhere
    "$HOME", "%USERPROFILE%", "%HOME%",
)
# Drive-letter prefix (Windows): C:\, D:/, etc.
_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_like_local_path(text: str | None) -> bool:
    """R-3 / R-4 sec: heuristic to detect leaked local paths (for face_ref /
    free-text fields — pure relative `outputs/foo/` is fine elsewhere)."""
    if not text:
        return False
    if _DRIVE_LETTER_RE.search(text):
        return True
    return any(pat in text for pat in _FACE_REF_LEAK_PATTERNS)


def _is_unsafe_output_dir(output_dir: str) -> bool:
    """R-2 sec fix: output dir-specific check — reject abs / traversal / win /
    env vars BUT allow plain relative `outputs/{anything}/` with `/` inside."""
    if not output_dir:
        return False
    if output_dir.startswith("/"):
        return True
    if _DRIVE_LETTER_RE.search(output_dir):
        return True
    return any(pat in output_dir for pat in _OUTPUT_DIR_FORBIDDEN_CONTAINS)


def _sanitize_face_ref(face_ref: str | None) -> str | None:
    """R-3 sec fix: cover Windows / env vars / drive letter."""
    if face_ref is None:
        return None
    if _looks_like_local_path(face_ref):
        return "<set face_ref locally>"
    return face_ref


def _sanitize_output_dir(output_dir: str, plan_id: str) -> str:
    """R-2 sec fix: reject abs / `..` / `~` / Windows; keep plain relative."""
    if _is_unsafe_output_dir(output_dir):
        return f"outputs/ar2-dgx-comfyui-gen/{plan_id}/"
    return output_dir


def _scan_free_text_leaks(plan: ps.Plan) -> list[str]:
    """R-4 sec fix: scan free-text fields for local paths; return field names."""
    warnings: list[str] = []
    if _looks_like_local_path(plan.story_vision):
        warnings.append("story_vision")
    if _looks_like_local_path(plan.open_notes):
        warnings.append("open_notes")
    if _looks_like_local_path(plan.description):
        warnings.append("description")
    for i, it in enumerate(plan.items, start=1):
        if _looks_like_local_path(it.prompt):
            warnings.append(f"items[{i}].prompt ({it.slug})")
    for t in plan.tags:
        if _looks_like_local_path(t):
            warnings.append(f"tags ({t})")
    return warnings
