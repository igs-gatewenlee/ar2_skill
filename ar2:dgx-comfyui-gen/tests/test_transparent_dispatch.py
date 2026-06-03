"""T3 per-route dispatch + M-1 前綴保留 + postprocess hook（BC-7 / BC-9 / BC-11）。"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import plan_runner  # noqa: E402

RI = plan_runner.plan_loader.ResolvedItem
LP = plan_runner.plan_loader.LoadedPlan


def _loaded(items, **kw):
    base = dict(raw=None, items=items, workflow="flux_basic", size=[1024, 1024],
                steps=20, lora=[], face_ref=None, pulid_weight=None,
                negative="", output_dir="", mode="plan")
    base.update(kw)
    return LP(**base)


# ── BC-9：透明 route 前綴不被 inject 覆寫（M-1 核心防線）──────────

def test_bc9_transparent_prefix_preserved_real_workflow():
    tmpl = plan_runner.plan_loader.strip_workflow_metadata(
        json.loads(plan_runner._resolve_route_workflow("rembg").read_text()))
    item = RI(index=1, slug="coin", final_prompt="gold coin", seed=7,
              filename_prefix="01_coin", route="rembg", asset_type="opaque",
              transparent={"bg_remove_strength": 0.6, "size": 512})
    wf = plan_runner._inject_transparent(tmpl, item, _loaded([item]), "myrun")

    saves = [n for n in wf.values()
             if isinstance(n, dict) and n.get("class_type") == "SaveImage"]
    prefixes = sorted(n["inputs"]["filename_prefix"] for n in saves)
    # {run_subdir} 被替換成 myrun，source/mask 子目錄保留，**未被覆寫成 /img**
    assert prefixes == ["myrun/mask/img", "myrun/source/img"]

    rembg = next(n for n in wf.values()
                 if isinstance(n, dict) and n.get("class_type") == "InspyrenetRembgAdvanced")
    assert rembg["inputs"]["threshold"] == 0.6  # bg_remove_strength 注入
    empty = next(n for n in wf.values()
                 if isinstance(n, dict) and n.get("class_type") == "EmptySD3LatentImage")
    assert empty["inputs"]["width"] == 512 and empty["inputs"]["height"] == 512
    clip = next(n for n in wf.values()
                if isinstance(n, dict) and n.get("class_type") == "CLIPTextEncode")
    assert clip["inputs"]["text"] == "gold coin"


# ── BC-7：route=none dispatch 與原行為一致；透明 route 傳雙 None ──

def test_bc7_route_none_dispatch_unchanged(monkeypatch):
    captured = []
    monkeypatch.setattr(plan_runner, "inject", lambda wf, **kw: captured.append(kw) or wf)
    monkeypatch.setattr(plan_runner.api, "submit_prompt", lambda w, c: ("pid", 0, {}))
    item = RI(index=1, slug="x", final_prompt="p", seed=1, filename_prefix="01_x")
    plan_runner._submit_all({"none": {}}, _loaded([item]), "run_x", face_ref_filename=None)
    kw = captured[0]
    assert kw["output_subdir"] == "run_x"            # 原行為保留
    assert kw["filename_prefix_override"] == "01_x"
    assert kw.get("bg_remove_strength") is None


def test_transparent_dispatch_passes_double_none(monkeypatch):
    captured = []
    monkeypatch.setattr(plan_runner, "inject", lambda wf, **kw: captured.append(kw) or wf)
    monkeypatch.setattr(plan_runner.api, "submit_prompt", lambda w, c: ("pid", 0, {}))
    item = RI(index=1, slug="coin", final_prompt="p", seed=1, filename_prefix="01_coin",
              route="rembg", asset_type="opaque", transparent={"bg_remove_strength": 0.7})
    tmpl = {"1": {"class_type": "SaveImage",
                  "inputs": {"filename_prefix": "{run_subdir}/source/img"}}}
    plan_runner._submit_all({"rembg": tmpl}, _loaded([item]), "run_x", face_ref_filename=None)
    kw = captured[0]
    assert kw["output_subdir"] is None and kw["filename_prefix_override"] is None  # M-1
    assert kw["bg_remove_strength"] == 0.7


def test_apply_run_subdir():
    wf = {"1": {"class_type": "SaveImage", "inputs": {"filename_prefix": "{run_subdir}/source/img"}},
          "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}}}
    plan_runner._apply_run_subdir(wf, "R")
    assert wf["1"]["inputs"]["filename_prefix"] == "R/source/img"
    assert wf["2"]["inputs"]["text"] == "x"  # 非 SaveImage 不動


# ── postprocess hook + BC-11 降級 ───────────────────────────────

def test_postprocess_hook_produces_final(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run = "run_x"
    src_dir = tmp_path / "outputs/ar2-dgx-comfyui-gen" / run / "source"
    msk_dir = tmp_path / "outputs/ar2-dgx-comfyui-gen" / run / "mask"
    src_dir.mkdir(parents=True)
    msk_dir.mkdir(parents=True)
    Image.new("RGB", (64, 64), (200, 100, 50)).save(src_dir / "img.png")
    m = np.zeros((64, 64), np.uint8)
    m[16:48, 16:48] = 255
    Image.fromarray(m, "L").save(msk_dir / "img.png")

    item = RI(index=1, slug="coin", final_prompt="p", seed=1, filename_prefix="01_coin",
              route="rembg", asset_type="opaque",
              transparent={"category": "symbol", "size": 512})
    sub = {"item": item}
    plan_runner._postprocess_transparent(
        item, [src_dir / "img.png", msk_dir / "img.png"], run, sub)
    assert sub.get("qc_result") in ("pass", "warning", "fail")
    out = tmp_path / "outputs/ar2-dgx-comfyui-transparent" / run / "symbol_coin"
    assert (out / "report.json").exists()
    assert (out / "symbol_coin_512_v001.png").exists()


def test_bc11_missing_mask_degrades(tmp_path):
    item = RI(index=1, slug="coin", final_prompt="p", seed=1, filename_prefix="01_coin",
              route="rembg", asset_type="opaque", transparent={})
    sub = {"item": item}
    # 只有 source（mask 鏈失敗）→ 降級不 raise
    plan_runner._postprocess_transparent(item, [tmp_path / "source" / "img.png"], "run", sub)
    assert "缺 mask" in sub.get("error", "")


# ── R-1：透明 route 忽略 plan 的 negative（單 encoder Flux）──────

def test_r1_transparent_ignores_negative(monkeypatch):
    captured = []
    monkeypatch.setattr(plan_runner, "inject", lambda wf, **kw: captured.append(kw) or wf)
    monkeypatch.setattr(plan_runner.api, "submit_prompt", lambda w, c: ("pid", 0, {}))
    item = RI(index=1, slug="coin", final_prompt="p", seed=1, filename_prefix="01_coin",
              route="rembg", asset_type="opaque", transparent={})
    tmpl = {"1": {"class_type": "SaveImage",
                  "inputs": {"filename_prefix": "{run_subdir}/source/img"}}}
    # 設了非空 negative — 不應導致 inject 收到 negative（否則單 encoder workflow raise）
    plan_runner._submit_all({"rembg": tmpl}, _loaded([item], negative="ugly, blurry"),
                            "run_x", face_ref_filename=None)
    assert captured[0]["negative_prompt"] is None


# ── R-4：semi 產生深淺底 preview 並傳給 run_qc（不再恆誤報 preview_missing）──

def test_r4_semi_generates_previews(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run = "run_x"
    rgb_dir = tmp_path / "outputs/ar2-dgx-comfyui-gen" / run / "rgb"
    alpha_dir = tmp_path / "outputs/ar2-dgx-comfyui-gen" / run / "alpha"
    rgb_dir.mkdir(parents=True)
    alpha_dir.mkdir(parents=True)
    Image.new("RGB", (80, 80), (100, 150, 200)).save(rgb_dir / "img.png")
    a = np.zeros((80, 80), np.uint8)
    a[20:60, 20:60] = np.tile(np.linspace(1, 254, 40).astype(np.uint8), (40, 1))  # 中介 alpha
    Image.fromarray(a, "L").save(alpha_dir / "img.png")

    item = RI(index=1, slug="smoke", final_prompt="p", seed=1, filename_prefix="01_smoke",
              route="layerdiffuse", asset_type="semi",
              transparent={"category": "vfx", "size": 1024})
    sub = {"item": item}
    plan_runner._postprocess_transparent(item, [rgb_dir / "img.png", alpha_dir / "img.png"], run, sub)
    out = tmp_path / "outputs/ar2-dgx-comfyui-transparent" / run / "vfx_smoke"
    assert (out / "preview_dark.png").exists() and (out / "preview_light.png").exists()
    import json
    rep = json.loads((out / "report.json").read_text())
    assert not any("preview_missing" in w for w in rep.get("warnings", []))


# ── vfx_additive route（luminance-matte 半透明）──────────────────

def test_vfx_additive_dispatch_black_bg_suffix(monkeypatch):
    captured = []
    monkeypatch.setattr(plan_runner, "inject", lambda wf, **kw: captured.append((wf, kw)) or wf)
    monkeypatch.setattr(plan_runner.api, "submit_prompt", lambda w, c: ("pid", 0, {}))
    item = RI(index=1, slug="glow", final_prompt="blue magic glow orb", seed=1,
              filename_prefix="01_glow", route="vfx_additive", asset_type="semi",
              transparent={"category": "vfx", "size": 768})
    tmpl = {"3": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
            "13": {"class_type": "SaveImage", "inputs": {"filename_prefix": "{run_subdir}/rgb/img"}}}
    plan_runner._submit_all({"vfx_additive": tmpl}, _loaded([item]), "run_x", face_ref_filename=None)
    wf, kw = captured[0]
    assert "black background" in kw["prompt"].lower()   # 自動補黑底（matte 前提）
    assert kw.get("bg_remove_strength") is None          # 無 rembg 節點
    assert kw["output_subdir"] is None and kw["filename_prefix_override"] is None  # M-1
    assert wf["13"]["inputs"]["filename_prefix"] == "run_x/rgb/img"  # {run_subdir} 替換、rgb/ 保留


def test_vfx_additive_postprocess_luminance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run = "run_x"
    rgb_dir = tmp_path / "outputs/ar2-dgx-comfyui-gen" / run / "rgb"
    rgb_dir.mkdir(parents=True)
    arr = np.zeros((80, 80, 3), np.uint8)
    arr[24:56, 24:56] = [80, 160, 240]  # 黑底亮中心
    Image.fromarray(arr, "RGB").save(rgb_dir / "img.png")
    item = RI(index=1, slug="glow", final_prompt="p", seed=1, filename_prefix="01_glow",
              route="vfx_additive", asset_type="semi", transparent={"category": "vfx", "size": 768})
    sub = {"item": item}
    # 只有 rgb（無 mask）→ luminance 分支不應誤判缺檔
    plan_runner._postprocess_transparent(item, [rgb_dir / "img.png"], run, sub)
    out = tmp_path / "outputs/ar2-dgx-comfyui-transparent" / run / "vfx_glow"
    assert (out / "vfx_glow_768_v001.png").exists()
    assert (out / "preview_dark.png").exists() and (out / "preview_light.png").exists()
    assert sub.get("qc_result") in ("pass", "warning")  # 半透明不二值化 → 不 fail
