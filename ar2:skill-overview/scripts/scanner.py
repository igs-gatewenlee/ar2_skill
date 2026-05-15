"""Scan workspace + installed ar2:* skill directories.

Builds canonical-path-based view of each skill's install status (BC-1 ~ BC-3).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Source-of-truth = directory that holds this skill's repo. Derived from this
# file's resolved location: scanner.py lives at <repo>/<skill>/scripts/scanner.py
# so parent³ is the repo root. Path.resolve() follows symlinks, so this works
# whether scanner is invoked via the symlink in .claude/skills/ or from the
# actual source repo (e.g. ~/Code/ar2-skills/).
WORKSPACE_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
USER_SKILLS_DIR = Path("~/.claude/skills").expanduser()
SKILL_PREFIX = "ar2:"


def _detect_project_root() -> Path | None:
    """Walk up from cwd looking for a Claude Code project root.

    Returns the nearest ancestor that contains `.claude/skills/`, or None
    if cwd is outside any Claude Code project. Used to scan project-level
    installed skills dynamically (post-抽-repo there's no fixed project path).
    """
    cur = Path.cwd().resolve()
    for p in [cur, *cur.parents]:
        if (p / ".claude" / "skills").is_dir():
            return p
    return None


PROJECT_SKILLS_DIR: Path | None = (
    _root / ".claude" / "skills" if (_root := _detect_project_root()) else None
)

# Scan installed skills: project-level (priority) → user-level (fallback).
# Project-level absent (invoked outside a project) → user-level only.
INSTALLED_SKILLS_DIRS: tuple[Path, ...] = tuple(
    d for d in (PROJECT_SKILLS_DIR, USER_SKILLS_DIR) if d is not None
)

SkillStatus = Literal["installed", "workspace_only", "orphan_install"]


@dataclass
class SkillInfo:
    """IF-2: canonical-path-based skill descriptor."""

    name: str
    workspace_path: Path | None  # canonical (Path.resolve())
    install_path: Path | None    # canonical (Path.resolve())
    status: SkillStatus


class WorkspaceMissing(Exception):
    """EH-1: workspace skills directory doesn't exist."""


def _list_ar2_entries(dir_path: Path) -> dict[str, Path]:
    """Return {skill_name: canonical_path} for all ar2:* dirs (EH-2: empty if missing)."""
    if not dir_path.exists():
        return {}
    return {
        entry.name: entry.resolve()
        for entry in dir_path.iterdir()
        if entry.name.startswith(SKILL_PREFIX) and entry.is_dir()
    }


def _list_installed_entries() -> dict[str, Path]:
    """Merge ar2:* entries across all INSTALLED_SKILLS_DIRS (first-seen wins)."""
    merged: dict[str, Path] = {}
    for d in INSTALLED_SKILLS_DIRS:
        for name, path in _list_ar2_entries(d).items():
            merged.setdefault(name, path)
    return merged


def _derive_status(workspace: Path | None, install: Path | None) -> SkillStatus:
    """BC-3: classify a skill by presence in workspace vs installed sets."""
    if workspace is not None and install is not None:
        return "installed"
    if workspace is not None:
        return "workspace_only"
    return "orphan_install"


def list_skills() -> list[SkillInfo]:
    """List all ar2:* skills with install status.

    Raises:
        WorkspaceMissing: if WORKSPACE_SKILLS_DIR doesn't exist.
    """
    if not WORKSPACE_SKILLS_DIR.exists():
        raise WorkspaceMissing(
            f"找不到 {WORKSPACE_SKILLS_DIR}，是否在錯誤的 workspace？"
        )

    workspace_entries = _list_ar2_entries(WORKSPACE_SKILLS_DIR)
    installed_entries = _list_installed_entries()

    all_names = sorted(workspace_entries.keys() | installed_entries.keys())
    return [
        SkillInfo(
            name=name,
            workspace_path=workspace_entries.get(name),
            install_path=installed_entries.get(name),
            status=_derive_status(
                workspace_entries.get(name), installed_entries.get(name)
            ),
        )
        for name in all_names
    ]
