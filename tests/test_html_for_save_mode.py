"""Task 8 — save_mode / save_endpoint plumbing into the generated Spark viewer.

Pure publish-time plumbing: ``html_for`` bakes two JS consts
(``SAVE_MODE`` / ``SAVE_ENDPOINT``) so a future Save UI can branch on them.
NOTHING reads them yet — they are inert by design (exactly like the Task-0
scaffold). The hard invariants these lock:

  * Defaults (``"cli"`` / ``None``) keep every existing scene byte-identical
    apart from the two new (inert) const lines — i.e. no behaviour change for
    the six live production scenes.
  * The per-scene SECRET is NEVER a kwarg, NEVER baked into the template,
    NEVER written to viewer-config.json (http-mode secret lives only in the
    author URL fragment — a later task, not here).
  * Both real call sites (``steps.publish.publish_scene`` and
    ``viewers.spark.assembler.SparkAssembler``) derive save_mode/endpoint
    from the ``[save_backend]`` config table, defaulting safely to
    ``"cli"`` / empty when the table is absent (old configs / scene_config).
"""

import inspect
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from splatpipe.core.events import ProgressEvent, StepResult
from splatpipe.steps.publish import publish_scene
from splatpipe.viewers.spark.template import html_for

# Pre-Task-8 ``html_for("HarnessScene")`` fingerprint (captured from the
# committed template at HEAD 5c0ae8a, BEFORE this task's edit): 161940 bytes,
# this SHA-256. Task 8 only inserts the inert SAVE_* const block right after
# ``const PAGED = ...;``; excising exactly that block must reproduce this
# fingerprint byte-for-byte → proof the six live scenes are untouched.
_PRE_TASK8_LEN = 161940
_PRE_TASK8_SHA = (
    "7476a4d787eb9060e0196644d65031f245ceeaeb87807ff5583d246d5712cba9"
)
_INSERT_ANCHOR = "const PAGED = true;\n"

_SECRET_SENTINEL = "s3cr3t-never-bake-me"


def _drain(gen):
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value


# --------------------------------------------------------------------------
# (a) defaults: consts present, value cli / empty, and otherwise unchanged
# --------------------------------------------------------------------------

def test_defaults_bake_cli_and_empty_endpoint():
    html = html_for("HarnessScene")
    assert "const SAVE_MODE = \"cli\";" in html
    assert "const SAVE_ENDPOINT = \"\";" in html


# Regenerating after a LEGITIMATE template change (e.g. Tasks 10-18 each
# add to _VIEWER_TEMPLATE): this lock asserts the 6 live scenes stay
# byte-identical except the current task's deliberate, inert addition.
# To update the baseline:
#   import hashlib, splatpipe.viewers.spark.template as t
#   h = t.html_for("HarnessScene")
#   print(len(h), hashlib.sha256(h.encode()).hexdigest())
# Set _PRE_TASK8_LEN/_PRE_TASK8_SHA to those, and re-derive the excision
# anchor to span ONLY your task's new lines. Do NOT relax the assertion.
def test_defaults_are_regression_safe_existing_scenes_byte_identical():
    """With defaults the ONLY delta vs the pre-Task-8 template is the inert
    SAVE_* const block inserted right after ``const PAGED = ...;``. Excising
    exactly that block must reproduce the pre-Task-8 output byte-for-byte
    (same length, same SHA-256) — hard proof the six live scenes (and every
    existing scene) are untouched."""
    import hashlib

    html = html_for("HarnessScene")

    # Locate the inserted block: from just after the anchor up to and
    # including the SAVE_ENDPOINT line's trailing newline.
    i = html.index(_INSERT_ANCHOR) + len(_INSERT_ANCHOR)
    j = html.index("const SAVE_ENDPOINT")
    j = html.index(";", j) + 1
    j = html.index("\n", j) + 1
    block = html[i:j]

    # The block is exactly: the explanatory comment + the two consts.
    assert "SAVE_MODE" in block and "SAVE_ENDPOINT" in block
    assert 'const SAVE_MODE = "cli";' in block
    assert 'const SAVE_ENDPOINT = "";' in block

    stripped = html[:i] + html[j:]
    # No SAVE_* token survives excision → the block is the *sole* addition.
    assert "SAVE_MODE" not in stripped
    assert "SAVE_ENDPOINT" not in stripped
    # Byte-for-byte identical to the pre-Task-8 generated viewer.
    assert len(stripped) == _PRE_TASK8_LEN
    assert hashlib.sha256(stripped.encode()).hexdigest() == _PRE_TASK8_SHA


# --------------------------------------------------------------------------
# (b) explicit kwargs are baked through verbatim
# --------------------------------------------------------------------------

def test_explicit_http_mode_and_endpoint_are_baked():
    html = html_for(
        "S", save_mode="http", save_endpoint="https://x.example/api/save"
    )
    assert "const SAVE_MODE = \"http\";" in html
    assert "const SAVE_ENDPOINT = \"https://x.example/api/save\";" in html


def test_none_endpoint_serialises_to_empty_string():
    html = html_for("S", save_mode="http", save_endpoint=None)
    assert "const SAVE_MODE = \"http\";" in html
    assert "const SAVE_ENDPOINT = \"\";" in html


def test_endpoint_with_quotes_is_json_escaped_not_injected():
    """save_endpoint goes through json.dumps → safe to embed in the JS."""
    html = html_for("S", save_endpoint='https://x/"+evil()+"')
    # json.dumps escapes the inner quotes; no raw break-out.
    assert "const SAVE_ENDPOINT = " in html
    assert json.dumps('https://x/"+evil()+"') in html
    assert 'const SAVE_ENDPOINT = "https://x/";' not in html


# --------------------------------------------------------------------------
# (c) the SECRET is never a kwarg, never baked, never in output
# --------------------------------------------------------------------------

def test_html_for_has_no_secret_kwarg():
    params = inspect.signature(html_for).parameters
    for bad in ("secret", "save_secret", "auth", "token", "password"):
        assert bad not in params, f"html_for must not expose a {bad!r} kwarg"
    # The two (and only two) new save-* kwargs exist with safe defaults.
    assert params["save_mode"].default == "cli"
    assert params["save_endpoint"].default is None


def test_secret_value_never_appears_in_generated_html():
    """Even if a caller (wrongly) routed a secret through endpoint, there is
    no separate secret channel; and the default output carries nothing
    secret. Belt-and-braces: the sentinel must not leak via defaults."""
    html = html_for("HarnessScene")
    assert _SECRET_SENTINEL not in html
    assert "SAVE_SECRET" not in html
    assert "save_secret" not in html


# --------------------------------------------------------------------------
# (d) both call sites derive save_mode/endpoint from [save_backend] config
# --------------------------------------------------------------------------

@pytest.fixture
def _rad_dir(tmp_path: Path) -> Path:
    d = tmp_path / "prebuilt"
    d.mkdir()
    (d / "scene-lod.rad").write_bytes(b"RADMANIFEST")
    (d / "scene-lod-0.radc").write_bytes(b"CHUNK0")
    return d


_ENV = {
    "BUNNY_CDN_URL": "https://splatpipe-cdn.b-cdn.net",
    "BUNNY_STORAGE_ZONE": "splatpipe",
    "BUNNY_STORAGE_PASSWORD": "pw",
    "BUNNY_ACCOUNT_API_KEY": "ak",
}


def _capture_deploy(captured):
    def _gen(slug, stage, env, *, workers=8, purge=False):
        captured["index_html"] = (Path(stage) / "index.html").read_text(
            encoding="utf-8"
        )
        captured["viewer_config"] = json.loads(
            (Path(stage) / "viewer-config.json").read_text(encoding="utf-8")
        )
        yield ProgressEvent(step="export", progress=1.0, message="Uploaded")
        return StepResult(
            step="export", success=True,
            summary={"uploaded": 2, "failed": 0, "failed_files": []},
        )
    return _gen


def _publish_with_base_config(rad_dir, base_config):
    captured: dict = {}
    with patch("splatpipe.steps.publish.ensure_edge_rules", return_value=True), \
         patch("splatpipe.steps.publish.deploy_to_bunny",
               _capture_deploy(captured)), \
         patch("splatpipe.steps.publish.list_bunny_subfolders",
               return_value=[]), \
         patch("splatpipe.steps.publish.purge_bunny_cache",
               side_effect=lambda api, urls: (len(urls), 0)):
        result = _drain(publish_scene(
            scene_name="S", slug="s", env=_ENV, rad_dir=rad_dir,
            base_config=base_config,
        ))
    assert result.success, result.error
    return captured


def test_publish_call_site_threads_save_backend_from_config(_rad_dir):
    """publish.py reads [save_backend] off the assembled viewer-config dict
    (its `cfg`). When present → baked into index.html."""
    captured = _publish_with_base_config(
        _rad_dir,
        {"save_backend": {"type": "http",
                          "endpoint": "https://api.example/save"}},
    )
    html = captured["index_html"]
    assert "const SAVE_MODE = \"http\";" in html
    assert "const SAVE_ENDPOINT = \"https://api.example/save\";" in html
    # The SECRET is never written to viewer-config.json.
    assert "secret" not in json.dumps(captured["viewer_config"]).lower()


def test_publish_call_site_defaults_to_cli_when_no_save_backend(_rad_dir):
    """A scene_config WITHOUT a [save_backend] table → cli / empty, no crash
    (the six live scenes' configs have no such table)."""
    captured = _publish_with_base_config(
        _rad_dir, {"annotations": [], "camera_paths": []}
    )
    html = captured["index_html"]
    assert "const SAVE_MODE = \"cli\";" in html
    assert "const SAVE_ENDPOINT = \"\";" in html


def test_assembler_call_site_threads_save_backend_from_step_config(
    tmp_path, monkeypatch
):
    """SparkAssembler reads [save_backend] off the merged step.config
    (load_project_config → defaults.toml carries the table)."""
    from splatpipe.steps.lod_assembly import LodAssemblyStep
    from splatpipe.viewers.spark import assembler as asm_mod
    from splatpipe.viewers.spark.assembler import SparkAssembler

    # Minimal project: spark renderer, one enabled LOD, a reviewed PLY.
    proj_dir = tmp_path / "proj"
    (proj_dir / "04_review").mkdir(parents=True)
    (proj_dir / "05_output").mkdir()
    (proj_dir / "04_review" / "lod0_reviewed.ply").write_bytes(b"PLY")

    class _Proj:
        name = "AsmScene"
        renderer = "spark"
        lod_levels = [{"name": "lod0", "enabled": True}]
        scene_config = {"annotations": []}
        state: dict = {}
        root = proj_dir

        def get_folder(self, n):
            return proj_dir / n

    cfg_with = {"save_backend": {"type": "http",
                                 "endpoint": "https://srv/api"}}
    step = LodAssemblyStep.__new__(LodAssemblyStep)
    step.project = _Proj()
    step.config = cfg_with

    out = proj_dir / "05_output"
    fake_rad = tmp_path / "cache" / "scene-lod.rad"
    fake_rad.parent.mkdir()
    fake_rad.write_bytes(b"RAD")

    monkeypatch.setattr(
        asm_mod, "verify_toolchain",
        lambda: {"command": ["build-lod"], "cwd": None, "version": "x",
                 "is_cargo": False, "platform": "test"},
    )
    monkeypatch.setattr(asm_mod, "build", lambda *a, **k: fake_rad)
    monkeypatch.setattr(asm_mod, "clear_output_dir", lambda d: None)

    _drain(SparkAssembler().assemble_streaming(step, out))
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "const SAVE_MODE = \"http\";" in html
    assert "const SAVE_ENDPOINT = \"https://srv/api\";" in html


def test_assembler_call_site_defaults_to_cli_when_no_save_backend(
    tmp_path, monkeypatch
):
    """step.config WITHOUT [save_backend] → cli / empty, no crash."""
    from splatpipe.steps.lod_assembly import LodAssemblyStep
    from splatpipe.viewers.spark import assembler as asm_mod
    from splatpipe.viewers.spark.assembler import SparkAssembler

    proj_dir = tmp_path / "proj"
    (proj_dir / "04_review").mkdir(parents=True)
    (proj_dir / "05_output").mkdir()
    (proj_dir / "04_review" / "lod0_reviewed.ply").write_bytes(b"PLY")

    class _Proj:
        name = "AsmScene2"
        renderer = "spark"
        lod_levels = [{"name": "lod0", "enabled": True}]
        scene_config = {"annotations": []}
        state: dict = {}
        root = proj_dir

        def get_folder(self, n):
            return proj_dir / n

    step = LodAssemblyStep.__new__(LodAssemblyStep)
    step.project = _Proj()
    step.config = {"tools": {}}  # no [save_backend] table

    out = proj_dir / "05_output"
    fake_rad = tmp_path / "cache" / "scene-lod.rad"
    fake_rad.parent.mkdir()
    fake_rad.write_bytes(b"RAD")

    monkeypatch.setattr(
        asm_mod, "verify_toolchain",
        lambda: {"command": ["build-lod"], "cwd": None, "version": "x",
                 "is_cargo": False, "platform": "test"},
    )
    monkeypatch.setattr(asm_mod, "build", lambda *a, **k: fake_rad)
    monkeypatch.setattr(asm_mod, "clear_output_dir", lambda d: None)

    _drain(SparkAssembler().assemble_streaming(step, out))
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "const SAVE_MODE = \"cli\";" in html
    assert "const SAVE_ENDPOINT = \"\";" in html
