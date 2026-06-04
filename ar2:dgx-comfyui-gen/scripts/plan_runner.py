"""Batch run for gen --plan / --preset (BC-13, BC-14, BC-15, BC-16, BC-17).

Loads plan, expands items, submits all to ComfyUI in single SSH session
(12-zodiac verified pattern), polls outputs, SCPs back, writes history.jsonl.

EH-7  ComfyUI rejects single item → record items_failed, continue.
EH-10 SCP single failure → record, continue (ssh_client now retries
      transient errors internally before raising).
EH-12 Queue pre-clear API failure → log warning, continue (best-effort).
BC-17 Exit codes: 0 = all OK, 1 = SSH conn failure, 2 = workflow rejected
      (the whole batch can't even submit), 3 = partial failure.
EH-9  Ctrl-C during polling → detach, training continues on DGX.
"""

from __future__ import annotations

import copy
import datetime
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import HOST, INPUT_DIR, OUTPUT_DIR, LOCAL_OUTPUT_DIR_NAME  # noqa: E402
from ssh_client import ensure_tunnel, ssh_exec, scp_get, scp_put  # noqa: E402
import comfyui_api as api  # noqa: E402
from workflow_params import inject, has_pulid_node, WorkflowParamError  # noqa: E402
import plan_loader  # noqa: E402

# ── 透明素材（Route A/B）跨 skill 資源定位 + per-route dispatch（T3 / M-1）──
_TRANSPARENT_SKILL = "ar2:dgx-comfyui-transparent"
_TRANSPARENT_ROUTE_WF = {
    "rembg": "route_a_rmbg.json",
    "layerdiffuse": "route_b_layerdiffuse_sdxl.json",
    "vfx_additive": "vfx_additive.json",
}
# matte 前提：vfx_additive 須在純黑底產圖，dispatch 自動補此 prompt 後綴。
_VFX_ADDITIVE_PROMPT_SUFFIX = ", on pure solid black background, no other objects"
_TRANSPARENT_OUTPUT_DIR_NAME = "outputs/ar2-dgx-comfyui-transparent"


def _transparent_skill_dir() -> Path | None:
    """定位 sibling ar2:dgx-comfyui-transparent skill（deployed 或 source repo）。"""
    skills_dir = Path(__file__).resolve().parent.parent.parent
    for base in (skills_dir, Path.home() / "Code" / "ar2-skills"):
        cand = base / _TRANSPARENT_SKILL
        if cand.exists():
            return cand
    return None


def _resolve_route_workflow(route: str) -> Path:
    d = _transparent_skill_dir()
    if d is None:
        raise WorkflowParamError(f"route={route} 需 {_TRANSPARENT_SKILL} skill，但找不到")
    p = d / "workflows" / _TRANSPARENT_ROUTE_WF[route]
    if not p.exists():
        raise WorkflowParamError(f"找不到 route workflow：{p}")
    return p


def _load_transparent_modules():
    """lazy 載入透明 skill 的本地後處理模組（只在處理透明 item 時呼叫）。"""
    d = _transparent_skill_dir()
    if d is None:
        raise WorkflowParamError(f"postprocess 需 {_TRANSPARENT_SKILL} skill，但找不到")
    scripts_dir = str(d / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import transparent_postprocess as pp  # noqa
    import qc as qcmod  # noqa
    import asset_spec  # noqa
    return pp, qcmod, asset_spec


def _apply_run_subdir(wf: dict, run_dir_name: str) -> None:
    """把透明 workflow 的 SaveImage filename_prefix 內 {run_subdir} 佔位換成 run_dir_name（M-1）。

    inject 對透明 route 完全不碰 SaveImage（傳雙 None），run subdir 隔離靠此處字串替換。
    """
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") == "SaveImage":
            fp = node.get("inputs", {}).get("filename_prefix", "")
            if "{run_subdir}" in fp:
                node["inputs"]["filename_prefix"] = fp.replace("{run_subdir}", run_dir_name)


def _build_template_cache(loaded: plan_loader.LoadedPlan) -> dict:
    """按 plan 出現的 route 預載各自 workflow template（strip metadata 後）。"""
    cache: dict[str, dict] = {}
    for route in {getattr(it, "route", "none") for it in loaded.items}:
        if route == "none":
            path = _resolve_workflow(loaded.workflow)
        else:
            path = _resolve_route_workflow(route)
        tmpl = plan_loader.strip_workflow_metadata(json.loads(path.read_text()))
        cache[route] = tmpl
    return cache


def run_plan(plan_id: str, plans_dir: Path, items_spec: str | None = None) -> int:
    """Entry for `gen --plan {id}`. Optional items_spec filters subset."""
    loaded = plan_loader.load_working(plans_dir, plan_id)
    if items_spec:
        loaded = plan_loader.filter_items(loaded, items_spec)
    history_path = plans_dir / f"{plan_id}.history.jsonl"
    return _run(loaded, history_path, plans_dir, run_dir_name=plan_id)


def run_preset(
    preset_id: str,
    presets_dir: Path,
    plans_dir: Path,
    items_spec: str | None = None,
) -> int:
    """Entry for `gen --preset {id}`. Optional items_spec filters subset."""
    loaded = plan_loader.load_preset(presets_dir, preset_id)
    if items_spec:
        loaded = plan_loader.filter_items(loaded, items_spec)
    ts = datetime.datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    run_dir_name = f"{preset_id}_{ts}"
    history_dir = plans_dir / "preset_runs"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"{run_dir_name}.history.jsonl"
    return _run(loaded, history_path, plans_dir, run_dir_name=run_dir_name)


def _run(
    loaded: plan_loader.LoadedPlan,
    history_path: Path,
    plans_dir: Path,
    run_dir_name: str,
) -> int:
    # per-route template cache（route=none → loaded.workflow；透明 route → bundled）
    templates = _build_template_cache(loaded)
    routes = sorted({getattr(it, "route", "none") for it in loaded.items})

    print(f"== ar2:dgx-comfyui-gen --{loaded.mode} @ {HOST} ==")
    print(f"  workflow: {loaded.workflow}" + (f"  routes: {routes}" if routes != ["none"] else ""))
    print(f"  items: {len(loaded.items)}")
    print(f"  run_dir: {run_dir_name}")
    print()

    print("Ensuring SSH tunnel...", flush=True)
    ensure_tunnel()

    # EH-12: best-effort clear any stale queue items from a previous run
    # before starting this batch. Placement note: before _upload_face_ref so
    # face_ref upload failure doesn't waste a queue-clear cycle.
    _clear_stale_queue()

    # R-2 code fix: upload face_ref once before batch submit
    face_ref_filename = _upload_face_ref(loaded.face_ref, run_dir_name)

    started_at = _now_tz()
    started_ts = time.time()

    submissions = _submit_all(templates, loaded, run_dir_name,
                              face_ref_filename)
    succeeded_prompts = [s for s in submissions if s["prompt_id"]]
    print(f"\nSubmitted {len(succeeded_prompts)}/{len(loaded.items)} items.")

    if not succeeded_prompts:
        print("❌ all submissions failed; aborting.")
        _write_history(history_path, loaded, run_dir_name,
                       started_at, submissions, downloaded=[])
        return 2

    # Poll + SCP per prompt sequentially (ComfyUI queues anyway).
    local_root = Path.cwd() / LOCAL_OUTPUT_DIR_NAME / run_dir_name
    local_root.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []
    print(f"\nPolling /history + SCP → {local_root}/ ...")
    print("  (Ctrl-C to detach; jobs continue on DGX)")
    try:
        for sub in succeeded_prompts:
            _process_prompt(sub, local_root, run_dir_name, downloaded)
    except KeyboardInterrupt:
        print("\n⚠️  detached from polling; DGX continues running queued items.")
        return 1

    elapsed = time.time() - started_ts
    print(f"\n✅ Done in {_humanize(elapsed)}")
    print(f"  succeeded: {len(downloaded)}/{len(loaded.items)}")

    _write_history(history_path, loaded, run_dir_name,
                   started_at, submissions, downloaded)

    # BC-17 exit code
    failed = len(loaded.items) - len(downloaded)
    return 3 if failed > 0 else 0


def _clear_stale_queue() -> None:
    """EH-12: best-effort clear of any pending+running ComfyUI items.

    If /queue check or POST fails, log a warning and continue. Never raises —
    queue cleanup is a courtesy, not a correctness requirement.
    """
    size = api.get_queue_size()
    if size is None:
        print("⚠️  queue check failed, skipping pre-clear", flush=True)
        return
    pending, running = size
    total = pending + running
    if total == 0:
        return
    print(f"⚠️  Found {total} stale queue items ({pending} pending, "
          f"{running} running), clearing...", flush=True)
    if not api.clear_queue():
        print("⚠️  queue clear POST failed, continuing anyway", flush=True)


def _upload_face_ref(face_ref_local: str | None, run_dir_name: str) -> str | None:
    """R-2 code fix: propagate plan.face_ref. Upload once before batch.

    Returns the basename for inject(), or None if no face_ref configured.
    Skips upload if face_ref equals the sanitized placeholder (preset case).
    """
    if not face_ref_local:
        return None
    if face_ref_local.startswith("<") and face_ref_local.endswith(">"):
        # sanitized placeholder, e.g. "<set face_ref locally>" — preset case
        print(f"⚠️  face_ref is placeholder '{face_ref_local}'; set it locally "
              "before --preset, or fork with --from-preset to customize")
        return None
    local = Path(face_ref_local).expanduser().resolve()
    if not local.exists():
        print(f"❌ face_ref not found: {local}")
        raise FileNotFoundError(face_ref_local)
    remote_dir = f"{INPUT_DIR}/{run_dir_name}"
    ssh_exec(f"mkdir -p {remote_dir}")
    remote_path = f"{remote_dir}/{local.name}"
    print(f"Uploading face_ref → {remote_path} ...", flush=True)
    scp_put(local, remote_path)
    return local.name


def _inject_transparent(template: dict, item, loaded, run_dir_name: str) -> dict:
    """透明 route 注入（M-1）：先替換 {run_subdir}，再 inject 傳雙 None 保留寫死前綴。"""
    wf = copy.deepcopy(template)
    _apply_run_subdir(wf, run_dir_name)
    tp = item.transparent or {}
    tsize = tp.get("size")
    w = h = int(tsize) if tsize else loaded.size[0]
    if not tsize:
        h = loaded.size[1]
    # vfx_additive 的 luminance-matte 前提：黑底。自動補後綴（作者已寫則不重複）。
    prompt = item.final_prompt
    if getattr(item, "route", "none") == "vfx_additive" and "black background" not in prompt.lower():
        prompt += _VFX_ADDITIVE_PROMPT_SUFFIX
    # R-1：route_a_rmbg.json 只有 1 個 CLIPTextEncode（Flux guidance-distilled 不吃 CFG
    # negative）。若傳 plan 的 negative，inject 因「no second CLIPTextEncode」對每個透明
    # item raise → 全數失敗。v1 Route A 不套用 negative prompt（與 Flux 單 encoder 對齊）。
    return inject(
        wf,
        prompt=prompt,
        negative_prompt=None,
        seed=item.seed,
        steps=loaded.steps,
        batch_size=1,
        width=w,
        height=h,
        bg_remove_strength=tp.get("bg_remove_strength"),
        output_subdir=None,            # M-1：兩參數皆 None → inject 跳過 SaveImage 覆寫
        filename_prefix_override=None,  # M-1：保留 JSON 寫死的 source/mask 子目錄前綴
        deep_copy=False,                # wf 已 deepcopy
    )


def _submit_all(
    templates: dict,
    loaded: plan_loader.LoadedPlan,
    run_dir_name: str,
    plan_face_ref: str | None,
) -> list[dict]:
    """Submit each item; tolerate per-item failure (EH-7). Per-route template
    dispatch（T3）+ Plan Y v1.3 per-item workflow / PuLID dispatch（Gap 1/2）。

    plan_face_ref: basename of the plan-level face_ref pre-uploaded once (v1.2
    behavior preserved). Per-item workflow_override templates (BC-G1-3) and v13
    override face_refs (BC-G2-7) are cached lazily below.
    """
    submissions: list[dict] = []
    wf_template_cache: dict[str, dict] = {}   # BC-G1-3: workflow_override → template
    face_ref_cache: dict[str, str | None] = {}  # v13 override face_ref → basename
    for item in loaded.items:
        tag = f"  [{item.index:02d}] {item.slug}"
        route = getattr(item, "route", "none")
        try:
            if route == "none":
                template = _select_none_template(item, templates, wf_template_cache)
                # BC-G2-6 / EH-G1-2: verify effective workflow ↔ pulid_enabled
                # AFTER template load ∧ BEFORE inject (v13 dispatch only).
                _check_pulid_alignment(template, item)
                face_ref_filename = _resolve_face_ref(
                    item, loaded, run_dir_name, plan_face_ref, face_ref_cache
                )
                patched = inject(
                    template,
                    prompt=item.final_prompt,
                    negative_prompt=(loaded.negative or None),
                    seed=item.seed,
                    steps=loaded.steps,
                    batch_size=1,
                    width=loaded.size[0],
                    height=loaded.size[1],
                    # BC-G2-7 caller mapping: take per-item effective values from
                    # ResolvedItem (dispatch strength → runtime weight); NOT
                    # LoadedPlan-level. inject(None) → skip (v1.2 :167/:177).
                    face_ref_filename=face_ref_filename,
                    pulid_weight=item.pulid_strength,
                    output_subdir=run_dir_name,
                    filename_prefix_override=item.filename_prefix,
                )
            else:
                patched = _inject_transparent(templates[route], item, loaded, run_dir_name)
        except WorkflowParamError as e:
            print(f"{tag}: inject failed: {e}")
            submissions.append(
                {"item": item, "prompt_id": None, "error": f"inject: {e}"}
            )
            continue
        try:
            prompt_id, queue_n, _ = api.submit_prompt(patched, str(uuid.uuid4()))
        except (api.WorkflowRejected, api.ComfyUIError) as e:
            print(f"{tag}: ComfyUI rejected: {e}")
            submissions.append({
                "item": item,
                "prompt_id": None,
                "error": f"reject: {type(e).__name__}",
            })
            continue
        print(f"{tag}: prompt_id={prompt_id[:8]}... queue={queue_n}")
        submissions.append(
            {"item": item, "prompt_id": prompt_id, "queue": queue_n}
        )
    return submissions


def _select_none_template(item, templates: dict, cache: dict) -> dict:
    """BC-G1-3: effective workflow template for a route=='none' item.

    workflow_override → load + cache that workflow (EH-G1-1: missing file →
    WorkflowParamError so the item fails without aborting the batch). No
    override → plan-level template (templates['none'])."""
    name = getattr(item, "workflow_override", None)
    if not name:
        return templates["none"]
    if name not in cache:
        try:
            path = _resolve_workflow(name)
        except FileNotFoundError as e:  # EH-G1-1
            raise WorkflowParamError(
                f"workflow_override {name!r} not found for item {item.slug!r}: {e}"
            ) from e
        cache[name] = plan_loader.strip_workflow_metadata(json.loads(path.read_text()))
    return cache[name]


def _check_pulid_alignment(template: dict, item) -> None:
    """BC-G2-6 / EH-G1-2 (v13 dispatch only): effective workflow ↔ pulid_enabled.

    Legacy items (pulid_dispatch != 'v13') keep exact v1.2 behavior — no gate
    (BC-G0 reconciliation; see plan_loader._resolve_dispatch)."""
    if getattr(item, "pulid_dispatch", "legacy") != "v13":
        return
    has_node = has_pulid_node(template)
    wf = item.workflow_override or "(plan workflow)"
    if item.pulid_enabled and not has_node:
        raise WorkflowParamError(
            f"pulid_enabled=true but workflow {wf} has no ApplyPulidFlux node; "
            f"either override workflow to a PuLID-enabled one or set "
            f"pulid.enabled=false"
        )
    if not item.pulid_enabled and has_node:
        raise WorkflowParamError(
            f"pulid_enabled=false but workflow {wf} contains ApplyPulidFlux "
            f"node; either override workflow to a non-PuLID one (e.g. flux_basic) "
            f"or set pulid.enabled=true"
        )


def _resolve_face_ref(item, loaded, run_dir_name: str, plan_face_ref: str | None,
                      cache: dict) -> str | None:
    """Per-item face_ref basename for inject (BC-G2-7 caller mapping).

    Reuses the plan-level pre-uploaded basename when the item's resolved
    face_ref equals plan.face_ref (legacy + v13-using-plan-default → byte-equiv
    v1.2). Uploads + caches a distinct v13 override face_ref otherwise."""
    frf_local = getattr(item, "pulid_face_ref", None)
    if frf_local is None:
        return None
    if frf_local == loaded.face_ref:
        return plan_face_ref
    if frf_local not in cache:
        try:
            cache[frf_local] = _upload_face_ref(frf_local, run_dir_name)
        except FileNotFoundError as e:
            raise WorkflowParamError(
                f"face_ref {frf_local!r} not found for item {item.slug!r}: {e}"
            ) from e
    return cache[frf_local]


def _process_prompt(
    sub: dict,
    local_root: Path,
    run_dir_name: str,
    downloaded: list[str],
) -> None:
    item = sub["item"]
    tag = f"  [{item.index:02d}] {item.slug}"
    try:
        outputs = api.wait_for_completion(
            sub["prompt_id"], poll_interval=2.0, timeout=900.0,
        )
    except api.ComfyUIError as e:
        print(f"{tag}: wait failed: {e}")
        sub["error"] = f"wait: {e}"
        return
    files = api.list_output_files(outputs)
    if not files:
        print(f"{tag}: no output files")
        sub["error"] = "no-output"
        return
    item_files: list[Path] = []  # 本 prompt 下載的本地檔（透明 postprocess hook 用）
    for filename, subfolder in files:
        remote = f"{OUTPUT_DIR}/{subfolder}/{filename}".replace("//", "/")
        # Preserve subdir structure under local_root (e.g. ch1/, ch2/ for
        # chapter-encoded slugs). Strip the run_dir_name prefix that ComfyUI
        # echoes back in subfolder.
        rel_sub = subfolder or ""
        prefix = f"{run_dir_name}/"
        if rel_sub.startswith(prefix):
            rel_sub = rel_sub[len(prefix):]
        elif rel_sub == run_dir_name:
            rel_sub = ""
        target_dir = local_root / rel_sub if rel_sub else local_root
        target_dir.mkdir(parents=True, exist_ok=True)
        local = target_dir / filename
        try:
            scp_get(remote, local)
        except Exception as e:  # EH-10
            print(f"{tag}: SCP failed: {e}")
            sub["error"] = f"scp: {e}"
            return
        downloaded.append(str(local))
        item_files.append(local)
        print(f"{tag}: {(rel_sub + '/' if rel_sub else '') + filename}")

    # 透明 route：source+mask 同一 prompt 內 → per-prompt postprocess（compose/QC，BC-11）
    if getattr(item, "route", "none") != "none":
        _postprocess_transparent(item, item_files, run_dir_name, sub)


def _postprocess_transparent(item, item_files, run_dir_name: str, sub: dict) -> None:
    """本地後處理：source+mask → compose_rgba straight → fix_alpha → trim → final → QC。

    BC-11：source/mask 任一缺漏（鏈中途失敗）→ 標降級不 raise（不中斷整批）。
    """
    tag = f"  [{item.index:02d}] {item.slug}"
    route = getattr(item, "route", "none")
    # 依子目錄前綴分類；vfx_additive 只有 rgb（alpha 由 luminance 算，無獨立 mask）
    src = next((p for p in item_files if p.parent.name in ("source", "rgb")), None)
    msk = next((p for p in item_files if p.parent.name in ("mask", "alpha")), None)
    need_mask = route != "vfx_additive"
    if src is None or (need_mask and msk is None):
        missing = "source/rgb" if src is None else "mask"
        sub["error"] = f"transparent: 缺 {missing}（BC-11 降級）"
        print(f"{tag}: ⚠️ 缺 {missing}，跳過 postprocess")
        return
    try:
        pp, qcmod, asset_spec = _load_transparent_modules()
        from PIL import Image
        tp = item.transparent or {}
        category = tp.get("category", "asset")
        size = tp.get("size", "")
        asset_type = item.asset_type or ("semi" if route == "vfx_additive" else "opaque")
        folder = (Path.cwd() / _TRANSPARENT_OUTPUT_DIR_NAME / run_dir_name
                  / f"{category}_{item.slug}")
        folder.mkdir(parents=True, exist_ok=True)
        if route == "vfx_additive":
            rgba = pp.luminance_matte(Image.open(src))  # 加色特效：alpha=亮度（黑底）
        else:
            rgba = pp.compose_rgba(Image.open(src), Image.open(msk))
            rgba = pp.edge_bleed(rgba)  # §5.2：blur 前填 alpha=0 RGB，避免邊緣黑/白暈
        shrink = int(tp.get("alpha_shrink", 1)) if asset_type == "opaque" else 0
        rgba, warns = pp.fix_alpha(rgba, asset_type, shrink=shrink,
                                   blur=float(tp.get("alpha_blur", 1.0)))
        rgba = pp.auto_trim(rgba, padding=int(tp.get("padding", 8)))
        ver = asset_spec.next_version(folder, category, item.slug, size)
        fn = asset_spec.asset_filename(category, item.slug, size, ver)
        rgba.save(folder / fn)
        previews: list[str] = []
        if asset_type == "semi":  # R-4：semi 必出深淺底預覽
            dark, light = pp.make_previews(rgba)
            dark.save(folder / "preview_dark.png")
            light.save(folder / "preview_light.png")
            previews = ["preview_dark.png", "preview_light.png"]
        rep = qcmod.run_qc(folder / fn, asset_type, route=item.route,
                           previews=previews or None)
        if warns:
            rep.setdefault("warnings", []).extend(warns)
        (folder / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2))
        sub["transparent_final"] = str(folder / fn)
        sub["qc_result"] = rep["result"]
        print(f"{tag}: ✅ transparent QC={rep['result']} → {fn}")
    except Exception as e:  # postprocess 失敗不中斷整批
        sub["error"] = f"postprocess: {e}"
        print(f"{tag}: ⚠️ postprocess 失敗：{e}")


def _write_history(
    history_path: Path,
    loaded: plan_loader.LoadedPlan,
    run_dir_name: str,
    started_at: str,
    submissions: list[dict],
    downloaded: list[str],
) -> None:
    """EH-11: history.jsonl uses O_APPEND single-line write."""
    succeeded = sum(
        1 for s in submissions if s["prompt_id"] and "error" not in s
    )
    finished_at = _now_tz()
    prompt_records = [
        {
            "slug": s["item"].slug,
            "prompt_id": s.get("prompt_id"),
            "failed": "error" in s,
        }
        for s in submissions
    ]
    record = {
        "run_id": run_dir_name,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": _duration(started_at, finished_at),
        "mode": loaded.mode,
        "items_total": len(loaded.items),
        "items_succeeded": succeeded,
        "items_failed": len(loaded.items) - succeeded,
        "comfyui_prompt_ids": prompt_records,
        "output_dir": str(Path(LOCAL_OUTPUT_DIR_NAME) / run_dir_name),
    }
    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _now_tz() -> str:
    """Delegate to plan_schema.now_iso for single source of truth (R-1 fix)."""
    return plan_loader._import_plan_schema().now_iso()


def _resolve_workflow(workflow: str) -> Path:
    p = Path(workflow)
    if p.is_absolute() and p.exists():
        return p
    skill_dir = Path(__file__).resolve().parent.parent
    bundled = skill_dir / "workflows" / f"{workflow}.json"
    if bundled.exists():
        return bundled
    raise FileNotFoundError(f"workflow not found: {workflow}")


def _duration(a: str, b: str) -> float:
    da = datetime.datetime.fromisoformat(a)
    db = datetime.datetime.fromisoformat(b)
    return (db - da).total_seconds()


def _humanize(s: float) -> str:
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{s / 60:.1f}m"
    return f"{s / 3600:.1f}h"
