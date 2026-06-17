"""ar2 家族 DGX 部署參數 SSOT loader（共用，git-tracked、零依賴）。

唯一真相來源 = ../../dgx-registry.toml（非機密）+ ~/.config/ar2/secrets.toml（密碼）。
各 skill 的 config.py 降為 thin shim：`from ar2_registry import *` + 在地推導 per-skill 值。

設計要點：
- tomllib（Python 3.11+ stdlib）→ 零新依賴，符合 `python3 foo.py` 無安裝呼叫。
- 非機密值 = 真實 module global（`import *` 直接帶入）。
- PASSWORD = 惰性解析（module __getattr__，PEP 562）：只在被存取時讀 secrets.toml。
  ∴ 純路徑消費者（plan）`import ar2_registry` 不會被迫要 secrets.toml；
    連線消費者（check/gen/train）`import *` 時才解析、缺則 fail-loud 給可操作錯誤。
- 唯一模組名 ar2_registry（非 'config'）→ 避開 sys.modules['config'] 跨 skill 借用碰撞。

模組命名紀律：沿用 transparent 既有 spec_from_file_location('ar2_config') 的唯一命名精神。
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

# --- 檔案定位（可用 env 覆蓋作逃生門）---------------------------------------
_HERE = Path(__file__).resolve()
REGISTRY_PATH = Path(
    os.environ.get("AR2_REGISTRY_FILE", _HERE.parents[2] / "dgx-registry.toml")
).expanduser()
SECRETS_PATH = Path(
    os.environ.get("AR2_SECRETS_FILE", Path.home() / ".config" / "ar2" / "secrets.toml")
).expanduser()

_REQUIRED_SCHEMA = (1, 0, 0)


def _load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        raise RuntimeError(
            f"ar2_registry: 找不到 registry {REGISTRY_PATH}。"
            f"（同 plugin 應 co-located；或設 AR2_REGISTRY_FILE 覆蓋）"
        )
    with open(REGISTRY_PATH, "rb") as f:
        return tomllib.load(f)


_REG = _load_registry()

# --- schema 版本守恆（fail-loud，同 plan_schema 1.4.0 慣例）------------------
SCHEMA_VERSION = _REG.get("schema_version", "0.0.0")
_sv = tuple(int(x) for x in SCHEMA_VERSION.split("."))
if _sv < _REQUIRED_SCHEMA:
    raise RuntimeError(
        f"ar2_registry: schema_version {SCHEMA_VERSION} < "
        f"required {'.'.join(map(str, _REQUIRED_SCHEMA))}。請更新 dgx-registry.toml。"
    )

# --- machine（v1 單台）------------------------------------------------------
_M = _REG["machine"]
_P = _M["paths"]
_G = _M["gpu_constraints"]
_C = _M["credential"]
_L = _REG["local"]

# 連線 ----------------------------------------------------------------------
HOST = _M["host"]
SSH_PORT = _M["ssh_port"]
USER = _M["user"]
SSH_OPTS = list(_M["ssh_opts"])
COMFYUI_PORT = _M["comfyui_port"]
COMFYUI_API_URL = f"http://localhost:{COMFYUI_PORT}"
DGX_HOSTKEY = _M["ssh_hostkey_sha256"]

# DGX 路徑（顯式 + 由 comfyui_root / aitk_root 衍生，與舊 config.py f-string 一致）---
COMFYUI_ROOT = _P["comfyui_root"]
MODELS_DIR = f"{COMFYUI_ROOT}/models"
OUTPUT_DIR = f"{COMFYUI_ROOT}/output"
INPUT_DIR = f"{COMFYUI_ROOT}/input"
CUSTOM_NODES_DIR = f"{COMFYUI_ROOT}/custom_nodes"
COMFYUI_LORAS_DIR = f"{COMFYUI_ROOT}/models/loras"
SAMS_DIR = f"{COMFYUI_ROOT}/models/sams"
# training_root 同值雙名 alias：check 用 TRAINING_DIR、train 用 TRAINING_ROOT
TRAINING_ROOT = _P["training_root"]
TRAINING_DIR = TRAINING_ROOT
AITK_ROOT = _P["aitk_root"]
AITK_RUN_PY = f"{AITK_ROOT}/run.py"
FLUX_BASE_PATH = _P["flux_base_path"]
COMFYUI_LOG = _P["comfyui_log"]
START_SCRIPT_DEPLOY_PATH = _P["start_script_deploy_path"]
DISK_PROBE_FS = _P["disk_probe_fs"]

# GPU / 啟動約束 ------------------------------------------------------------
GPU_DRIVER = _G["driver"]
GPU_CUDA = _G["cuda"]
GPU_MODEL = _G["gpu_model"]
COMFYUI_LAUNCH_FLAGS = list(_G["comfyui_launch_flags"])
COMFYUI_LISTEN = _G["comfyui_listen"]
PROCESS_PGREP_PATTERN = _G["process_pgrep_pattern"]
MIN_VRAM_FREE_MB = _G["min_vram_free_mb"]
MIN_DISK_FREE_GB = _G["min_disk_free_gb"]

# 本機端慣例（family 共用常數）----------------------------------------------
LAST_INVENTORY_FILE = _L["last_inventory_file"]
LAST_RUN_FILE = _L["last_run_file"]
LOCAL_DATASET_DIR_NAME = _L["local_dataset_dir_name"]
OUTPUT_ANCHOR_ORDER = list(_L["output_anchor_order"])
_CACHE_DIR_TPL = _L["cache_dir_tpl"]
_OUTPUT_DIR_NAME_TPL = _L["output_dir_name_tpl"]

# 模型盤點對照（inspect.py 的 EXPECTED 直接讀此）-----------------------------
EXPECTED_MODELS = {k: list(v) for k, v in _REG["expected_models"].items()}

# 全補納管：workflow 模型 / 自訂節點 / 路線狀態（守恆測試 CT-5/11 用）-----------
WORKFLOW_MODELS = {k: list(v) for k, v in _REG.get("workflow_models", {}).items()}
REQUIRED_NODES = {k: dict(v) for k, v in _REG.get("required_nodes", {}).items()}
ROUTE_STATUS = dict(_REG.get("route_status", {}))

# 憑證 metadata（非密值）----------------------------------------------------
CREDENTIAL_KIND = _C["kind"]
CREDENTIAL_SECRET_REF = _C["secret_ref"]
CREDENTIAL_DISTRIBUTION = _C["distribution"]


# --- per-skill 值的 helper（同名異值由此集中產生，shim 在地呼叫）-------------
def cache_dir_for(skill: str) -> str:
    """`~/.cache/ar2-dgx-comfyui-{skill}`。skill = 短名（check/gen/train/...）。"""
    return _CACHE_DIR_TPL.format(skill=skill)


def output_dir_name_for(skill: str) -> str:
    """`outputs/ar2-dgx-comfyui-{skill}`（cwd 相對輸出目錄名）。"""
    return _OUTPUT_DIR_NAME_TPL.format(skill=skill)


# --- 密碼惰性解析（PEP 562 module __getattr__）------------------------------
_PASSWORD_CACHE: str | None = None


def _resolve_password() -> str:
    global _PASSWORD_CACHE
    if _PASSWORD_CACHE is not None:
        return _PASSWORD_CACHE
    # 逃生門：環境變數優先（避免單一 secrets.toml 故障鎖死全家族）
    env = os.environ.get("AR2_DGX_PASSWORD")
    if env:
        _PASSWORD_CACHE = env
        return env
    if not SECRETS_PATH.exists():
        raise RuntimeError(
            f"ar2_registry: 找不到密碼。請建立 {SECRETS_PATH}：\n"
            f'  [machine]\n  password = "root"\n'
            f"（內網共用預設 root/root），或設環境變數 AR2_DGX_PASSWORD。"
        )
    with open(SECRETS_PATH, "rb") as f:
        secrets = tomllib.load(f)
    # 解析 credential.secret_ref（如 "machine.password"）；綁定 namespace 防跨機污染
    parts = CREDENTIAL_SECRET_REF.split(".")
    if parts[0] != "machine":
        raise RuntimeError(
            f"ar2_registry: secret_ref {CREDENTIAL_SECRET_REF!r} namespace "
            f"前綴非 'machine'（防跨機 secret 污染）。"
        )
    node: object = secrets
    for p in parts:
        try:
            node = node[p]  # type: ignore[index]
        except (KeyError, TypeError):
            raise RuntimeError(
                f"ar2_registry: secrets.toml 缺 {CREDENTIAL_SECRET_REF}（找不到 {p!r}）。"
                f"請補：[machine]\\npassword = \"root\"。"
            )
    if not isinstance(node, str):
        raise RuntimeError(f"ar2_registry: secret {CREDENTIAL_SECRET_REF} 不是字串。")
    _PASSWORD_CACHE = node
    return node


def __getattr__(name: str):
    # 惰性屬性：PASSWORD 只在被存取時解析（plan 純路徑消費者不觸發）
    if name == "PASSWORD":
        return _resolve_password()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# `from ar2_registry import *` 帶入的扁平面（PASSWORD 惰性、仍列入 → import * 時解析）
__all__ = [
    # 連線
    "HOST", "SSH_PORT", "USER", "PASSWORD", "SSH_OPTS",
    "COMFYUI_PORT", "COMFYUI_API_URL", "DGX_HOSTKEY",
    # 路徑
    "COMFYUI_ROOT", "MODELS_DIR", "OUTPUT_DIR", "INPUT_DIR", "CUSTOM_NODES_DIR",
    "COMFYUI_LORAS_DIR", "SAMS_DIR", "TRAINING_ROOT", "TRAINING_DIR",
    "AITK_ROOT", "AITK_RUN_PY", "FLUX_BASE_PATH",
    "COMFYUI_LOG", "START_SCRIPT_DEPLOY_PATH", "DISK_PROBE_FS",
    # GPU
    "GPU_DRIVER", "GPU_CUDA", "GPU_MODEL", "COMFYUI_LAUNCH_FLAGS",
    "COMFYUI_LISTEN", "PROCESS_PGREP_PATTERN", "MIN_VRAM_FREE_MB", "MIN_DISK_FREE_GB",
    # 本機慣例
    "LAST_INVENTORY_FILE", "LAST_RUN_FILE", "LOCAL_DATASET_DIR_NAME",
    "OUTPUT_ANCHOR_ORDER",
    # 模型 / 節點 / 路線 / 憑證 metadata
    "EXPECTED_MODELS", "WORKFLOW_MODELS", "REQUIRED_NODES", "ROUTE_STATUS",
    "CREDENTIAL_KIND", "CREDENTIAL_SECRET_REF", "CREDENTIAL_DISTRIBUTION",
    "SCHEMA_VERSION",
    # helper
    "cache_dir_for", "output_dir_name_for",
]
