"""Plan markdown schema: parse / serialize / id_gen.

Implements IF-1 contract (P1 design spec v2):
- YAML frontmatter (required + optional fields)
- Markdown body sections (固定順序)
- Items table (| # | slug | prompt | full? |)

BC-2: id generation `{slug}_{4hex}`, 衝突重 roll 最多 3 次.
BC-3: schema validation.
BC-18: prompt 字符邊界 (| escape, U+FF5C 全形保留, no multi-line).
EH-1/2/3: parse errors with clear messages.
EH-11: atomic write helper (write-tmp + rename).
"""

from __future__ import annotations

import datetime
import os
import re
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml  # PyYAML 6.x
except ImportError:
    sys.stderr.write("ERROR: PyYAML not installed. Run: pip install pyyaml\n")
    raise


_FRONTMATTER_DELIM = "---"
_REQUIRED_FRONTMATTER = {
    "id", "title", "version", "created", "updated",
    "status", "workflow", "size", "steps",
    "batch_per_item", "seed_strategy",
}
_VALID_STATUS = {"planning", "ready", "done"}
# pulid_weight bounds: 0.0 is a defined value-write (DR-4 — we do not
# claim "PuLID off"). 3.0 is a conservative upper buffer (by-design,
# no A-grade ComfyUI ApplyPulidFlux upstream evidence; revisit if a
# counter-example surfaces).
_PULID_WEIGHT_MIN = 0.0
_PULID_WEIGHT_MAX = 3.0
_REQUIRED_SECTIONS = [
    "# Story / Vision",
    "# Style anchor",
    "# Output",
    "# Items",
    "# Open notes",
]
_ITEMS_HEADER_RE = re.compile(
    r"^\|\s*#\s*\|\s*slug\s*\|\s*prompt\s*\|\s*full\?\s*\|\s*$",
    re.IGNORECASE,
)
_TABLE_SEP_RE = re.compile(r"^\|[\s\-:]+\|[\s\-:]+\|[\s\-:]+\|[\s\-:]+\|\s*$")

# Design Dimensions section header (optional section, BC-1).
_DESIGN_DIMENSIONS_HEADER = "# Design Dimensions"
# Layer A: 9 visual dimensions whitelist (EH-2b).
_LAYER_A_DIMENSION_NAMES = (
    "hair", "outfit", "composition", "background", "lighting",
    "expression", "style_intensity", "view_angle", "color_palette",
)
# Layer A: scope enum (EH-2). per_item removed per DR-1; per-item variation
# uses manual override (item.prompt as a literal string, not "<derived>").
_SCOPE_VALUES = {"locked", "per_group", "unspecified"}
# Layer B: grouping_axis enum (EH-3).
_GROUPING_AXIS_VALUES = {"rarity", "chapter", "custom"}
# YAML top-level keys inside Design Dimensions section.
_DD_KEY_LAYER_B = "season_structure"
_DD_KEY_LAYER_C = "narrative_direction"
_DD_KEY_LAYER_A = "visual_lock"
# Plan Y v1.2 — per_item beat (Layer D) YAML key inside Design Dimensions.
_DD_KEY_PER_ITEM_BEATS = "per_item_beats"

# BC-S0 (Plan Y v1.2): Module-level enum SSoT — all literal usages MUST
# reference these (#009 prevention落地).
MODE_ENUM = ("album", "storyboard")
SIZE_ASPECT_ENUM = (
    "square", "landscape_16_9", "portrait_9_16", "classic_4_3", "portrait_2_3",
)
CHARACTER_CONSISTENCY_ENUM = ("prompt_only", "pulid_face_ref", "both")
SIZE_ASPECT_TO_SIZE: dict[str, tuple[int, int]] = {
    "square": (1024, 1024), "landscape_16_9": (1280, 720),
    "portrait_9_16": (720, 1280), "classic_4_3": (1024, 768),
    "portrait_2_3": (768, 1152),
}

# Plan dataclass / frontmatter 契約版本。跨 skill 消費者（gen/plan_loader）import 後
# assert 此值 >= 其 REQUIRED，防 version drift 時 sibling-import 撿到舊版 module 而 silent
# 漏欄（M-2）。新增/移除影響 Plan 序列化的欄位時 bump。
SCHEMA_VERSION = "1.3.0"  # 1.3.0: 新增 transparent_assets（透明素材 route/asset_type block）


@dataclass
class Dimension:
    """Layer A 維度的單一欄位 (value + scope + optional zh)."""
    value: str | None
    scope: str  # locked | per_group | unspecified
    value_zh: str | None = None  # BC-B1 (Plan Y v1.2): Chinese companion for chat UI


@dataclass
class LayerA:
    """Visual Lock — 9 維度視覺鎖定 (BC-4)."""
    hair: Dimension
    outfit: Dimension
    composition: Dimension
    background: Dimension
    lighting: Dimension
    expression: Dimension
    style_intensity: Dimension
    view_angle: Dimension
    color_palette: Dimension


@dataclass
class LayerB:
    """Season Structure — 季結構 (BC-5)."""
    theme: str
    grouping_axis: str
    groups: dict[str, dict[str, Any]]
    cross_group_progression: dict[str, dict[str, str]] | None = None
    character_continuity: str | None = None
    acceptance: str | None = None


@dataclass
class LayerC:
    """Narrative Direction — 敘事方向. chat-driven 引導用、不直接進 prompt (DR-6)."""
    character_seed: str
    group_arc: dict[str, str]
    emotion_palette: str | None = None


@dataclass
class Item:
    """One row of the items table (+ optional Layer D per-item beat)."""
    slug: str
    prompt: str
    full: bool = False  # ✓ → self-contained, no auto inject
    # BC-D1 (Plan Y v1.2): Layer D per-item beat (storyboard mode); stored in
    # Design Dimensions per_item_beats block, not in Items table.
    beat_description: str | None = None
    beat_description_zh: str | None = None


@dataclass
class Plan:
    """Parsed plan outline.md."""
    # Required frontmatter
    id: str
    title: str
    version: int
    created: str
    updated: str
    status: str
    workflow: str
    size: list[int]
    steps: int
    batch_per_item: int
    seed_strategy: dict
    # Optional frontmatter
    lora: list[dict] = field(default_factory=list)
    face_ref: str | None = None
    pulid_weight: float | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    provenance: dict | None = None
    promoted: str | None = None
    # Body sections (raw text)
    story_vision: str = ""
    style_prefix: str = "(none)"
    style_suffix: str = "(none)"
    style_negative: str = "(none)"
    # BC-B4 (Plan Y v1.2): bilingual companions for style anchors.
    style_prefix_zh: str | None = None
    style_suffix_zh: str | None = None
    style_negative_zh: str | None = None
    output_dir: str = ""
    output_naming: str = ""
    items: list[Item] = field(default_factory=list)
    open_notes: str = ""
    # Design Dimensions (BC-1, optional — None when section absent).
    layer_b: LayerB | None = None
    layer_c: LayerC | None = None
    layer_a: LayerA | None = None
    # BC-S0/S1/S2/S3 (Plan Y v1.2): defaults are ENUM[0]; size_aspect=None for legacy.
    mode: str = "album"  # MODE_ENUM
    size_aspect: str | None = None  # SIZE_ASPECT_ENUM
    character_consistency: str = "prompt_only"  # CHARACTER_CONSISTENCY_ENUM
    # 透明素材（Route A/B）per-asset 設定，opaque schema dict（{defaults, items}）。
    # None=非透明 plan（現役行為零變化）。plan_loader 按 slug 映射到 ResolvedItem.route/asset_type。
    transparent_assets: dict | None = None


_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")


def now_iso() -> str:
    """ISO8601 with local tz (DR-13). Use this everywhere — do NOT duplicate."""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def validate_id(plan_or_preset_id: str) -> str:
    """Validate user-supplied plan / preset id (Phase 3 R-1 sec fix).

    Reject path traversal vectors: `/`, `..`, `~`, drive letters, env vars,
    spaces, special characters. Accept only `[a-z][a-z0-9_]{0,63}`.

    Raises:
        ValueError: id is not safe to use as a path component.
    """
    if not isinstance(plan_or_preset_id, str):
        raise ValueError(f"id must be str, got {type(plan_or_preset_id).__name__}")
    if not plan_or_preset_id:
        raise ValueError("id is empty")
    if len(plan_or_preset_id) > 64:
        raise ValueError(f"id too long ({len(plan_or_preset_id)} > 64 chars)")
    if not _ID_PATTERN.match(plan_or_preset_id):
        raise ValueError(
            f"invalid id '{plan_or_preset_id}': must match [a-z][a-z0-9_]{{0,63}} "
            "(no path separators, no special characters)"
        )
    return plan_or_preset_id


def slugify(title: str, max_len: int = 20) -> str:
    """Derive lowercase ASCII slug from title.

    Strategy: keep [a-z0-9], replace spaces / 中文 / 符號 with `_`,
    collapse consecutive `_`, strip leading / trailing `_`, truncate.
    If empty after processing → fallback to "plan".
    """
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        s = "plan"
    return s[:max_len]


def gen_id(title: str, exists_check) -> str:
    """BC-2: `{slug}_{4hex}`, 衝突重 roll 最多 3 次.

    Args:
        title: plan title
        exists_check: callable(id) -> bool

    Raises:
        RuntimeError: 衝突 ≥ 3 次
    """
    base = slugify(title)
    for _ in range(3):
        suffix = secrets.token_hex(2)  # 4 hex chars
        candidate = f"{base}_{suffix}"
        if not exists_check(candidate):
            return candidate
    raise RuntimeError(
        f"id collision: tried 3 random suffixes for slug '{base}'"
    )


def atomic_write(path: Path, content: str) -> None:
    """EH-11: write-tmp + rename pattern. Excludes append (history.jsonl)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.rename(tmp, path)


def parse(path: Path) -> Plan:
    """Parse outline.md → Plan dataclass.

    Raises:
        ValueError: EH-1 (frontmatter) / EH-2 (sections) / EH-3 (items table)
    """
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text, path)
    fm = _parse_frontmatter(frontmatter, path)
    sections = _split_sections(body, path)
    return _build_plan(fm, sections, path)


def serialize(plan: Plan) -> str:
    """Plan → outline.md string."""
    fm_dict = _plan_to_frontmatter(plan)
    fm_yaml = yaml.safe_dump(fm_dict, allow_unicode=True, sort_keys=False)
    body = _plan_to_body(plan)
    return f"---\n{fm_yaml}---\n\n{body}"


# ---------- internal helpers ----------


def _split_frontmatter(text: str, path: Path) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        raise ValueError(
            f"EH-1: {path}: missing frontmatter opening `---`"
        )
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == _FRONTMATTER_DELIM:
            end = i
            break
    if end is None:
        raise ValueError(
            f"EH-1: {path}: frontmatter not closed (no second `---`)"
        )
    fm_text = "\n".join(lines[1:end])
    body_text = "\n".join(lines[end + 1:])
    return fm_text, body_text


def _parse_frontmatter(text: str, path: Path) -> dict:
    try:
        fm = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"EH-1: {path}: YAML parse failed: {e}") from e
    missing = _REQUIRED_FRONTMATTER - set(fm.keys())
    if missing:
        raise ValueError(
            f"EH-1: {path}: missing required frontmatter fields: {sorted(missing)}"
        )
    if fm["status"] not in _VALID_STATUS:
        raise ValueError(
            f"EH-1: {path}: status='{fm['status']}' not in {_VALID_STATUS}"
        )
    return fm


def _split_sections(body: str, path: Path) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in body.splitlines():
        if line.startswith("# "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = line.rstrip()
            buf = []
        else:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    missing = [s for s in _REQUIRED_SECTIONS if s not in sections]
    if missing:
        raise ValueError(
            f"EH-2: {path}: missing sections: {missing}"
        )
    return sections


def _parse_pulid_weight(value) -> float | None:
    """Optional pulid_weight: None / absent → None; else float in [0.0, 3.0].

    Raises ValueError early (at plan-load) on non-numeric or out-of-range
    input so the failure does not surface at DGX submission time.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"pulid_weight must be numeric, got {value!r}") from e
    if not (_PULID_WEIGHT_MIN <= v <= _PULID_WEIGHT_MAX):
        raise ValueError(
            f"pulid_weight {v} out of range "
            f"[{_PULID_WEIGHT_MIN}, {_PULID_WEIGHT_MAX}]"
        )
    return v


def _build_plan(fm: dict, sections: dict[str, str], path: Path) -> Plan:
    style = sections["# Style anchor"]
    out_block = sections["# Output"]
    items = _parse_items_table(sections["# Items"], path)
    # Design Dimensions section is optional (BC-1).
    dimensions_text = sections.get(_DESIGN_DIMENSIONS_HEADER)
    if dimensions_text and dimensions_text.strip():
        layer_b, layer_c, layer_a = _parse_design_dimensions(
            dimensions_text, items, path
        )
    else:
        layer_b, layer_c, layer_a = (None, None, None)
    # BC-S1/S2/S3 (Plan Y v1.2): parse mode + size_aspect + character_consistency.
    mode = _parse_enum(fm.get("mode"), MODE_ENUM, "mode", path)
    size_aspect = _parse_enum(
        fm.get("size_aspect"), SIZE_ASPECT_ENUM, "size_aspect", path,
        none_passthrough=True,
    )
    character_consistency = _parse_enum(
        fm.get("character_consistency"), CHARACTER_CONSISTENCY_ENUM,
        "character_consistency", path,
    )
    # BC-S5 (Plan Y v1.2): size_aspect is SSoT; warn + override on size mismatch.
    declared_size = list(fm["size"])
    if size_aspect is not None:
        expected = list(SIZE_ASPECT_TO_SIZE[size_aspect])
        if declared_size != expected:
            sys.stdout.write(
                f"WARN: {path}: size_aspect={size_aspect!r} implies size={expected}, "
                f"got size={declared_size}; using size_aspect-derived size\n"
            )
            declared_size = expected
    # BC-B4 (Plan Y v1.2): style anchor _zh extraction (None when absent).
    style_zh = {
        k: _extract_style_field(style, f"{k.capitalize()}_zh", None)
        for k in ("prefix", "suffix", "negative")
    }
    return Plan(
        id=fm["id"],
        title=fm["title"],
        version=int(fm["version"]),
        created=str(fm["created"]),
        updated=str(fm["updated"]),
        status=fm["status"],
        workflow=fm["workflow"],
        size=declared_size,
        steps=int(fm["steps"]),
        batch_per_item=int(fm["batch_per_item"]),
        seed_strategy=dict(fm["seed_strategy"]),
        lora=list(fm.get("lora") or []),
        face_ref=fm.get("face_ref"),
        pulid_weight=_parse_pulid_weight(fm.get("pulid_weight")),
        description=fm.get("description"),
        tags=list(fm.get("tags") or []),
        provenance=fm.get("provenance"),
        promoted=fm.get("promoted"),
        story_vision=sections["# Story / Vision"],
        style_prefix=_extract_style(style, "Prefix"),
        style_suffix=_extract_style(style, "Suffix"),
        style_negative=_extract_style(style, "Negative"),
        style_prefix_zh=style_zh["prefix"],
        style_suffix_zh=style_zh["suffix"],
        style_negative_zh=style_zh["negative"],
        output_dir=_extract_output(out_block, "dir") or "",
        output_naming=_extract_output(out_block, "naming") or "",
        items=items,
        open_notes=sections["# Open notes"],
        layer_b=layer_b,
        layer_c=layer_c,
        layer_a=layer_a,
        mode=mode,
        size_aspect=size_aspect,
        character_consistency=character_consistency,
        transparent_assets=fm.get("transparent_assets"),
    )


def _parse_enum(
    value: Any, enum: tuple[str, ...], field_name: str, path: Path,
    *, none_passthrough: bool = False,
) -> str | None:
    """BC-S1/S2/S3 (Plan Y v1.2): validate enum value.

    None → enum[0] default; none_passthrough=True → None (BC-S2/C2.5 legacy).
    """
    if value is None:
        return None if none_passthrough else enum[0]
    if value not in enum:
        raise ValueError(
            f"EH-S: {path}: plan.{field_name} must be one of {enum}; got {value!r}"
        )
    return value


def _extract_style_field(text: str, key: str, default: str | None) -> str | None:
    """Shared **Key**: value extractor. BC-B4: pass default=None for _zh fields."""
    m = re.search(rf"\*\*{key}\*\*\s*[:：]\s*(.*?)(?=\n\*\*|\Z)", text, re.DOTALL)
    if not m:
        return default
    return m.group(1).strip() or default


def _extract_style(text: str, key: str) -> str:
    return _extract_style_field(text, key, "(none)")  # type: ignore[return-value]


def _extract_output(text: str, key: str) -> str | None:
    m = re.search(rf"^-\s*{key}\s*[:：]\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def _parse_items_table(text: str, path: Path) -> list[Item]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError(
            f"EH-3: {path}: items table has < 2 lines (header + sep required)"
        )
    if not _ITEMS_HEADER_RE.match(lines[0]):
        raise ValueError(
            f"EH-3: {path}: items table header mismatch. expected "
            f"`| # | slug | prompt | full? |`, got `{lines[0]}`"
        )
    if not _TABLE_SEP_RE.match(lines[1]):
        raise ValueError(
            f"EH-3: {path}: items table separator missing (line 2 of table)"
        )
    items: list[Item] = []
    for row_idx, line in enumerate(lines[2:], start=3):
        cells = _split_table_row(line, path, row_idx)
        if len(cells) != 4:
            raise ValueError(
                f"EH-3: {path}: items row {row_idx} expected 4 columns, got "
                f"{len(cells)}: `{line}`"
            )
        slug = cells[1].strip()
        prompt = cells[2].strip()
        full_raw = cells[3].strip().lower()
        if not re.fullmatch(r"[a-z0-9_]+", slug):
            raise ValueError(
                f"EH-3: {path}: slug `{slug}` (row {row_idx}) must match "
                f"[a-z0-9_]+"
            )
        if not prompt:
            raise ValueError(
                f"EH-3: {path}: prompt empty (row {row_idx})"
            )
        if "\n" in prompt:
            raise ValueError(
                f"EH-3: {path}: prompt contains newline (row {row_idx})"
            )
        # restore escaped `\|` → `|` (BC-18)
        prompt = prompt.replace(r"\|", "|")
        full = full_raw in {"✓", "yes", "y"}
        items.append(Item(slug=slug, prompt=prompt, full=full))
    return items


def _split_table_row(line: str, path: Path, row_idx: int) -> list[str]:
    # Strip leading/trailing `|`, then split by `|` (but not `\|`).
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        raise ValueError(
            f"EH-3: {path}: row {row_idx} not surrounded by `|`"
        )
    s = s[1:-1]
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            buf.append("\\|")
            i += 2
        elif ch == "|":
            parts.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(ch)
            i += 1
    parts.append("".join(buf))
    return parts


def _plan_to_frontmatter(plan: Plan) -> dict[str, Any]:
    # Required + always-present optional fields (lora / face_ref kept for
    # schema stability even when empty/None).
    d: dict[str, Any] = {
        "id": plan.id,
        "title": plan.title,
        "version": plan.version,
        "created": plan.created,
        "updated": plan.updated,
        "status": plan.status,
        "workflow": plan.workflow,
        "size": plan.size,
        "steps": plan.steps,
        "batch_per_item": plan.batch_per_item,
        "seed_strategy": plan.seed_strategy,
        "lora": plan.lora,
        "face_ref": plan.face_ref,
    }
    # Conditional optional fields (omitted from YAML when unset).
    optional = {
        "pulid_weight": plan.pulid_weight,
        "description": plan.description,
        "tags": plan.tags or None,
        "provenance": plan.provenance,
        "promoted": plan.promoted,
        "transparent_assets": plan.transparent_assets,  # M-3: round-trip（None 時略過）
    }
    for key, value in optional.items():
        if value is not None:
            d[key] = value
    # Plan Y v1.2 (BC-S1/S2/S3): mode + character_consistency always emitted
    # for round-trip; size_aspect only when non-None (BC-C2.5 legacy preset).
    d["mode"] = plan.mode
    if plan.size_aspect is not None:
        d["size_aspect"] = plan.size_aspect
    d["character_consistency"] = plan.character_consistency
    return d


def _plan_to_body(plan: Plan) -> str:
    # Design Dimensions section is optional (BC-2): only emit when any layer
    # has meaningful content. "All-None / all-unspecified" → omit (BC-3b).
    dimensions_section = _design_dimensions_to_body(plan)
    lines = [
        "# Story / Vision",
        plan.story_vision or "(empty)",
        "",
    ]
    if dimensions_section:
        lines.extend([dimensions_section, ""])
    # BC-B4 (Plan Y v1.2): style anchor with optional _zh companions.
    lines.append("# Style anchor")
    for label, val, val_zh in (
        ("Prefix", plan.style_prefix, plan.style_prefix_zh),
        ("Suffix", plan.style_suffix, plan.style_suffix_zh),
        ("Negative", plan.style_negative, plan.style_negative_zh),
    ):
        lines.append(f"**{label}**: {val}")
        if val_zh is not None:
            lines.append(f"**{label}_zh**: {val_zh}")
    lines.extend([
        "",
        "# Output",
        f"- dir: {plan.output_dir}",
        f"- naming: {plan.output_naming}",
        "",
        "# Items",
        "| # | slug | prompt | full? |",
        "|---|------|--------|-------|",
    ])
    for i, item in enumerate(plan.items, start=1):
        prompt_esc = item.prompt.replace("|", r"\|")
        full_mark = "✓" if item.full else ""
        lines.append(f"| {i} | {item.slug} | {prompt_esc} | {full_mark} |")
    lines.extend([
        "",
        "# Open notes",
        plan.open_notes or "(empty)",
    ])
    return "\n".join(lines) + "\n"


# ---------- Design Dimensions: parse / serialize ----------


def _parse_design_dimensions(
    text: str, items: list[Item], path: Path
) -> tuple[LayerB | None, LayerC | None, LayerA | None]:
    """Parse `# Design Dimensions` section → (LayerB, LayerC, LayerA).

    Also applies per_item_beats (Plan Y v1.2 Layer D, BC-D2/D5) to `items`
    in place. Accepts bare YAML or ```yaml fence. Missing layer key → None.
    Missing Layer A dim → default Dimension(None, "unspecified") (BC-4).
    """
    yaml_text = _strip_yaml_fence(text)
    try:
        data = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as e:
        raise ValueError(
            f"EH-1: {path}: Design Dimensions YAML parse failed: {e}"
        ) from e
    if not isinstance(data, dict):
        raise ValueError(
            f"EH-1: {path}: Design Dimensions must be a YAML mapping, "
            f"got {type(data).__name__}"
        )
    layer_b = _layer_b_from_dict(data.get(_DD_KEY_LAYER_B), path)
    layer_c = _layer_c_from_dict(data.get(_DD_KEY_LAYER_C), path)
    layer_a = _layer_a_from_dict(data.get(_DD_KEY_LAYER_A), path)
    # BC-D2 (Plan Y v1.2): apply per_item_beats to items.
    _apply_per_item_beats(data.get(_DD_KEY_PER_ITEM_BEATS), items, path)
    return layer_b, layer_c, layer_a


def _apply_per_item_beats(data: Any, items: list[Item], path: Path) -> None:
    """BC-D2/D5 + EH-D1/D2 (Plan Y v1.2): Apply per_item_beats to items in place.

    None → no-op (BC-D4 legacy compat). Unknown slug → EH-D1. Non-mapping
    entry → EH-D2. Item without entry → beat_description stays None (BC-D5).
    """
    if data is None:
        return
    data = _require_mapping(data, _DD_KEY_PER_ITEM_BEATS, path)
    items_by_slug = {item.slug: item for item in items}
    for slug, entry in data.items():
        if slug not in items_by_slug:
            raise ValueError(
                f"EH-D1: {path}: per_item_beats has unknown slug: {slug!r}; "
                f"valid slugs: {sorted(items_by_slug.keys())}"
            )
        if not isinstance(entry, dict):
            raise ValueError(
                f"EH-D2: {path}: per_item_beats[{slug!r}] must be a mapping, "
                f"got {type(entry).__name__}"
            )
        item = items_by_slug[slug]
        desc = entry.get("description")
        if desc is not None:
            item.beat_description = str(desc)
        desc_zh = entry.get("description_zh")
        if desc_zh is not None:
            if not isinstance(desc_zh, str):
                raise ValueError(
                    f"EH-D2: {path}: per_item_beats[{slug!r}].description_zh "
                    f"must be string, got {type(desc_zh).__name__}"
                )
            item.beat_description_zh = desc_zh


def _per_item_beats_to_dict(items: list[Item]) -> dict[str, dict[str, str]] | None:
    """BC-D3 (Plan Y v1.2): Build per_item_beats YAML block; None if all empty."""
    out: dict[str, dict[str, str]] = {}
    for item in items:
        entry = {
            k: v for k, v in (
                ("description", item.beat_description),
                ("description_zh", item.beat_description_zh),
            ) if v is not None
        }
        if entry:
            out[item.slug] = entry
    return out or None


def _strip_yaml_fence(text: str) -> str:
    """Strip ```yaml ... ``` (or generic ```) fence if present."""
    s = text.strip()
    if not s.startswith("```"):
        return text
    lines = s.splitlines()
    if len(lines) < 2 or lines[-1].strip() != "```":
        return text
    return "\n".join(lines[1:-1])


def _require_mapping(data: Any, label: str, path: Path) -> dict:
    """Shared guard: None passes through (caller returns None); non-dict raises EH-1."""
    if not isinstance(data, dict):
        raise ValueError(
            f"EH-1: {path}: {label} must be a mapping, "
            f"got {type(data).__name__}"
        )
    return data


def _layer_b_from_dict(data: Any, path: Path) -> LayerB | None:
    if data is None:
        return None
    data = _require_mapping(data, _DD_KEY_LAYER_B, path)
    grouping_axis = data.get("grouping_axis", "")
    if not grouping_axis:
        # R-3 fix: grouping_axis is required when season_structure is present.
        raise ValueError(
            f"EH-3: {path}: grouping_axis is required for "
            f"{_DD_KEY_LAYER_B}, must be one of {sorted(_GROUPING_AXIS_VALUES)}"
        )
    if grouping_axis not in _GROUPING_AXIS_VALUES:
        raise ValueError(
            f"EH-3: {path}: grouping_axis must be one of "
            f"{sorted(_GROUPING_AXIS_VALUES)}, got {grouping_axis!r}"
        )
    return LayerB(
        theme=str(data.get("theme", "")),
        grouping_axis=str(grouping_axis),
        groups=dict(data.get("groups") or {}),
        cross_group_progression=data.get("cross_group_progression"),
        character_continuity=data.get("character_continuity"),
        acceptance=data.get("acceptance"),
    )


def _layer_c_from_dict(data: Any, path: Path) -> LayerC | None:
    if data is None:
        return None
    data = _require_mapping(data, _DD_KEY_LAYER_C, path)
    return LayerC(
        character_seed=str(data.get("character_seed", "")),
        group_arc=dict(data.get("group_arc") or {}),
        emotion_palette=data.get("emotion_palette"),
    )


def _layer_a_from_dict(data: Any, path: Path) -> LayerA | None:
    if data is None:
        return None
    data = _require_mapping(data, _DD_KEY_LAYER_A, path)
    # EH-2b: reject unknown dim keys.
    unknown = set(data.keys()) - set(_LAYER_A_DIMENSION_NAMES)
    if unknown:
        raise ValueError(
            f"EH-2b: {path}: unknown dimension(s) {sorted(unknown)}, "
            f"expected one of {list(_LAYER_A_DIMENSION_NAMES)}"
        )
    dims = {
        name: _dimension_from_dict(name, data.get(name), path)
        for name in _LAYER_A_DIMENSION_NAMES
    }
    return LayerA(**dims)


def _dimension_from_dict(name: str, data: Any, path: Path) -> Dimension:
    """Missing dim → default unspecified (BC-4)."""
    if data is None:
        return Dimension(value=None, scope="unspecified")
    data = _require_mapping(data, f"dimension {name}", path)
    has_scope = "scope" in data
    scope = data.get("scope", "unspecified")
    if scope not in _SCOPE_VALUES:
        raise ValueError(
            f"EH-2: {path}: dimension {name} has invalid scope {scope!r}, "
            f"expected one of {sorted(_SCOPE_VALUES)}"
        )
    value = data.get("value")
    # R-6 fix: setting value without explicit scope is ambiguous (user might
    # mean "locked" but get silent "unspecified" default which discards value).
    if value is not None and not has_scope:
        raise ValueError(
            f"EH-2: {path}: dimension {name} has value={value!r} but no "
            f"explicit `scope` key — scope must be specified explicitly when "
            f"value is set"
        )
    # R-4 fix: normalize — scope=unspecified can never carry a meaningful value.
    if scope == "unspecified":
        value = None
    # BC-B1 + EH-B1 (Plan Y v1.2): optional value_zh with type check.
    value_zh = data.get("value_zh")
    if value_zh is not None and not isinstance(value_zh, str):
        raise ValueError(
            f"EH-B1: {path}: Dimension.{name}.value_zh must be string, "
            f"got {type(value_zh).__name__}"
        )
    return Dimension(
        value=str(value) if value is not None else None,
        scope=scope, value_zh=value_zh,
    )


def _design_dimensions_to_body(plan: Plan) -> str:
    """Serialize layer_b/c/a → `# Design Dimensions` section.

    Returns "" when all three layers are effectively empty (BC-3b normalize):
    layer_b/c are None and layer_a is None or all dimensions unspecified.
    """
    per_item_beats = _per_item_beats_to_dict(plan.items)
    if _all_layers_empty(plan) and per_item_beats is None:
        return ""
    body: dict[str, Any] = {}
    if plan.layer_b is not None:
        body[_DD_KEY_LAYER_B] = _layer_b_to_dict(plan.layer_b)
    if plan.layer_c is not None:
        body[_DD_KEY_LAYER_C] = _layer_c_to_dict(plan.layer_c)
    if plan.layer_a is not None and not layer_a_is_empty(plan.layer_a):
        body[_DD_KEY_LAYER_A] = _layer_a_to_dict(plan.layer_a)
    # BC-D3 (Plan Y v1.2): emit per_item_beats block if any item has beat.
    if per_item_beats is not None:
        body[_DD_KEY_PER_ITEM_BEATS] = per_item_beats
    yaml_text = yaml.safe_dump(body, allow_unicode=True, sort_keys=False)
    return f"{_DESIGN_DIMENSIONS_HEADER}\n\n```yaml\n{yaml_text}```"


def _all_layers_empty(plan: Plan) -> bool:
    """True iff layer_b/c are None and layer_a is None-or-all-unspecified."""
    if plan.layer_b is not None or plan.layer_c is not None:
        return False
    return plan.layer_a is None or layer_a_is_empty(plan.layer_a)


def layer_a_is_empty(la: LayerA) -> bool:
    """True if all 9 dimensions are scope=unspecified."""
    return all(
        getattr(la, name).scope == "unspecified"
        for name in _LAYER_A_DIMENSION_NAMES
    )


def _layer_b_to_dict(lb: LayerB) -> dict[str, Any]:
    d: dict[str, Any] = {
        "theme": lb.theme,
        "grouping_axis": lb.grouping_axis,
        "groups": lb.groups,
    }
    for k in ("cross_group_progression", "character_continuity", "acceptance"):
        v = getattr(lb, k)
        if v is not None:
            d[k] = v
    return d


def _layer_c_to_dict(lc: LayerC) -> dict[str, Any]:
    d: dict[str, Any] = {"character_seed": lc.character_seed, "group_arc": lc.group_arc}
    if lc.emotion_palette is not None:
        d["emotion_palette"] = lc.emotion_palette
    return d


def _layer_a_to_dict(la: LayerA) -> dict[str, Any]:
    """Serialize Layer A. R-4: skip dims with scope=unspecified.
    BC-B2 (Plan Y v1.2): emit value / value_zh only when non-None."""
    out: dict[str, Any] = {}
    for name in _LAYER_A_DIMENSION_NAMES:
        dim: Dimension = getattr(la, name)
        if dim.scope == "unspecified":
            continue
        entry: dict[str, Any] = {"scope": dim.scope}
        if dim.value is not None:
            entry["value"] = dim.value
        if dim.value_zh is not None:
            entry["value_zh"] = dim.value_zh
        out[name] = entry
    return out
