"""Render OverviewData list into standalone HTML knowledge base.

Loads HTML template, substitutes content placeholders, prepends
generated_at marker for BC-12 cache freshness detection.
"""

import html
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from parser import OverviewData

GENERATED_AT_MARKER = "<!-- generated_at: {} -->"

EXPECTED_SECTIONS = [
    "一句話：這 skill 解什麼問題？",
    "什麼時候會想到要用？",
    "最簡單的用法",
    "常用參數",
    "跟家族裡其他 skill 怎麼配合？",
    "容易踩的坑",
]

# Install-status badge HTML by SkillInfo.status
INSTALL_BADGES = {
    "installed":      '<span class="badge b-installed">✅ 已 install</span>',
    "workspace_only": '<span class="badge b-pending">🟡 未 install</span>',
    "orphan_install": '<span class="badge b-orphan">⚠️ 孤立</span>',
}

# Meta-status badge HTML by frontmatter `status`
META_STATUS_BADGES = {
    "stable":       '<span class="badge b-stable">stable</span>',
    "beta":         '<span class="badge b-beta">beta</span>',
    "experimental": '<span class="badge b-exp">experimental</span>',
}

INLINE_CODE_RE = re.compile(r"`([^`]+)`")
INLINE_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


def _esc(text: str) -> str:
    """HTML-escape including quotes."""
    return html.escape(text, quote=True)


def _render_inline(text: str) -> str:
    """Inline markdown: backtick code spans + **bold**."""
    out = _esc(text)
    out = INLINE_CODE_RE.sub(r"<code>\1</code>", out)
    out = INLINE_BOLD_RE.sub(r"<strong>\1</strong>", out)
    return out


def _md_to_html(md: str) -> str:
    """Minimal markdown → HTML: paragraphs, bullet lists, pipe tables."""
    if not md.strip():
        return ""

    blocks: list[str] = []
    cur_list: list[str] = []
    cur_table: list[list[str]] = []
    cur_para: list[str] = []

    def flush_list() -> None:
        if cur_list:
            items = "".join(f"<li>{_render_inline(it)}</li>" for it in cur_list)
            blocks.append(f"<ul>{items}</ul>")
            cur_list.clear()

    def flush_table() -> None:
        if cur_table:
            head = cur_table[0]
            body = cur_table[2:] if len(cur_table) >= 2 else []
            head_html = "".join(f"<th>{_render_inline(c)}</th>" for c in head)
            rows = "".join(
                "<tr>" + "".join(f"<td>{_render_inline(c)}</td>" for c in row) + "</tr>"
                for row in body
            )
            blocks.append(
                f"<table><thead><tr>{head_html}</tr></thead>"
                f"<tbody>{rows}</tbody></table>"
            )
            cur_table.clear()

    def flush_para() -> None:
        if cur_para:
            text = " ".join(cur_para)
            blocks.append(f"<p>{_render_inline(text)}</p>")
            cur_para.clear()

    for line in md.splitlines():
        stripped = line.strip()
        if not stripped:
            flush_list()
            flush_table()
            flush_para()
        elif stripped.startswith("- "):
            flush_table()
            flush_para()
            cur_list.append(stripped[2:])
        elif stripped.startswith("|") and stripped.endswith("|"):
            flush_list()
            flush_para()
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            cur_table.append(cells)
        else:
            flush_list()
            flush_table()
            cur_para.append(stripped)
    flush_list()
    flush_table()
    flush_para()
    return "\n".join(blocks)


def _anchor(skill_name: str) -> str:
    """Stable HTML anchor id for a skill (used by pipeline and cards)."""
    return "skill-" + skill_name.replace(":", "-")


def _skill_badges(data: OverviewData) -> str:
    """Install badge + meta-status badge concatenated."""
    return (
        INSTALL_BADGES.get(data.skill.status, "")
        + META_STATUS_BADGES.get(data.meta.get("status", ""), "")
    )


def _skill_display(data: OverviewData) -> tuple[str, str]:
    """Return (escaped emoji, escaped display name) with fallbacks."""
    emoji = _esc(data.meta.get("emoji", "📦"))
    name = _esc(data.meta.get("display_name", data.skill.name))
    return emoji, name


def _render_pipeline(workflow_skills: list[OverviewData]) -> str:
    """BC-7: linear pipeline (left → right) of workflow skills, with arrows between."""
    if not workflow_skills:
        return '<p class="subtitle">（尚無 workflow 類型 skill）</p>'

    def node(data: OverviewData) -> str:
        emoji, name = _skill_display(data)
        return (
            f'<a class="pipeline-node" href="#{_anchor(data.skill.name)}">'
            f'<div class="pipeline-emoji">{emoji}</div>'
            f'<div class="pipeline-name">{name}</div>'
            f'</a>'
        )

    inner = '<div class="pipeline-arrow">→</div>'.join(node(d) for d in workflow_skills)
    return f'<div class="pipeline">{inner}</div>'


def _render_skill_card(data: OverviewData) -> str:
    """Index card. R-13: broken skills render non-clickable (no detail to link to)."""
    emoji, name = _skill_display(data)
    inner = (
        f'<div class="card-emoji">{emoji}</div>'
        f'<div class="card-name">{name}</div>'
        f'<div class="card-badges">{_skill_badges(data)}</div>'
    )
    if data.parse_state == "ok":
        return f'<a class="card" href="#{_anchor(data.skill.name)}">{inner}</a>'
    return f'<div class="card card-broken">{inner}</div>'


def _render_skill_section(data: OverviewData) -> str:
    """Detailed section — 6 大段，BC-6b 跳過 missing/empty sections."""
    emoji, name = _skill_display(data)
    skill_id = _esc(data.skill.name)
    anchor = _anchor(data.skill.name)

    parts: list[str] = []
    if data.parse_state != "ok":
        parts.append(
            f'<div class="error-banner">⚠️ {_esc(data.error_msg or "解析失敗")}</div>'
        )

    for title in EXPECTED_SECTIONS:
        body = data.sections.get(unicodedata.normalize("NFC", title), "").strip()
        if not body:
            continue
        parts.append(
            f'<div class="subsection">'
            f"<h3>{_esc(title)}</h3>"
            f"{_md_to_html(body)}"
            f"</div>"
        )

    body_html = "\n".join(parts)
    return (
        f'<section class="skill-section" id="{anchor}">'
        f"<header>"
        f'<span class="skill-emoji">{emoji}</span>'
        f"<h2>{name}</h2>"
        f'<span class="skill-id">{skill_id}</span>'
        f'<span class="skill-badges">{_skill_badges(data)}</span>'
        f"</header>"
        f"{body_html}"
        f"</section>"
    )


def _sort_key(data: OverviewData) -> tuple[int, str]:
    """BC-7 fallback: ascending order, then skill name."""
    return (data.meta.get("order", 9999), data.skill.name)


def render(skills_data: list[OverviewData], template_path: Path) -> str:
    """IF-4: produce standalone HTML with embedded generated_at marker (BC-12)."""
    # BC-7/BC-8: sort by order, then name; partition by category
    by_category: dict[str, list[OverviewData]] = {"workflow": [], "meta": []}
    for d in skills_data:
        cat = d.meta.get("category")
        if cat in by_category:
            by_category[cat].append(d)
    workflow = sorted(by_category["workflow"], key=_sort_key)
    meta_list = sorted(by_category["meta"], key=_sort_key)
    broken = [d for d in skills_data if d.parse_state != "ok"]

    def cards(items: list[OverviewData]) -> str:
        return "\n".join(_render_skill_card(d) for d in items)

    pipeline_html = _render_pipeline([d for d in workflow if d.parse_state == "ok"])
    workflow_cards = cards([d for d in workflow if d.parse_state == "ok"])
    meta_cards = cards([d for d in meta_list if d.parse_state == "ok"])
    broken_cards = cards(broken)
    skill_sections = "\n".join(
        _render_skill_section(d)
        for d in workflow + meta_list
        if d.parse_state == "ok"
    )

    template = template_path.read_text(encoding="utf-8")
    now = datetime.now(timezone.utc).isoformat()
    empty_subtitle = '<p class="subtitle">（尚無）</p>'

    out = (
        template.replace("{{GENERATED_AT_DISPLAY}}", now)
        .replace("{{PIPELINE}}", pipeline_html)
        .replace("{{WORKFLOW_CARDS}}", workflow_cards or empty_subtitle)
        .replace("{{META_CARDS}}", meta_cards or empty_subtitle)
        .replace("{{BROKEN_CARDS}}", broken_cards)
        .replace("{{BROKEN_VISIBILITY}}", "" if broken else "hidden")
        .replace("{{SKILL_SECTIONS}}", skill_sections)
    )

    return GENERATED_AT_MARKER.format(now) + "\n" + out
