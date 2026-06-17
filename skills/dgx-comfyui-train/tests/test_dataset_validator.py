"""Tests for dataset_validator.validate() — gating logic before LoRA upload/train.

Covers P3 coverage gaps:
- train-5: validate() overall logic (happy path / bad-ext / too-few / missing-caption
           / empty-caption-warning / dir-not-found).
- train-6: OSError on caption read → graceful degrade to empty content → warning
           (not a blocker, no exception leakage).
- train-7: PIL resolution branch (min(w,h) < 512 warn, boundary < not <=, corrupt
           image swallowed by except Exception: continue).

All tests are hermetic (no AR2_OUTPUT_ROOT / CLAUDE_PROJECT_DIR dependency, no DGX /
GPU / SSH / network). validate() only reads a local directory Path, so synthetic
dataset trees are built under tmp_path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import dataset_validator as dv  # noqa: E402


# ---------- hermetic isolation ----------

@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    """F-1: never depend on process env; pin cwd to an isolated tmp dir."""
    monkeypatch.delenv("AR2_OUTPUT_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)


# ---------- helpers ----------

def _write_pair(d: Path, stem: str, ext: str = ".jpg", caption: str = "a caption",
                img_bytes: bytes = b"\xff\xd8\xff\xe0fakejpeg"):
    """Create an image file `stem+ext` and a same-name .txt caption.

    img_bytes default is junk — validate()'s core logic never decodes pixels
    (only PIL resolution check does, and it swallows decode errors). Tests that
    exercise the PIL branch pass real PNG bytes instead.
    """
    (d / f"{stem}{ext}").write_bytes(img_bytes)
    (d / f"{stem}.txt").write_text(caption)


def _make_dataset(d: Path, n: int = 5, ext: str = ".jpg",
                  caption: str = "a caption"):
    """n image+caption pairs under d."""
    for i in range(n):
        _write_pair(d, f"img{i}", ext=ext, caption=caption)


# ================= train-5: validate() overall logic =================

def test_train5_case_a_happy_path(tmp_path):
    """Case A: 5 jpg + 5 non-empty txt → ok, count 5, no blockers."""
    ds = tmp_path / "ds_a"
    ds.mkdir()
    _make_dataset(ds, n=5)

    r = dv.validate(ds)

    assert r.ok is True
    assert r.image_count == 5
    assert r.blockers == []


def test_train5_case_b_bad_ext_blocker(tmp_path):
    """Case B: happy path + 1 bad.webp → blocked; webp NOT counted as image."""
    ds = tmp_path / "ds_b"
    ds.mkdir()
    _make_dataset(ds, n=5)
    (ds / "bad.webp").write_bytes(b"RIFFfakewebp")
    # webp has no .txt; that's fine — webp is not in `images` so no caption check.

    r = dv.validate(ds)

    assert r.ok is False
    assert r.image_count == 5  # webp excluded from image count
    assert any("unsupported image extensions" in b for b in r.blockers)
    assert any("bad.webp" in b for b in r.blockers)


def test_train5_case_c_too_few_images(tmp_path):
    """Case C: only 3 jpg+txt pairs → blocked, count 3, 'need ≥ 5' blocker."""
    ds = tmp_path / "ds_c"
    ds.mkdir()
    _make_dataset(ds, n=3)

    r = dv.validate(ds)

    assert r.ok is False
    assert r.image_count == 3
    assert any("need ≥ 5" in b for b in r.blockers)


def test_train5_case_d_missing_caption_blocker(tmp_path):
    """Case D: 5 jpg but only 3 have .txt → blocked on missing caption."""
    ds = tmp_path / "ds_d"
    ds.mkdir()
    # 3 full pairs
    for i in range(3):
        _write_pair(ds, f"img{i}")
    # 2 images with NO caption
    (ds / "img3.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    (ds / "img4.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")

    r = dv.validate(ds)

    assert r.ok is False
    assert r.image_count == 5
    assert any("missing .txt caption" in b for b in r.blockers)


def test_train5_case_e_empty_caption_is_warning_not_blocker(tmp_path):
    """Case E: 5 jpg + 5 whitespace-only txt → ok (warning only, no blocker)."""
    ds = tmp_path / "ds_e"
    ds.mkdir()
    for i in range(5):
        _write_pair(ds, f"img{i}", caption="   \n  \t ")

    r = dv.validate(ds)

    assert r.ok is True
    assert r.blockers == []
    assert any("empty caption" in w for w in r.warnings)


def test_train5_case_f_dir_not_found(tmp_path):
    """Case F: nonexistent dir → blocked, count 0, 'dataset dir not found'."""
    missing = tmp_path / "nope" / "xyz123"

    r = dv.validate(missing)

    assert r.ok is False
    assert r.image_count == 0
    assert any("dataset dir not found" in b for b in r.blockers)


def test_train5_path_to_a_file_not_dir(tmp_path):
    """Defensive: a path that exists but is a file (not dir) → dir-not-found blocker.

    Guards the `not dataset_dir.is_dir()` half of the early-return condition.
    """
    f = tmp_path / "afile.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")

    r = dv.validate(f)

    assert r.ok is False
    assert r.image_count == 0
    assert any("dataset dir not found" in b for b in r.blockers)


def test_train5_txt_and_json_metadata_ignored(tmp_path):
    """.txt captions and .json aitk metadata must not count as bad_ext nor images."""
    ds = tmp_path / "ds_meta"
    ds.mkdir()
    _make_dataset(ds, n=5)
    (ds / "config.json").write_text("{}")  # aitk metadata — must be ignored

    r = dv.validate(ds)

    assert r.ok is True
    assert r.image_count == 5
    assert r.blockers == []


# ================= train-6: OSError on caption read (graceful) =================

@pytest.mark.skipif(os.getuid() == 0, reason="root bypasses chmod 000 read protection")
def test_train6_oserror_caption_read_degrades_to_empty_warning(tmp_path):
    """train-6: a read-protected .txt raises OSError on read_text → caught →
    content="" → counted as empty caption (warning), never a blocker, no raise.
    """
    ds = tmp_path / "ds_perm"
    ds.mkdir()
    # 5 valid pairs; img0's caption will be made unreadable.
    for i in range(5):
        _write_pair(ds, f"img{i}", caption="a real caption")
    protected = ds / "img0.txt"
    os.chmod(protected, 0o000)

    try:
        r = dv.validate(ds)  # must NOT raise
    finally:
        os.chmod(protected, 0o644)  # restore for cleanup

    assert r.image_count == 5
    # OSError must not be promoted into a blocker.
    assert not any("missing" in b for b in r.blockers)
    assert not any("images, need" in b for b in r.blockers)
    assert r.blockers == []
    # OSError → content="" → empty caption warning mentioning img0.jpg.
    empty_warnings = [w for w in r.warnings if "empty caption" in w]
    assert empty_warnings
    assert any("img0.jpg" in w for w in empty_warnings)
    assert r.ok is True


# ================= train-7: PIL resolution branch =================

def _save_png(path: Path, w: int, h: int):
    from PIL import Image
    Image.new("RGB", (w, h), color=(123, 222, 64)).save(path)


def test_train7_low_res_short_side_triggers_warning(tmp_path):
    """train-7.1: min(w,h) < 512 triggers low_res warning; guards min() semantics
    by including a landscape image (wide but short) that must also trigger.
    """
    ds = tmp_path / "ds_lowres"
    ds.mkdir()
    # portrait 400x600 → short side 400 < 512
    _save_png(ds / "portrait.png", 400, 600)
    (ds / "portrait.txt").write_text("cap")
    # landscape 600x400 → short side 400 < 512 (would NOT trip if check were w<512)
    _save_png(ds / "landscape.png", 600, 400)
    (ds / "landscape.txt").write_text("cap")
    # 3 more big images to satisfy MIN_IMAGES=5
    for i in range(3):
        _save_png(ds / f"big{i}.png", 800, 800)
        (ds / f"big{i}.txt").write_text("cap")

    r = dv.validate(ds)

    low_res = [w for w in r.warnings if "side < 512px" in w]
    assert low_res, "expected a low-resolution warning"
    joined = " ".join(low_res)
    assert "400x600" in joined  # portrait short side reported
    assert "600x400" in joined  # landscape also flagged (min(w,h) semantics)


def test_train7_exactly_512_passes_no_warning(tmp_path):
    """train-7.2: 512x512 + four ≥512 images → no low_res warning; ok True."""
    ds = tmp_path / "ds_512"
    ds.mkdir()
    _save_png(ds / "ok.png", 512, 512)
    (ds / "ok.txt").write_text("cap")
    for i in range(4):
        _save_png(ds / f"big{i}.png", 700, 700)
        (ds / f"big{i}.txt").write_text("cap")

    r = dv.validate(ds)

    assert not any("side <" in w for w in r.warnings)
    assert r.ok is True
    assert r.blockers == []


def test_train7_corrupt_image_does_not_crash(tmp_path):
    """train-7.3: a corrupt .png is swallowed by `except Exception: continue`;
    validate() returns a ValidationResult and the bad file is in no low_res warning.
    """
    ds = tmp_path / "ds_corrupt"
    ds.mkdir()
    (ds / "corrupt.png").write_bytes(b"not a real image")
    (ds / "corrupt.txt").write_text("cap")
    # fill to MIN_IMAGES with valid big images
    for i in range(4):
        _save_png(ds / f"big{i}.png", 800, 800)
        (ds / f"big{i}.txt").write_text("cap")

    r = dv.validate(ds)  # must NOT raise

    assert isinstance(r, dv.ValidationResult)
    assert r.image_count == 5  # corrupt.png still counts (valid ext)
    assert not any("corrupt.png" in w for w in r.warnings)


def test_train7_boundary_511_warns_513_does_not(tmp_path):
    """train-7.4: strict `<` — 511px short side warns, 513px does not."""
    ds = tmp_path / "ds_boundary"
    ds.mkdir()
    # 511 short side → should warn
    _save_png(ds / "small.png", 511, 1000)
    (ds / "small.txt").write_text("cap")
    # 513 short side → must NOT warn (guards < vs <=)
    _save_png(ds / "edge.png", 513, 1000)
    (ds / "edge.txt").write_text("cap")
    for i in range(3):
        _save_png(ds / f"big{i}.png", 800, 800)
        (ds / f"big{i}.txt").write_text("cap")

    r = dv.validate(ds)

    low_res = [w for w in r.warnings if "side < 512px" in w]
    joined = " ".join(low_res)
    assert "511x1000" in joined  # 511 < 512 → warned
    assert "513x1000" not in joined  # 513 not < 512 → not warned
