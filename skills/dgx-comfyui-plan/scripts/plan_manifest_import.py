"""--from-manifest：comfyui-reskin-manifest v1.0.0 JSON → ar2 plan outline.md。

uk:local-play gen-manifest --style 產出的換皮工單（155 item）→ 按 genSize 分桶
產多份 plans/{id}_{WxH}_outline.md（plan 級 size 消費兩維 plan_runner.py:335-336，
分桶即可全件精確比例，零失真）。

承重設計（P1-manifest2plan-design-spec.md v1.1）：
- 走 ps.Plan dataclass + ps.serialize()（plan_schema 公開序列化入口），不手拼
  frontmatter 字串 → version 型別 / 必填欄 / 欄位漂移整類風險由 schema 接管。
- 版本鎖（#013）：manifest 端 schemaName + major==1 斷言在讀任何 item 之前
  （exit 4 fail-loud）。ar2 端 importer **不另設版本斷言**——與 plan_schema 同
  scripts/ 同 commit 部署（結構保證），消費側由 gen plan_loader 的
  _REQUIRED_SCHEMA_VERSION guard fail-loud（R-2：勿宣稱「雙鎖皆斷言」）。
- Style anchor 全 (none)：manifest prompt.positive 已 self-contained；
  Negative 禁填 globalNegative（flux_basic 單 CLIPTextEncode，非空 negative
  會讓 route=none item 在 workflow_params inject 全數 raise → 整 plan 零產出）。
- full?=✓：gen 端 plan_loader item.full 分支 verbatim，不 inject prefix/suffix。
- 永不輸出 route="layerdiffuse"（DGX Route B PoC-pending，單 entry 即整批 abort）。

exit codes: 0 OK / 2 用法錯（--id 不合法 / 目標已存在無 --overwrite / 桶 id 過長）/
3 manifest JSON parse 失敗 / 4 版本斷言失敗 / 5 item 級驗證失敗（未知
alphaStrategy.mode / prompt.positive 空 / id 非 slug-legal / genSize 缺 w·h /
category 撞保留字 / route resolution 內部不變量破壞）——全部 fail-fast 不臆測。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import plan_schema as ps

# ── manifest 端版本鎖（#013 對稱顯式鎖；本 importer 是 manifest 第一個程式化 consumer）──
_EXPECTED_SCHEMA_NAME = "comfyui-reskin-manifest"
_EXPECTED_MAJOR = 1

# 入表過濾：只收可生成項（gen 對 Items 表每列無條件 submit，無 skip 機制 —
# plan_runner.py:315 `for item in loaded.items`；過濾是 importer 的責任）。
_GENWORTHY_FIT_POLICY = "gen_bucket_then_resize"

# alphaStrategy.mode 封閉 enum（COMFYUI_PROMPT_SCHEMA.md v1.0.0）。未知值 exit 5。
_KNOWN_ALPHA_MODES = frozenset({"layerdiffuse_native", "postprocess_matte", "none"})

# aggressive route-policy：functionalRole → vfx_additive 白名單（明確自發光才走
# luminance-matte；black-bg 後綴會不可逆改寫 prompt，弱證據一律保守 rembg）。
# 依 722 manifest 實際 role 分布鎖定：light 是唯一明確自發光 role。
_VFX_ROLES = frozenset({"light"})

# asset_spec.py:18-25 category 保留字（postprocess 子目錄名）。前移到 importer
# 守衛，避免 GPU 產圖後才在 postprocess raise 白燒算力。
_CATEGORY_RESERVED = frozenset({"source", "mask", "rgb", "alpha", "preview"})

# transparent_assets defaults（對齊 dgx-comfyui-plan/tests/test_transparent_assets.py）。
_TA_DEFAULTS = {"bg_remove_strength": 0.5, "alpha_shrink": 1, "padding": 8}

_ROUTE_POLICIES = ("conservative", "aggressive")


def _fail(code: int, msg: str) -> int:
    sys.stderr.write(f"ERROR: {msg}\n")
    return code


def _warn(msg: str) -> None:
    sys.stdout.write(f"WARN: {msg}\n")


# ---------- 版本鎖 ----------


def _assert_manifest_version(data: dict, src: str) -> str | None:
    """schemaName + major==1 斷言。回傳 error message（None=通過）。

    此斷言必須在讀任何 item 之前執行（BC-7 反向遍歷驗證點）。
    """
    name = data.get("schemaName")
    if name != _EXPECTED_SCHEMA_NAME:
        return (
            f"{src}: schemaName={name!r}，預期 {_EXPECTED_SCHEMA_NAME!r}"
            "（不是換皮 manifest，拒收）"
        )
    raw_ver = str(data.get("schemaVersion", ""))
    major_str = raw_ver.split(".", 1)[0]
    if not major_str.isdigit() or int(major_str) != _EXPECTED_MAJOR:
        return (
            f"{src}: schemaVersion={raw_ver!r} major 不符（預期 {_EXPECTED_MAJOR}.x.x）。"
            "major 破壞性變更，importer 須同步更新後才能消費"
        )
    minor_str = raw_ver.split(".")[1] if raw_ver.count(".") >= 1 else "0"
    if minor_str.isdigit() and int(minor_str) > 0:
        # minor=純加欄位向後相容（schema 自宣告），但語意漂移不可偵測 → WARN 不擋。
        _warn(
            f"manifest schemaVersion={raw_ver}（minor > 本 importer 認證的 1.0.x）："
            "新欄位將被忽略；若語意有變請人工核對"
        )
    return None


# ---------- item 前處理 ----------


def _one_line(prompt: str) -> str:
    """prompt 單行化（plan_schema parse 對含換行 prompt raise EH-3；
    `|` escape 由 ps.serialize 處理，importer 不重複做）。"""
    return " ".join(prompt.split())


def _item_error(item: dict, why: str) -> str:
    return f"item id={item.get('id')!r}: {why}"


def _resolve_route(mode: str, role: str, policy: str) -> tuple[str, str | None]:
    """alphaStrategy.mode → (route, asset_type)。route='none' 表不入 transparent_assets。

    conservative：layerdiffuse_native → none（無 alpha 平圖，整批保證不 abort；
    83/90 件暫無真 alpha 是 DGX Route B pending 的硬限制傳導，非 importer 缺陷）。
    aggressive：明確自發光 role → vfx_additive/semi；其餘 → rembg/opaque。
    """
    if mode == "none":
        return "none", None
    # postprocess_matte 屬 spine（BiRefNet），已被 fitPolicy 過濾擋掉；防衛性同 none。
    if mode == "postprocess_matte":
        return "none", None
    # layerdiffuse_native
    if policy == "conservative":
        return "none", None
    if role in _VFX_ROLES:
        return "vfx_additive", "semi"
    return "rembg", "opaque"


# ---------- 分桶 ----------


def _bucket_key(item: dict) -> tuple[int, int]:
    g = item["genSize"]
    return int(g["w"]), int(g["h"])


def _group_adjacent_order(items: list[dict]) -> list[dict]:
    """consistencyGroup 組內相鄰排列（graft B 去矛盾版）：
    同組 member 連續 + seed_strategy=incremental → seed 落連續區間。
    排序鍵 =（該組首見位置, 原始位置），無組項視為單人組 → 整體仍保 manifest 順序。
    """
    first_seen: dict[str, int] = {}
    keyed = []
    for idx, it in enumerate(items):
        gid = it.get("consistencyGroupRef") or f"__solo_{idx}"
        if gid not in first_seen:
            first_seen[gid] = idx
        keyed.append((first_seen[gid], idx, it))
    keyed.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in keyed]


# ---------- open notes / 失真報告 ----------


def _build_open_notes(
    bucket_wh: tuple[int, int],
    bucket_items: list[dict],
    skipped_summary: str,
    policy: str,
    vfx_slugs: list[str],
    ta_present: bool,
) -> str:
    w, h = bucket_wh
    lines = [
        "- 來源：comfyui-reskin-manifest（uk:local-play gen-manifest --style 產出）",
        f"- genSize 桶：{w}x{h}（{len(bucket_items)} 件）；多桶分 plan 是 plan 級 size 結構限制，逐桶跑 gen --plan",
        f"- route-policy：{policy}",
    ]
    groups: dict[str, list[str]] = {}
    for it in bucket_items:
        gid = it.get("consistencyGroupRef")
        if gid:
            groups.setdefault(gid, []).append(it["id"])
    for gid, members in groups.items():
        lines.append(
            f"- consistencyGroup {gid}: {', '.join(members)} — 已相鄰排列 + incremental seed；建議同 LoRA 同批"
        )
    if policy == "conservative":
        lines.append(
            "- 失真：layerdiffuse_native 件以 route=none 平圖產出（無真 alpha）——"
            "DGX Route B LayerDiffuse pending 的傳導限制，補建後可重產"
        )
    for slug in vfx_slugs:
        lines.append(
            f"- ⚠️ vfx_additive: {slug} — gen 端會注入黑底後綴改寫 prompt（plan_runner.py:278 不可逆），人工覆核"
        )
    lines.append(
        "- 失真：negativeExtra / globalNegative 已丟棄（Flux 單 encoder 不吃 negative CFG）；"
        "finalSize/fitPolicy 的 resize 責任在下游 uk 消費端；textEmbed 疊字另軌不入 ar2"
    )
    if ta_present:
        lines.append(
            "- 部署前提：本 plan 含 transparent_assets，gen 消費時需 plan/gen/transparent 三 skill 同 commit（M-2）+ DGX rembg CPU patch"
        )
    if skipped_summary:
        lines.append(f"- 入表過濾：{skipped_summary}")
    return "\n".join(lines)


# ---------- 主流程 ----------


def from_manifest(
    manifest_path: str,
    plans_dir: Path,
    *,
    plan_id: str | None,
    title: str,
    route_policy: str = "conservative",
    workflow: str = "flux_basic",
    overwrite: bool = False,
) -> int:
    """manifest JSON → N 個 plans/{id}_{WxH}_outline.md（N = distinct genSize 桶）。"""
    if route_policy not in _ROUTE_POLICIES:
        return _fail(2, f"--route-policy 必須 {_ROUTE_POLICIES}，got {route_policy!r}")
    if not title:
        return _fail(2, "--title 必填（frontmatter required field）")

    # 讀 JSON（exit 3）
    src = manifest_path
    try:
        if manifest_path == "-":
            data = json.load(sys.stdin)
            src = "<stdin>"
        else:
            data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return _fail(3, f"manifest 讀取/解析失敗：{src}: {e}")
    if not isinstance(data, dict):
        return _fail(3, f"{src}: manifest 頂層必須是 JSON object")

    # 版本鎖（在讀任何 item 之前，exit 4）
    err = _assert_manifest_version(data, src)
    if err is not None:
        return _fail(4, err)

    # base id（過 validate_id；桶後綴另驗）
    styles = data.get("styles") or [{}]
    style0 = styles[0] if isinstance(styles, list) and styles else {}
    if plan_id is None:
        plan_id = "reskin_" + ps.slugify(str(style0.get("id") or "style"), max_len=24)
    try:
        ps.validate_id(plan_id)
    except ValueError as e:
        return _fail(2, f"--id 不合法：{e}")

    # 過濾 + 逐項驗證（exit 5 fail-fast）
    all_items = data.get("items") or []
    genworthy: list[dict] = []
    skipped: dict[str, int] = {}
    for it in all_items:
        fp = it.get("fitPolicy")
        if fp != _GENWORTHY_FIT_POLICY:
            skipped[fp or "<missing>"] = skipped.get(fp or "<missing>", 0) + 1
            continue
        mode = (it.get("alphaStrategy") or {}).get("mode")
        if mode not in _KNOWN_ALPHA_MODES:
            return _fail(5, _item_error(it, f"未知 alphaStrategy.mode={mode!r}（封閉 enum，不臆測）"))
        positive = (it.get("prompt") or {}).get("positive")
        if not positive or not str(positive).strip():
            return _fail(5, _item_error(it, "prompt.positive 為空"))
        slug = it.get("id")
        if not isinstance(slug, str) or not ps._ID_PATTERN.match(slug):
            return _fail(5, _item_error(it, "id 非 slug-legal（[a-z0-9][a-z0-9_]{0,63}）"))
        g = it.get("genSize")
        if not isinstance(g, dict) or not g.get("w") or not g.get("h"):
            return _fail(5, _item_error(it, f"genSize 缺 w/h：{g!r}"))
        genworthy.append(it)

    skipped_summary = "; ".join(f"{k}×{v}" for k, v in sorted(skipped.items()))
    if not genworthy:
        _warn(f"0 件 genworthy（{skipped_summary or '空 manifest'}），不產 outline")
        return 0

    # 分桶（genSize 結構性切分）+ 桶內 consistencyGroup 相鄰
    buckets: dict[tuple[int, int], list[dict]] = {}
    for it in genworthy:
        buckets.setdefault(_bucket_key(it), []).append(it)

    render_hints = data.get("renderHints") or {}
    steps = int(render_hints.get("steps") or 30)
    created = str(data.get("generatedAt") or "")[:10] or ps.now_iso()[:10]
    style_directive = str(style0.get("styleDirective") or "")

    plans_dir.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, Path, int]] = []
    total_vfx: list[str] = []

    # 桶排序：件數降冪、再依 (w,h)，輸出順序穩定（BC-9 determinism）
    for (w, h), bucket in sorted(buckets.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        bucket = _group_adjacent_order(bucket)
        bucket_id = f"{plan_id}_{w}x{h}"
        try:
            ps.validate_id(bucket_id)
        except ValueError as e:
            return _fail(2, f"桶 id {bucket_id!r} 不合法（--id 過長？）：{e}")
        out_path = plans_dir / f"{bucket_id}_outline.md"
        if out_path.exists() and not overwrite:
            return _fail(2, f"{out_path} 已存在（用 --overwrite 覆蓋）")

        ta_entries: dict[str, dict] = {}
        vfx_slugs: list[str] = []
        items: list[ps.Item] = []
        for it in bucket:
            slug = it["id"]
            mode = it["alphaStrategy"]["mode"]
            role = str(it.get("functionalRole") or "asset")
            route, asset_type = _resolve_route(mode, role, route_policy)
            if route != "none":
                # 不變量（BC-5）：產出永無 route=layerdiffuse；entry 必帶 asset_type（H2）。
                if route not in ("rembg", "vfx_additive") or not asset_type:
                    return _fail(5, _item_error(it, f"internal: route resolution broken（{route}/{asset_type}）"))
                # R-1：下游 asset_spec 比對是 case-insensitive（.lower()），守衛須對齊，
                # 否則大寫變體（如 "Mask"）穿過這裡、GPU 產圖後才在 postprocess raise。
                if role.lower() in _CATEGORY_RESERVED:
                    return _fail(5, _item_error(
                        it, f"functionalRole={role!r} 撞 asset_spec category 保留字 "
                            f"{sorted(_CATEGORY_RESERVED)}（前移守衛，避免 GPU 產圖後才 raise）"))
                ta_entries[slug] = {
                    "category": role,
                    "route": route,
                    "asset_type": asset_type,
                    # transparent route per-item size 為純量正方（plan_runner.py:273 w=h）。
                    "size": max(w, h),
                }
                if route == "vfx_additive":
                    vfx_slugs.append(slug)
            items.append(ps.Item(slug=slug, prompt=_one_line(str(it["prompt"]["positive"])), full=True))
        total_vfx.extend(vfx_slugs)

        plan = ps.Plan(
            id=bucket_id,
            title=f"{title} {w}x{h}",
            version=1,  # 整數（plan_schema.py:480 int(fm['version'])；字串 "1.0" 會 ValueError）
            created=created,
            updated=created,  # 與 created 同源 → 同 manifest 重跑 byte-identical（BC-9）
            status="ready",
            workflow=workflow,
            size=[w, h],  # plan 級兩維（plan_runner.py:335-336 消費 [0]/[1]）→ 桶內精確比例
            steps=steps,
            batch_per_item=1,  # gen plan 模式恆 1（plan_runner.py:333）
            seed_strategy={"type": "incremental", "base": 1000, "step": 1},
            story_vision=(
                f"換皮批次產圖：styleDirective = {style_directive or '(未提供)'}；"
                f"baseTheme = {data.get('baseTheme') or '(未提供)'}（僅追溯，不入 prompt）"
            ),
            # style anchor 維持 dataclass 預設 "(none)" ×3：positive 已 self-contained，
            # Negative 禁填 globalNegative（見模組 docstring 承重設計）。
            output_dir=f"outputs/ar2-dgx-comfyui-gen/{bucket_id}/",
            output_naming="{NN}_{slug}_{n}.png",
            items=items,
            open_notes=_build_open_notes(
                (w, h), bucket, skipped_summary, route_policy, vfx_slugs,
                ta_present=bool(ta_entries),
            ),
            transparent_assets=(
                {"defaults": dict(_TA_DEFAULTS), "items": ta_entries} if ta_entries else None
            ),
        )
        ps.atomic_write(out_path, ps.serialize(plan))
        written.append((bucket_id, out_path, len(items)))

    # 摘要
    sys.stdout.write(
        f"✅ {src} → {len(written)} 個 plan（genworthy {len(genworthy)} 件；"
        f"skip：{skipped_summary or '無'}；route-policy={route_policy}）\n"
    )
    for bucket_id, out_path, n in written:
        sys.stdout.write(f"   - {out_path}（{n} 件）→ ar2:dgx-comfyui-gen --plan {bucket_id}\n")
    if total_vfx:
        sys.stdout.write(
            f"⚠️ vfx_additive {len(total_vfx)} 件需人工覆核（黑底後綴改寫 prompt）："
            f"{', '.join(total_vfx)}\n"
        )
    return 0
