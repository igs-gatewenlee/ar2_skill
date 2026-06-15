"""spine manifest 契約 builder + content_bbox + 本地校驗（純函式，無 DGX，fixture 可測）。

manifest schema：
  top-level: reference(str) / reference_size[w,h] / parts{name -> entry}
  entry:     name(slug) / bbox[x,y,w,h] / pivot{x,y,best_effort}
             / rotation{deg,best_effort} / draw_order(int·允許同層重複) / source

設計依據（P1 設計規格 §1.4 / §1.7 / BC-1/5/7）：
- content_bbox 自寫 padding=0（修正致命缺陷 #4：auto_trim DEFAULT_PADDING=8 會破壞 bbox↔PNG 嚴格相等）
- pivot/rotation 標 best_effort=True（BC-5：視覺提示，非程式驅動旋轉契約）
- draw_order 整數、**允許同層重複**（BC-7：L/R 對稱件天然同層）
"""
from __future__ import annotations

import re

import numpy as np
from PIL import Image

import spine_qc_thresholds as T

SLUG_RE = re.compile(r"^[a-z0-9_]+$")


def content_bbox(rgba: Image.Image, *, alpha_thresh: int = T.ALPHA_OPAQUE_THRESH):
    """回 alpha>thresh 區的 bbox (x, y, w, h)，**padding=0**。全透明回 None。

    座標 = 傳入圖（= reference 全圖尺寸的 masked RGBA）的左上原點座標系。
    spine 專屬自寫（不用 transparent.auto_trim 的 padding 預設、語意=全圖座標非面積比）。
    """
    a = np.asarray(rgba.convert("RGBA"))[..., 3]
    ys, xs = np.where(a > alpha_thresh)
    if xs.size == 0:
        return None
    x0, y0 = int(xs.min()), int(ys.min())
    x1, y1 = int(xs.max()), int(ys.max())
    return (x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def crop_part(full_rgba: Image.Image, bbox) -> Image.Image:
    """依 content_bbox 結果裁出 part PNG（尺寸嚴格 = (w,h)，BC-1 由同一 bbox 保證）。"""
    x, y, w, h = bbox
    return full_rgba.convert("RGBA").crop((x, y, x + w, y + h))


def build_manifest(reference_name: str, reference_size, parts: dict) -> dict:
    """組 manifest。

    parts: dict name -> {"bbox": (x,y,w,h), "draw_order": int,
                         "pivot": (px,py)|None, "rotation": deg|None}
    pivot 預設取「靠父關節端」近似：bbox 上緣中點（best_effort）。
    """
    out = {
        "reference": reference_name,
        "reference_size": [int(reference_size[0]), int(reference_size[1])],
        "parts": {},
    }
    for name, p in parts.items():
        x, y, w, h = (int(v) for v in p["bbox"])
        pv = p.get("pivot")
        px, py = (int(pv[0]), int(pv[1])) if pv else (x + w // 2, y)
        rot = p.get("rotation")
        out["parts"][name] = {
            "name": name,
            "bbox": [x, y, w, h],
            "pivot": {"x": px, "y": py, "best_effort": True},
            "rotation": {"deg": float(rot) if rot is not None else 0.0, "best_effort": True},
            "draw_order": int(p["draw_order"]),
            "source": reference_name,
        }
    return out


def validate_manifest(manifest: dict) -> list:
    """回 errors list（空 = 合法）。slug / 數值有效 / draw_order 整數(非唯一) / bbox 在 reference 內。"""
    errs: list[str] = []
    size = manifest.get("reference_size") or [0, 0]
    rw, rh = int(size[0]), int(size[1])
    parts = manifest.get("parts") or {}
    if not parts:
        errs.append("manifest 無 parts")
    for name, e in parts.items():
        if not SLUG_RE.match(name):
            errs.append(f"{name}: slug 非法（須 [a-z0-9_]+）")
        bbox = e.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(v, int) for v in bbox)):
            errs.append(f"{name}: bbox 格式錯（須 4 整數）")
            continue
        x, y, w, h = bbox
        if w <= 0 or h <= 0:
            errs.append(f"{name}: bbox w/h ≤ 0")
        if x < 0 or y < 0 or (rw and x + w > rw) or (rh and y + h > rh):
            errs.append(f"{name}: bbox 超出 reference {rw}x{rh}")
        if not isinstance(e.get("draw_order"), int):
            errs.append(f"{name}: draw_order 非整數")
        # BC-7：draw_order 不檢查唯一性（L/R 同層合法）
    return errs
