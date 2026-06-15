"""獨立『純依 manifest』貼回器（P1 設計規格 §1.5 / BC-4）。

只讀 manifest 的 `bbox[x,y]` + `draw_order` 把各 part PNG 貼回空畫布，
**不 import spine_sam、不重用切件階段任何 transform** —— 這是 QC 第 7 閘 desync
偵測能成立的前提（若重用切件 transform，bbox 錯位也會被一起錯回去而抓不到）。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image


def recompose(parts_dir, manifest: dict) -> Image.Image:
    """回 RGBA 畫布（= reference_size），各 part 依 draw_order（小→先畫/底層）貼在 bbox[x,y]。

    同 draw_order 以 name 字典序 tie-break（BC-7）。缺檔的 part 跳過（齊全性由 QC 閘1 管）。
    """
    rw, rh = manifest["reference_size"]
    canvas = Image.new("RGBA", (int(rw), int(rh)), (0, 0, 0, 0))
    parts_dir = Path(parts_dir)
    order = sorted(manifest["parts"].items(), key=lambda kv: (kv[1]["draw_order"], kv[0]))
    for name, e in order:
        png = parts_dir / f"{name}.png"
        if not png.exists():
            continue
        part = Image.open(png).convert("RGBA")
        x, y = int(e["bbox"][0]), int(e["bbox"][1])
        # 用整畫布 layer + paste（paste 會自動裁切超界，避免 alpha_composite 越界 raise）
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        layer.paste(part, (x, y))
        canvas = Image.alpha_composite(canvas, layer)
    return canvas
