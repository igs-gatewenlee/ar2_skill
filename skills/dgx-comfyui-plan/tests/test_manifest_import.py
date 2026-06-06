"""plan_manifest_import（--from-manifest）BC 測試。

承重原則（#012 AND 邏輯 / #011 真跑不靜態推論）：
- BC-1 不只驗「檔案存在」，真跑 ps.parse round-trip（version 必須是 int —
  三個設計方案都曾誤填字串 "1.0"，int("1.0") raise ValueError 的歷史教訓）。
- BC-2/3 真餵 gen 端 plan_loader._expand_items + workflow_params.inject +
  真 flux_basic.json（route=none item 的 negative 路徑不撞
  「no second CLIPTextEncode」—— B 方案整批零產出 fatal 的回歸測試）。
- BC-5 反向遍歷：最毒組合（aggressive + 全 layerdiffuse_native）下產出
  grep 不到 route=layerdiffuse。
"""
import copy
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
GEN_SCRIPTS = Path(__file__).resolve().parents[2] / "dgx-comfyui-gen" / "scripts"
GEN_WORKFLOWS = Path(__file__).resolve().parents[2] / "dgx-comfyui-gen" / "workflows"
sys.path.insert(0, str(SCRIPTS))
import plan_schema as ps  # noqa: E402
import plan_manifest_import as pmi  # noqa: E402


# ---------- fixture ----------

def _fixture_manifest() -> dict:
    """最小 manifest：2 桶（1024x1024 ×2 件、640x1024 ×1 件）+ 1 skip spine +
    含 `|` prompt + 含換行 prompt + globalNegative 非空 + consistencyGroup。"""
    return {
        "schemaName": "comfyui-reskin-manifest",
        "schemaVersion": "1.0.0",
        "generatedAt": "2026-06-05T12:00:00Z",
        "baseTheme": "robinhood",
        "source": {"catalogPath": "docs/ASSET_CATALOG.md", "ref": "test"},
        "styles": [{
            "id": "teststyle",
            "styleDirective": "賽博龐克霓虹",
            "stylePrompt": "cyberpunk neon",
            "globalNegative": "blurry, lowres",  # 必須被丟棄（BC-2 承重）
            "lora": "<STYLE_LORA_PLACEHOLDER>",
        }],
        "locales": [],
        "renderHints": {"steps": 30, "sampler": "dpmpp_2m"},
        "consistencyGroups": {
            "grp_sym": {"consistencyReason": "同符號群", "members": ["sym_a", "sym_b"]},
        },
        "expectedCounts": {"img": 3, "spine": 1},
        "items": [
            {
                "id": "sym_a", "kind": "img", "functionalRole": "high_symbol",
                "fitPolicy": "gen_bucket_then_resize",
                "genSize": {"w": 1024, "h": 1024}, "finalSize": {"w": 900, "h": 900},
                "alphaStrategy": {"mode": "layerdiffuse_native", "graphImpact": "x"},
                "prompt": {"positive": "ornate gold emblem | jeweled crest, centered",
                           "negativeExtra": "text"},
                "consistencyGroupRef": "grp_sym",
                "outputPath": "assets/game/img/sym_a.png",
            },
            {
                "id": "plain_bg", "kind": "img", "functionalRole": "bg_fullscreen",
                "fitPolicy": "gen_bucket_then_resize",
                "genSize": {"w": 1024, "h": 1024}, "finalSize": {"w": 1024, "h": 1024},
                "alphaStrategy": {"mode": "none", "graphImpact": "none"},
                "prompt": {"positive": "lush forest\nbackground, wide view"},
                "outputPath": "assets/game/img/bg.png",
            },
            {
                "id": "sym_b", "kind": "img", "functionalRole": "low_symbol",
                "fitPolicy": "gen_bucket_then_resize",
                "genSize": {"w": 640, "h": 1024}, "finalSize": {"w": 600, "h": 980},
                "alphaStrategy": {"mode": "layerdiffuse_native", "graphImpact": "x"},
                "prompt": {"positive": "silver arrow badge, centered"},
                "consistencyGroupRef": "grp_sym",
                "outputPath": "assets/game/img/sym_b.png",
            },
            {
                "id": "spine_x", "kind": "spine", "functionalRole": "wild",
                "fitPolicy": "skip_not_genworthy",
                "genSize": {"w": 0, "h": 0}, "finalSize": None,
                "alphaStrategy": {"mode": "postprocess_matte", "graphImpact": "n"},
                "prompt": {"positive": "(not generated)"},
                "outputPath": "assets/game/spine/x",
            },
        ],
    }


def _run(tmp_path, manifest=None, **kw):
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps(manifest or _fixture_manifest(), ensure_ascii=False))
    plans = tmp_path / "plans"
    defaults = dict(plan_id="reskin_test", title="測試換皮", overwrite=True)
    defaults.update(kw)
    rc = pmi.from_manifest(str(mf), plans, **defaults)
    return rc, plans


def _outlines(plans: Path) -> list[Path]:
    return sorted(plans.glob("*_outline.md"))


# ---------- BC-1：產出可被 plan_schema 解析（version=int、必填齊、sections 齊）----------

def test_bc1_parse_roundtrip(tmp_path):
    rc, plans = _run(tmp_path)
    assert rc == 0
    outs = _outlines(plans)
    assert len(outs) == 2  # 2 個 genSize 桶
    for out in outs:
        plan = ps.parse(out)  # 不 raise = frontmatter/sections/items 全合法
        assert isinstance(plan.version, int) and plan.version == 1
        assert plan.status == "ready"
        assert plan.batch_per_item == 1
        assert plan.seed_strategy["type"] == "incremental"


def test_bc1_bucket_sizes_exact(tmp_path):
    """plan 級 size 兩維精確比例（分桶承重：零失真）。"""
    rc, plans = _run(tmp_path)
    sizes = {tuple(ps.parse(o).size) for o in _outlines(plans)}
    assert sizes == {(1024, 1024), (640, 1024)}


# ---------- BC-2/3：gen 端端到端（plan_loader 展開 + flux_basic inject 不 raise）----------

def _gen_load(outline: Path):
    sys.path.insert(0, str(GEN_SCRIPTS))
    try:
        import plan_loader  # noqa: E402
        return plan_loader._load(outline, mode="plan")
    finally:
        sys.path.remove(str(GEN_SCRIPTS))


def test_bc2_bc3_gen_end_to_end(tmp_path):
    rc, plans = _run(tmp_path)
    manifest = _fixture_manifest()
    positives = {i["id"]: " ".join(i["prompt"]["positive"].split())
                 for i in manifest["items"] if i["fitPolicy"] == "gen_bucket_then_resize"}
    template = json.loads((GEN_WORKFLOWS / "flux_basic.json").read_text())
    sys.path.insert(0, str(GEN_SCRIPTS))
    try:
        import workflow_params  # noqa: E402
        for out in _outlines(plans):
            loaded = _gen_load(out)
            # BC-2 承重：Negative=(none) → loaded.negative=""，`or None` 跳過注入，
            # 單 CLIPTextEncode 的 flux_basic 不 raise（B 方案 fatal 回歸）。
            assert loaded.negative == ""
            for item in loaded.items:
                assert item.route == "none"  # conservative：全不入 transparent
                # BC-3 承重：full=✓ → final_prompt verbatim == manifest positive。
                assert item.final_prompt == positives[item.slug]
                workflow_params.inject(
                    copy.deepcopy(template),
                    prompt=item.final_prompt,
                    negative_prompt=(loaded.negative or None),
                    seed=item.seed, steps=loaded.steps, batch_size=1,
                    width=loaded.size[0], height=loaded.size[1],
                )  # 不 raise = 端到端可消費
    finally:
        sys.path.remove(str(GEN_SCRIPTS))


def test_bc3_globalnegative_dropped(tmp_path):
    """globalNegative 必須被丟棄（不得出現在任何產出）。"""
    rc, plans = _run(tmp_path)
    for out in _outlines(plans):
        text = out.read_text()
        assert "blurry, lowres" not in text
        assert "**Negative**: (none)" in text


# ---------- BC-4：skip 過濾（雙向反向遍歷）----------

def test_bc4_skip_filtering_bidirectional(tmp_path):
    rc, plans = _run(tmp_path)
    slugs: set[str] = set()
    for out in _outlines(plans):
        slugs |= {i.slug for i in ps.parse(out).items}
    assert slugs == {"sym_a", "plain_bg", "sym_b"}  # 入表 = genworthy 全集
    assert "spine_x" not in slugs  # skip 不入表


# ---------- BC-5/6：route 白名單 + asset_type + category 守衛（aggressive 最毒組合）----------

def test_bc5_aggressive_no_layerdiffuse(tmp_path):
    rc, plans = _run(tmp_path, route_policy="aggressive")
    assert rc == 0
    saw_ta = False
    for out in _outlines(plans):
        text = out.read_text()
        assert "layerdiffuse" not in text  # 反向遍歷：整份產出零命中
        plan = ps.parse(out)
        ta = plan.transparent_assets
        if ta:
            saw_ta = True
            for slug, entry in ta["items"].items():
                assert entry["route"] in ("rembg", "vfx_additive")
                assert entry["asset_type"] in ("opaque", "semi")
                assert entry["category"] not in ("source", "mask", "rgb", "alpha", "preview")
            # BC-6：ta slug ⊆ items slug
            assert set(ta["items"]) <= {i.slug for i in plan.items}
    assert saw_ta  # aggressive + layerdiffuse_native 件存在 → 必有 transparent block


def test_bc5_vfx_no_rembg_param_and_inject_ok(tmp_path):
    """2026-06-06 runtime bug 回歸：bg_remove_strength 是 rembg 專屬 inject 參數
    （InspyrenetRembgAdvanced.threshold），不可經 defaults 漏進 vfx entry —
    否則 vfx_additive.json 無該節點 → inject raise、vfx 件全失敗。"""
    m = _fixture_manifest()
    m["items"][0]["functionalRole"] = "light"  # sym_a → vfx_additive
    rc, plans = _run(tmp_path, manifest=m, route_policy="aggressive")
    assert rc == 0
    vfx_template = json.loads((GEN_WORKFLOWS.parent.parent / "dgx-comfyui-transparent" / "workflows" / "vfx_additive.json").read_text())
    sys.path.insert(0, str(GEN_SCRIPTS))
    try:
        import plan_loader  # noqa: E402
        import workflow_params  # noqa: E402
        seen_vfx = False
        for out in _outlines(plans):
            plan = ps.parse(out)
            ta = plan.transparent_assets
            if not ta: continue
            assert "bg_remove_strength" not in ta.get("defaults", {})  # defaults 禁含 rembg 專屬
            for slug, entry in ta["items"].items():
                if entry["route"] == "vfx_additive":
                    assert "bg_remove_strength" not in (entry.get("params") or {})
                if entry["route"] == "rembg":
                    assert (entry.get("params") or {}).get("bg_remove_strength") == 0.5  # rembg 保留
            loaded = plan_loader._load(out, mode="plan")
            for item in loaded.items:
                if item.route != "vfx_additive": continue
                seen_vfx = True
                # 端到端：vfx item 的 transparent params 餵 vfx_additive.json inject 不 raise
                assert "bg_remove_strength" not in (item.transparent or {})
                # 重現 plan_runner 注入路徑：vfx 的 transparent params 無 bg_remove_strength
                # → 傳 None → inject 跳過 rembg 節點檢查（舊 bug：0.5 → raise）
                workflow_params.inject(
                    copy.deepcopy(vfx_template),
                    prompt=item.final_prompt, negative_prompt=None,
                    seed=item.seed, steps=loaded.steps, batch_size=1,
                    width=512, height=512,
                    bg_remove_strength=(item.transparent or {}).get("bg_remove_strength"),
                )
        assert seen_vfx  # fixture 必須真的產生 vfx 路徑（防偽綠）
    finally:
        sys.path.remove(str(GEN_SCRIPTS))


def test_bc5_conservative_no_transparent_block(tmp_path):
    """conservative：全 route=none → transparent_assets 整塊不存在（無冗餘 entry）。"""
    rc, plans = _run(tmp_path)
    for out in _outlines(plans):
        assert ps.parse(out).transparent_assets is None


# ---------- BC-7：manifest 版本鎖（exit 4，且斷言在讀 item 之前）----------

def test_bc7_version_lock_major_mismatch(tmp_path):
    m = _fixture_manifest()
    m["schemaVersion"] = "2.0.0"
    rc, _ = _run(tmp_path, manifest=m)
    assert rc == 4


def test_bc7_version_lock_wrong_schema_name(tmp_path):
    m = _fixture_manifest()
    m["schemaName"] = "something-else"
    rc, _ = _run(tmp_path, manifest=m)
    assert rc == 4


def test_bc7_assert_before_item_read():
    """反向遍歷：源碼中版本斷言（_assert_manifest_version 呼叫）必須出現在
    items 讀取之前（行號序 = 執行序，from_manifest 是直線流程）。"""
    src = (SCRIPTS / "plan_manifest_import.py").read_text()
    body = src[src.index("def from_manifest"):]
    assert body.index("_assert_manifest_version") < body.index('data.get("items")')


# ---------- BC-8：prompt 字元邊界（| escape round-trip + 換行剝除）----------

def test_bc8_pipe_escape_and_newline(tmp_path):
    rc, plans = _run(tmp_path)
    seen = set()
    for out in _outlines(plans):
        plan = ps.parse(out)
        for i in plan.items:
            seen.add(i.slug)
            if i.slug == "sym_a":
                assert i.prompt == "ornate gold emblem | jeweled crest, centered"
            if i.slug == "plain_bg":
                assert "\n" not in i.prompt
                assert i.prompt == "lush forest background, wide view"
    assert {"sym_a", "plain_bg"} <= seen


# ---------- BC-9：determinism + 桶切分 ----------

def test_bc9_deterministic_reruns(tmp_path):
    rc1, plans = _run(tmp_path)
    first = {p.name: p.read_text() for p in _outlines(plans)}
    rc2, plans = _run(tmp_path)  # overwrite=True 重跑
    second = {p.name: p.read_text() for p in _outlines(plans)}
    assert first == second  # byte-identical（created/updated 取自 generatedAt）


def test_bc9_group_adjacency():
    """consistencyGroup 成員相鄰（同桶內）。"""
    items = [
        {"id": "a", "consistencyGroupRef": "g1"},
        {"id": "x"},
        {"id": "b", "consistencyGroupRef": "g1"},
        {"id": "y"},
    ]
    ordered = [i["id"] for i in pmi._group_adjacent_order(items)]
    assert ordered.index("b") == ordered.index("a") + 1  # g1 成員相鄰


# ---------- exit codes / 邊界 ----------

def test_exit3_bad_json(tmp_path):
    mf = tmp_path / "bad.json"
    mf.write_text("{not json")
    rc = pmi.from_manifest(str(mf), tmp_path / "plans", plan_id="x", title="t")
    assert rc == 3


def test_exit5_reserved_category_case_insensitive(tmp_path):
    """R-1 回歸：大寫保留字變體（'Mask'）也要被擋（下游 asset_spec 比對是
    case-insensitive，守衛大小寫不對齊會讓它 GPU 產圖後才 raise）。"""
    m = _fixture_manifest()
    m["items"][0]["functionalRole"] = "Mask"
    rc, _ = _run(tmp_path, manifest=m, route_policy="aggressive")
    assert rc == 5


def test_exit5_unknown_alpha_mode(tmp_path):
    m = _fixture_manifest()
    m["items"][0]["alphaStrategy"]["mode"] = "magic_unknown"
    rc, _ = _run(tmp_path, manifest=m)
    assert rc == 5


def test_exit2_existing_without_overwrite(tmp_path):
    rc1, plans = _run(tmp_path)
    assert rc1 == 0
    rc2, _ = _run(tmp_path, overwrite=False)
    assert rc2 == 2


def test_zero_genworthy_warns_exit0(tmp_path):
    m = _fixture_manifest()
    for it in m["items"]:
        it["fitPolicy"] = "skip_not_genworthy"
    rc, plans = _run(tmp_path, manifest=m)
    assert rc == 0
    assert not _outlines(plans)


# ---------- 安全（負面斷言：產出與源碼零連線資訊）----------

def test_security_no_secrets_in_output(tmp_path):
    rc, plans = _run(tmp_path)
    src = (SCRIPTS / "plan_manifest_import.py").read_text()
    for blob in [src] + [o.read_text() for o in _outlines(plans)]:
        for needle in ("192.168.5.27", "PASSWORD", "root@", "ssh "):
            assert needle not in blob


# ---------- CLI dispatch（subprocess 黑箱，接線驗證）----------

def test_cli_dispatch_subprocess(tmp_path):
    mf = tmp_path / "m.json"
    mf.write_text(json.dumps(_fixture_manifest(), ensure_ascii=False))
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "plan_main.py"),
         "--from-manifest", str(mf), "--title", "t", "--id", "cli_test"],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "plans" / "cli_test_1024x1024_outline.md").exists()


def test_cli_missing_title_exit2(tmp_path):
    mf = tmp_path / "m.json"
    mf.write_text(json.dumps(_fixture_manifest(), ensure_ascii=False))
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "plan_main.py"), "--from-manifest", str(mf)],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert r.returncode == 2
