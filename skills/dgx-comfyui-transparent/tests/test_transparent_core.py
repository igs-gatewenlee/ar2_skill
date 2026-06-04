"""本地核心契約測試（BC-1/2/3/4/5/10，route/DGX 無關）。"""
import numpy as np
import pytest
from PIL import Image

import asset_spec
import qc
import transparent_postprocess as pp


# ── fixtures helpers ────────────────────────────────────────────

def _semi_rgba(size=400, inner=304, value=None):
    """中心 inner×inner alpha=漸層中介值(1~254)、外圍 alpha=0 的半透明 fixture。

    邊距 (size-inner)/2 須 > qc_thresholds.CORNER_N(16)，否則角落檢查區與內容區重疊誤觸
    corner_residual warning。預設 400/304 → 邊距 48；bbox=304²/400²=0.5776（>0.5）。
    """
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    arr[..., :3] = 120  # 任意 RGB
    off = (size - inner) // 2
    if value is None:
        grad = np.linspace(1, 254, inner).astype(np.uint8)
        arr[off:off + inner, off:off + inner, 3] = np.tile(grad, (inner, 1))
    else:
        arr[off:off + inner, off:off + inner, 3] = value
    return Image.fromarray(arr, "RGBA")


# ── BC-1：RGBA straight 重組 ────────────────────────────────────

def test_bc1_compose_rgba_straight():
    rgb = Image.new("RGB", (8, 8), (200, 100, 50))
    mask = Image.new("L", (8, 8), 128)
    out = pp.compose_rgba(rgb, mask)
    arr = np.asarray(out)
    assert out.mode == "RGBA"
    # alpha 逐像素 == mask
    assert (arr[..., 3] == 128).all()
    # RGB 未被 alpha 衰減（straight，非 premultiplied）
    assert (arr[..., 0] == 200).all() and (arr[..., 1] == 100).all() and (arr[..., 2] == 50).all()


# ── BC-2：semi 早退出不 shrink，保留中介 alpha ──────────────────

def test_bc2_semi_shrink_skipped():
    semi = _semi_rgba()
    out, warns = pp.fix_alpha(semi, "semi", shrink=2)
    a = np.asarray(out)[..., 3]
    assert any("shrink skipped" in w for w in warns)
    assert int(((a >= 1) & (a <= 254)).sum()) > 0  # 中介 alpha 仍在


def test_bc2_opaque_shrink_runs():
    op = _semi_rgba(value=255)  # 實心方塊
    before = int((np.asarray(op)[..., 3] > 0).sum())
    out, warns = pp.fix_alpha(op, "opaque", shrink=2)
    after = int((np.asarray(out)[..., 3] > 0).sum())
    assert not warns
    assert after < before  # erosion 內縮了不透明區


# ── BC-4：midtone 分母定義 ──────────────────────────────────────

def test_bc4_midtone_denominator():
    alpha = np.array([0, 128, 255], dtype=np.uint8)  # 各 1/3
    # 分母=非全透明(α>0)=2、分子=中介(1~254)=1 → 0.5（非全圖 1/3）
    assert qc.midtone_alpha_ratio(alpha) == pytest.approx(0.5)


def test_bc4_all_transparent_zero():
    assert qc.midtone_alpha_ratio(np.zeros(10, dtype=np.uint8)) == 0.0


# ── BC-3：QC 反向分流（同圖 opaque vs semi 判定相反）────────────

def test_bc3_reverse_split_midtone_image(tmp_path):
    """高 midtone 圖：semi→pass、opaque→warning。"""
    p = tmp_path / "vfx_smoke_512_v001.png"
    _semi_rgba().save(p)
    semi = qc.run_qc(p, "semi", previews=["preview_dark.png", "preview_light.png"])
    opaque = qc.run_qc(p, "opaque")
    assert semi["result"] == "pass", semi
    assert opaque["result"] == "warning"
    assert any("opaque_midtone_high" in w for w in opaque["warnings"])


def test_bc3_reverse_split_binarized_image(tmp_path):
    """二值化圖（無中介 alpha）：semi→fail、opaque→pass。"""
    p = tmp_path / "symbol_coin_512_v001.png"
    _semi_rgba(value=255).save(p)  # 中心實心、外圍透明
    semi = qc.run_qc(p, "semi", previews=["d.png", "l.png"])
    opaque = qc.run_qc(p, "opaque")
    assert semi["result"] == "fail", semi
    assert any("semi_binarized" in f for f in semi.get("fails", []))
    assert opaque["result"] == "pass", opaque


# ── BC-5：QC 輸入契約 ───────────────────────────────────────────

def test_bc5_reject_intermediate(tmp_path):
    p = tmp_path / "mask_00001_.png"
    Image.new("L", (8, 8), 255).save(p)
    with pytest.raises(qc.QCInputError):
        qc.run_qc(p, "opaque")


def test_bc5_final_without_alpha_fails(tmp_path):
    p = tmp_path / "symbol_coin_512_v001.png"
    Image.new("RGB", (8, 8), (10, 20, 30)).save(p)  # 無 alpha 通道
    rep = qc.run_qc(p, "opaque")
    assert rep["result"] == "fail"
    assert rep["has_alpha"] is False


def test_fake_transparent_fails(tmp_path):
    p = tmp_path / "symbol_coin_512_v001.png"
    Image.new("RGBA", (8, 8), (10, 20, 30, 255)).save(p)  # alpha 全 255
    rep = qc.run_qc(p, "opaque")
    assert rep["fake_transparent"] is True
    assert rep["result"] == "fail"


# ── auto_trim ───────────────────────────────────────────────────

def test_auto_trim_shrinks_canvas():
    big = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    big.paste(Image.new("RGBA", (40, 40), (255, 0, 0, 255)), (80, 80))
    trimmed = pp.auto_trim(big, padding=8)
    # 主體 40 + padding 16 ≈ 56；遠小於 200，且主體未被裁（紅色像素仍在）
    assert trimmed.width < 80 and trimmed.height < 80
    assert (np.asarray(trimmed)[..., 3] > 0).sum() >= 40 * 40


# ── BC-10：版本不覆蓋 ───────────────────────────────────────────

# ── R-3：category 保留字校驗 ────────────────────────────────────

def test_r3_reserved_category_rejected():
    for bad in ("source", "mask", "rgb", "alpha", "preview"):
        with pytest.raises(ValueError):
            asset_spec.asset_filename(bad, "x", 512, 1)
    assert asset_spec.asset_filename("symbol", "x", 512, 1) == "symbol_x_512_v001.png"


# ── L-7：邊界輸入 ───────────────────────────────────────────────

def test_l7_compose_size_mismatch_resizes():
    rgb = Image.new("RGB", (20, 20), (1, 2, 3))
    mask = Image.new("L", (10, 10), 128)
    out = pp.compose_rgba(rgb, mask)
    assert out.size == (20, 20)  # mask resize 到 rgb 尺寸


def test_l7_trim_all_transparent_noop():
    img = Image.new("RGBA", (30, 30), (0, 0, 0, 0))
    assert pp.auto_trim(img).size == (30, 30)  # 全透明不裁


def test_luminance_matte():
    """加色特效：alpha=亮度（黑=透明、亮=不透明），RGB 維持 straight、不二值化。"""
    arr = np.zeros((20, 20, 3), np.uint8)
    arr[8:12, 8:12] = [200, 200, 255]  # 亮藍中心
    rgba = pp.luminance_matte(Image.fromarray(arr, "RGB"))
    a = np.asarray(rgba)
    assert rgba.mode == "RGBA"
    assert a[0, 0, 3] == 0          # 黑底 → 透明
    assert a[10, 10, 3] > 100       # 亮中心 → 不透明（中介~高）
    assert tuple(a[10, 10, :3]) == (200, 200, 255)  # RGB 未被 alpha 衰減（straight）


def test_l7_all_opaque_chain():
    rgb = Image.new("RGB", (40, 40), (10, 20, 30))
    mask = Image.new("L", (40, 40), 255)
    rgba = pp.compose_rgba(rgb, mask)
    rgba = pp.edge_bleed(rgba)  # 全不透明 → 無 holes → 原樣
    rgba, _ = pp.fix_alpha(rgba, "opaque", shrink=1, blur=0.5)
    rgba = pp.auto_trim(rgba)
    assert rgba.mode == "RGBA"


def test_bc10_version_increment(tmp_path):
    folder = tmp_path / "symbol_gold_coin"
    folder.mkdir()
    assert asset_spec.next_version(folder, "symbol", "gold_coin", 512) == 1
    (folder / asset_spec.asset_filename("symbol", "gold_coin", 512, 1)).write_bytes(b"x")
    assert asset_spec.next_version(folder, "symbol", "gold_coin", 512) == 2
    assert asset_spec.asset_filename("symbol", "gold_coin", 512, 2) == "symbol_gold_coin_512_v002.png"
    # v001 不被動
    assert (folder / "symbol_gold_coin_512_v001.png").read_bytes() == b"x"
