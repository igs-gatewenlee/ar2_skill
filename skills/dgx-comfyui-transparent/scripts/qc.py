"""自動品質檢查（QC engine）。對 trim 後的 final.png 執行，依 asset_type 反向分流。

對應 P1 設計規格 §5.4 / §8：
- midtone_alpha_ratio = count(1≤α≤254) / count(α>0)（分母=非全透明像素，非全圖）BC-4
- opaque vs semi 反向判定（BC-3）；route↔asset_type guard
- QC 輸入契約：只吃 final.png，拒中間檔 alpha/mask/source/rgb（BC-5）
- 輸出 report.json 結構（§5.5）
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

import qc_thresholds as T

# 中間檔前綴（BC-5：QC 拒絕，避免對 α 全 255 的 mask/source 反判）
_INTERMEDIATE = ("source", "mask", "rgb", "alpha", "preview", "preview_dark", "preview_light")


class QCInputError(ValueError):
    """QC 被餵了非 final.png（中間檔）—— 違反輸入契約 BC-5。"""


def midtone_alpha_ratio(alpha) -> float:
    """count(1≤α≤254) / count(α>0)。分母=非全透明像素；全透明回 0.0（BC-4）。"""
    a = np.asarray(alpha).ravel()
    nonzero = int((a > 0).sum())
    if nonzero == 0:
        return 0.0
    mid = int(((a >= 1) & (a <= 254)).sum())
    return mid / nonzero


def _corner_residual(alpha: np.ndarray, n: int) -> bool:
    """四角 n×n 區域是否有不透明殘留（> CORNER_ALPHA_MAX）。"""
    h, w = alpha.shape
    n = min(n, h, w)
    corners = [alpha[:n, :n], alpha[:n, -n:], alpha[-n:, :n], alpha[-n:, -n:]]
    return any(int(c.max()) > T.CORNER_ALPHA_MAX for c in corners)


def _content_bbox_ratio(alpha: np.ndarray) -> float:
    """有效像素 bbox 面積 / 全圖面積。"""
    ys, xs = np.where(alpha > T.TRIM_ALPHA_THRESH)
    if xs.size == 0:
        return 0.0
    bw = int(xs.max()) - int(xs.min()) + 1
    bh = int(ys.max()) - int(ys.min()) + 1
    return (bw * bh) / float(alpha.shape[0] * alpha.shape[1])


def run_qc(final_path: str | Path, asset_type: str, *, route: str | None = None,
           previews: list | None = None, expected_size=None, alpha_type: str = "straight") -> dict:
    """對 final.png 跑 QC，回 report dict（result: pass|warning|fail）。

    BC-5：basename 為中間檔前綴 → raise QCInputError。
    BC-3：opaque（midtone 多→warning）vs semi（midtone 太少→fail）反向分流。
    """
    final_path = Path(final_path)
    name = final_path.name
    stem = name.split("_", 1)[0].lower()
    if stem in _INTERMEDIATE:
        raise QCInputError(f"QC 只接受 final.png，拒絕中間檔「{name}」（BC-5）")

    img = Image.open(final_path)
    has_alpha = (img.mode in ("RGBA", "LA")) or ("transparency" in img.info)

    report: dict = {
        "file": name,
        "asset_type": asset_type,
        "result": "pass",
        "has_alpha": has_alpha,
        "fake_transparent": None,
        "alpha_type": alpha_type,
        "midtone_alpha_ratio": None,
        "content_bbox_ratio": None,
        "size": list(img.size),
        "file_size_kb": round(final_path.stat().st_size / 1024, 1) if final_path.exists() else None,
        "previews": list(previews) if previews else [],
        "warnings": [],
    }

    fails: list[str] = []
    warns: list[str] = []

    if not has_alpha:
        # 無 alpha 通道 → 共用檢查直接 fail（BC-5 的 has_alpha 分支）
        report["result"] = "fail"
        report["warnings"] = ["no_alpha_channel"]
        return report

    rgba = img.convert("RGBA")
    arr = np.asarray(rgba)
    a = arr[..., 3]

    fake = bool((a == 255).all())
    report["fake_transparent"] = fake
    mid = midtone_alpha_ratio(a)
    report["midtone_alpha_ratio"] = round(mid, 4)
    report["content_bbox_ratio"] = round(_content_bbox_ratio(a), 4)

    # ── 共用 fail ──
    if fake:
        fails.append("fake_transparent_all_255")

    # ── asset_type 反向分流 ──
    if asset_type == "semi":
        if mid < T.SEMI_MIDTONE_MIN:
            fails.append(f"semi_binarized(midtone={mid:.3f}<{T.SEMI_MIDTONE_MIN})")
        if not report["previews"] or len(report["previews"]) < 2:
            warns.append("semi_preview_missing(need dark+light)")
        # route guard：semi 不應近 0 midtone（已由上面 fail 涵蓋）
    else:  # opaque
        if mid > T.OPAQUE_MIDTONE_MAX:
            warns.append(f"opaque_midtone_high(midtone={mid:.3f}>{T.OPAQUE_MIDTONE_MAX})")
        # route guard：Route A(opaque) 不應高 midtone（上面 warning 已涵蓋）

    # ── 共用 warning ──
    if _corner_residual(a, T.CORNER_N):
        warns.append("corner_residual(possible leftover background)")
    if report["content_bbox_ratio"] < T.CONTENT_BBOX_MIN:
        warns.append(f"excess_transparent(bbox={report['content_bbox_ratio']}<{T.CONTENT_BBOX_MIN})")
    if expected_size is not None and list(img.size) != list(expected_size):
        warns.append(f"size_mismatch({img.size}!={tuple(expected_size)})")

    report["warnings"] = warns
    report["result"] = "fail" if fails else ("warning" if warns else "pass")
    if fails:
        report["fails"] = fails
    return report
