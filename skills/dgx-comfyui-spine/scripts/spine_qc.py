"""spine 8 閘硬 QC engine（P1 設計規格 §1.6）。純函式（numpy/PIL/scipy），fixture 可測。

8 閘：
1 部件齊全（manifest ⊇ EXPECTED_PARTS）         5 L/R upper_arm 對稱
2 命名 bijection 雙向（manifest ↔ parts/*.png）  6 部件內破洞偵測
3 manifest 數值有效（委派 manifest_builder）      7 可組回 masked-SSIM ≥0.95（用 spine_recompose）
4 上肢分離 ≤5%                                    8 全圖前景覆蓋率 ≥0.97（抓相連漏抓假象）

輸入契約（BC-8）：bijection 只認 final part PNG，過濾切件中間檔（hint_/sam_/legmask_…）。
第 8 閘（BC-10）：分母用白底閾值法（PoC 同把尺）→ 限定白底 reference 列硬 fail；非白底降 warn。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import binary_fill_holes, uniform_filter

import manifest_builder
import spine_qc_thresholds as T
import spine_recompose


# ── helpers ─────────────────────────────────────────────────────

def _part_pngs(parts_dir: Path) -> dict:
    """parts/*.png → {slug: path}，過濾切件中間檔前綴（BC-8）。"""
    out = {}
    for p in sorted(parts_dir.glob("*.png")):
        if p.stem.split("_")[0] in T.INTERMEDIATE_PREFIXES:
            continue
        out[p.stem] = p
    return out


def _opaque_on_canvas(part_png: Path, bbox, size) -> np.ndarray:
    """把 part 的不透明足跡（alpha>thresh）放回 reference 全圖座標，回 bool array。"""
    rw, rh = size
    canvas = np.zeros((rh, rw), dtype=bool)
    a = np.asarray(Image.open(part_png).convert("RGBA"))[..., 3] > T.ALPHA_OPAQUE_THRESH
    x, y, w, h = bbox
    ph, pw = a.shape
    # 容錯裁切到畫布內
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(rw, x + pw), min(rh, y + ph)
    if x1 <= x0 or y1 <= y0:
        return canvas
    canvas[y0:y1, x0:x1] = a[y0 - y:y1 - y, x0 - x:x1 - x]
    return canvas


def _fg_mask(ref_rgb: np.ndarray) -> np.ndarray:
    """白底前景判定：(255-r)+(255-g)+(255-b) > delta。"""
    inv = (255 - ref_rgb.astype(np.int32)).sum(axis=2)
    return inv > T.WHITE_BG_FG_DELTA


def _is_white_bg(fg: np.ndarray) -> bool:
    """邊框前景比例 < 閾值 → 判定白底（第 8 閘可硬 fail）。"""
    h, w = fg.shape
    b = max(1, min(h, w) // 50)
    border = np.concatenate([fg[:b].ravel(), fg[-b:].ravel(), fg[:, :b].ravel(), fg[:, -b:].ravel()])
    return border.mean() <= T.WHITE_BG_BORDER_MAX_FG


def _ssim_masked(a: np.ndarray, b: np.ndarray, mask: np.ndarray, win: int = 7) -> float:
    """灰階 SSIM map 在 mask 區的平均。a,b: float [0,255]。"""
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a = uniform_filter(a, win)
    mu_b = uniform_filter(b, win)
    mu_a2, mu_b2, mu_ab = mu_a * mu_a, mu_b * mu_b, mu_a * mu_b
    va = uniform_filter(a * a, win) - mu_a2
    vb = uniform_filter(b * b, win) - mu_b2
    vab = uniform_filter(a * b, win) - mu_ab
    smap = ((2 * mu_ab + C1) * (2 * vab + C2)) / ((mu_a2 + mu_b2 + C1) * (va + vb + C2))
    if mask.sum() == 0:
        return float(smap.mean())
    return float(smap[mask].mean())


def _interior_hole_ratio(part_png: Path) -> float:
    """部件內封閉透明洞面積 / 部件 bbox 面積。"""
    a = np.asarray(Image.open(part_png).convert("RGBA"))[..., 3] > T.ALPHA_OPAQUE_THRESH
    if a.sum() == 0:
        return 0.0
    filled = binary_fill_holes(a)
    holes = filled & ~a
    return float(holes.sum()) / float(a.shape[0] * a.shape[1])


def _gray_over_white(rgba: Image.Image) -> np.ndarray:
    """RGBA 合成到白底 → 灰階 float。"""
    bg = Image.new("RGB", rgba.size, (255, 255, 255))
    bg.paste(rgba, (0, 0), rgba)
    arr = np.asarray(bg).astype(np.float64)
    return 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]


# ── main ────────────────────────────────────────────────────────

def run_spine_qc(parts_dir, manifest: dict, reference_path, *, thresholds=T) -> dict:
    """跑 8 閘，回 report dict（result: pass|warning|fail）。"""
    parts_dir = Path(parts_dir)
    report = {"result": "pass", "gates": {}, "fails": [], "warnings": []}
    fails, warns = report["fails"], report["warnings"]

    def gate(n, name, status, detail=""):
        report["gates"][f"{n}_{name}"] = {"status": status, "detail": detail}
        if status == "fail":
            fails.append(f"gate{n}_{name}: {detail}")
        elif status == "warning":
            warns.append(f"gate{n}_{name}: {detail}")

    mparts = manifest.get("parts", {})
    disk = _part_pngs(parts_dir)
    size = manifest.get("reference_size") or [0, 0]

    # 閘 1：齊全
    expected = set(thresholds.EXPECTED_PARTS)
    missing = expected - set(mparts)
    gate(1, "complete", "fail" if missing else "pass",
         f"missing={sorted(missing)}" if missing else "all present")

    # 閘 2：bijection 雙向
    m_names, d_names = set(mparts), set(disk)
    if m_names == d_names:
        gate(2, "bijection", "pass", f"{len(m_names)} parts")
    else:
        gate(2, "bijection", "fail",
             f"manifest_only={sorted(m_names - d_names)} disk_only={sorted(d_names - m_names)}")

    # 閘 3：manifest 數值有效
    errs = manifest_builder.validate_manifest(manifest)
    gate(3, "manifest_valid", "fail" if errs else "pass", "; ".join(errs) if errs else "ok")

    # 閘 4：上肢分離 ≤5%
    if {"upper_arm_l", "upper_arm_r"} <= (m_names & d_names):
        ml = _opaque_on_canvas(disk["upper_arm_l"], mparts["upper_arm_l"]["bbox"], size)
        mr = _opaque_on_canvas(disk["upper_arm_r"], mparts["upper_arm_r"]["bbox"], size)
        smaller = max(1, min(int(ml.sum()), int(mr.sum())))
        ov = int((ml & mr).sum()) / smaller
        gate(4, "arm_separation", "fail" if ov > thresholds.ARM_SEPARATION_MAX else "pass",
             f"overlap={ov:.3f} (max {thresholds.ARM_SEPARATION_MAX})")
    else:
        gate(4, "arm_separation", "warning", "upper_arm_l/r 缺，跳過")

    # 閘 5：L/R 對稱
    if {"upper_arm_l", "upper_arm_r"} <= (m_names & d_names):
        bl, br = mparts["upper_arm_l"]["bbox"], mparts["upper_arm_r"]["bbox"]
        al, ar = bl[2] * bl[3], br[2] * br[3]
        ratio = min(al, ar) / max(1, max(al, ar))
        cy_l, cy_r = bl[1] + bl[3] / 2, br[1] + br[3] / 2
        rh = max(1, size[1])
        cy_dev = abs(cy_l - cy_r) / rh
        ok = ratio >= thresholds.SYMMETRY_AREA_RATIO_MIN and cy_dev <= thresholds.SYMMETRY_CENTER_Y_TOL
        gate(5, "lr_symmetry", "pass" if ok else "warning",
             f"area_ratio={ratio:.2f} center_y_dev={cy_dev:.3f}")
    else:
        gate(5, "lr_symmetry", "warning", "upper_arm_l/r 缺，跳過")

    # 閘 6：部件內破洞
    holey = []
    for name, p in disk.items():
        if _interior_hole_ratio(p) > thresholds.HOLE_AREA_MAX:
            holey.append(name)
    gate(6, "interior_holes", "warning" if holey else "pass",
         f"holey={holey}" if holey else "none")

    # 閘 7：可組回 masked-SSIM
    ref = Image.open(reference_path).convert("RGB")
    ref_arr = np.asarray(ref)
    fg = _fg_mask(ref_arr)
    if disk and m_names == d_names:
        recom = spine_recompose.recompose(parts_dir, manifest)
        if recom.size != ref.size:
            recom = recom.resize(ref.size)
        g_ref = 0.299 * ref_arr[..., 0] + 0.587 * ref_arr[..., 1] + 0.114 * ref_arr[..., 2]
        g_rec = _gray_over_white(recom)
        # mask = recompose 實際貼了部件的區域（非全圖前景）→ desync 仍抓得到（部件貼錯位
        # 與 reference 對不上），但不罰 v1 scope 外、reference 上有但本就不打包的身體段（如腿）
        recom_mask = np.asarray(recom)[..., 3] > 0
        ssim = _ssim_masked(g_ref.astype(np.float64), g_rec, recom_mask)
        gate(7, "reassembly_ssim", "fail" if ssim < thresholds.REASSEMBLY_SSIM_MIN else "pass",
             f"ssim={ssim:.3f} (min {thresholds.REASSEMBLY_SSIM_MIN})")
    else:
        gate(7, "reassembly_ssim", "warning", "bijection 不成立，跳過")

    # 閘 8：前景覆蓋率（分母 = 部件 bbox 聯集區內的前景，非全圖）
    # 抓「打包區內的相連漏抓」（如 PoC 腿間尿布：在部件 bbox 內卻沒蓋），但不罰 v1 scope
    # 外、reference 上有但本就不打包的整段身體（如全身圖的下半身）——後者落在 bbox 聯集外。
    union = np.zeros(fg.shape, dtype=bool)
    present_boxes = []
    for name, p in disk.items():
        if name in mparts:
            union |= _opaque_on_canvas(p, mparts[name]["bbox"], size)
            present_boxes.append(mparts[name]["bbox"])
    region = np.zeros(fg.shape, dtype=bool)
    if present_boxes:
        ux0 = min(b[0] for b in present_boxes)
        uy0 = min(b[1] for b in present_boxes)
        ux1 = max(b[0] + b[2] for b in present_boxes)
        uy1 = max(b[1] + b[3] for b in present_boxes)
        region[max(0, uy0):uy1, max(0, ux0):ux1] = True
    else:
        region[:] = True
    fg_in = fg & region
    fg_total = int(fg_in.sum())
    cov = int((union & fg_in).sum()) / max(1, fg_total)
    white_bg = _is_white_bg(fg)
    if not white_bg:
        gate(8, "coverage", "warning", f"coverage={cov:.3f}（非白底 reference，分母近似不可信→降 warn）")
    elif cov >= thresholds.COVERAGE_TARGET:
        gate(8, "coverage", "pass", f"coverage={cov:.3f}（部件 bbox 聯集區內）")
    elif cov < thresholds.COVERAGE_GROSS_FAIL:
        gate(8, "coverage", "fail",
             f"coverage={cov:.3f}<{thresholds.COVERAGE_GROSS_FAIL}（gross 漏抓：整部件/大塊缺）")
    else:
        gate(8, "coverage", "warning",
             f"coverage={cov:.3f}<{thresholds.COVERAGE_TARGET}（seam loss：需 joint-dilate/更緊 hints 達標）")

    report["result"] = "fail" if fails else ("warning" if warns else "pass")
    report["coverage"] = round(cov, 4)
    return report
