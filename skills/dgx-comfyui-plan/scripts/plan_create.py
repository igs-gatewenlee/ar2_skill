"""Interactive plan create (BC-1, 4-round dialogue).

This module exposes `create_plan(plans_dir)` which conducts a 4-round
interactive dialogue with the user via stdin/stdout, then writes a
new outline.md and returns the plan id.

Round 1 — 高層意圖 (theme / count / mode)
Round 2 — items 收集 (free-form)
Round 3 — 技術 anchor (size / steps / lora / seed)
Round 4 — review + confirm
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from pathlib import Path

import plan_schema as ps


@dataclass
class Round1Result:
    title: str
    estimated_count: str  # "5" / "10-20" / "30+" / "不確定"
    mode: str  # "series" / "independent"


def create_plan(plans_dir: Path, *, preload: ps.Plan | None = None) -> str:
    """Run 4-round interactive create, return new plan id.

    Args:
        plans_dir: target dir for `plans/{id}_outline.md`
        preload: optional Plan to use as initial values (--from-preset case)
    """
    plans_dir.mkdir(parents=True, exist_ok=True)

    # Round 1
    if preload is None:
        r1 = _round1_intent()
    else:
        _print("--from-preset detected, skipping Round 1 (title inherited)")
        r1 = Round1Result(
            title=preload.title, estimated_count="?", mode="series"
        )

    # Round 2 — items
    items = _round2_items(r1, preload)

    # Round 3 — 技術 anchor
    style_prefix, style_suffix, style_negative = _round3_style(preload)
    size, steps, lora, seed_strategy, batch = _round3_tech(preload)
    workflow = _round3_workflow(preload)

    # Build draft plan
    def _id_exists(candidate: str) -> bool:
        return (plans_dir / f"{candidate}_outline.md").exists()

    plan_id = ps.gen_id(r1.title, _id_exists)
    now = ps.now_iso()
    provenance = (
        {"from_preset": preload.id, "forked_at": now}
        if preload is not None else None
    )
    output_dir = f"outputs/ar2-dgx-comfyui-gen/{plan_id}/"
    output_naming = "{NN}_{slug}_{n}.png"
    if preload is not None:
        # R-1 fix: dataclasses.replace propagates ALL fields (mode / size_aspect
        # / character_consistency / layer_a/b/c / style_*_zh / future fields)
        # automatically — 防 #009 shared-schema blind-assign 第 6 次踩.
        plan = replace(
            preload,
            id=plan_id,
            title=r1.title,
            version=1,
            created=now,
            updated=now,
            status="ready",
            workflow=workflow,
            size=size,
            steps=steps,
            batch_per_item=batch,
            seed_strategy=seed_strategy,
            lora=lora,
            face_ref=None,
            style_prefix=style_prefix,
            style_suffix=style_suffix,
            style_negative=style_negative,
            output_dir=output_dir,
            output_naming=output_naming,
            items=items,
            provenance=provenance,
            # Implicitly inherited from preload: story_vision, open_notes,
            # layer_a, layer_b, layer_c, mode, size_aspect, character_consistency,
            # style_prefix_zh, style_suffix_zh, style_negative_zh
        )
    else:
        # BC-G9-2 (#009 prevention): fresh-create unified to the replace pattern
        # (matching the preload branch). Construct a minimal Plan with required
        # fields only, then replace the optionals — future optional fields then
        # auto-inherit their dataclass default instead of being silently dropped.
        plan = replace(
            ps.Plan(
                id=plan_id,
                title=r1.title,
                version=1,
                created=now,
                updated=now,
                status="ready",
                workflow=workflow,
                size=size,
                steps=steps,
                batch_per_item=batch,
                seed_strategy=seed_strategy,
            ),
            lora=lora,
            face_ref=None,
            story_vision="(empty)",
            style_prefix=style_prefix,
            style_suffix=style_suffix,
            style_negative=style_negative,
            output_dir=output_dir,
            output_naming=output_naming,
            items=items,
            open_notes="(empty)",
            provenance=provenance,
        )

    # Round 4 — review + confirm
    if not _round4_review(plan):
        _print("Aborted by user.")
        sys.exit(130)

    out_path = plans_dir / f"{plan_id}_outline.md"
    ps.atomic_write(out_path, ps.serialize(plan))
    _print(f"\n✅ wrote {out_path}")
    _print(f"   id: {plan_id}")
    _print(f"   next: gen --plan {plan_id}")
    return plan_id


# ---------- Round 1 ----------


_MODE_SERIES_LABEL = "系列同主題不同變奏 (series)"
_MODE_INDEPENDENT_LABEL = "獨立 prompts (independent)"


def _round1_intent() -> Round1Result:
    _print("\n═══ Round 1 — 高層意圖 ═══")
    title = _prompt("主題 / 標題 (free text): ").strip()
    if not title:
        _err("title cannot be empty")
        sys.exit(1)
    count = _choice(
        "預估數量",
        ["5", "10-20", "30+", "不確定"],
    )
    mode_label = _choice(
        "模式",
        [_MODE_SERIES_LABEL, _MODE_INDEPENDENT_LABEL],
    )
    mode_short = "series" if mode_label == _MODE_SERIES_LABEL else "independent"
    return Round1Result(title=title, estimated_count=count, mode=mode_short)


# ---------- Round 2 ----------


def _round2_items(r1: Round1Result, preload: ps.Plan | None) -> list[ps.Item]:
    _print("\n═══ Round 2 — Items 收集 ═══")
    if preload is None or not preload.items:
        return _round2_collect_fresh(r1)
    _print(f"  preset 含 {len(preload.items)} 個 items")
    action = _choice(
        "保留 / 修改",
        ["保持原 items", "全部重列", "進入編輯逐項"],
    )
    if "保持" in action:
        return [_clone_item(it) for it in preload.items]
    if "全部" in action:
        return _round2_collect_fresh(r1)
    # 編輯模式：MVP 簡化為「列出 preset items、用戶 free-text 修正」
    return _round2_edit(preload.items)


def _clone_item(it: ps.Item) -> ps.Item:
    """Shallow copy so caller can mutate without affecting preload.

    Uses dataclasses.replace to inherit ALL fields automatically (R-2 fix:
    防 #009 — 未來再加 Item 欄位永遠不會漏 propagation).
    """
    return replace(it)


def _round2_collect_fresh(r1: Round1Result) -> list[ps.Item]:
    if r1.mode == "series":
        _print("\n系列模式：每行輸入一個元素（如生肖、節氣、塔羅）。空行結束。")
        _print("格式：<slug> <主體描述>")
        _print("範例：rat young girl with cute white mouse")
        return _read_items_lines()
    _print("\n獨立模式：每個 prompt 一段、用 --- 分隔。空行結束。")
    return _read_items_blocks()


def _read_items_lines() -> list[ps.Item]:
    items: list[ps.Item] = []
    idx = 1
    while True:
        line = _prompt(f"  [{idx}] ").strip()
        if not line:
            break
        parts = line.split(maxsplit=1)
        if len(parts) < 2:
            _err(f"  expected `<slug> <prompt>`, got `{line}`. skipped.")
            continue
        slug, prompt = parts[0], parts[1]
        # BC-G9 (#009): minimal Item + replace → v1.3/future optional fields inherit.
        items.append(replace(ps.Item(slug=slug, prompt=prompt), full=False))
        idx += 1
    if not items:
        _err("at least 1 item required")
        sys.exit(1)
    return items


def _read_items_blocks() -> list[ps.Item]:
    items: list[ps.Item] = []
    idx = 1
    while True:
        _print(f"  [{idx}] (--- 結束) ")
        prompt = _prompt("").strip()
        if prompt == "---" or not prompt:
            break
        slug = _prompt(f"  slug for item {idx}: ").strip() or f"item_{idx}"
        # BC-G9 (#009): minimal Item + replace → v1.3/future optional fields inherit.
        items.append(replace(ps.Item(slug=slug, prompt=prompt), full=False))
        idx += 1
    if not items:
        _err("at least 1 item required")
        sys.exit(1)
    return items


def _round2_edit(seed: list[ps.Item]) -> list[ps.Item]:
    _print("\n編輯模式（MVP 簡化）：每行輸出 `<i> <new prompt>` 修改、`<i> del` 刪除、空行結束。")
    items = [_clone_item(it) for it in seed]
    for i, it in enumerate(items, start=1):
        _print(f"  [{i}] {it.slug}: {it.prompt[:80]}")
    while True:
        cmd = _prompt("\n> ").strip()
        if not cmd:
            break
        parts = cmd.split(maxsplit=1)
        try:
            i = int(parts[0]) - 1
        except ValueError:
            _err("bad index")
            continue
        if i < 0 or i >= len(items):
            _err("index out of range")
            continue
        if len(parts) == 2 and parts[1].strip() == "del":
            del items[i]
            _print(f"  deleted #{i + 1}")
        elif len(parts) == 2:
            items[i].prompt = parts[1].strip()
            _print(f"  updated #{i + 1}")
    return items


# ---------- Round 3 ----------

_KEEP_PRESET = "保持 preset 設定"


def _keep_preset(label: str, alt_label: str) -> bool:
    """Show 2-choice prompt; True if user picked the 'keep preset' option."""
    return _choice(label, [_KEEP_PRESET, alt_label]) == _KEEP_PRESET


def _round3_style(preload: ps.Plan | None) -> tuple[str, str, str]:
    _print("\n═══ Round 3 — 技術 anchor ═══")
    if preload is not None and _keep_preset(
        "風格 prefix/suffix/negative", "重新輸入"
    ):
        return preload.style_prefix, preload.style_suffix, preload.style_negative
    prefix = _prompt("Style Prefix (空=none): ").strip() or "(none)"
    suffix = _prompt("Style Suffix (空=none): ").strip() or "(none)"
    negative = _prompt("Negative Prompt (空=none): ").strip() or "(none)"
    return prefix, suffix, negative


def _round3_tech(
    preload: ps.Plan | None,
) -> tuple[list[int], int, list[dict], dict, int]:
    if preload is not None and _keep_preset(
        "技術參數 (size/steps/lora/seed/batch)", "重新設定"
    ):
        return (
            preload.size, preload.steps, preload.lora,
            preload.seed_strategy, preload.batch_per_item,
        )
    size_choice = _choice("圖尺寸", ["1024x1024", "1024x1536", "768x1024", "自訂"])
    size = _parse_size(size_choice)
    steps_choice = _choice("步數", ["20 (快)", "30 (標準)", "50 (精細)"])
    steps = int(steps_choice.split()[0])
    lora = _round3_lora()
    seed_strategy = _round3_seed()
    batch = 1  # MVP 固定 1，Phase 2 開放
    return size, steps, lora, seed_strategy, batch


def _round3_workflow(preload: ps.Plan | None) -> str:
    if preload is not None:
        return preload.workflow
    wf = _choice("Workflow", ["flux_basic", "flux_pulid", "自訂路徑"])
    if wf == "自訂路徑":
        return _prompt("輸入 workflow JSON 絕對路徑: ").strip()
    return wf


def _round3_lora() -> list[dict]:
    if _choice("使用 LoRA?", ["否", "是"]) == "否":
        return []
    loras: list[dict] = []
    while True:
        name = _prompt("LoRA 檔名 (不含 .safetensors、空=結束): ").strip()
        if not name:
            break
        sval = _prompt(f"  strength for {name} (預設 1.0): ").strip() or "1.0"
        try:
            strength = float(sval)
        except ValueError:
            _err("bad float, defaulting 1.0")
            strength = 1.0
        loras.append({"name": name, "strength": strength})
    return loras


def _round3_seed() -> dict:
    typ = _choice("Seed strategy", ["fixed", "random", "incremental"])
    if typ == "fixed":
        base = int(_prompt("seed value (預設 42): ").strip() or "42")
        return {"type": "fixed", "base": base, "step": 0}
    if typ == "random":
        return {"type": "random", "base": 0, "step": 0}
    base = int(_prompt("incremental base (預設 1000): ").strip() or "1000")
    step = int(_prompt("incremental step (預設 137): ").strip() or "137")
    return {"type": "incremental", "base": base, "step": step}


def _parse_size(choice: str) -> list[int]:
    if "自訂" in choice:
        w = int(_prompt("width: ").strip())
        h = int(_prompt("height: ").strip())
        return [w, h]
    w_s, h_s = choice.split("x")
    return [int(w_s), int(h_s)]


# ---------- Round 4 ----------


_CONFIRM_WRITE = "是、寫入"
_CONFIRM_ABORT = "否、放棄"


def _round4_review(plan: ps.Plan) -> bool:
    _print("\n═══ Round 4 — Review ═══")
    _print(ps.serialize(plan))
    _print("─" * 50)
    return _choice("確認寫入?", [_CONFIRM_WRITE, _CONFIRM_ABORT]) == _CONFIRM_WRITE


# ---------- IO helpers ----------


def _print(s: str = "") -> None:
    print(s, flush=True)


def _err(s: str) -> None:
    sys.stderr.write(f"⚠️  {s}\n")
    sys.stderr.flush()


def _prompt(s: str) -> str:
    try:
        return input(s)
    except (EOFError, KeyboardInterrupt):
        _print("\n[interrupted]")
        sys.exit(130)


def _choice(label: str, options: list[str]) -> str:
    _print(f"\n{label}:")
    for i, opt in enumerate(options, start=1):
        _print(f"  {i}. {opt}")
    while True:
        s = _prompt(f"選擇 (1-{len(options)}): ").strip()
        try:
            idx = int(s)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except ValueError:
            pass
        _err("invalid choice, retry")
