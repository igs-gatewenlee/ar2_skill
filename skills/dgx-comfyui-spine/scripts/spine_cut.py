"""hint∩前景 切件 primitive（白底 reference · 純函式 numpy/PIL · fixture 可測）。

白底 reference 的切件：`part = (人標 hint 區) ∩ (前景=非白)`。hint 定「切哪塊」、
白底前景定 alpha。比 SAM 穩（demo 實證）：
- 多色部件不漏（不靠顏色分群 → 頭=髮+膚、穿衣=衣+膚 都完整）
- 瘦件不 over-grab（背景被 ∩前景 濾掉 → 手臂不吞整身）
- 純本地、無 DGX/SAM round-trip → 快

SAM 對白底是過度設計（白底圖無內部自然邊可 snap，邊精修空轉）→ 降為 `--method sam`
的非白底 / 需自動邊精修選項。
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation

import manifest_builder as mb
import spine_qc_thresholds as T


def foreground_mask(ref: Image.Image, *, delta: int = T.WHITE_BG_FG_DELTA) -> np.ndarray:
    """白底前景 bool mask：(255-r)+(255-g)+(255-b) > delta。"""
    a = np.asarray(ref.convert("RGB")).astype(np.int32)
    return (255 - a).sum(axis=2) > delta


def cut_part(ref: Image.Image, hint: Image.Image, *,
             delta: int = T.WHITE_BG_FG_DELTA, dilate: int = 0):
    """回 (full_rgba, bbox)。full_rgba = reference 尺寸、alpha = hint∩前景；
    bbox = content_bbox(padding=0)。hint∩前景 全空回 (None, None)。

    dilate>0：關節 overlap 帶——把 mask 外擴 dilate px 但**夾在前景內**（不長進背景）。
    相鄰部件各自外擴 → 在關節縫重疊 → 縫消除（PoC §6.4 已證）。本地、無 DGX。
    """
    fg = foreground_mask(ref, delta=delta)
    hl = hint.convert("L")
    if hl.size != ref.size:
        hl = hl.resize(ref.size)
    h = np.asarray(hl) > 127
    mask = fg & h
    if dilate and dilate > 0:
        mask = binary_dilation(mask, iterations=int(dilate)) & fg  # 夾前景，往相鄰部件方向關縫
    arr = np.asarray(ref.convert("RGBA")).copy()
    arr[..., 3] = np.where(mask, 255, 0).astype(np.uint8)
    full = Image.fromarray(arr, "RGBA")
    bbox = mb.content_bbox(full)
    if bbox is None:
        return None, None
    return full, bbox
