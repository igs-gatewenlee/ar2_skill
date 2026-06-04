"""per-asset 資料夾結構 + 版本遞增 + 檔名生成（P1 設計規格 §5.6 / §10）。

循序執行，不支援並發（v1 不做並發批次）。
檔名：{category}_{slug}_{size}_v{NNN}.png
資料夾：{out_root}/{run_tag}/{category}_{slug}/
"""
from __future__ import annotations

import re
from pathlib import Path

_VER_RE = re.compile(r"_v(\d{3})\.png$", re.IGNORECASE)

# 保留字：final 檔名為 {category}_{slug}_..., stem=category。若 category 取這些值，final
# 會被 qc.run_qc 的 BC-5 中間檔守衛假判為中間檔而 raise。在命名來源直接擋掉（R-3）。
_RESERVED_CATEGORIES = {"source", "mask", "rgb", "alpha", "preview"}


def validate_category(category: str) -> str:
    if str(category).lower() in _RESERVED_CATEGORIES:
        raise ValueError(
            f"category={category!r} 為保留字（{sorted(_RESERVED_CATEGORIES)}）"
            f"，會與中間檔前綴衝突，請改名（R-3）"
        )
    return category


def asset_folder(out_root: str | Path, run_tag: str, category: str, slug: str) -> Path:
    """回傳 per-asset 資料夾路徑（不建立）。"""
    return Path(out_root) / run_tag / f"{category}_{slug}"


def next_version(asset_folder_path: str | Path, category: str, slug: str, size) -> int:
    """掃 asset_folder 內既有 {category}_{slug}_{size}_v{NNN}.png，回 max+1（首次 1）。

    BC-10：同資料夾已有 v001 → 回 2（v001 不被覆蓋）。
    """
    folder = Path(asset_folder_path)
    prefix = f"{category}_{slug}_{size}_v"
    mx = 0
    if folder.is_dir():
        for p in folder.glob(f"{category}_{slug}_{size}_v*.png"):
            m = _VER_RE.search(p.name)
            if m and p.name.startswith(prefix):
                mx = max(mx, int(m.group(1)))
    return mx + 1


def asset_filename(category: str, slug: str, size, version: int) -> str:
    """{category}_{slug}_{size}_v{NNN}.png（§10）。category 保留字 → raise（R-3）。"""
    validate_category(category)
    return f"{category}_{slug}_{size}_v{version:03d}.png"
