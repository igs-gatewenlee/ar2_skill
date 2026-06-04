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
# Plan Y v1.3 — panel_taxonomy + cast YAML keys inside Design Dimensions
# (BC-G3-5 / BC-G4-5、與既有 DD key 並列).
_DD_KEY_PANEL_TAXONOMY = "panel_taxonomy"
_DD_KEY_CAST = "cast"

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
SCHEMA_VERSION = "1.4.0"  # 1.4.0: Plan Y v1.3（panel_taxonomy / cast / plan_quality + 7 Item 新欄位）
# 1.3.0: 新增 transparent_assets（透明素材 route/asset_type block）

# ─── Plan Y v1.3 — module-level SSoT constants（#009 prevention 延續 BC-S0 精神）───
# BC-G5-1: narrative event_type enum（per_item_beats entry 可選欄位）。
EVENT_TYPE_ENUM = ("action", "dialogue", "discovery", "transition", "mood")
# BC-G4-1: cast entry type enum（default human）。
CAST_TYPE_ENUM = ("human", "creature", "object")
# BC-G3-2 (DR-R3-5): panel_type / panel_taxonomy key 規範 — 採 validate_id docstring
# 規範（首字符限 [a-z]、收緊），**不複用 _ID_PATTERN**（後者允許數字開頭）。
_PANEL_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# BC-G3-2: panel_type reserved keys（禁用作自訂名）。
_PANEL_TYPE_RESERVED = frozenset({"default", "__fallback__"})
# EH-G3-2: panel_taxonomy entry 允許的 key 白名單。
_PANEL_TAXONOMY_ALLOWED_KEYS = frozenset({"workflow", "pulid", "beat_prefix", "beat_suffix"})
# BC-G2-1: pulid override（item / panel_taxonomy）允許的 key。
_PULID_OVERRIDE_ALLOWED_KEYS = frozenset({"enabled", "strength", "face_ref"})
# EH-G4-4 (DR-R2-5, evidence_level: empirical, tunable): cast visual 字符 budget。
# 來源：reviewer round 2 推算（IF-G2 上限 2000 - locked/beat/per_group 平均 ≈ 1500
# cast budget）、非 ground-truthed。實戰過嚴/過鬆改此常數即可（無 schema 變更）。
_CAST_VISUAL_BUDGET_SINGLE = 500      # 單一 cast.X.visual.Y string 上限
_CAST_VISUAL_BUDGET_PER_ENTRY = 800   # 單一 cast entry 全部 visual keys 加總上限
_CAST_VISUAL_BUDGET_PER_PLAN = 1500   # 整 plan cast prepend 累加上限（derive 端用）
# BC-G5-3 (DR-8): plan_quality.event_density_warning 預設與範圍。
_EVENT_DENSITY_WARNING_DEFAULT = 0.7
_CAST_IN_PANEL_WARNING_DEFAULT = True


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
class PanelTypeConfig:
    """Plan Y v1.3 — panel_taxonomy entry (BC-G3-1).

    User-defined panel type → dispatch config (workflow / pulid / beat
    templates). All fields optional; absent → that dimension falls through to
    plan-level default (BC-G3-4 Layer 2).
    """
    workflow: str | None = None
    pulid: dict | None = None  # {enabled: bool, strength: float, face_ref: str}
    beat_prefix: str | None = None  # BC-G6-1 (storyboard only)
    beat_suffix: str | None = None


@dataclass
class CastEntry:
    """Plan Y v1.3 — multi-character cast entry (BC-G4-1)."""
    name: str
    type: str = "human"  # CAST_TYPE_ENUM: human | creature | object
    # free-key visual dict, 慣例 hair / outfit / build / accessory / color / size / features
    visual: dict = field(default_factory=dict)


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
    # ─── Plan Y v1.3 新增（皆 optional、缺值 → fallback、BC-G0-2）───
    panel_type: str | None = None              # BC-G3-3 (dispatch 入口)
    workflow_override: str | None = None       # BC-G1-1
    pulid_override: dict | None = None         # BC-G2-1 {enabled, strength, face_ref}
    cast_in_panel: list[str] = field(default_factory=list)  # BC-G4-2
    event_type: str | None = None              # BC-G5-1
    event_description: str | None = None       # BC-G5-2
    use_template: bool = True                  # BC-G6-3 (beat template opt-out)


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
    # ─── Plan Y v1.3 新增（皆 optional、None 表示無、BC-G0-2/3）───
    panel_taxonomy: dict[str, PanelTypeConfig] | None = None  # BC-G3-1 (Design Dimensions key)
    cast: dict[str, CastEntry] | None = None                 # BC-G4-1 (Design Dimensions key)
    plan_quality: dict | None = None  # BC-G5-3 frontmatter {event_density_warning, cast_in_panel_warning}


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
        layer_b, layer_c, layer_a, panel_taxonomy, cast = _parse_design_dimensions(
            dimensions_text, items, path
        )
    else:
        layer_b, layer_c, layer_a, panel_taxonomy, cast = (None, None, None, None, None)
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
        panel_taxonomy=panel_taxonomy,
        cast=cast,
        plan_quality=_parse_plan_quality(fm.get("plan_quality"), path),
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
        "plan_quality": plan.plan_quality,  # BC-G5-3 (None 時略過、保 v1.2 round-trip)
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
) -> tuple[
    LayerB | None, LayerC | None, LayerA | None,
    dict[str, PanelTypeConfig] | None, dict[str, CastEntry] | None,
]:
    """Parse `# Design Dimensions` → (LayerB, LayerC, LayerA, panel_taxonomy, cast).

    Also applies per_item_beats (Plan Y v1.2 Layer D, BC-D2/D5 + v1.3 per-item
    fields) to `items` in place. Accepts bare YAML or ```yaml fence. Missing
    layer key → None. Missing Layer A dim → default Dimension(None, "unspecified").

    Plan Y v1.3: panel_taxonomy / cast parsed BEFORE per_item_beats so the
    latter can validate cast_in_panel references (EH-G4-1).
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
    # Plan Y v1.3: panel_taxonomy (BC-G3-5) + cast (BC-G4-5).
    panel_taxonomy = _panel_taxonomy_from_dict(data.get(_DD_KEY_PANEL_TAXONOMY), path)
    cast = _cast_from_dict(data.get(_DD_KEY_CAST), path)
    # BC-D2 (Plan Y v1.2) + Plan Y v1.3 per-item fields: apply per_item_beats.
    _apply_per_item_beats(data.get(_DD_KEY_PER_ITEM_BEATS), items, cast, path)
    return layer_b, layer_c, layer_a, panel_taxonomy, cast


def _apply_per_item_beats(
    data: Any, items: list[Item],
    cast: dict[str, CastEntry] | None, path: Path,
) -> None:
    """BC-D2/D5 + EH-D1/D2 (Plan Y v1.2) + Plan Y v1.3 per-item fields.

    None → no-op (BC-D4 legacy compat). Unknown slug → EH-D1. Non-mapping
    entry → EH-D2. Item without entry → all v1.3 fields stay default (BC-G0-2).

    Plan Y v1.3 entry keys (all optional, additive on existing shape):
    panel_type / workflow / pulid / cast_in_panel / event_type /
    event_description / use_template.
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
        _apply_v13_item_fields(item, entry, slug, cast, path)


def _apply_v13_item_fields(
    item: Item, entry: dict, slug: str,
    cast: dict[str, CastEntry] | None, path: Path,
) -> None:
    """Plan Y v1.3: parse + validate per-item dispatch / event / cast fields.

    Mutates `item` in place. All keys optional; absent → field stays default.
    """
    # BC-G3-3: panel_type (regex-validated, EXISTENCE vs taxonomy is a
    # dispatch-time warning EH-G3-1, NOT a parse error).
    panel_type = entry.get("panel_type")
    if panel_type is not None:
        item.panel_type = _validate_panel_type(panel_type, f"{slug}.panel_type", path)
    # BC-G1-1: workflow override.
    workflow = entry.get("workflow")
    if workflow is not None:
        if not isinstance(workflow, str) or not workflow:
            raise ValueError(
                f"EH-3: {path}: per_item_beats[{slug!r}].workflow must be a "
                f"non-empty string, got {workflow!r}"
            )
        item.workflow_override = workflow
    # BC-G2-1: pulid override {enabled, strength, face_ref} (partial-override OK).
    pulid = entry.get("pulid")
    if pulid is not None:
        item.pulid_override = _validate_pulid_override(
            pulid, f"per_item_beats[{slug!r}].pulid", path
        )
    # BC-G4-2: cast_in_panel list[str] → validate refs against cast (EH-G4-1).
    cast_in_panel = entry.get("cast_in_panel")
    if cast_in_panel is not None:
        item.cast_in_panel = _validate_cast_in_panel(cast_in_panel, slug, cast, path)
    # BC-G5-1/2 + EH-G5-1/2/3: event_type / event_description.
    _apply_event_fields(item, entry, slug, path)
    # BC-G6-3: use_template (default True).
    use_template = entry.get("use_template")
    if use_template is not None:
        if not isinstance(use_template, bool):
            raise ValueError(
                f"EH-3: {path}: per_item_beats[{slug!r}].use_template must be "
                f"bool, got {type(use_template).__name__}"
            )
        item.use_template = use_template


def _apply_event_fields(item: Item, entry: dict, slug: str, path: Path) -> None:
    """BC-G5-1/2 + EH-G5-1/2/3: parse + validate event_type / event_description.

    Both互相 optional (BC-G5-5): both absent → no-op; one present → other
    required (EH-G5-2). event_type enum-checked (EH-G5-1); description ≥ 10
    chars (EH-G5-3).
    """
    event_type = entry.get("event_type")
    event_description = entry.get("event_description")
    if event_type is None and event_description is None:
        return
    if event_type is None or event_description is None:
        raise ValueError(
            f"EH-G5-2: {path}: item {slug!r} event_type 與 event_description "
            f"必須同時存在或同時缺（got event_type={event_type!r}, "
            f"event_description={event_description!r}）"
        )
    if event_type not in EVENT_TYPE_ENUM:
        raise ValueError(
            f"EH-G5-1: {path}: item {slug!r} event_type 必為 {EVENT_TYPE_ENUM}，"
            f"got {event_type!r}"
        )
    if not isinstance(event_description, str):
        raise ValueError(
            f"EH-G5-2: {path}: item {slug!r} event_description must be string, "
            f"got {type(event_description).__name__}"
        )
    if len(event_description) < 10:
        raise ValueError(
            f"EH-G5-3: {path}: item {slug!r} event_description 至少 10 字元"
            f"（got {len(event_description)}）"
        )
    item.event_type = event_type
    item.event_description = event_description


# ---------- Plan Y v1.3: shared input-side validators ----------


def _has_unescaped_pipe(s: str) -> bool:
    """True if `s` contains a `|` not preceded by `\\`.

    Local copy (parse-side input validation); prompt_derive has the derive-side
    twin. plan_schema cannot import prompt_derive (would be circular — derive
    imports schema). Both enforce the same IF-G2 / BC-18 boundary.
    """
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            i += 2
            continue
        if s[i] == "|":
            return True
        i += 1
    return False


def _validate_derive_fragment(value: Any, ctx: str, path: Path, max_len: int) -> str:
    """BC-G4-6 + BC-G6 補充 (IF-G2 前置條件 propagate): a string destined to be
    prepended/appended into a derived prompt must already satisfy the callee
    post-condition (no newline / no unescaped `|` / within budget). Names the
    offending `ctx` so the user can locate it (not a generic 'derive failed').
    """
    if not isinstance(value, str):
        raise ValueError(f"EH: {path}: {ctx} must be a string, got {type(value).__name__}")
    if "\n" in value:
        raise ValueError(f"EH: {path}: {ctx} 含換行（newline 禁止）")
    if _has_unescaped_pipe(value):
        raise ValueError(f"EH: {path}: {ctx} 含未跳脫的 `|`（需 `\\|`）")
    if len(value) > max_len:
        raise ValueError(f"EH: {path}: {ctx} 過長（{len(value)} chars > {max_len}）")
    return value


def _validate_panel_type(value: Any, ctx: str, path: Path) -> str:
    """BC-G3-2 (DR-R3-5): panel_type / panel_taxonomy key regex + reserved guard."""
    if not isinstance(value, str):
        raise ValueError(f"EH: {path}: {ctx} must be a string, got {type(value).__name__}")
    if value in _PANEL_TYPE_RESERVED:
        raise ValueError(
            f"EH: {path}: {ctx}={value!r} 為保留字，不可作 panel_type 名稱"
            f"（reserved: {sorted(_PANEL_TYPE_RESERVED)}）"
        )
    if not _PANEL_TYPE_PATTERN.match(value):
        raise ValueError(
            f"EH: {path}: {ctx}={value!r} 不合法，必須匹配 "
            f"^[a-z][a-z0-9_]{{0,63}}$（首字符限 [a-z]、≤ 64 chars）"
        )
    return value


def _validate_pulid_override(value: Any, ctx: str, path: Path) -> dict | None:
    """BC-G2-1/5: pulid override dict {enabled?, strength?, face_ref?} (partial OK).

    Three-state key semantics (dev-review L1/L2): an EXPLICIT `null` value is
    treated as "not provided" (same as an absent key) — the key is skipped so
    the dispatch fallback chain runs (BC-G2-3), rather than short-circuiting to
    None. An empty / all-null override declares nothing → returns None (so the
    item is NOT elevated to v13 dispatch by _item_engages_v13_pulid_dispatch).
    Returns a normalized dict of provided non-null keys, or None. Unknown keys →
    ValueError. strength reuses v1.2 _parse_pulid_weight bounds [0.0, 3.0].
    """
    value = _require_mapping(value, ctx, path)
    unknown = set(value.keys()) - _PULID_OVERRIDE_ALLOWED_KEYS
    if unknown:
        raise ValueError(
            f"EH: {path}: {ctx} unknown key(s) {sorted(unknown)}; "
            f"allowed: {sorted(_PULID_OVERRIDE_ALLOWED_KEYS)}"
        )
    out: dict[str, Any] = {}
    if value.get("enabled") is not None:  # explicit null = not provided
        enabled = value["enabled"]
        if not isinstance(enabled, bool):
            raise ValueError(
                f"EH: {path}: {ctx}.enabled must be bool, got {type(enabled).__name__}"
            )
        out["enabled"] = enabled
    if value.get("strength") is not None:
        # BC-G2-5: reuse v1.2 pulid_weight bounds (raises on non-numeric / OOR).
        out["strength"] = _parse_pulid_weight(value["strength"])
    if value.get("face_ref") is not None:
        face_ref = value["face_ref"]
        if not isinstance(face_ref, str) or not face_ref:
            raise ValueError(
                f"EH: {path}: {ctx}.face_ref must be a non-empty string, got {face_ref!r}"
            )
        out["face_ref"] = face_ref
    return out or None  # empty override → None (no v13 elevation, L1)


def _validate_cast_in_panel(
    value: Any, slug: str, cast: dict[str, CastEntry] | None, path: Path,
) -> list[str]:
    """BC-G4-2 + EH-G4-1: cast_in_panel list[str]; every ref must be a defined
    cast key (caught at plan-stage parse, not surfacing only at derive)."""
    if not isinstance(value, list):
        raise ValueError(
            f"EH: {path}: per_item_beats[{slug!r}].cast_in_panel must be a list, "
            f"got {type(value).__name__}"
        )
    refs: list[str] = []
    known = set(cast.keys()) if cast else set()
    for ref in value:
        if not isinstance(ref, str) or not ref:
            raise ValueError(
                f"EH: {path}: item {slug!r} cast_in_panel entry must be a "
                f"non-empty string, got {ref!r}"
            )
        if ref not in known:
            raise ValueError(
                f"EH-G4-1: {path}: unknown character {ref!r} in cast_in_panel "
                f"of item {slug!r}; defined cast: {sorted(known)}"
            )
        refs.append(ref)
    return refs


# ---------- Plan Y v1.3: panel_taxonomy / cast / plan_quality parsers ----------


def _panel_taxonomy_from_dict(
    data: Any, path: Path,
) -> dict[str, PanelTypeConfig] | None:
    """BC-G3-1/2/5 + EH-G3-2: parse panel_taxonomy mapping → {name: PanelTypeConfig}."""
    if data is None:
        return None
    data = _require_mapping(data, _DD_KEY_PANEL_TAXONOMY, path)
    out: dict[str, PanelTypeConfig] = {}
    for name, cfg in data.items():
        _validate_panel_type(name, f"panel_taxonomy key {name!r}", path)
        cfg = _require_mapping(cfg, f"panel_taxonomy[{name!r}]", path)
        unknown = set(cfg.keys()) - _PANEL_TAXONOMY_ALLOWED_KEYS
        if unknown:
            raise ValueError(
                f"EH-G3-2: {path}: unknown key in panel_taxonomy[{name!r}]: "
                f"{sorted(unknown)}; allowed: {sorted(_PANEL_TAXONOMY_ALLOWED_KEYS)}"
            )
        workflow = cfg.get("workflow")
        if workflow is not None and (not isinstance(workflow, str) or not workflow):
            raise ValueError(
                f"EH-G3-2: {path}: panel_taxonomy[{name!r}].workflow must be a "
                f"non-empty string, got {workflow!r}"
            )
        pulid = cfg.get("pulid")
        if pulid is not None:
            pulid = _validate_pulid_override(
                pulid, f"panel_taxonomy[{name!r}].pulid", path
            )
        beat_prefix = cfg.get("beat_prefix")
        if beat_prefix is not None:
            beat_prefix = _validate_derive_fragment(
                beat_prefix, f"panel_taxonomy[{name!r}].beat_prefix", path,
                _CAST_VISUAL_BUDGET_SINGLE,
            )
        beat_suffix = cfg.get("beat_suffix")
        if beat_suffix is not None:
            beat_suffix = _validate_derive_fragment(
                beat_suffix, f"panel_taxonomy[{name!r}].beat_suffix", path,
                _CAST_VISUAL_BUDGET_SINGLE,
            )
        out[name] = PanelTypeConfig(
            workflow=workflow, pulid=pulid,
            beat_prefix=beat_prefix, beat_suffix=beat_suffix,
        )
    return out


def _cast_from_dict(data: Any, path: Path) -> dict[str, CastEntry] | None:
    """BC-G4-1/5/6 + EH-G4-4: parse cast mapping → {character_id: CastEntry}.

    Input-side budget validation (BC-G4-6 single ≤ 500 chars + EH-G4-4 per-entry
    ≤ 800 chars), naming the offending entry/key. Per-plan ≤ 1500 budget is
    enforced derive-side (cumulative prepend).
    """
    if data is None:
        return None
    data = _require_mapping(data, _DD_KEY_CAST, path)
    out: dict[str, CastEntry] = {}
    for char_id, entry in data.items():
        if not isinstance(char_id, str) or not char_id:
            raise ValueError(
                f"EH: {path}: cast key must be a non-empty string, got {char_id!r}"
            )
        entry = _require_mapping(entry, f"cast[{char_id!r}]", path)
        name = entry.get("name")
        if name is None or not isinstance(name, str) or not name:
            raise ValueError(
                f"EH: {path}: cast[{char_id!r}].name is required and must be a "
                f"non-empty string, got {name!r}"
            )
        ctype = entry.get("type", "human")
        if ctype not in CAST_TYPE_ENUM:
            raise ValueError(
                f"EH: {path}: cast[{char_id!r}].type must be one of {CAST_TYPE_ENUM}, "
                f"got {ctype!r}"
            )
        visual = entry.get("visual") or {}
        visual = _require_mapping(visual, f"cast[{char_id!r}].visual", path)
        norm_visual = _validate_cast_visual(visual, char_id, path)
        out[char_id] = CastEntry(name=name, type=ctype, visual=norm_visual)
    return out


def _validate_cast_visual(visual: dict, char_id: str, path: Path) -> dict[str, str]:
    """BC-G4-6 (single ≤ 500, no newline / unescaped `|`) + EH-G4-4 (per-entry
    sum ≤ 800). Names the offending cast entry + visual key."""
    out: dict[str, str] = {}
    total = 0
    for key, val in visual.items():
        if not isinstance(key, str) or not key:
            raise ValueError(
                f"EH: {path}: cast[{char_id!r}].visual key must be a non-empty "
                f"string, got {key!r}"
            )
        sval = _validate_derive_fragment(
            val, f"cast[{char_id!r}].visual[{key!r}]", path,
            _CAST_VISUAL_BUDGET_SINGLE,
        )
        total += len(sval)
        out[key] = sval
    if total > _CAST_VISUAL_BUDGET_PER_ENTRY:
        raise ValueError(
            f"EH-G4-4: {path}: cast {char_id!r} visual 描述過長（{total} chars > "
            f"{_CAST_VISUAL_BUDGET_PER_ENTRY} budget）、derive 後可能超 2000 chars "
            f"IF-G2 上限"
        )
    return out


def _parse_plan_quality(value: Any, path: Path) -> dict | None:
    """BC-G5-3 + EH-G5-4: plan_quality frontmatter {event_density_warning,
    cast_in_panel_warning}. None → None. Defaults filled; density range [0,1]."""
    if value is None:
        return None
    value = _require_mapping(value, "plan_quality", path)
    unknown = set(value.keys()) - {"event_density_warning", "cast_in_panel_warning"}
    if unknown:
        raise ValueError(
            f"EH: {path}: unknown key in plan_quality: {sorted(unknown)}; "
            f"allowed: event_density_warning, cast_in_panel_warning"
        )
    density = value.get("event_density_warning", _EVENT_DENSITY_WARNING_DEFAULT)
    try:
        density = float(density)
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"EH-G5-4: {path}: event_density_warning must be numeric, got {density!r}"
        ) from e
    if not (0.0 <= density <= 1.0):
        raise ValueError(
            f"EH-G5-4: {path}: event_density_warning 必須在 0.0-1.0 範圍、got {density}"
        )
    cast_warning = value.get("cast_in_panel_warning", _CAST_IN_PANEL_WARNING_DEFAULT)
    if not isinstance(cast_warning, bool):
        raise ValueError(
            f"EH: {path}: cast_in_panel_warning must be bool, "
            f"got {type(cast_warning).__name__}"
        )
    return {
        "event_density_warning": density,
        "cast_in_panel_warning": cast_warning,
    }


# ---------- Plan Y v1.3: DR-4 shared dispatch helper (#009 / DRY SSoT) ----------

# The ONLY place caller-side dispatch resolution may read raw item /
# panel_taxonomy / plan-level fields. plan_loader (gen) + plan_main --validate
# both go through these — no other caller accesses item.workflow_override /
# panel_taxonomy[...].X directly (DR-4 P2 hard requirement; Phase 3 grep gate).

_DISPATCH_DIMS = (
    "workflow", "pulid.enabled", "pulid.strength", "pulid.face_ref",
    "beat_prefix", "beat_suffix",
)


def _pulid_enabled_from_consistency(character_consistency: str) -> bool:
    """BC-G2-3: derive pulid_enabled from plan.character_consistency.

    CHARACTER_CONSISTENCY_ENUM = (prompt_only, pulid_face_ref, both).
    pulid_face_ref / both → True; prompt_only → False.
    """
    return character_consistency in ("pulid_face_ref", "both")


def _dispatch_candidates(plan: Plan, item: Item, dim_name: str) -> list[tuple[str, Any]]:
    """Ordered (source_layer, value) candidates for `dim_name`, non-None only.

    Layers in precedence order: item → panel_type → plan_level (BC-G3-4).
    The single home for raw dispatch field access (DR-4). Callers must use
    _resolve_per_item_config / _dispatch_double_written, never raw access.
    """
    if dim_name not in _DISPATCH_DIMS:
        raise ValueError(f"_dispatch_candidates: unknown dim {dim_name!r}")
    pt_cfg = None
    if item.panel_type and plan.panel_taxonomy:
        pt_cfg = plan.panel_taxonomy.get(item.panel_type)
    cands: list[tuple[str, Any]] = []

    if dim_name == "workflow":
        if item.workflow_override is not None:
            cands.append(("item", item.workflow_override))
        if pt_cfg is not None and pt_cfg.workflow is not None:
            cands.append(("panel_type", pt_cfg.workflow))
        cands.append(("plan_level", plan.workflow))  # always present
    elif dim_name.startswith("pulid."):
        key = dim_name.split(".", 1)[1]  # enabled | strength | face_ref
        if item.pulid_override is not None and key in item.pulid_override:
            cands.append(("item", item.pulid_override[key]))
        if pt_cfg is not None and pt_cfg.pulid is not None and key in pt_cfg.pulid:
            cands.append(("panel_type", pt_cfg.pulid[key]))
        if key == "enabled":
            cands.append((
                "plan_level",
                _pulid_enabled_from_consistency(plan.character_consistency),
            ))
        elif key == "strength":
            if plan.pulid_weight is not None:
                cands.append(("plan_level", plan.pulid_weight))
        elif key == "face_ref":
            if plan.face_ref is not None:
                cands.append(("plan_level", plan.face_ref))
    elif dim_name in ("beat_prefix", "beat_suffix"):
        if pt_cfg is not None:
            val = getattr(pt_cfg, dim_name)
            if val is not None:
                cands.append(("panel_type", val))
    return cands


# Dimension defaults applied when no layer supplies a value (source="default").
_DISPATCH_DEFAULTS: dict[str, Any] = {
    "workflow": None, "pulid.enabled": False, "pulid.strength": 1.0,
    "pulid.face_ref": None, "beat_prefix": None, "beat_suffix": None,
}


def _resolve_per_item_config(
    plan: Plan, item: Item, dim_name: str,
) -> tuple[Any, str]:
    """DR-4 P2 hard requirement: single shared 3-layer dispatch resolver.

    Returns (effective_value, source_layer) where source_layer ∈
    {"item", "panel_type", "plan_level", "default"}. source_layer feeds
    plan_main --validate C2 double-write detection without re-implementing the
    fallback chain. Note: BC-G2-3 conditional gating (enabled=false → strength /
    face_ref forced None) is applied by the CALLER, not here — this resolves one
    dimension's raw 3-layer fallback in isolation.
    """
    cands = _dispatch_candidates(plan, item, dim_name)
    if cands:
        source_layer, value = cands[0]
        return value, source_layer
    return _DISPATCH_DEFAULTS[dim_name], "default"


def _item_engages_v13_pulid_dispatch(plan: Plan, item: Item) -> bool:
    """True iff the item OR its panel_type EXPLICITLY declares v1.3 pulid /
    workflow dispatch intent (item.pulid_override / item.workflow_override, or a
    panel_taxonomy entry supplying workflow / pulid).

    BC-G0 reconciliation (Phase 2 implementer decision — ground-truthed):
    when False, gen-side preserves EXACT v1.2 behavior (plan-level pulid_weight
    + face_ref passed straight to inject, NO BC-G2-7 force-None, NO EH-G1-2
    gate). Reason: legacy flux_pulid plans (e.g. preset cards_a11c) set face_ref
    but leave character_consistency at its prompt_only default; deriving
    pulid_enabled=false from that default + EH-G1-2 would reject the workflow
    and break a working production plan — violating BC-G0-1 byte-equivalence.
    The per-item PuLID toggle + EH-G1-2 gate (BC-G2-3/6/7) still apply in full
    whenever the user opts in via an item/panel_type declaration.

    Raw panel_taxonomy access stays here in the helper module (DR-4 SSoT)."""
    if item.workflow_override is not None or item.pulid_override is not None:
        return True
    if item.panel_type and plan.panel_taxonomy:
        pt = plan.panel_taxonomy.get(item.panel_type)
        if pt is not None and (pt.workflow is not None or pt.pulid is not None):
            return True
    return False


def _dispatch_double_written(plan: Plan, item: Item, dim_name: str) -> bool:
    """BC-G5-4 C2: True iff both the item layer AND the panel_type layer supply
    a value for `dim_name` (用 item 為準 per BC-G3-4 Layer 1). Built on the same
    _dispatch_candidates SSoT — no separate判斷邏輯 (DR-R2-7)."""
    layers = {layer for layer, _ in _dispatch_candidates(plan, item, dim_name)}
    return "item" in layers and "panel_type" in layers


def _per_item_beats_to_dict(items: list[Item]) -> dict[str, dict[str, Any]] | None:
    """BC-D3 (Plan Y v1.2) + Plan Y v1.3 per-item fields: build per_item_beats
    YAML block; None if all empty. BC-G0-5: v1.3 fields emitted only when
    non-default (so v1.2 outlines round-trip byte-equivalent)."""
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        entry: dict[str, Any] = {}
        if item.beat_description is not None:
            entry["description"] = item.beat_description
        if item.beat_description_zh is not None:
            entry["description_zh"] = item.beat_description_zh
        # Plan Y v1.3 (additive; only when non-default).
        if item.panel_type is not None:
            entry["panel_type"] = item.panel_type
        if item.workflow_override is not None:
            entry["workflow"] = item.workflow_override
        if item.pulid_override:
            entry["pulid"] = dict(item.pulid_override)
        if item.cast_in_panel:
            entry["cast_in_panel"] = list(item.cast_in_panel)
        if item.event_type is not None:
            entry["event_type"] = item.event_type
        if item.event_description is not None:
            entry["event_description"] = item.event_description
        if item.use_template is not True:  # default True → omit
            entry["use_template"] = item.use_template
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
    if (
        _all_layers_empty(plan) and per_item_beats is None
        and plan.panel_taxonomy is None and plan.cast is None
    ):
        return ""
    body: dict[str, Any] = {}
    if plan.layer_b is not None:
        body[_DD_KEY_LAYER_B] = _layer_b_to_dict(plan.layer_b)
    if plan.layer_c is not None:
        body[_DD_KEY_LAYER_C] = _layer_c_to_dict(plan.layer_c)
    if plan.layer_a is not None and not layer_a_is_empty(plan.layer_a):
        body[_DD_KEY_LAYER_A] = _layer_a_to_dict(plan.layer_a)
    # Plan Y v1.3: panel_taxonomy (BC-G3-5) + cast (BC-G4-5).
    if plan.panel_taxonomy is not None:
        body[_DD_KEY_PANEL_TAXONOMY] = _panel_taxonomy_to_dict(plan.panel_taxonomy)
    if plan.cast is not None:
        body[_DD_KEY_CAST] = _cast_to_dict(plan.cast)
    # BC-D3 (Plan Y v1.2): emit per_item_beats block if any item has beat.
    if per_item_beats is not None:
        body[_DD_KEY_PER_ITEM_BEATS] = per_item_beats
    yaml_text = yaml.safe_dump(body, allow_unicode=True, sort_keys=False)
    return f"{_DESIGN_DIMENSIONS_HEADER}\n\n```yaml\n{yaml_text}```"


def _panel_taxonomy_to_dict(
    pt: dict[str, PanelTypeConfig],
) -> dict[str, dict[str, Any]]:
    """Serialize panel_taxonomy; emit only non-None fields per entry."""
    out: dict[str, dict[str, Any]] = {}
    for name, cfg in pt.items():
        entry: dict[str, Any] = {}
        if cfg.workflow is not None:
            entry["workflow"] = cfg.workflow
        if cfg.pulid is not None:
            entry["pulid"] = dict(cfg.pulid)
        if cfg.beat_prefix is not None:
            entry["beat_prefix"] = cfg.beat_prefix
        if cfg.beat_suffix is not None:
            entry["beat_suffix"] = cfg.beat_suffix
        out[name] = entry
    return out


def _cast_to_dict(cast: dict[str, CastEntry]) -> dict[str, dict[str, Any]]:
    """Serialize cast; type emitted only when non-default, visual when non-empty."""
    out: dict[str, dict[str, Any]] = {}
    for char_id, entry in cast.items():
        d: dict[str, Any] = {"name": entry.name}
        if entry.type != "human":  # default → omit (round-trip stable)
            d["type"] = entry.type
        if entry.visual:
            d["visual"] = dict(entry.visual)
        out[char_id] = d
    return out


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
