"""ComfyUI HTTP API client.

Requires SSH tunnel to forward localhost:8199 → DGX:8199 (use
ssh_client.ensure_tunnel() before calling these functions).

Public surface:
- submit_prompt(workflow, client_id) -> (prompt_id, queue_number, node_errors)
- wait_for_completion(prompt_id, poll_interval, timeout) -> outputs dict
- list_output_files(outputs) -> list of (filename, subfolder)
- get_queue_position(prompt_id) -> int | None
- get_queue_size() -> tuple[int, int] | None
- clear_queue() -> bool
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import COMFYUI_API_URL  # noqa: E402


class ComfyUIError(RuntimeError):
    """Generic ComfyUI API failure."""


class WorkflowRejected(ComfyUIError):
    """ComfyUI returned node_errors — workflow did not pass validation."""

    def __init__(self, node_errors: dict):
        self.node_errors = node_errors
        super().__init__(f"workflow rejected: {json.dumps(node_errors, indent=2)}")


def _post_json(path: str, payload: dict, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{COMFYUI_API_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise ComfyUIError(f"HTTP {e.code} on {path}: {body}") from e
    except urllib.error.URLError as e:
        raise ComfyUIError(
            f"Cannot reach ComfyUI at {COMFYUI_API_URL}{path}: {e.reason}. "
            f"Is the SSH tunnel up?"
        ) from e


def _get_json(path: str, timeout: int = 10) -> dict:
    try:
        with urllib.request.urlopen(f"{COMFYUI_API_URL}{path}", timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise ComfyUIError(f"HTTP {e.code} on {path}: {body}") from e
    except urllib.error.URLError as e:
        raise ComfyUIError(
            f"Cannot reach ComfyUI at {COMFYUI_API_URL}{path}: {e.reason}"
        ) from e


def submit_prompt(
    workflow: dict, client_id: str
) -> tuple[str, int, dict]:
    """POST a workflow to /prompt. Returns (prompt_id, queue_number, node_errors)."""
    result = _post_json("/prompt", {"prompt": workflow, "client_id": client_id})
    prompt_id = result.get("prompt_id")
    queue_number = result.get("number", 0)
    node_errors = result.get("node_errors") or {}

    if node_errors:
        raise WorkflowRejected(node_errors)
    if not prompt_id:
        raise ComfyUIError(f"unexpected response: {result}")

    return prompt_id, queue_number, node_errors


def wait_for_completion(
    prompt_id: str,
    poll_interval: float = 1.0,
    timeout: float = 1800.0,
    progress_cb=None,
) -> dict:
    """Poll /history/{prompt_id} until outputs appear. Returns the outputs dict.

    progress_cb(elapsed_sec) called once per poll cycle (for caller UI).
    """
    started = time.time()
    while True:
        elapsed = time.time() - started
        if elapsed > timeout:
            raise ComfyUIError(
                f"timeout after {timeout:.0f}s waiting for prompt {prompt_id}"
            )

        history = _get_json(f"/history/{prompt_id}")
        if prompt_id in history:
            entry = history[prompt_id]
            outputs = entry.get("outputs", {})
            if outputs:
                return outputs

        if progress_cb is not None:
            progress_cb(elapsed)

        time.sleep(poll_interval)


def list_output_files(outputs: dict) -> list[tuple[str, str]]:
    """Walk the outputs tree, return list of (filename, subfolder) for images."""
    files: list[tuple[str, str]] = []
    for node_out in outputs.values():
        for img in node_out.get("images", []):
            filename = img.get("filename")
            subfolder = img.get("subfolder", "")
            if filename:
                files.append((filename, subfolder))
    return files


def get_queue_position(prompt_id: str) -> int | None:
    """Look at /queue and return this prompt's position (1-indexed) or None."""
    try:
        q = _get_json("/queue")
    except ComfyUIError:
        return None
    pending = q.get("queue_pending", [])
    running = q.get("queue_running", [])
    # Each entry shape: [number, prompt_id, prompt_dict, extra, ...]
    for i, entry in enumerate(running):
        if len(entry) >= 2 and entry[1] == prompt_id:
            return 0  # running now
    for i, entry in enumerate(pending):
        if len(entry) >= 2 and entry[1] == prompt_id:
            return i + 1
    return None


def get_queue_size() -> tuple[int, int] | None:
    """GET /queue. Returns (pending_count, running_count) or None on error.

    Missing keys default to (0, 0); a non-dict response returns None. Never
    raises — matches the "do not raise" style of clear_queue/get_queue_position.
    """
    try:
        q = _get_json("/queue")
    except ComfyUIError:
        return None
    try:
        return len(q.get("queue_pending", [])), len(q.get("queue_running", []))
    except (AttributeError, TypeError):
        return None


def clear_queue() -> bool:
    """POST /queue {clear: true}. Returns True on success, False on error.

    Does NOT raise — caller decides whether to abort or continue.
    """
    try:
        _post_json("/queue", {"clear": True})
        return True
    except ComfyUIError:
        return False
