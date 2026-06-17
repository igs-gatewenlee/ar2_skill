"""ar2 家族 SSOT registry 守恆測試（DGX 無關，純本地）。

可 `python3 test_registry.py` 跑，也可 pytest discover。
這些是「registry ↔ 消費者不可漂移」的機械鎖（CT-1/2 + 值等價 + EXPECTED 守恆）。
跨 skill 的 workflow/preset 守恆（CT-5/CT-6/CT-11）待 Phase 3 補。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SHARED = _HERE.parent.parent
_SKILLS = _SHARED.parent
sys.path.insert(0, str(_SHARED))

import ar2_registry as reg  # noqa: E402

# shim 在地提供的 per-skill 同名異值欄位（不在 registry 扁平面，由 config.py shim assign）
_SHIM_LOCAL = {"CACHE_DIR", "LOCAL_OUTPUT_DIR_NAME"}

_IMPORT_BLOCK = re.compile(r"from\s+config\s+import\s+\(([^)]*)\)", re.DOTALL)
_IMPORT_LINE = re.compile(r"from\s+config\s+import\s+([^\(\n]+)")


def _scan_config_imports() -> dict[str, set[str]]:
    """掃全家族 scripts/*.py 的 `from config import` 名 → {file: {names}}。"""
    found: dict[str, set[str]] = {}
    for py in _SKILLS.glob("dgx-comfyui-*/scripts/*.py"):
        text = py.read_text(encoding="utf-8")
        names: set[str] = set()
        for m in _IMPORT_BLOCK.finditer(text):
            names |= _parse_names(m.group(1))
        for m in _IMPORT_LINE.finditer(text):
            # 跳過多行型（已被 _IMPORT_BLOCK 抓），只認單行非 '(' 開頭
            seg = m.group(1).strip()
            if seg.startswith("("):
                continue
            names |= _parse_names(seg)
        if names:
            found[str(py.relative_to(_SKILLS))] = names
    return found


def _parse_names(blob: str) -> set[str]:
    out: set[str] = set()
    for raw in blob.split(","):
        tok = raw.split("#")[0].strip()
        if not tok:
            continue
        tok = tok.split(" as ")[0].strip()  # `X as Y` → X
        if tok.isidentifier():
            out.add(tok)
    return out


def test_ct1_name_coverage():
    """CT-1：所有 `from config import` 名 ⊆ registry 扁平面 ∪ shim-local。

    擋 `import *` 漏 re-export 造成某 skill 靜默 ImportError。
    """
    allowed = set(reg.__all__) | _SHIM_LOCAL
    imports = _scan_config_imports()
    union: set[str] = set()
    for names in imports.values():
        union |= names
    missing = union - allowed
    assert not missing, (
        f"以下 from-config import 名無對應 registry 屬性/shim-local：{sorted(missing)}\n"
        f"逐檔：{ {f: sorted(n - allowed) for f, n in imports.items() if n - allowed} }"
    )


def test_ct2_per_skill_distinct():
    """CT-2：同名異值欄位 per-skill 各異且正確（擋『一個 flat attr 裝三值』假 drop-in）。"""
    assert reg.cache_dir_for("check") == "~/.cache/ar2-dgx-comfyui-check"
    assert reg.cache_dir_for("gen") == "~/.cache/ar2-dgx-comfyui-gen"
    assert reg.cache_dir_for("train") == "~/.cache/ar2-dgx-comfyui-train"
    assert len({reg.cache_dir_for(s) for s in ("check", "gen", "train")}) == 3
    assert reg.output_dir_name_for("gen") == "outputs/ar2-dgx-comfyui-gen"
    assert reg.output_dir_name_for("train") == "outputs/ar2-dgx-comfyui-train"
    assert reg.output_dir_name_for("gen") != reg.output_dir_name_for("train")


def test_value_equality_vs_legacy_configs():
    """registry 值 == 遷移前 config.py 字面值（ground-truthed 2026-06-17）。"""
    assert reg.HOST == "192.168.5.27"
    assert reg.SSH_PORT == 7915
    assert reg.USER == "root"
    assert reg.PASSWORD == "root"
    assert reg.COMFYUI_PORT == 8199
    assert reg.COMFYUI_API_URL == "http://localhost:8199"
    assert reg.COMFYUI_ROOT == "/root/ComfyUI"
    assert reg.MODELS_DIR == "/root/ComfyUI/models"
    assert reg.OUTPUT_DIR == "/root/ComfyUI/output"
    assert reg.INPUT_DIR == "/root/ComfyUI/input"
    assert reg.CUSTOM_NODES_DIR == "/root/ComfyUI/custom_nodes"
    assert reg.COMFYUI_LORAS_DIR == "/root/ComfyUI/models/loras"
    assert reg.TRAINING_DIR == reg.TRAINING_ROOT == "/root/lora_training"
    assert reg.AITK_ROOT == "/root/ai-toolkit"
    assert reg.AITK_RUN_PY == "/root/ai-toolkit/run.py"
    assert reg.FLUX_BASE_PATH == "/root/flux-dev"
    assert reg.MIN_VRAM_FREE_MB == 22000
    assert reg.MIN_DISK_FREE_GB == 10
    assert reg.LAST_INVENTORY_FILE == "last-inventory.json"
    assert reg.LAST_RUN_FILE == "last-run.json"
    assert reg.LOCAL_DATASET_DIR_NAME == "datasets"
    assert reg.DGX_HOSTKEY == "SHA256:OtBB08rctm5cBhh7549/AGRICofd7LXa8Fw2sJXvOOA"
    assert reg.SSH_OPTS == [
        "-o", "PubkeyAuthentication=no",
        "-o", "PreferredAuthentications=password",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
    ]


def test_expected_models_superset_of_legacy():
    """EXPECTED_MODELS 涵蓋遷移前 inspect.py 的 14 類核心 + 新增 sams。"""
    legacy = {
        "checkpoints": [],
        "diffusion_models": ["flux1-dev.safetensors"],
        "clip": ["clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"],
        "vae": ["flux_ae.safetensors"],
        "loras": [],
        "controlnet": [],
        "embeddings": [],
        "upscale_models": [],
        "pulid": ["pulid_flux_v0.9.1.safetensors"],
        "clip_vision": [
            "EVA02_CLIP_L_336_psz14_s6B.safetensors",
            "sigclip_vision_patch14_384.safetensors",
        ],
        "style_models": ["flux1-redux-dev.safetensors"],
        "insightface": [],
        "facerestore_models": [],
        "layer_model": [],
    }
    for cat, files in legacy.items():
        assert cat in reg.EXPECTED_MODELS, f"EXPECTED_MODELS 漏類別 {cat}"
        assert reg.EXPECTED_MODELS[cat] == files, f"{cat} 檔名不符"
    assert "sams" in reg.EXPECTED_MODELS  # 新增第 15 類（開放）


def test_schema_version():
    assert reg.SCHEMA_VERSION == "1.0.0"


def test_no_secret_value_in_registry():
    """CT-8 雛形：registry 檔本身不含密碼字面（只准 secret_ref）。"""
    toml_text = (_SKILLS.parent / "dgx-registry.toml").read_text(encoding="utf-8")
    assert 'password' not in toml_text.lower() or 'secret_ref' in toml_text
    # 明確：registry 不得出現 password 鍵的字面賦值（等號後接引號的形式）
    assert not re.search(r'password\s*=\s*["\']', toml_text), "registry 不可含 password 字面賦值"


def test_ct8_no_secret_in_tracked_config():
    """CT-8：所有（現已 track 的）config.py shim 不得含密碼字面。

    config.py 從 gitignored 改為 tracked 零密值 shim 後，這道測試取代原本
    『gitignore 整個檔』的防線——擋住肥 config.py（含密碼）誤被 commit 回流。
    """
    cfgs = list(_SKILLS.glob("dgx-comfyui-*/config.py"))
    assert cfgs, "找不到任何 config.py shim（應有 check/gen/train）"
    for cfg in cfgs:
        text = cfg.read_text(encoding="utf-8")
        assert not re.search(r'PASSWORD\s*=\s*["\']', text), f"{cfg} 含 PASSWORD 字面賦值"
        assert not re.search(r'password\s*=\s*["\']', text), f"{cfg} 含 password 字面賦值"
        # shim 應走 ar2_registry，不得自帶 HOST/PASSWORD 等連線值字面
        assert "ar2_registry" in text, f"{cfg} 未透過 ar2_registry（疑似非 shim）"


def test_load_registry_missing_file_fail_loud():
    """_shared-10：registry 檔不存在時 fail-loud 給可操作 RuntimeError。

    覆蓋 ar2_registry.py line 36-40 的 not-found 分支——既有測試因真實
    dgx-registry.toml co-located 而從不觸發此路徑。用 subprocess 隔離：
    REGISTRY_PATH 與 _REG 皆在 import 時解析、模組已被 sibling 測試載入，
    in-process import 不會重跑；subprocess 全新 interpreter 才能命中分支，
    且不污染本進程 sys.modules（保護 sibling 測試）。

    斷言 4 個契約：① 非零 exit ② RuntimeError 型別 ③ 可操作中文訊息
    （含路徑回顯）④ AR2_REGISTRY_FILE 逃生門提示出現在訊息內。
    """
    bogus = "/nonexistent/ar2_registry_test/registry.toml"
    # hermetic（F-1）：clean env，移除 process 漂移變數，顯式設 AR2_REGISTRY_FILE
    env = {k: v for k, v in os.environ.items()}
    env.pop("AR2_OUTPUT_ROOT", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    env["AR2_REGISTRY_FILE"] = bogus
    r = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import ar2_registry",
            str(_SHARED),
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0, f"應 fail-loud 非零 exit，實得 0；stderr={r.stderr!r}"
    assert "RuntimeError" in r.stderr, f"應拋 RuntimeError；stderr={r.stderr!r}"
    assert "找不到 registry" in r.stderr, f"缺可操作中文訊息；stderr={r.stderr!r}"
    assert bogus in r.stderr, f"訊息未回顯違規路徑；stderr={r.stderr!r}"
    assert "AR2_REGISTRY_FILE" in r.stderr, f"缺逃生門提示；stderr={r.stderr!r}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  💥 {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
