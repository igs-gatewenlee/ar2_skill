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


@dataclass
class Item:
    """One row of the items table."""
    slug: str
    prompt: str
    full: bool = False  # ✓ → self-contained, no auto inject


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
    output_dir: str = ""
    output_naming: str = ""
    items: list[Item] = field(default_factory=list)
    open_notes: str = ""


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
    return Plan(
        id=fm["id"],
        title=fm["title"],
        version=int(fm["version"]),
        created=str(fm["created"]),
        updated=str(fm["updated"]),
        status=fm["status"],
        workflow=fm["workflow"],
        size=list(fm["size"]),
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
        output_dir=_extract_output(out_block, "dir") or "",
        output_naming=_extract_output(out_block, "naming") or "",
        items=_parse_items_table(sections["# Items"], path),
        open_notes=sections["# Open notes"],
    )


def _extract_style(text: str, key: str) -> str:
    m = re.search(rf"\*\*{key}\*\*\s*[:：]\s*(.*?)(?=\n\*\*|\Z)",
                  text, re.DOTALL)
    if not m:
        return "(none)"
    val = m.group(1).strip()
    return val or "(none)"


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
    }
    for key, value in optional.items():
        if value is not None:
            d[key] = value
    return d


def _plan_to_body(plan: Plan) -> str:
    lines = [
        "# Story / Vision",
        plan.story_vision or "(empty)",
        "",
        "# Style anchor",
        f"**Prefix**: {plan.style_prefix}",
        f"**Suffix**: {plan.style_suffix}",
        f"**Negative**: {plan.style_negative}",
        "",
        "# Output",
        f"- dir: {plan.output_dir}",
        f"- naming: {plan.output_naming}",
        "",
        "# Items",
        "| # | slug | prompt | full? |",
        "|---|------|--------|-------|",
    ]
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
