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

# Pre-Task-10 ``html_for("HarnessScene")`` fingerprint, captured from the
# committed template at HEAD f62c12a (the commit BEFORE Task 10's edit;
# i.e. this baseline ALREADY contains Task 8's inert SAVE_* block but NOT
# Task 10's visibilitychange rebase): 161816 bytes, this SHA-256.
#
# Task 10 adds exactly TWO contiguous, well-anchored blocks to
# ``_VIEWER_TEMPLATE`` (the path-player tab-background pause):
#   • BLOCK A — the ``_hidAt`` declaration + its explanatory comment,
#     inserted right after the ``let _player = null, ...;`` line.
#   • BLOCK B — the ``visibilitychange`` rebase handler + its comment,
#     inserted right after the ``scrubEl`` ``input`` listener.
# Excising EXACTLY those two blocks from the current generated HTML must
# reproduce the pre-Task-10 fingerprint byte-for-byte → hard proof every
# existing scene (the six live production scenes included) is otherwise
# untouched. (Task 8's SAVE_* block is part of this baseline, so it is NOT
# excised here; its own presence/escaping is asserted by the other tests
# in this file — that contract is unchanged.)
_PRE_TASK10_LEN = 161816
_PRE_TASK10_SHA = (
    "20d31d2810c5e52127e5a4d2ba1fb9c03028415548f4c1140d12771ac8819b5a"
)
# Block A: from the start of its leading comment line up to and including
# the ``let _hidAt = 0;`` line's trailing newline. The comment's first
# line is unique in the generated output.
_BLOCK_A_START = "  // Tab-background pause: timestamp the path-player clock"
_BLOCK_A_END_TOK = "let _hidAt = 0;"
# Block B: from the start of its leading comment up to and including the
# handler's closing ``});`` + trailing newline. Both anchor strings are
# unique in the generated output.
_BLOCK_B_START = "  // Pause (don't teleport) the path player when the tab"
_BLOCK_B_END_TOK = "document.addEventListener('visibilitychange'"

# Task 8's SAVE_* anchor (still asserted present by the (a) tests below;
# kept here so the inert-const contract stays explicitly pinned).
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


def _excise(text: str, start_anchor: str, end_token: str,
            close_after: str | None = None) -> str:
    """Remove a contiguous block from ``text``.

    The span runs from ``start_anchor`` up to (and including the trailing
    newline of):
      * the line containing ``end_token``                  — if
        ``close_after`` is None (single-line / decl block); OR
      * the FIRST line at-or-after ``end_token`` that equals
        ``close_after`` — used for the multi-line ``visibilitychange``
        handler, whose self-contained closer is the first 2-space-indented
        ``});`` after the ``addEventListener(`` opening (its body is
        indented deeper, so this match is unambiguous).

    ``start_anchor`` MUST be unique in ``text`` (asserted) so a future
    template edit that duplicates/moves it fails LOUDLY rather than
    silently excising the wrong span (which would weaken the guard).

    ``end_token`` (and ``close_after`` if used) must also uniquely identify
    the block's end within the region AFTER ``start_anchor`` — it is
    searched forward from ``start_anchor`` so the first match wins; a
    non-unique ``end_token`` silently excises too little or too much (only
    ``start_anchor`` uniqueness is assertion-guarded). Pick an end token
    unique to your block."""
    assert text.count(start_anchor) == 1, (
        f"excision start anchor not unique: {start_anchor!r}"
    )
    i = text.index(start_anchor)
    k = text.index(end_token, i)
    if close_after is None:
        j = text.index("\n", k) + 1  # through end of the end_token's line
    else:
        # Walk forward line-by-line to the first line == close_after.
        j = text.index("\n", k) + 1
        while True:
            nl = text.index("\n", j)
            line = text[j:nl]
            j = nl + 1
            if line == close_after:
                break
    return text[:i] + text[j:]


# Regenerating after a LEGITIMATE _VIEWER_TEMPLATE change (each behavioural
# task — Tasks 10-18 — adds its own well-anchored block): this lock asserts
# every existing scene (the 6 live production scenes included) stays
# byte-identical APART FROM that task's deliberate, anchored additions. It
# is a real "no unintended OTHER drift" guard and must NOT be relaxed or
# made tautological.
#
# To update the baseline + excision for the NEXT task:
#   1. Capture the CURRENT-HEAD (pre-your-task) fingerprint from the
#      *committed* template (NOT your dirty working tree):
#        git show <HEAD>:src/splatpipe/viewers/spark/template.py > /tmp/t.py
#        python - <<'PY'
#        import hashlib, importlib.util, os
#        s=importlib.util.spec_from_file_location('t', os.environ['TMP']+'/t.py')
#        m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
#        h=m.html_for('HarnessScene')
#        print(len(h), hashlib.sha256(h.encode()).hexdigest())
#        PY
#      Set _PRE_TASKnn_LEN / _PRE_TASKnn_SHA to those (a moving baseline:
#      each task's pins are the PREVIOUS task's committed output, so the
#      excision only ever spans the NEW task's lines).
#   2. Add unique start/end anchors for YOUR task's block(s) and excise
#      them too (via _excise) before the byte-for-byte compare.
#   Do NOT relax the assertion; the regression INTENT must remain enforced.
def test_defaults_are_regression_safe_existing_scenes_byte_identical():
    """With defaults the ONLY delta vs the pre-Task-10 committed template
    (``f62c12a`` — which already carries Task 8's SAVE_* block) is Task 10's
    two anchored blocks: the ``_hidAt`` declaration (BLOCK A) and the
    ``visibilitychange`` rebase handler (BLOCK B). Excising EXACTLY those
    two blocks must reproduce the pre-Task-10 output byte-for-byte (same
    length, same SHA-256) — hard proof the six live scenes (and every
    existing scene) are otherwise untouched. Task 8's SAVE_* block is part
    of this baseline and is therefore (correctly) NOT excised here."""
    import hashlib

    html = html_for("HarnessScene")

    # Sanity: Task 8's SAVE_* block must STILL be present and intact in the
    # baseline territory (this test no longer excises it; it must survive).
    assert 'const SAVE_MODE = "cli";' in html
    assert 'const SAVE_ENDPOINT = "";' in html
    assert _INSERT_ANCHOR in html

    # Excise Task 10's two deliberate blocks (disjoint spans; A precedes B
    # but order is irrelevant). Block A is a single-line decl block; Block
    # B is the multi-line visibilitychange handler — its self-contained
    # closer is the first 2-space-indented "});" after the addEventListener
    # opening (the body is indented deeper). Anchors asserted unique inside
    # _excise.
    stripped = _excise(html, _BLOCK_A_START, _BLOCK_A_END_TOK)
    stripped = _excise(
        stripped, _BLOCK_B_START, _BLOCK_B_END_TOK, close_after="  });"
    )

    # After excision NOTHING from Task 10 survives → the two blocks are the
    # SOLE additions (any leftover token means the excision under-cut and
    # the byte compare below would be meaningless).
    assert "_hidAt" not in stripped
    assert "visibilitychange" not in stripped
    assert "Tab-background pause" not in stripped
    assert "Pause (don't teleport)" not in stripped
    # …while Task 8's SAVE_* block is UNTOUCHED by the excision (proves we
    # removed only Task 10's lines, not Task 8's baseline content).
    assert 'const SAVE_MODE = "cli";' in stripped
    assert 'const SAVE_ENDPOINT = "";' in stripped

    # Byte-for-byte identical to the pre-Task-10 *committed* generated
    # viewer → no unintended drift anywhere else in the template.
    assert len(stripped) == _PRE_TASK10_LEN, (
        f"length drift: {len(stripped)} != {_PRE_TASK10_LEN} "
        "(an UNINTENDED change leaked outside Task 10's two blocks)"
    )
    assert hashlib.sha256(stripped.encode()).hexdigest() == _PRE_TASK10_SHA


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
