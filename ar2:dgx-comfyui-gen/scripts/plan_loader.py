"""Plan loader for gen --plan / --preset (IF-3 contract).

Reads outline.md (working OR preset path), parses via plan_schema, expands
items to concrete (prompt, seed, filename_prefix) tuples.

Reuses the same parser as the plan skill — to avoid a hard cross-skill
import, this module loads plan_schema from a sibling skill path if available
(install-to.sh deploys both via project-level symlinks). Falls back to a
minimal inline parser if plan_schema cannot be located.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


@dataclass
class ResolvedItem:
    """Expanded item ready for ComfyUI submission."""
    index: int  # 1-based
    slug: str
    final_prompt: str
    seed: int
    filename_prefix: str  # `{NN}_{slug}` per output naming


@dataclass
class LoadedPlan:
    """Wrapper around parsed schema.Plan + resolved items."""
    raw: Any  # schema.Plan instance
    items: list[ResolvedItem]
    workflow: str
    size: list[int]
    steps: int
    lora: list[dict]
    face_ref: str | None
    pulid_weight: float | None
    negative: str
    output_dir: str
    mode: str  # "plan" | "preset"


_PLAN_SCHEMA_MODULE_NAME = "ar2_plan_schema"


def _import_plan_schema():
    """Locate plan_schema.py from sibling ar2:dgx-comfyui-plan skill.

    Returns the loaded module. Raises RuntimeError if not found.
    """
    if _PLAN_SCHEMA_MODULE_NAME in sys.modules:
        return sys.modules[_PLAN_SCHEMA_MODULE_NAME]

    # Common candidate paths (project-level install via symlink)
    here = Path(__file__).resolve()
    # ar2:dgx-comfyui-gen/scripts/ → parent ar2:dgx-comfyui-gen/ → parent .claude/skills/
    skills_dir = here.parent.parent.parent
    candidates = [
        skills_dir / "ar2:dgx-comfyui-plan" / "scripts" / "plan_schema.py",
        # Also try ~/Code/ar2-skills/ when running from source repo
        Path.home() / "Code" / "ar2-skills" / "ar2:dgx-comfyui-plan"
            / "scripts" / "plan_schema.py",
    ]
    for cand in candidates:
        if cand.exists():
            spec = importlib.util.spec_from_file_location(
                _PLAN_SCHEMA_MODULE_NAME, cand
            )
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[_PLAN_SCHEMA_MODULE_NAME] = mod
            spec.loader.exec_module(mod)
            return mod
    raise RuntimeError(
        "plan_schema not found. Install ar2:dgx-comfyui-plan skill first "
        f"(searched: {[str(c) for c in candidates]})"
    )


def load_working(plans_dir: Path, plan_id: str) -> LoadedPlan:
    """Load working plan: plans/{id}_outline.md. (validates id, R-1 sec fix)"""
    schema = _import_plan_schema()
    schema.validate_id(plan_id)
    path = plans_dir / f"{plan_id}_outline.md"
    return _load(path, mode="plan")


def load_preset(presets_dir: Path, preset_id: str) -> LoadedPlan:
    """Load preset: ar2-skills/.../presets/{id}_outline.md. (validates id)"""
    schema = _import_plan_schema()
    schema.validate_id(preset_id)
    path = presets_dir / f"{preset_id}_outline.md"
    return _load(path, mode="preset")


def _load(path: Path, *, mode: str) -> LoadedPlan:
    if not path.exists():
        raise FileNotFoundError(f"plan / preset not found: {path}")
    schema = _import_plan_schema()
    plan = schema.parse(path)
    items = _expand_items(plan)
    return LoadedPlan(
        raw=plan,
        items=items,
        workflow=plan.workflow,
        size=plan.size,
        steps=plan.steps,
        lora=plan.lora,
        face_ref=plan.face_ref,
        pulid_weight=plan.pulid_weight,
        negative=_resolve_negative(plan.style_negative),
        output_dir=plan.output_dir,
        mode=mode,
    )


_SENTINEL_EMPTY = ("(none)", "", None)
# Recognize chapter-encoded slugs like `ch1_01_home_morning`
_CHAPTER_SLUG_RE = re.compile(r"^(ch\d+)_(\d{2})_(.+)$")


def _norm_style(value) -> str:
    """Normalize style anchor to empty string when unset."""
    return "" if value in _SENTINEL_EMPTY else value


def _slug_to_filename_prefix(slug: str, global_index: int) -> str:
    """Map slug → filename_prefix.

    If slug matches `ch{N}_{NN}_{rest}` (chapter-encoded), return
    `ch{N}/{NN}_{rest}` so ComfyUI SaveImage drops the file into a
    chapter subdir. Otherwise flat fallback `{NN}_{slug}` (1-based).
    """
    m = _CHAPTER_SLUG_RE.match(slug)
    if m:
        chapter, num, rest = m.groups()
        return f"{chapter}/{num}_{rest}"
    return f"{global_index:02d}_{slug}"


def _expand_items(plan) -> list[ResolvedItem]:
    """Apply prefix/suffix (or skip if full?), expand seed_strategy."""
    prefix = _norm_style(plan.style_prefix)
    suffix = _norm_style(plan.style_suffix)
    seed_seq = _build_seed_iter(plan.seed_strategy, len(plan.items))
    resolved: list[ResolvedItem] = []
    for i, item in enumerate(plan.items, start=1):
        final = item.prompt if item.full else _join_prompt(prefix, item.prompt, suffix)
        resolved.append(ResolvedItem(
            index=i,
            slug=item.slug,
            final_prompt=final.strip(),
            seed=next(seed_seq),
            filename_prefix=_slug_to_filename_prefix(item.slug, i),
        ))
    return resolved


def _join_prompt(prefix: str, prompt: str, suffix: str) -> str:
    """Concatenate prefix + prompt + suffix.

    If both prefix and suffix are comma-free, use `", "` separator
    (clean style-anchor case). If either already contains a comma,
    fall back to space-joining so the user's own punctuation stays
    intact (e.g. "high quality, detailed" stays as-is, separated by
    spaces from the body prompt).
    """
    bookends_have_comma = ("," in prefix) or ("," in suffix)
    if not bookends_have_comma:
        parts = [s for s in (prefix, prompt, suffix) if s]
        return ", ".join(parts)
    head = prefix + " " if prefix else ""
    tail = " " + suffix if suffix else ""
    return f"{head}{prompt}{tail}"


def _resolve_negative(neg: str) -> str:
    return "" if neg in _SENTINEL_EMPTY else neg


def _build_seed_iter(strategy: dict, count: int):
    typ = strategy.get("type", "random")
    base = int(strategy.get("base") or 0)
    step = int(strategy.get("step") or 0)
    if typ == "fixed":
        for _ in range(count):
            yield base
        return
    if typ == "incremental":
        for i in range(count):
            yield base + i * step
        return
    # random (default fallback)
    import secrets as _s
    for _ in range(count):
        yield _s.randbits(32)


def parse_items_spec(spec: str) -> set[int]:
    """Parse subset spec into set of 1-based indices.

    Examples:
        '5'        → {5}
        '1-5'      → {1,2,3,4,5}
        '1,3,5-7'  → {1,3,5,6,7}

    Raises ValueError on malformed input.
    """
    result: set[int] = set()
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo, hi = chunk.split("-", 1)
            result.update(range(int(lo), int(hi) + 1))
        else:
            result.add(int(chunk))
    return result


def filter_items(loaded: "LoadedPlan", items_spec: str) -> "LoadedPlan":
    """Return new LoadedPlan with items filtered to indices in items_spec."""
    indices = parse_items_spec(items_spec)
    filtered = [it for it in loaded.items if it.index in indices]
    if not filtered:
        raise ValueError(
            f"items_spec '{items_spec}' matched 0 items (plan has "
            f"{len(loaded.items)} items, indices 1..{len(loaded.items)})"
        )
    return replace(loaded, items=filtered)


def strip_workflow_metadata(workflow: dict) -> dict:
    """Strip non-node keys (e.g. _comment) that ComfyUI rejects on /prompt.

    Discovered bug 2026-05-16 (12 zodiac session): ComfyUI returns HTTP 500
    when workflow contains `_comment` or other non-node top-level keys.
    """
    return {k: v for k, v in workflow.items() if not k.startswith("_")}
