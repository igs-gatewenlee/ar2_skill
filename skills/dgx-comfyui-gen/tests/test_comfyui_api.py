"""Tests for comfyui_api._post_json error-handling + success branches (gap gen-1).

Covers the previously-untested function body of comfyui_api._post_json
(scripts/comfyui_api.py lines 49-59): the urlopen call, HTTPError → ComfyUIError
wrapping (HTTP code + body capture), URLError → ComfyUIError wrapping (SSH tunnel
hint), and the success path. Also pins the *actual* behavior for malformed JSON
(raw json.JSONDecodeError bubbles up — it is NOT wrapped into ComfyUIError,
because the except clauses only catch HTTPError/URLError).

All tests mock urllib.request.urlopen — the real function body runs, no DGX /
GPU / network / SSH tunnel is touched. Fully hermetic and offline.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest import mock

import pytest

# Path setup so `import comfyui_api` works without installing the skill.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import comfyui_api  # noqa: E402


# -------- helpers ---------------------------------------------------------

class _FakeResp:
    """Context-manager stub mimicking urllib's HTTPResponse for the happy path."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _raise_http(code: int, body: bytes):
    """Build an urlopen side-effect that raises HTTPError(code) with a readable body."""

    def _side_effect(*_a, **_k):
        raise urllib.error.HTTPError(
            url="http://x/prompt",
            code=code,
            msg="error",
            hdrs=None,
            fp=io.BytesIO(body),
        )

    return _side_effect


def _raise_url(reason: str):
    """Build an urlopen side-effect that raises URLError(reason)."""

    def _side_effect(*_a, **_k):
        raise urllib.error.URLError(reason)

    return _side_effect


# -------- Branch 1: HTTPError → ComfyUIError (code + body captured) --------

def test_post_json_http_error_wraps_in_comfyui_error():
    """HTTP 500 → ComfyUIError carrying the status code, the path, and the body."""
    with mock.patch("urllib.request.urlopen", _raise_http(500, b"boom")):
        with pytest.raises(comfyui_api.ComfyUIError) as ei:
            comfyui_api._post_json("/prompt", {"a": 1})

    msg = str(ei.value)
    assert "HTTP 500" in msg          # status code surfaced
    assert "/prompt" in msg           # offending path surfaced
    assert "boom" in msg              # response body captured into message


def test_post_json_http_error_preserves_cause():
    """The wrapped ComfyUIError chains the original HTTPError as its cause."""
    with mock.patch("urllib.request.urlopen", _raise_http(404, b"missing")):
        with pytest.raises(comfyui_api.ComfyUIError) as ei:
            comfyui_api._post_json("/prompt", {})

    assert isinstance(ei.value.__cause__, urllib.error.HTTPError)
    assert "HTTP 404" in str(ei.value)


# -------- Branch 2: URLError → ComfyUIError (tunnel hint) ------------------

def test_post_json_url_error_includes_tunnel_hint():
    """URLError → ComfyUIError mentioning the URL, the reason, and the tunnel hint."""
    with mock.patch("urllib.request.urlopen", _raise_url("connection refused")):
        with pytest.raises(comfyui_api.ComfyUIError) as ei:
            comfyui_api._post_json("/prompt", {})

    msg = str(ei.value)
    assert "Is the SSH tunnel up?" in msg          # diagnostic hint present
    assert "connection refused" in msg             # underlying reason surfaced
    assert comfyui_api.COMFYUI_API_URL in msg      # full URL surfaced


# -------- Branch 3: success path regression -------------------------------

def test_post_json_success_returns_parsed_dict():
    """Normal 200 response → parsed JSON dict returned verbatim."""
    with mock.patch(
        "urllib.request.urlopen",
        lambda *a, **k: _FakeResp(b'{"prompt_id": "abc", "number": 3}'),
    ):
        result = comfyui_api._post_json("/prompt", {})

    assert result == {"prompt_id": "abc", "number": 3}


def test_post_json_sends_encoded_payload_to_correct_url():
    """The request targets COMFYUI_API_URL+path, POST method, JSON-encoded body."""
    captured: dict = {}

    def _capture(req, *a, **k):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["body"] = req.data
        captured["content_type"] = req.get_header("Content-type")
        return _FakeResp(b"{}")

    with mock.patch("urllib.request.urlopen", _capture):
        comfyui_api._post_json("/prompt", {"hello": "world"})

    assert captured["url"] == comfyui_api.COMFYUI_API_URL + "/prompt"
    assert captured["method"] == "POST"
    assert captured["body"] == json.dumps({"hello": "world"}).encode("utf-8")
    assert captured["content_type"] == "application/json"


# -------- Branch 4: malformed JSON — pin ACTUAL behavior -------------------

def test_post_json_malformed_body_raises_raw_jsondecodeerror():
    """Malformed JSON body bubbles up as raw json.JSONDecodeError, NOT ComfyUIError.

    The except clauses in _post_json only catch HTTPError/URLError, so the
    json.loads() failure is not wrapped. This pins the real (undefended) edge
    rather than the originally-claimed (false) ComfyUIError behavior.
    """
    with mock.patch(
        "urllib.request.urlopen", lambda *a, **k: _FakeResp(b"not json{{")
    ):
        with pytest.raises(json.JSONDecodeError):
            comfyui_api._post_json("/prompt", {})


def test_post_json_malformed_body_is_not_comfyui_error():
    """Explicit negative: the malformed-JSON failure is not a ComfyUIError subtype."""
    with mock.patch(
        "urllib.request.urlopen", lambda *a, **k: _FakeResp(b"<<bad")
    ):
        with pytest.raises(Exception) as ei:
            comfyui_api._post_json("/prompt", {})

    assert not isinstance(ei.value, comfyui_api.ComfyUIError)
    assert isinstance(ei.value, json.JSONDecodeError)
