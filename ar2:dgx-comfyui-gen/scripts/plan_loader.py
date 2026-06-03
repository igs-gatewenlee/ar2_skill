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
    # 透明素材（Route A/B）。route 預設 "none" → 走原 Flux 管線零行為改變（白名單 dispatch §7.4）。
    route: str = "none"  # "none" | "rembg" | "layerdiffuse"
    asset_type: str | None = None  # "opaque" | "semi"（route≠none 時必填，BC-6）
    transparent: dict | None = None  # 合併 defaults+item params（category/size/bg_remove_strength…）


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
_PROMPT_DERIVE_MODULE_NAME = "ar2_prompt_derive"

# gen 需要的 plan_schema 最低契約版本（M-2）。plan_schema 加 transparent_assets = 1.3.0。
_REQUIRED_SCHEMA_VERSION = "1.3.0"


def _version_tuple(v: str) -> tuple[int, ...]:
    """'1.10.0' → (1,10,0)，數值比較（避免字串 '1.10'<'1.9' 的陷阱）。非數字段視為 0。"""
    parts = []
    for seg in str(v).split("."):
        parts.append(int(seg) if seg.isdigit() else 0)
    return tuple(parts)


def _import_plan_schema():
    """Locate plan_schema.py from sibling ar2:dgx-comfyui-plan skill.

    Returns the loaded module. Raises RuntimeError if not found.

    M-2：import 後 assert SCHEMA_VERSION >= REQUIRED，把跨 skill version drift 從
    silent（setdefault 撿舊版 → 缺欄 AttributeError 在很後面才爆）升為 fail-loud。
    此處執行即涵蓋 _import_prompt_derive 路徑（它先呼叫本函式）。
    """
    mod = _import_sibling_module(_PLAN_SCHEMA_MODULE_NAME, "plan_schema.py")
    have = getattr(mod, "SCHEMA_VERSION", "0.0.0")
    if _version_tuple(have) < _version_tuple(_REQUIRED_SCHEMA_VERSION):
        raise RuntimeError(
            f"plan_schema 版本過舊：SCHEMA_VERSION={have!r} < 需要 "
            f"{_REQUIRED_SCHEMA_VERSION!r}。gen 與 plan skill 須同 commit 部署。"
        )
    return mod


def _import_prompt_derive():
    """Locate prompt_derive.py from sibling ar2:dgx-comfyui-plan skill.

    BC-G1 / BC-G6 (M2-P1 design spec): same sibling-import pattern as
    _import_plan_schema; called eagerly at _expand_items entry.

    prompt_derive.py uses `from plan_schema import ...` (raw sibling
    name), so we alias the cached `ar2_plan_schema` module under
    `plan_schema` in sys.modules to make that import resolve.
    """
    plan_schema_mod = _import_plan_schema()
    sys.modules.setdefault("plan_schema", plan_schema_mod)
    return _import_sibling_module(
        _PROMPT_DERIVE_MODULE_NAME, "prompt_derive.py"
    )


def _import_sibling_module(module_name: str, file_name: str):
    """Locate `file_name` in sibling ar2:dgx-comfyui-plan skill scripts dir.

    Returns the loaded module, caching it in sys.modules under `module_name`.
    Raises RuntimeError if not found in any candidate path.
    """
    if module_name in sys.modules:
        return sys.modules[module_name]

    # ar2:dgx-comfyui-gen/scripts/ → ar2:dgx-comfyui-gen/ → .claude/skills/
    skills_dir = Path(__file__).resolve().parent.parent.parent
    # Deployed skills layout first, source repo fallback for dev mode.
    candidates = [
        skills_dir / "ar2:dgx-comfyui-plan" / "scripts" / file_name,
        Path.home() / "Code" / "ar2-skills" / "ar2:dgx-comfyui-plan"
            / "scripts" / file_name,
    ]
    for cand in candidates:
        if not cand.exists():
            continue
        spec = importlib.util.spec_from_file_location(module_name, cand)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod
    raise RuntimeError(
        f"{file_name[:-3]} not found. Install ar2:dgx-comfyui-plan skill "
        f"first (searched: {[str(c) for c in candidates]})"
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


_TRANSPARENT_ROUTES = ("rembg", "layerdiffuse", "vfx_additive")


def _resolve_transparent(slug: str, ta_items: dict, ta_defaults: dict):
    """回 (route, asset_type, transparent_params)。slug 不在 transparent_assets → route='none'。

    BC-6：route 屬 rembg/layerdiffuse 但缺 asset_type → raise（防 semi fail-gate 被靜默跳過）。
    """
    entry = ta_items.get(slug)
    if not entry:
        return "none", None, None
    route = entry.get("route", "none")
    asset_type = entry.get("asset_type")
    if route in _TRANSPARENT_ROUTES and not asset_type:
        raise ValueError(
            f"EH: transparent_assets 項 {slug!r} route={route!r} 缺 asset_type"
            f"（必須 opaque 或 semi，BC-6）"
        )
    params = dict(ta_defaults)
    params.update({k: v for k, v in entry.items() if k not in ("route", "asset_type", "params")})
    params.update(entry.get("params") or {})
    return route, asset_type, params


def _expand_items(plan) -> list[ResolvedItem]:
    """Apply prefix/suffix (or skip if full?), expand seed_strategy.

    BC-G2 / BC-G3 (M2-P1 design spec): items whose prompt exactly equals
    prompt_derive.DERIVED_SENTINEL are resolved via derive_prompt(); the
    derived string IS the final_prompt — no _join_prompt wrap, no item.full
    branch — because derive is the single source of truth for derived
    prompts (avoids letting style_prefix/suffix containing `|` violate
    M1 IF-1's "no unescaped `|`" post-condition).
    """
    prompt_derive = _import_prompt_derive()  # BC-G6: eager
    sentinel = prompt_derive.DERIVED_SENTINEL
    prefix = _norm_style(plan.style_prefix)
    suffix = _norm_style(plan.style_suffix)
    seed_seq = _build_seed_iter(plan.seed_strategy, len(plan.items))
    # 透明素材 block（None=非透明 plan → 所有 item route='none'，現役行為零變化）。
    ta = getattr(plan, "transparent_assets", None) or {}
    ta_items = ta.get("items", {}) if isinstance(ta, dict) else {}
    ta_defaults = ta.get("defaults", {}) if isinstance(ta, dict) else {}
    resolved: list[ResolvedItem] = []
    for i, item in enumerate(plan.items, start=1):
        if item.prompt == sentinel:
            final = _resolve_derived(prompt_derive, plan, item, i)
        elif item.full:
            final = item.prompt
        else:
            final = _join_prompt(prefix, item.prompt, suffix)
        route, asset_type, transparent = _resolve_transparent(item.slug, ta_items, ta_defaults)
        resolved.append(ResolvedItem(
            index=i,
            slug=item.slug,
            final_prompt=final.strip(),
            seed=next(seed_seq),
            filename_prefix=_slug_to_filename_prefix(item.slug, i),
            route=route,
            asset_type=asset_type,
            transparent=transparent,
        ))
    return resolved


def _resolve_derived(prompt_derive, plan, item, index: int) -> str:
    """EH-G2: wrap derive_prompt ValueError with item context.

    Re-raise (with `from e` chain) so plan_runner sees a user-friendly
    message that identifies which item triggered the failure and how to
    recover (fill Design Dimensions, or replace <derived> with a manual
    prompt string). Fail-fast on first failing item (EH-G3).
    """
    try:
        return prompt_derive.derive_prompt(plan, item)
    except ValueError as e:
        raise ValueError(
            f"item {index} '{item.slug}' uses <derived> sentinel: {e}. "
            "Fill Design Dimensions via plan skill, or replace <derived> "
            "with a manual prompt string."
        ) from e


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
