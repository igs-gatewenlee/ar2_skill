"""透明素材本地後處理純函式（無 SSH / 無 GPU，fixture 可測）。

對應 P1 設計規格 §5：
- RGBA straight 重組（BC-1：RGB 不乘 alpha）
- un-premultiply（decode 為 premultiplied 時）+ edge-bleed（避免 blur 黑邊）
- alpha 修正：shrink（opaque）/ blur·feather / contrast；semi 早退出不 shrink（BC-2）
- auto-trim（getbbox + padding + keep_square）
- 深淺底 preview（semi 必出）

順序（§5.2）：un-premultiply(若需) → edge-bleed → shrink → blur/feather → contrast。
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, gaussian_filter, grey_erosion

import qc_thresholds as T


# ── RGBA 重組 ───────────────────────────────────────────────────

def compose_rgba(rgb_img: Image.Image, mask_img: Image.Image) -> Image.Image:
    """source(RGB) + mask(灰階) → RGBA straight。

    BC-1：alpha 通道逐像素 == mask 灰階；RGB 三通道逐像素 == source（**不乘 alpha**）。
    """
    rgb = rgb_img.convert("RGB")
    mask = mask_img.convert("L")
    if mask.size != rgb.size:
        mask = mask.resize(rgb.size, Image.BILINEAR)
    r, g, b = rgb.split()
    return Image.merge("RGBA", (r, g, b, mask))


def luminance_matte(rgb_img: Image.Image, *, gamma: float = 1.0) -> Image.Image:
    """加色特效（純黑底）→ RGBA：alpha = 亮度（保留中介值，**不二值化**），RGB 維持 straight。

    Route `vfx_additive`：發光 / 能量 / 火焰 / 魔法光 / 粒子等加色效果（黑=透明、亮=不透明），
    用現有 Flux 管線（黑底產圖）+ 本地 matte，不需 LayerDiffuse。
    ⚠️ 不適用煙霧 / 玻璃（吸收/折射類，亮度近似會偏）→ 那類走 Route B（LayerDiffuse）。
    """
    arr = np.asarray(rgb_img.convert("RGB")).astype(np.float32)
    lum = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    if gamma and gamma != 1.0:
        lum = 255.0 * np.clip(lum / 255.0, 0.0, 1.0) ** float(gamma)
    alpha = np.clip(lum, 0, 255).astype(np.uint8)
    out = np.dstack([arr.astype(np.uint8), alpha])
    return Image.fromarray(out, "RGBA")


def un_premultiply(rgba: Image.Image) -> Image.Image:
    """premultiplied → straight：RGB = RGB / (alpha/255)。alpha=0 處不除（留給 edge-bleed）。"""
    arr = np.asarray(rgba.convert("RGBA")).astype(np.float32)
    a = arr[..., 3:4] / 255.0
    rgb = arr[..., :3]
    safe = np.where(a > 0, a, 1.0)
    straight = np.where(a > 0, rgb / safe, rgb)
    out = np.concatenate([np.clip(straight, 0, 255), arr[..., 3:4]], axis=-1)
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def edge_bleed(rgba: Image.Image) -> Image.Image:
    """把 alpha==0 像素的 RGB 用最近的不透明像素顏色填充，避免之後 blur 把黑/白吃進邊緣。"""
    arr = np.asarray(rgba.convert("RGBA")).copy()
    holes = arr[..., 3] == 0
    if not holes.any() or holes.all():
        return Image.fromarray(arr, "RGBA")
    # 最近非洞像素的索引
    idx = distance_transform_edt(holes, return_distances=False, return_indices=True)
    yy, xx = idx[0][holes], idx[1][holes]
    for c in range(3):
        ch = arr[..., c]
        ch[holes] = ch[yy, xx]
    return Image.fromarray(arr, "RGBA")


# ── alpha 修正 ──────────────────────────────────────────────────

def fix_alpha(rgba: Image.Image, asset_type: str, *, shrink: int = 0,
              blur: float = 0.0, feather: float = 0.0, contrast: float = 1.0):
    """alpha-fix。回傳 (新 RGBA, warnings)。

    BC-2：asset_type=='semi' 時即使 shrink≠0 也 **早退出不執行 erosion**（保留中介 alpha），記 warning。
    順序：shrink(opaque) → blur/feather → contrast。
    """
    arr = np.asarray(rgba.convert("RGBA")).copy()
    a = arr[..., 3].astype(np.float32)
    warnings: list[str] = []

    if shrink and shrink > 0:
        if asset_type == "semi":
            warnings.append("alpha_shrink skipped for semi (preserve midtone alpha)")
        else:
            size = 2 * int(shrink) + 1
            a = grey_erosion(a, size=(size, size))

    amt = float(blur or 0.0) + float(feather or 0.0)
    if amt > 0:
        a = gaussian_filter(a, sigma=amt)

    if contrast and contrast != 1.0:
        # 對比繞中點 127.5；clip 0~255（semi 不做二值化，這裡也不強推到極端）
        a = np.clip((a - 127.5) * float(contrast) + 127.5, 0, 255)

    arr[..., 3] = np.clip(a, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA"), warnings


# ── trim + preview ──────────────────────────────────────────────

def auto_trim(rgba: Image.Image, *, alpha_thresh: int = T.TRIM_ALPHA_THRESH,
              padding: int = T.DEFAULT_PADDING, keep_square: bool = False,
              min_size: int = 0) -> Image.Image:
    """裁掉多餘透明區（保留 padding）。主體（α>thresh）不被裁到。全透明則原樣回。"""
    a = np.asarray(rgba.convert("RGBA"))[..., 3]
    ys, xs = np.where(a > alpha_thresh)
    if xs.size == 0:
        return rgba  # 全透明，不裁
    W, H = rgba.size
    x0 = max(0, int(xs.min()) - padding)
    y0 = max(0, int(ys.min()) - padding)
    x1 = min(W, int(xs.max()) + 1 + padding)
    y1 = min(H, int(ys.max()) + 1 + padding)
    crop = rgba.crop((x0, y0, x1, y1))

    if keep_square:
        side = max(crop.size)
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
        crop = sq
    if min_size and (crop.width < min_size or crop.height < min_size):
        side_w = max(crop.width, min_size)
        side_h = max(crop.height, min_size)
        pad = Image.new("RGBA", (side_w, side_h), (0, 0, 0, 0))
        pad.paste(crop, ((side_w - crop.width) // 2, (side_h - crop.height) // 2))
        crop = pad
    return crop


def make_previews(rgba: Image.Image):
    """純黑底 / 純白底合成預覽（半透明素材必出，產出非驗證手段）。回傳 (dark, light) RGB。"""
    rgba = rgba.convert("RGBA")
    dark = Image.new("RGB", rgba.size, (0, 0, 0))
    dark.paste(rgba, (0, 0), rgba)
    light = Image.new("RGB", rgba.size, (255, 255, 255))
    light.paste(rgba, (0, 0), rgba)
    return dark, light
