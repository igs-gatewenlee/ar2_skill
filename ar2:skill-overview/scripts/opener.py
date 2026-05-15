"""Open a file path in the system default browser via macOS `open`.

EH-5 fallback: print file:// URL to stderr when `open` is unavailable.
"""

import subprocess
import sys
from pathlib import Path


def open_file(path: Path) -> bool:
    """Open `path` via macOS `open`. Returns True on success, False on fallback."""
    url = f"file://{path}"
    try:
        result = subprocess.run(
            ["open", url],
            check=False,
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    print(f"請手動打開：{url}", file=sys.stderr)
    return False
