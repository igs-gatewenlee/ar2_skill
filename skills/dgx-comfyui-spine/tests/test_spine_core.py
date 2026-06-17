"""spine v1 本地核心契約測試（BC-1/2/3/4/5/7/8/10 + 閘4，DGX 無關，fixture-driven）。"""
import time

import numpy as np
import pytest
from PIL import Image, ImageDraw

import manifest_builder as mb
import spine_cut
import spine_qc
import spine_qc_thresholds as T
import spine_recompose


# ── fixtures：合成「白底角色」reference + 對齊的 part PNG + manifest ──

# 各部件在 reference 全圖座標的 rect (x0,y0,x1,y1)，互不重疊、皆在白底上
RECTS = {
    "head":        (85, 20, 116, 56),
    "torso":       (80, 60, 121, 141),
    "upper_arm_l": (50, 70, 79, 92),
    "upper_arm_r": (121, 70, 150, 92),
}
REF_SIZE = (200, 200)
COLORS = {"head": (240, 200, 180), "torso": (120, 150, 200),
          "upper_arm_l": (200, 160, 140), "upper_arm_r": (200, 160, 140)}


def _build_fixture(tmp_path, rects=RECTS, extra_fg=None):
    """產 reference.png（白底+彩塊）+ parts/*.png（裁好帶 alpha）+ manifest。回 (parts_dir, manifest, ref_path)。"""
    ref = Image.new("RGB", REF_SIZE, (255, 255, 255))
    rp = ref.load()
    for name, (x0, y0, x1, y1) in rects.items():
        for y in range(y0, y1):
            for x in range(x0, x1):
                rp[x, y] = COLORS[name]
    if extra_fg:  # 模擬「漏抓」：reference 有前景但無對應 part（PoC 尿布教訓）
        x0, y0, x1, y1 = extra_fg
        for y in range(y0, y1):
            for x in range(x0, x1):
                rp[x, y] = (90, 90, 90)
    ref_path = tmp_path / "reference.png"
    ref.save(ref_path)

    parts_dir = tmp_path / "parts"
    parts_dir.mkdir()
    parts = {}
    for name, (x0, y0, x1, y1) in rects.items():
        w, h = x1 - x0, y1 - y0
        part = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        pp = part.load()
        for y in range(h):
            for x in range(w):
                pp[x, y] = (*COLORS[name], 255)
        part.save(parts_dir / f"{name}.png")
        parts[name] = {"bbox": (x0, y0, w, h), "draw_order": T.DEFAULT_DRAW_ORDER.get(name, 1)}
    manifest = mb.build_manifest("reference.png", REF_SIZE, parts)
    return parts_dir, manifest, ref_path


# ── BC-1：content_bbox padding=0 + crop 尺寸嚴格相等 ──

def test_bc1_content_bbox_padding0_and_crop_size():
    full = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    a = np.asarray(full).copy()
    a[30:60, 20:50, :] = (255, 0, 0, 255)  # rows30-59 cols20-49
    full = Image.fromarray(a, "RGBA")
    bbox = mb.content_bbox(full)
    assert bbox == (20, 30, 30, 30)  # padding=0：無多餘邊界
    part = mb.crop_part(full, bbox)
    assert part.size == (bbox[2], bbox[3])  # BC-1：PNG 尺寸 == bbox (w,h)


def test_bc1_all_transparent_none():
    assert mb.content_bbox(Image.new("RGBA", (10, 10), (0, 0, 0, 0))) is None


# ── BC-5：pivot/rotation 標 best_effort ──

def test_bc5_best_effort_flags():
    m = mb.build_manifest("r.png", (50, 50), {"head": {"bbox": (1, 2, 3, 4), "draw_order": 1}})
    e = m["parts"]["head"]
    assert e["pivot"]["best_effort"] is True
    assert e["rotation"]["best_effort"] is True


# ── BC-7：draw_order 允許同層重複 / 非整數 fail ──

def test_bc7_draworder_duplicate_ok():
    m = mb.build_manifest("r.png", (200, 200), {
        "upper_arm_l": {"bbox": (10, 10, 20, 20), "draw_order": 2},
        "upper_arm_r": {"bbox": (50, 10, 20, 20), "draw_order": 2},  # L/R 同層
    })
    assert mb.validate_manifest(m) == []  # 同 draw_order 不判 fail


def test_bc7_draworder_non_int_fails():
    m = mb.build_manifest("r.png", (200, 200), {"head": {"bbox": (1, 1, 5, 5), "draw_order": 1}})
    m["parts"]["head"]["draw_order"] = 1.5
    assert any("draw_order" in e for e in mb.validate_manifest(m))


# ── BC-3 / validate：bbox 超界 / slug 非法 ──

def test_validate_bbox_out_of_bounds():
    m = mb.build_manifest("r.png", (50, 50), {"head": {"bbox": (40, 40, 30, 30), "draw_order": 1}})
    assert any("超出" in e for e in mb.validate_manifest(m))


# ── BC-4：recompose 獨立性 + desync 偵測 ──

def test_bc4_recompose_no_sam_import():
    # BC-4 獨立性：recompose 不把切件模組/後處理 transform import 進命名空間
    assert not hasattr(spine_recompose, "spine_sam")
    assert not hasattr(spine_recompose, "transparent_postprocess")
    assert not hasattr(spine_recompose, "pp")


def test_bc4_desync_drops_ssim(tmp_path):
    parts_dir, manifest, ref = _build_fixture(tmp_path)
    good = spine_qc.run_spine_qc(parts_dir, manifest, ref)
    assert good["gates"]["7_reassembly_ssim"]["status"] == "pass", good
    # 故意把 torso 的 manifest bbox 平移 30px（切件 transform 不變）→ desync
    manifest["parts"]["torso"]["bbox"][0] += 30
    bad = spine_qc.run_spine_qc(parts_dir, manifest, ref)
    assert bad["gates"]["7_reassembly_ssim"]["status"] == "fail", bad


# ── 閘1 齊全 / 閘2 bijection / BC-8 中間檔過濾 ──

def test_gate1_complete_pass_and_missing(tmp_path):
    parts_dir, manifest, ref = _build_fixture(tmp_path)
    assert spine_qc.run_spine_qc(parts_dir, manifest, ref)["gates"]["1_complete"]["status"] == "pass"
    # 抽掉 torso（manifest + disk 都拿掉）→ 閘1 fail
    del manifest["parts"]["torso"]
    (parts_dir / "torso.png").unlink()
    rep = spine_qc.run_spine_qc(parts_dir, manifest, ref)
    assert rep["gates"]["1_complete"]["status"] == "fail"
    assert "torso" in rep["gates"]["1_complete"]["detail"]


def test_bc8_intermediate_files_ignored(tmp_path):
    parts_dir, manifest, ref = _build_fixture(tmp_path)
    # 丟切件中間檔進 parts/（hint_/sam_/legmask_）→ bijection 不該被它們破壞
    for junk in ("hint_head.png", "sam_character.png", "legmask_leg_l.png"):
        Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(parts_dir / junk)
    rep = spine_qc.run_spine_qc(parts_dir, manifest, ref)
    assert rep["gates"]["2_bijection"]["status"] == "pass", rep["gates"]["2_bijection"]


def test_gate2_real_extra_part_fails(tmp_path):
    parts_dir, manifest, ref = _build_fixture(tmp_path)
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(parts_dir / "foot.png")  # 非中間檔前綴
    rep = spine_qc.run_spine_qc(parts_dir, manifest, ref)
    assert rep["gates"]["2_bijection"]["status"] == "fail"


# ── BC-10：覆蓋率閘抓相連漏抓（PoC 尿布教訓）──

def test_bc10_coverage_pass_full(tmp_path):
    parts_dir, manifest, ref = _build_fixture(tmp_path)
    assert spine_qc.run_spine_qc(parts_dir, manifest, ref)["gates"]["8_coverage"]["status"] == "pass"


def test_bc10_coverage_fail_gross_miss(tmp_path):
    # bbox 聯集區內「大塊」前景漏抓（模擬整部件/大區沒切，如 PoC 尿布 63%）→ < 0.70 gross fail
    parts_dir, manifest, ref = _build_fixture(tmp_path, extra_fg=(50, 95, 150, 140))
    rep = spine_qc.run_spine_qc(parts_dir, manifest, ref)
    assert rep["gates"]["8_coverage"]["status"] == "fail", rep["gates"]["8_coverage"]


def test_bc10_coverage_warn_seam_loss(tmp_path):
    # bbox 區內「小塊」漏抓（seam 級，0.70~0.97）→ warning 非 fail（誠實標需 dilate/更緊 hints）
    parts_dir, manifest, ref = _build_fixture(tmp_path, extra_fg=(52, 100, 78, 138))
    rep = spine_qc.run_spine_qc(parts_dir, manifest, ref)
    assert rep["gates"]["8_coverage"]["status"] == "warning", rep["gates"]["8_coverage"]


def test_bc10_coverage_ignores_out_of_scope_region(tmp_path):
    # reference 在「部件 bbox 聯集區外」有前景（如全身圖下半身腿）→ v1 上肢 scope 不該被罰 → pass
    parts_dir, manifest, ref = _build_fixture(tmp_path, extra_fg=(70, 160, 130, 195))
    rep = spine_qc.run_spine_qc(parts_dir, manifest, ref)
    assert rep["gates"]["8_coverage"]["status"] == "pass", rep["gates"]["8_coverage"]


# ── 閘4：上肢分離 ──

def test_gate4_arm_separation_pass(tmp_path):
    parts_dir, manifest, ref = _build_fixture(tmp_path)
    assert spine_qc.run_spine_qc(parts_dir, manifest, ref)["gates"]["4_arm_separation"]["status"] == "pass"


def test_gate4_arm_overlap_fails(tmp_path):
    # 讓左右臂 bbox 重疊 → 重疊率 > 5% fail
    rects = dict(RECTS)
    rects["upper_arm_r"] = (60, 70, 89, 92)  # 與 upper_arm_l(50-79) 大幅重疊
    parts_dir, manifest, ref = _build_fixture(tmp_path, rects=rects)
    rep = spine_qc.run_spine_qc(parts_dir, manifest, ref)
    assert rep["gates"]["4_arm_separation"]["status"] == "fail", rep["gates"]["4_arm_separation"]


# ── spine_cut：hint∩前景 primitive（白底，多色不漏）──

def test_spine_cut_foreground_white_vs_color():
    ref = Image.new("RGB", (40, 40), (255, 255, 255))
    ref.load()[20, 20] = (90, 60, 40)
    fg = spine_cut.foreground_mask(ref)
    assert not fg[0, 0]      # 白底=非前景
    assert fg[20, 20]        # 有色=前景


def test_spine_cut_multicolor_part_not_dropped():
    # 雙色 blob（上半棕=髮、下半膚）+ hint 覆蓋 → hint∩前景 抓「整個雙色 blob」
    # （SAM 單 seed 會只抓一色，此測證 hintfg 不漏色）
    ref = Image.new("RGB", (100, 100), (255, 255, 255))
    rp = ref.load()
    for y in range(20, 50):
        for x in range(30, 70):
            rp[x, y] = (90, 60, 40)       # 髮
    for y in range(50, 80):
        for x in range(30, 70):
            rp[x, y] = (240, 200, 180)    # 膚
    hint = Image.new("L", (100, 100), 0)
    ImageDraw.Draw(hint).rectangle((25, 15, 75, 85), fill=255)
    full, bbox = spine_cut.cut_part(ref, hint)
    assert bbox == (30, 20, 40, 60)                    # 整個雙色 blob 的 bbox
    a = np.asarray(mb.crop_part(full, bbox))[..., 3]
    assert (a > 0).sum() == 40 * 60                    # 髮+膚兩色全抓、不漏


def test_spine_cut_empty_when_hint_misses_fg():
    ref = Image.new("RGB", (40, 40), (255, 255, 255))
    ref.load()[5, 5] = (10, 10, 10)
    hint = Image.new("L", (40, 40), 0)
    ImageDraw.Draw(hint).rectangle((20, 20, 35, 35), fill=255)  # hint 在白底區
    full, bbox = spine_cut.cut_part(ref, hint)
    assert full is None and bbox is None


def test_spine_cut_dilate_grows_within_fg_only():
    # 水平前景條 + 只蓋左半的 hint；dilate 後往右長（夾前景）覆蓋更多、但不長進背景
    ref = Image.new("RGB", (60, 30), (255, 255, 255))
    rp = ref.load()
    for y in range(10, 20):
        for x in range(5, 55):
            rp[x, y] = (50, 50, 50)
    hint = Image.new("L", (60, 30), 0)
    ImageDraw.Draw(hint).rectangle((5, 8, 25, 22), fill=255)
    f0, _ = spine_cut.cut_part(ref, hint, dilate=0)
    f1, _ = spine_cut.cut_part(ref, hint, dilate=6)
    a0 = int((np.asarray(f0)[..., 3] > 0).sum())
    a1 = int((np.asarray(f1)[..., 3] > 0).sum())
    assert a1 > a0  # dilate 後覆蓋更多前景（關縫）
    fg = spine_cut.foreground_mask(ref)
    assert int(((np.asarray(f1)[..., 3] > 0) & ~fg).sum()) == 0  # 不長進背景


# ════════════════════════════════════════════════════════════════════════
# spine-15：spine_sam.build_sam_workflow() JSON 注入邏輯（純函式，零外部依賴）
#   conftest 已把 scripts/ 掛上 sys.path；spine_sam 讀靜態 sam_part.json + strip + inject。
# ════════════════════════════════════════════════════════════════════════

import spine_sam  # noqa: E402  （此前無任何 test import 它，build_sam_workflow 完全未測）


def test_build_sam_workflow_strips_comment():
    # BC-6：送 /prompt 前 strip 非 dict 頂層 key（_comment）；節點集合鎖 1..7
    wf = spine_sam.build_sam_workflow("c.png", "h.png", "p")
    assert "_comment" not in wf
    assert all(isinstance(v, dict) for v in wf.values())
    assert sorted(wf.keys()) == ["1", "2", "3", "4", "5", "6", "7"]


def test_build_sam_workflow_injection():
    # 三個注入點：char→node1、hint→node2、prefix→node7
    wf = spine_sam.build_sam_workflow("c.png", "h.png", "p")
    assert wf["1"]["inputs"]["image"] == "c.png"
    assert wf["2"]["inputs"]["image"] == "h.png"
    assert wf["7"]["inputs"]["filename_prefix"] == "p"


def test_build_sam_workflow_node_class_contract():
    # 鎖 JSON↔code 的 node 映射，防 sam_part.json 重新編號靜默把值寫進錯節點
    wf = spine_sam.build_sam_workflow("c.png", "h.png", "p")
    assert wf["1"]["class_type"] == "LoadImage"
    assert wf["2"]["class_type"] == "LoadImageMask"
    assert wf["7"]["class_type"] == "SaveImage"


def test_build_sam_workflow_preserves_other_nodes():
    # 未注入的 node（SAMDetectorCombined）預設值原樣保留 → 確認 strip/inject 沒誤刪未動節點
    wf = spine_sam.build_sam_workflow("c.png", "h.png", "p")
    assert wf["5"]["class_type"] == "SAMDetectorCombined"
    assert wf["5"]["inputs"]["threshold"] == 0.93


def test_build_sam_workflow_distinct_args_no_crosstalk():
    # 不同呼叫的三參數各自獨立、互不串味（防注入點寫錯欄位）
    wf = spine_sam.build_sam_workflow("CHAR.png", "HINT.png", "PREFIX")
    assert wf["1"]["inputs"]["image"] == "CHAR.png"
    assert wf["2"]["inputs"]["image"] == "HINT.png"
    assert wf["7"]["inputs"]["filename_prefix"] == "PREFIX"
    # node2 的 channel 預設不被 image 注入污染
    assert wf["2"]["inputs"]["channel"] == "red"


# ════════════════════════════════════════════════════════════════════════
# spine-16：spine.run() 編排/arg-routing 邏輯
#   hintfg + --reference 路徑 100% 純本地（檔案 I/O + numpy/PIL，零 DGX）。
#   全程 monkeypatch DGX 依賴成 raise（守恆斷言）；用合成白底 reference + 對齊 hint-dir。
#   hermetic（F-1）：delenv 兩個 env → 再把 AR2_OUTPUT_ROOT 指向 tmp_path 控制落點。
# ════════════════════════════════════════════════════════════════════════

import spine  # noqa: E402  （此前無任何 test import spine / 觸 run()）


class _Args:
    """模擬 argparse.Namespace（run() 只讀屬性）。"""

    def __init__(self, **kw):
        self.character_id = None
        self.hint_dir = None
        self.reference = None
        self.prompt = None
        self.size = 1024
        self.seed = 20260615
        self.method = "hintfg"
        self.dilate = 0
        for k, v in kw.items():
            setattr(self, k, v)


def _make_spine_ref(tmp_path, rects=RECTS):
    """合成白底 reference.png（同 _build_fixture 的彩塊配置），回 ref 路徑。"""
    ref = Image.new("RGB", REF_SIZE, (255, 255, 255))
    rp = ref.load()
    for name, (x0, y0, x1, y1) in rects.items():
        for y in range(y0, y1):
            for x in range(x0, x1):
                rp[x, y] = COLORS[name]
    ref_path = tmp_path / "ref.png"
    ref.save(ref_path)
    return ref_path


def _make_hint_dir(tmp_path, names, rects=RECTS):
    """每件造一個略大於 rect 的白底 hint PNG（hintfg 會 ∩ 前景），回 hint-dir 路徑。"""
    hint_dir = tmp_path / "hints"
    hint_dir.mkdir()
    for name in names:
        x0, y0, x1, y1 = rects[name]
        h = Image.new("L", REF_SIZE, 0)
        ImageDraw.Draw(h).rectangle((x0 - 2, y0 - 2, x1 + 1, y1 + 1), fill=255)
        h.save(hint_dir / f"{name}.png")
    return hint_dir


def _block_dgx(monkeypatch):
    """把四個 DGX 依賴全 monkeypatch 成 raise-on-call（守恆：被呼叫即測試失敗）。"""
    def boom(*a, **k):
        raise AssertionError("DGX 依賴在純本地路徑被呼叫了（need_dgx 判定錯）")

    monkeypatch.setattr(spine.ssh_client, "ensure_tunnel", boom)
    monkeypatch.setattr(spine.ssh_client, "scp_put", boom)
    monkeypatch.setattr(spine.ssh_client, "scp_get", boom)
    monkeypatch.setattr(spine.comfyui_api, "submit_prompt", boom)


def _run_folder(tmp_path, run_tag):
    """run() 的輸出夾路徑（_output_root()/outputs/.../{date}_{tag}）。"""
    return (tmp_path / "outputs" / "ar2-dgx-comfyui-spine"
            / f"{time.strftime('%Y-%m-%d')}_{run_tag}")


def test_run_hintfg_reference_is_fully_local(tmp_path, monkeypatch):
    # need_dgx=(not reference) or method=='sam' → hintfg+reference 為 False → 全本地、零 DGX
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("AR2_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    _block_dgx(monkeypatch)

    ref_path = _make_spine_ref(tmp_path)
    hint_dir = _make_hint_dir(tmp_path, T.EXPECTED_PARTS)
    args = _Args(character_id="loc", hint_dir=str(hint_dir),
                 reference=str(ref_path), method="hintfg", dilate=0)
    rc = spine.run(args)  # 任一 DGX mock 被碰 → boom AssertionError；能回來即證純本地

    assert rc == 0  # 四件齊全 → QC pass → exit 0
    folder = _run_folder(tmp_path, "loc")
    for name in T.EXPECTED_PARTS:
        assert (folder / "parts" / f"{name}.png").exists()
    assert (folder / "manifest.json").exists()
    assert (folder / "qc_report.json").exists()


def test_run_exit_code_fail_returns_2(tmp_path, monkeypatch, capsys):
    # hint-dir 只放 head.png → 缺件 warning loop（EXPECTED_PARTS 驅動）+ 閘1 missing → fail → rc 2
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("AR2_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    _block_dgx(monkeypatch)

    ref_path = _make_spine_ref(tmp_path)
    hint_dir = _make_hint_dir(tmp_path, ["head"])  # 只 head，缺 torso/upper_arm_l/upper_arm_r
    args = _Args(character_id="fail", hint_dir=str(hint_dir),
                 reference=str(ref_path), method="hintfg")
    rc = spine.run(args)

    out = capsys.readouterr().out
    assert "缺必備 hint torso.png" in out
    assert "缺必備 hint upper_arm_l.png" in out
    assert "缺必備 hint upper_arm_r.png" in out
    assert rc == 2  # result=='fail' → return 0 if result!='fail' else 2 契約


def test_run_dilate_routed_to_cut_part(tmp_path, monkeypatch):
    # --dilate 應原值透傳到 spine_cut.cut_part（hintfg 路徑）
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("AR2_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    _block_dgx(monkeypatch)

    real_cut = spine_cut.cut_part
    seen = {}

    def spy(ref_img, hint_img, **kw):
        seen.setdefault("dilate", kw.get("dilate"))  # 記第一次的 dilate
        return real_cut(ref_img, hint_img, **kw)

    monkeypatch.setattr(spine.spine_cut, "cut_part", spy)

    ref_path = _make_spine_ref(tmp_path)
    hint_dir = _make_hint_dir(tmp_path, T.EXPECTED_PARTS)
    args = _Args(character_id="dil", hint_dir=str(hint_dir),
                 reference=str(ref_path), method="hintfg", dilate=6)
    spine.run(args)

    assert seen.get("dilate") == 6  # 透傳正確（非 0/None）


def test_run_reference_skips_generation(tmp_path, monkeypatch):
    # 帶 --reference → 不走 _gen_reference（submit_prompt raise 不被觸發）；
    # 且 folder/reference.png 內容 == 給定 reference（轉 RGB 後）
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("AR2_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    _block_dgx(monkeypatch)  # 含 submit_prompt=boom → 若誤入 _gen_reference 會炸

    ref_path = _make_spine_ref(tmp_path)
    hint_dir = _make_hint_dir(tmp_path, T.EXPECTED_PARTS)
    args = _Args(character_id="skip", hint_dir=str(hint_dir),
                 reference=str(ref_path), method="hintfg")
    rc = spine.run(args)  # 不 raise 即證明沒走生成路徑

    assert rc == 0
    folder = _run_folder(tmp_path, "skip")
    saved = np.asarray(Image.open(folder / "reference.png").convert("RGB"))
    given = np.asarray(Image.open(ref_path).convert("RGB"))
    assert np.array_equal(saved, given)  # 既有 reference 原樣落地（轉 RGB）
