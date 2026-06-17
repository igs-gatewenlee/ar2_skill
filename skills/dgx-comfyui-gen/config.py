"""Thin shim — DGX 部署參數 SSOT 在 ../../dgx-registry.toml + ~/.config/ar2/secrets.toml。

保留此檔僅為向後相容既有 `from config import X` 呼叫點；值由 _shared/ar2_registry 提供。
（gitignored，沿襲家族慣例；本檔已無任何密碼字面 —— 密碼在 repo 外 secrets.toml。）
"""
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "_shared"))

from ar2_registry import *  # noqa: F401,F403,E402
import ar2_registry as _reg  # noqa: E402

# per-skill 同名異值（在地推導 skill 短名：dgx-comfyui-<skill>）
_SKILL = _Path(__file__).resolve().parent.name.replace("dgx-comfyui-", "")
CACHE_DIR = _reg.cache_dir_for(_SKILL)
LOCAL_OUTPUT_DIR_NAME = _reg.output_dir_name_for(_SKILL)
