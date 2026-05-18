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

# ── Moving baseline (Task 11) ───────────────────────────────────────────
# The byte-identity guard pins the PREVIOUS task's COMMITTED generated
# output and asserts the only delta is THIS task's deliberate change. The
# baseline therefore moves forward one commit each task (see the regen
# recipe below). For Task 11 the pinned baseline is the committed template
# at HEAD ``0c377a5`` (the commit BEFORE Task 11's edit) — which ALREADY
# contains Task 8's inert SAVE_* block AND Task 10's two visibilitychange
# blocks. ``html_for("HarnessScene")`` there is 163800 bytes.
#
# Unlike Tasks 8/10 (purely-additive contiguous blocks → excising them
# reproduced the pre-add baseline), Task 11 *modifies in place* the spline
# (``CubicSpline.calcKnots`` per-keyframe interpolation + the small
# ``buildPlayer`` / ctor / evaluate plumbing it needs). A modify-task can't
# be reduced to the old bytes by deleting added lines, so the guard works
# the other way round: excise the WHOLE deliberately-touched spline region
# (the ``CubicSpline`` class + ``buildPlayer``) from BOTH sides and assert
# the REMAINDER is byte-for-byte the pinned baseline's remainder. That
# proves every byte OUTSIDE the spline region is byte-identical to the
# ``0c377a5`` committed output → the six live production scenes are
# untouched everywhere except the deliberate spline change. Task 8's
# SAVE_* and Task 10's blocks live OUTSIDE that region, so they are in the
# compared remainder and thus asserted-surviving (explicit `in stripped`
# checks below pin that contract too — unchanged).
#
# ``_PRE_TASK11_REMAINDER_*`` = LEN/SHA-256 of the ``0c377a5`` baseline
# AFTER excising the same spline region with the same anchors (computed
# from ``git show 0c377a5:…/template.py`` — NOT the dirty tree).
_PRE_TASK11_REMAINDER_LEN = 158963
_PRE_TASK11_REMAINDER_SHA = (
    "5cbf43bed9f911449b62705dacc246e35578bd535d5ff1e4ecc6a30bd7839190"
)
# Full ``0c377a5`` baseline fingerprint (documentation / cross-check; the
# remainder pin above is what the assertion uses).
_PRE_TASK11_FULL_LEN = 163800
_PRE_TASK11_FULL_SHA = (
    "649b8c822bd03a43de856244cbce947f81d6d1e4ffd34095f140fd0d5153eefb"
)
# The Task-11-modified spline region = the line that immediately precedes
# it (identical & unique in both baseline and current) through the close
# of ``buildPlayer``. START anchor is the last camera-path comment line
# (asserted unique by _excise); END token is ``buildPlayer``'s unique
# return line; the block closes at the FIRST 2-space ``  }`` after it
# (``buildPlayer``'s own closer — its body is indented deeper so this is
# unambiguous). Excising [start, …, that ``  }``] removes exactly the
# ``CubicSpline`` class + ``buildPlayer`` and nothing else.
#
# Infra-hardening (folded into this commit): an in-source ``// LOCKSTEP:``
# banner was added at the spline-section opening. It is DELIBERATELY placed
# IMMEDIATELY AFTER this START anchor line (i.e. INSIDE the excised region,
# right before ``Per-keyframe interp modes`` / ``const KF_LINEAR``) so the
# compared *remainder* is byte-for-byte unaffected — ``_PRE_TASK11_*`` were
# verified UNCHANGED (remainder still 158963 / 5cbf43be…). The anchor was
# therefore NOT moved (moving it onto the new banner line would have pulled
# the 4 unchanged ``// Same CubicSpline…`` comment lines out of the
# remainder AND broken the moving-baseline, since the banner line does not
# exist in the pre-Task-11 ``0c377a5`` reference). A future Tasks-12..18
# editor MUST keep any spline-section banner BELOW this anchor line for the
# same reason; ``_excise`` still asserts this anchor stays unique.
_SPLINE_REGION_START = (
    "  // camera_paths JSON plays back byte-for-byte in either."
)
_SPLINE_REGION_END_TOK = (
    "return { spline, times, sortedKfs, sourceKf, "
    "duration, loop: !!p.loop, playSpeed };"
)
_SPLINE_REGION_CLOSE_AFTER = "  }"

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
    # Fail-loud if the end token (or, when used, the close_after closer)
    # is missing AFTER the start anchor: a non-unique/absent end_token
    # silently mis-excises the wrong span (only start_anchor uniqueness
    # was guarded before). Guards against a future task growing the
    # template until the end anchor disappears -> silent false PASS.
    _after = text[text.index(start_anchor):]
    assert _after.count(end_token) >= 1, (
        f"excision end_token not found after start anchor: {end_token!r}"
    )
    if close_after is not None:
        _after_end = _after[_after.index(end_token):]
        assert _after_end.count(close_after) >= 1, (
            "excision close_after not found after end_token: "
            f"{close_after!r}"
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
# task adds/modifies its own well-anchored region): this lock asserts every
# existing scene (the 6 live production scenes included) stays byte-identical
# APART FROM that task's deliberate, anchored change. It is a real "no
# unintended OTHER drift" guard and must NOT be relaxed or made tautological.
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
#   2a. PURELY-ADDITIVE task (like Tasks 8/10): set the baseline LEN/SHA to
#       the step-1 fingerprint, add unique anchors for YOUR new block(s),
#       and EXCISE them from the current HTML; the excised result must equal
#       that pinned baseline byte-for-byte.
#   2b. MODIFY-IN-PLACE task (like Task 11 — it rewrites the spline rather
#       than only adding lines, so deleting added lines can't reproduce the
#       old bytes): pick stable anchors that bound the WHOLE deliberately-
#       touched region, excise that SAME region from BOTH the step-1
#       baseline AND the current HTML, and pin the *baseline's* excised
#       LEN/SHA (``_PRE_TASKnn_REMAINDER_*``). The assertion excises the
#       region from the current HTML and compares to that remainder pin →
#       proves every byte OUTSIDE the touched region is byte-identical.
#   2c. REGION-INTERIOR-ONLY change (e.g. the Task-11 ``// LOCKSTEP:``
#       banner folded into this commit): if the only delta lands strictly
#       INSIDE an already-excised region (here: AFTER ``_SPLINE_REGION_START``
#       and before its END), the compared remainder is unaffected → keep
#       the existing ``_PRE_TASKnn_*`` pins UNCHANGED (verified, not
#       assumed). Do NOT move the START anchor onto a newly-added line: a
#       line that does not exist in the pre-task reference cannot anchor
#       the moving baseline's excision (it would also pull the unchanged
#       pre-anchor comment lines out of the remainder). Keep banners BELOW
#       the START anchor.
#   Each task's pins are the PREVIOUS task's committed output (a moving
#   baseline). Do NOT relax the assertion; the regression INTENT must
#   remain enforced, and prior tasks' anchored blocks must stay
#   asserted-surviving.
def test_defaults_are_regression_safe_existing_scenes_byte_identical():
    """Task 11 modifies the camera-path spline IN PLACE (per-keyframe
    interpolation in ``CubicSpline.calcKnots`` + the tiny ``buildPlayer`` /
    ctor / ``evaluate`` plumbing). Excising the WHOLE deliberately-touched
    spline region (the ``CubicSpline`` class + ``buildPlayer``) from the
    current generated HTML must reproduce the ``0c377a5`` committed
    template's SAME-region excision byte-for-byte (same length, same
    SHA-256) — hard proof every byte OUTSIDE that region (the six live
    scenes' behaviour, Task 8's SAVE_* block, Task 10's two blocks) is
    untouched. Task 8's SAVE_* + Task 10's blocks live OUTSIDE the spline
    region, so they survive the excision and are explicitly asserted-present
    here (their contracts stay pinned)."""
    import hashlib

    html = html_for("HarnessScene")

    # Sanity: prior tasks' anchored content must STILL be present and intact
    # (this test excises only the spline region; they must survive it).
    assert 'const SAVE_MODE = "cli";' in html          # Task 8
    assert 'const SAVE_ENDPOINT = "";' in html          # Task 8
    assert _INSERT_ANCHOR in html                        # Task 8
    assert "_hidAt" in html                              # Task 10 BLOCK A
    assert "visibilitychange" in html                    # Task 10 BLOCK B

    # Excise the Task-11-modified region: the ``CubicSpline`` class +
    # ``buildPlayer``. START anchor (last camera-path comment line) is
    # asserted unique inside _excise; END token is ``buildPlayer``'s unique
    # return line; the block closes at the FIRST 2-space ``  }`` after it
    # (``buildPlayer``'s own closer — its body is indented deeper, so this
    # is unambiguous).
    stripped = _excise(
        html, _SPLINE_REGION_START, _SPLINE_REGION_END_TOK,
        close_after=_SPLINE_REGION_CLOSE_AFTER,
    )

    # The ENTIRE spline region must be gone → the excision spanned exactly
    # the deliberately-touched code (any leftover means it under-cut and the
    # byte compare below would be meaningless / weakened).
    assert "class CubicSpline" not in stripped
    assert "function buildPlayer" not in stripped
    assert "calcKnots" not in stripped
    assert "_kfMeta" not in stripped
    assert "KF_AUTO_CLAMPED" not in stripped
    # …while prior tasks' anchored content (OUTSIDE the spline region) is
    # UNTOUCHED by the excision (proves we removed only the spline region,
    # not Task 8's / Task 10's baseline content — they must survive).
    assert 'const SAVE_MODE = "cli";' in stripped        # Task 8 survives
    assert 'const SAVE_ENDPOINT = "";' in stripped        # Task 8 survives
    assert "_hidAt" in stripped                           # Task 10 survives
    assert "visibilitychange" in stripped                 # Task 10 survives

    # Byte-for-byte identical to the ``0c377a5`` committed template with the
    # SAME spline region excised → NO unintended drift anywhere outside the
    # deliberate Task-11 spline change (would FAIL loudly if e.g. a stray
    # uncommitted block elsewhere in the template leaked in).
    assert len(stripped) == _PRE_TASK11_REMAINDER_LEN, (
        f"length drift: {len(stripped)} != {_PRE_TASK11_REMAINDER_LEN} "
        "(an UNINTENDED change leaked OUTSIDE Task 11's spline region)"
    )
    assert (
        hashlib.sha256(stripped.encode()).hexdigest()
        == _PRE_TASK11_REMAINDER_SHA
    )


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
