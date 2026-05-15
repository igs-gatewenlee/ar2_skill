"""Parse OVERVIEW.md frontmatter + 6 大段 sections.

Implements:
- mini YAML parser (only what frontmatter needs)
- IF-1 frontmatter validation (DR-2)
- NFC-normalized section name comparison (DR-7)
- fallback meta for missing/parse_error skills (DR-3)
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

from scanner import SkillInfo

# Frontmatter validation rules (DR-2 採納)
VALID_STATUS = {"stable", "beta", "experimental"}
VALID_CATEGORY = {"workflow", "meta"}
REQUIRED_FIELDS = (
    "display_name", "emoji", "status", "order",
    "category", "upstream", "downstream",
)
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
H2_RE = re.compile(r"^##\s+(.+?)\s*$")


@dataclass
class OverviewData:
    """IF-3: parsed OVERVIEW.md result."""

    skill: SkillInfo
    meta: dict[str, Any] = field(default_factory=dict)
    sections: dict[str, str] = field(default_factory=dict)
    parse_state: Literal["ok", "missing_overview", "parse_error"] = "ok"
    error_msg: str | None = None


def _strip_yaml_comment(line: str) -> str:
    """Strip YAML `#` comment but ignore `#` inside quoted strings (R-4 採納)."""
    in_quote: str | None = None
    for i, ch in enumerate(line):
        if ch in ('"', "'"):
            if in_quote is None:
                in_quote = ch
            elif in_quote == ch:
                in_quote = None
        elif ch == "#" and in_quote is None:
            return line[:i]
    return line


def _parse_mini_yaml(text: str) -> dict[str, Any]:
    """Tiny YAML parser: key:value, lists [a, b], quoted strings, ints."""
    result: dict[str, Any] = {}
    for raw in text.splitlines():
        stripped = _strip_yaml_comment(raw).strip()
        if not stripped or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                result[key] = []
            else:
                items = [
                    it.strip().strip('"').strip("'")
                    for it in inner.split(",")
                ]
                result[key] = items
        elif (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            result[key] = value[1:-1]
        elif value.lstrip("-").isdigit():
            result[key] = int(value)
        else:
            result[key] = value
    return result


def _validate_frontmatter(meta: dict[str, Any]) -> str | None:
    """Per IF-1 rules. Returns error message if invalid, else None."""
    for key in REQUIRED_FIELDS:
        if key not in meta:
            return f"必要欄位缺失: {key}"
    if not isinstance(meta["display_name"], str) or not meta["display_name"]:
        return "display_name 必須為非空字串"
    emoji = meta["emoji"]
    if not isinstance(emoji, str) or not (1 <= len(emoji) <= 4):
        return "emoji 必須為 1-4 字元字串"
    if meta["status"] not in VALID_STATUS:
        return f"status 必須為 {sorted(VALID_STATUS)} 之一"
    if not isinstance(meta["order"], int) or meta["order"] < 0:
        return "order 必須為 ≥ 0 的整數"
    if meta["category"] not in VALID_CATEGORY:
        return f"category 必須為 {sorted(VALID_CATEGORY)} 之一"
    for field_name in ("upstream", "downstream"):
        items = meta[field_name]
        if not isinstance(items, list):
            return f"{field_name} 必須為列表"
        for item in items:
            if not isinstance(item, str) or not item.startswith("ar2:"):
                return f"{field_name} 元素須以 'ar2:' 開頭"
    return None


def _split_sections(body: str) -> dict[str, str]:
    """Split Markdown body by H2 (## ). Section names NFC-normalized.

    BC-6b: empty sections excluded from result (won't render).
    """
    sections: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_name is not None:
            content = "\n".join(current_lines).strip()
            if content:
                sections[current_name] = content

    for line in body.splitlines():
        match = H2_RE.match(line)
        if match:
            flush()
            current_name = unicodedata.normalize("NFC", match.group(1).strip())
            current_lines = []
        else:
            current_lines.append(line)
    flush()
    return sections


def _fallback_meta(skill_name: str) -> dict[str, Any]:
    """DR-3 fallback meta — places skill in 「待補/損壞」 region of HTML."""
    return {
        "display_name": skill_name,
        "emoji": "🚧",
        "status": "experimental",
        "order": 9999,
        "category": "meta",
        "upstream": [],
        "downstream": [],
    }


def _error_result(
    skill: SkillInfo,
    state: Literal["missing_overview", "parse_error"],
    msg: str,
) -> OverviewData:
    """Build an error OverviewData with DR-3 fallback meta."""
    return OverviewData(
        skill=skill,
        meta=_fallback_meta(skill.name),
        parse_state=state,
        error_msg=msg,
    )


def parse_overview(skill: SkillInfo) -> OverviewData:
    """Read + parse OVERVIEW.md from skill.workspace_path.

    EH-3: missing OVERVIEW.md → fallback meta, parse_state=missing_overview.
    EH-4: parse errors → fallback meta, parse_state=parse_error.
    """
    if skill.workspace_path is None:
        return _error_result(
            skill, "missing_overview", "只存在於 installed，無 workspace 版本"
        )

    overview_path = skill.workspace_path / "OVERVIEW.md"
    if not overview_path.exists():
        return _error_result(
            skill, "missing_overview", f"OVERVIEW.md 不存在於 {overview_path}"
        )

    text = overview_path.read_text(encoding="utf-8")
    fm_match = FRONTMATTER_RE.match(text)
    if not fm_match:
        return _error_result(
            skill, "parse_error", "找不到 YAML frontmatter（必須以 --- 包圍）"
        )

    try:
        meta = _parse_mini_yaml(fm_match.group(1))
    except Exception as exc:
        return _error_result(
            skill, "parse_error", f"YAML frontmatter 解析失敗: {exc}"
        )

    err = _validate_frontmatter(meta)
    if err:
        return _error_result(skill, "parse_error", err)

    return OverviewData(
        skill=skill,
        meta=meta,
        sections=_split_sections(fm_match.group(2)),
        parse_state="ok",
    )
