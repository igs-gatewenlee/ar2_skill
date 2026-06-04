"""Local dataset validation before upload.

Plan E (medium strictness):
- ≥ 5 images (block on fail)
- every image has same-name .txt caption (block on fail)
- extension in {.jpg, .jpeg, .png} (block on others)
- resolution ≥ 512px (warn only)
- caption non-empty (warn only)

Uses PIL if available; otherwise resolution check is skipped with a warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

VALID_IMG_EXTS = {".jpg", ".jpeg", ".png"}
MIN_IMAGES = 5
MIN_RESOLUTION = 512


@dataclass
class ValidationResult:
    ok: bool
    image_count: int
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate(dataset_dir: Path) -> ValidationResult:
    """Validate dataset_dir contents. Returns ValidationResult."""
    result = ValidationResult(ok=False, image_count=0)

    if not dataset_dir.exists() or not dataset_dir.is_dir():
        result.blockers.append(f"dataset dir not found: {dataset_dir}")
        return result

    images: list[Path] = []
    bad_ext: list[Path] = []
    for p in dataset_dir.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() in VALID_IMG_EXTS:
            images.append(p)
        elif p.suffix.lower() not in {".txt", ".json"}:  # ignore captions and aitk metadata
            # Treat as bad if it looks like an image with wrong ext
            if p.suffix.lower() in {".webp", ".bmp", ".tiff", ".gif"}:
                bad_ext.append(p)

    result.image_count = len(images)

    if bad_ext:
        result.blockers.append(
            f"unsupported image extensions ({len(bad_ext)}): "
            f"convert to {VALID_IMG_EXTS}. e.g. {bad_ext[0].name}"
        )

    if len(images) < MIN_IMAGES:
        result.blockers.append(
            f"only {len(images)} images, need ≥ {MIN_IMAGES}"
        )

    # caption pairing
    missing_caption: list[str] = []
    empty_caption: list[str] = []
    for img in images:
        txt = img.with_suffix(".txt")
        if not txt.exists():
            missing_caption.append(img.name)
            continue
        try:
            content = txt.read_text().strip()
        except OSError:
            content = ""
        if not content:
            empty_caption.append(img.name)

    if missing_caption:
        result.blockers.append(
            f"{len(missing_caption)} image(s) missing .txt caption: "
            f"{', '.join(missing_caption[:3])}"
            f"{'...' if len(missing_caption) > 3 else ''}"
        )
    if empty_caption:
        result.warnings.append(
            f"{len(empty_caption)} image(s) have empty caption (will still work "
            f"with trigger_word auto-prepend): {', '.join(empty_caption[:3])}"
        )

    # resolution (best effort, requires PIL)
    try:
        from PIL import Image  # noqa: F401
        low_res: list[str] = []
        for img in images:
            try:
                with Image.open(img) as im:
                    w, h = im.size
                    if min(w, h) < MIN_RESOLUTION:
                        low_res.append(f"{img.name} ({w}x{h})")
            except Exception:
                continue
        if low_res:
            result.warnings.append(
                f"{len(low_res)} image(s) have side < {MIN_RESOLUTION}px (ai-toolkit "
                f"will bucket but quality may suffer): "
                f"{', '.join(low_res[:3])}"
            )
    except ImportError:
        result.warnings.append(
            "PIL/Pillow not installed locally — skipping resolution check. "
            "Install with `pip install Pillow` to enable."
        )

    result.ok = not result.blockers
    return result
