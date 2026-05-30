"""Sanitize the public viewer-config.json written by publish_scene.

Bug-audit #3 (severity HIGH): the standalone ``--config`` JSON path lets any
top-level / nested key flow from a hostile or careless config file straight
into the CDN-public ``viewer-config.json``. Specifically, a
``save_backend.secret`` (or any internal note / local-only path / dev flag)
would have been deep-copied and written verbatim alongside the
``primary_asset`` pointer.

These tests lock the fix from two angles:

  1. **Unit** -- ``sanitize_public_viewer_config`` is a strict allow-list
     pass: only known public keys flow through, ``save_backend`` is filtered
     to its own narrow sub-key allow-list, and the function returns a deep
     copy (mutating either side does not bleed into the other).

  2. **Integration** -- end-to-end ``publish_scene`` with a hostile
     ``base_config`` (carrying a ``save_backend.secret`` + ``internal_notes``
     + ``local_only_path`` + ``_dev_flag``) writes a sanitized
     ``viewer-config.json`` to the staged tree, while the legitimate
     ``save_backend.mode`` + ``endpoint`` still reach the generated
     ``index.html`` (so the Save button keeps working).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from splatpipe.core.config_safety import (
    PUBLIC_SAVE_BACKEND_KEYS,
    PUBLIC_VIEWER_CONFIG_KEYS,
    sanitize_public_viewer_config,
)
from splatpipe.core.events import ProgressEvent, StepResult
from splatpipe.steps.publish import publish_scene


_SECRET = "BUNNY_KEY_SHOULD_NEVER_LEAK"
_OPTIONS_API_KEY = "ALSO_LEAK"
_INTERNAL_NOTE = "private DB connection string"
_LOCAL_PATH = "C:/Users/sasch/credentials.json"


# --------------------------------------------------------------------------
# Unit tests on sanitize_public_viewer_config
# --------------------------------------------------------------------------


def test_sanitize_removes_unknown_top_level_keys():
    """Keys outside the public allow-list are stripped."""
    cfg = {
        "primary_asset": "ok.rad",
        "internal_notes": _INTERNAL_NOTE,
        "local_only_path": _LOCAL_PATH,
        "_dev_flag": True,
        "secret_global": "TOPLEVEL_LEAK",
        "BUNNY_STORAGE_PASSWORD": "OOPS",
    }
    out = sanitize_public_viewer_config(cfg)
    assert "primary_asset" in out
    assert "internal_notes" not in out
    assert "local_only_path" not in out
    assert "_dev_flag" not in out
    assert "secret_global" not in out
    assert "BUNNY_STORAGE_PASSWORD" not in out


def test_sanitize_keeps_known_public_keys():
    """Every documented public key passes through untouched."""
    cfg = {
        "primary_asset": "scene.rad",
        "start_view": {"pos": [1, 2, 3], "target": [0, 0, 0]},
        "cameras": [{"id": "cam0", "name": "Default"}],
        "camera_paths": [{"id": "p0", "name": "Tour"}],
        "default_path_id": "p0",
        "clips": [{"id": "c0", "camera_id": "cam0"}],
        "annotations": [{"pos": [0, 1, 0], "title": "X"}],
        "audio": [{"file": "a.mp3"}],
        "spark_render": {"clip_xy": 1.4, "paged_ext_splats": True},
        "splat_budget": 3_000_000,
        "background": {"type": "color", "color": "#222"},
        "postprocessing": {"tonemapping": "neutral", "exposure": 1.5},
        "camera": {"pitch_min": -90, "pitch_max": 90,
                   "zoom_min": 1, "zoom_max": 100, "bounds_radius": 50,
                   "ground_height": 0},
        "intro": {"ms": 600},
        "titles3d": [],
        "probe_views": [],
    }
    out = sanitize_public_viewer_config(cfg)
    for k in cfg:
        assert k in out, f"public key {k!r} dropped by sanitizer"
        assert out[k] == cfg[k]


def test_sanitize_save_backend_removes_secret():
    """The centerpiece: a save_backend.secret never reaches the output."""
    cfg = {
        "primary_asset": "ok.rad",
        "save_backend": {
            "type": "cli",
            "endpoint": "https://endpoint.example",
            "secret": _SECRET,
        },
    }
    out = sanitize_public_viewer_config(cfg)
    assert "save_backend" in out
    assert "secret" not in out["save_backend"]
    # And, belt-and-braces: the secret string itself is nowhere in the dump.
    assert _SECRET not in json.dumps(out)


def test_sanitize_save_backend_keeps_mode_and_endpoint():
    """save_backend.{type,endpoint} are public — viewer needs them for Save."""
    cfg = {
        "save_backend": {
            "type": "http",
            "endpoint": "https://srv/api/save",
            "secret": _SECRET,
        },
    }
    out = sanitize_public_viewer_config(cfg)
    assert out["save_backend"]["type"] == "http"
    assert out["save_backend"]["endpoint"] == "https://srv/api/save"


def test_sanitize_save_backend_drops_private_subkeys():
    """Any unknown save_backend sub-key is dropped (allow-list)."""
    cfg = {
        "save_backend": {
            "type": "cli",
            "endpoint": "https://e.x",
            "secret": _SECRET,
            "api_key": _OPTIONS_API_KEY,
            "token": "TOKEN_LEAK",
            "password": "PW_LEAK",
            "auth": "AUTH_LEAK",
            "BUNNY_STORAGE_PASSWORD": "STORAGE_LEAK",
        },
    }
    out = sanitize_public_viewer_config(cfg)
    sb = out["save_backend"]
    for bad in ("secret", "api_key", "token", "password", "auth",
                "BUNNY_STORAGE_PASSWORD"):
        assert bad not in sb, f"private sub-key {bad!r} leaked"
    # And: no secret value appears anywhere in the dump.
    dump = json.dumps(out)
    for leak in (_SECRET, _OPTIONS_API_KEY, "TOKEN_LEAK", "PW_LEAK",
                 "AUTH_LEAK", "STORAGE_LEAK"):
        assert leak not in dump


def test_sanitize_is_deep_copy_no_mutation():
    """Returned object is a deep copy — mutating either side does not bleed."""
    cfg = {
        "primary_asset": "ok.rad",
        "start_view": {"pos": [1, 2, 3]},
        "save_backend": {"type": "cli", "endpoint": "https://e.x",
                         "secret": _SECRET},
    }
    out = sanitize_public_viewer_config(cfg)
    # Mutate output — input is unchanged.
    out["start_view"]["pos"][0] = 999
    assert cfg["start_view"]["pos"][0] == 1
    # And the other way: mutate input — output unchanged.
    cfg["start_view"]["pos"][1] = 888
    assert out["start_view"]["pos"][1] == 2
    # save_backend object identity is also not shared.
    out["save_backend"]["type"] = "http"
    assert cfg["save_backend"]["type"] == "cli"


def test_sanitize_handles_missing_keys_gracefully():
    """Empty / minimal configs do not raise; allow-list stays consistent."""
    assert sanitize_public_viewer_config({}) == {}
    # Unknown-only input -> empty result, no crash.
    assert sanitize_public_viewer_config({"x": 1, "y": "z"}) == {}
    # save_backend absent -> result has no save_backend key (not synthesised).
    out = sanitize_public_viewer_config({"primary_asset": "a.rad"})
    assert "save_backend" not in out


def test_sanitize_save_backend_non_dict_is_dropped():
    """A non-dict save_backend (corrupt / hostile) is silently dropped."""
    for bad in (None, "leaked-string", 42, [1, 2, 3]):
        cfg = {"primary_asset": "ok.rad", "save_backend": bad}
        out = sanitize_public_viewer_config(cfg)
        assert "save_backend" not in out


def test_sanitize_allowlist_constants_are_frozen():
    """The allow-lists are read-only constants (catches accidental mutation)."""
    assert isinstance(PUBLIC_VIEWER_CONFIG_KEYS, frozenset)
    assert isinstance(PUBLIC_SAVE_BACKEND_KEYS, frozenset)
    # primary_asset MUST be in the public list (publish_scene relies on it).
    assert "primary_asset" in PUBLIC_VIEWER_CONFIG_KEYS
    # save_backend MUST be in the public list (with its own sub-key gate).
    assert "save_backend" in PUBLIC_VIEWER_CONFIG_KEYS
    # And NO secret-ish key is in either allow-list.
    for bad in ("secret", "api_key", "token", "password", "auth"):
        assert bad not in PUBLIC_VIEWER_CONFIG_KEYS
        assert bad not in PUBLIC_SAVE_BACKEND_KEYS


# --------------------------------------------------------------------------
# Integration: publish_scene staged viewer-config.json + index.html
# --------------------------------------------------------------------------


_ENV = {
    "BUNNY_CDN_URL": "https://splatpipe-cdn.b-cdn.net",
    "BUNNY_STORAGE_ZONE": "splatpipe",
    "BUNNY_STORAGE_PASSWORD": "pw",
    "BUNNY_ACCOUNT_API_KEY": "ak",
}


def _drain(gen):
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


@pytest.fixture
def _rad_dir(tmp_path: Path) -> Path:
    d = tmp_path / "prebuilt"
    d.mkdir()
    (d / "scene-lod.rad").write_bytes(b"RADMANIFEST")
    (d / "scene-lod-0.radc").write_bytes(b"CHUNK0")
    return d


def _capture_deploy(captured: dict):
    def _gen(slug, stage, env, *, workers=8, purge=False):
        captured["index_html"] = (Path(stage) / "index.html").read_text(
            encoding="utf-8")
        captured["viewer_config"] = json.loads(
            (Path(stage) / "viewer-config.json").read_text(encoding="utf-8"))
        yield ProgressEvent(step="export", progress=1.0, message="Uploaded")
        return StepResult(step="export", success=True,
                          summary={"uploaded": 2, "failed": 0,
                                   "failed_files": []})
    return _gen


def _hostile_base_config() -> dict:
    """The exact regression payload from the audit's suggested-fix."""
    return {
        "primary_asset": "STALE_DO_NOT_LET_THIS_WIN.rad",  # publish overwrites
        "start_view": {"pos": [1, 2, 3], "target": [0, 0, 0]},
        "save_backend": {
            "type": "cli",
            "endpoint": "https://endpoint.example",
            "secret": _SECRET,
            "api_key": _OPTIONS_API_KEY,
        },
        "internal_notes": _INTERNAL_NOTE,
        "local_only_path": _LOCAL_PATH,
        "_dev_flag": True,
    }


def test_publish_scene_staged_viewer_config_omits_secret(_rad_dir):
    """Hostile base_config -> staged viewer-config.json carries only public
    keys; secret + internal notes + local path + dev flag are gone."""
    captured: dict = {}
    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.deploy_to_bunny",
               _capture_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders", return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache",
               side_effect=lambda api, urls: (len(urls), 0)):
        result = _drain(publish_scene(
            scene_name="S", slug="s", env=_ENV, rad_dir=_rad_dir,
            base_config=_hostile_base_config()))
    assert result.success, result.error
    vc = captured["viewer_config"]
    # Public keys present.
    assert vc["start_view"] == {"pos": [1, 2, 3], "target": [0, 0, 0]}
    assert vc["save_backend"]["type"] == "cli"
    assert vc["save_backend"]["endpoint"] == "https://endpoint.example"
    # primary_asset is set by publish (NEVER inherited from a patch).
    assert vc["primary_asset"].endswith("/scene.rad")
    assert vc["primary_asset"] != "STALE_DO_NOT_LET_THIS_WIN.rad"
    # Private keys gone (centerpiece).
    assert "secret" not in vc.get("save_backend", {})
    assert "api_key" not in vc.get("save_backend", {})
    assert "internal_notes" not in vc
    assert "local_only_path" not in vc
    assert "_dev_flag" not in vc
    # Belt-and-braces: none of the secret strings survive the serialisation.
    dump = json.dumps(vc)
    assert _SECRET not in dump
    assert _OPTIONS_API_KEY not in dump
    assert _INTERNAL_NOTE not in dump
    assert _LOCAL_PATH not in dump


def test_publish_scene_staged_index_html_still_has_save_mode_wiring(_rad_dir):
    """The legitimate save_mode/endpoint flow keeps working: the sanitized
    save_backend still threads {type,endpoint} into index.html so the Save
    button is wired."""
    captured: dict = {}
    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.deploy_to_bunny",
               _capture_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders", return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache",
               side_effect=lambda api, urls: (len(urls), 0)):
        result = _drain(publish_scene(
            scene_name="S", slug="s", env=_ENV, rad_dir=_rad_dir,
            base_config={
                "save_backend": {
                    "type": "http",
                    "endpoint": "https://srv/api/save",
                    "secret": _SECRET,
                },
            },
        ))
    assert result.success, result.error
    html = captured["index_html"]
    assert 'const SAVE_MODE = "http";' in html
    assert 'const SAVE_ENDPOINT = "https://srv/api/save";' in html
    # And, critically: even in index.html the secret never appears.
    assert _SECRET not in html


def test_publish_scene_unknown_keys_stripped_no_crash(_rad_dir):
    """A config with ONLY unknown keys (degenerate but real) doesn't crash."""
    captured: dict = {}
    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.deploy_to_bunny",
               _capture_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders", return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache",
               side_effect=lambda api, urls: (len(urls), 0)):
        result = _drain(publish_scene(
            scene_name="S", slug="s", env=_ENV, rad_dir=_rad_dir,
            base_config={"_weird": True, "x": [1, 2]},
        ))
    assert result.success, result.error
    vc = captured["viewer_config"]
    # primary_asset still set by publish.
    assert vc["primary_asset"].endswith("/scene.rad")
    # Nothing weird leaked.
    assert "_weird" not in vc
    assert "x" not in vc
