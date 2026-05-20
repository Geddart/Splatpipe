"""AnnotationModule contract tests (Phase 5 -- editor-arc-design #122 §4.2).

Per user-locked Q6 (2026-05-20 17:38 voice) and the editor architecture
spec §4.2 + §11.6, the AnnotationModule is the canonical owner of the
``cfg.annotations`` slot. Renders dot markers (visible everywhere)
that unfold into title+text+media panels on distance OR click; emits
annotation [t_in..t_out] bars into the multi-lane bottom-timeline;
populates the Scene Settings drawer's Annotations section.

Two test layers:

(a) STATIC: the generated viewer HTML carries the documented surface
    markers (fragment present, module registration, helpers, schema
    mirror, click handler, distance + timeline-opacity logic, "+ Add
    annotation" wiring, test surface). Pure Python -- no browser, no
    Node.

(b) DYNAMIC (Node): extract the AnnotationModule IIFE verbatim from
    the rendered HTML and exercise its pure helpers (_upgradeAnnotation
    + _timelineOpacity + ANNOTATION_DEFAULTS mirror) under Node so the
    Python/JS schema parity is byte-runtime-checked. Mirrors the
    pattern in test_editor_module_registry.py + test_edit_history.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from splatpipe.core.path_io import ANNOTATION_DEFAULTS
from splatpipe.viewers.spark.template import html_for

_NODE = shutil.which("node")


# --------------------------------------------------------------------------
# (a) STATIC: the rendered HTML carries the documented surface markers
# --------------------------------------------------------------------------


_ANNOTATION_MODULE_MARKERS = (
    # 15c fragment loaded into the bundle
    "//  AnnotationModule (Phase 5 -- editor-arc-design #122",
    "(function _annInit() {",
    "EditorModuleRegistry.register(annotationModule);",
    # Module identity
    "name: 'annotations',",
    "stateKey: 'annotations',",
    "defaultModes: ['author', 'user', 'embed']",
    # JS mirror of the Python AnnotationDict expansion (the 7
    # ANNOTATION_DEFAULTS keys + the upgrade helper)
    "const ANNOTATION_DEFAULTS = {",
    "kind: 'dot_unfold',",
    "unfold_radius_m: 5.0,",
    "t_in: 0.0,",
    "t_out: 999.0,",
    "fade_ms: 300,",
    "media_url: null,",
    "billboard: true,",
    "function _upgradeAnnotation(ann) {",
    "function _newAnnotationId() {",
    # Per-frame tick infrastructure
    "function _annTick(",
    "function _timelineOpacity(",
    "function _smoothstep(",
    # Distance + click semantics
    "ann.unfold_radius_m",
    "dot_unfold",
    "title3d_overlay",
    # Legacy teardown -- module owns rendering
    "function _teardownLegacy() {",
    "typeof markerObjs !== 'undefined'",
    # Click handler on the dot DOM
    "dotEl.addEventListener('click'",
    # Path-active glow class preserved (legacy 18_frame_loop +
    # 10_camera_select behaviour folded into the module's tick)
    "'path-active'",
    "_lastTriggeredAnnotation",
    # OverlayScene tick registration
    "id: 'annotations-tick',",
    # Timeline lane contributes [t_in..t_out] bars
    "timelineLane: {",
    "label: 'ann',",
    # Scene Settings drawer section + Add button
    "renderSceneSettings: function (parentEl)",
    "'+ Add annotation'",
    "data-section=\"annotations\"",  # placeholder replacement targets this
    # Test surface
    "testSurface: {",
    "get annotations()",
    "_ANNOTATION_DEFAULTS: ANNOTATION_DEFAULTS,",
    # 08_input guard so legacy DOM construction no-ops when the
    # module is registered (the guard is value-false at 08's runtime
    # since 15c registers later, but the AnnotationModule's mount
    # tears down the legacy DOM either way -- the guard documents
    # the invariant + is defensive against a future load-order change)
    "_annotationsOwnedByModule",
    # Phase-5 ann-* EditHistory commit labels (per spec §6.3 + R8 §4.2
    # -- ONE per gesture, NOT per keystroke)
    "'ann-add'",
    "'ann-delete'",
    "'ann-set-kind'",
    "'ann-radius'",
    "'ann-t-in'",
    "'ann-t-out'",
    "'ann-fade-ms'",
)


def test_annotation_module_markers_present_in_rendered_html():
    """The 15c AnnotationModule fragment + the 08_input guard are
    both wired into the generated viewer HTML."""
    html = html_for("HarnessScene")
    for mk in _ANNOTATION_MODULE_MARKERS:
        assert mk in html, f"AnnotationModule marker missing: {mk!r}"


def test_annotation_module_fragment_file_exists():
    """The 15c fragment is on disk + at the expected location (the
    orchestrator loads it in lexical order between 15a and 16)."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    f = parts / "15c_annotation_module.js_tmpl"
    assert f.exists(), f"missing fragment: {f}"
    raw = f.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM corruption"
    assert b"\r" not in raw, "CRLF corruption"
    txt = raw.decode("utf-8")
    assert "AnnotationModule" in txt
    assert "annotationModule" in txt
    assert "annotations" in txt


def test_annotation_module_concatenates_before_18_frame_loop():
    """Fragment-ordering invariant: 15c must concatenate BEFORE
    18_frame_loop (which reads `_lastTriggeredAnnotation` set by 09).
    The module's per-frame tick uses that closure-scoped value so
    the path-active glow stays cinematic during a tour even after
    the legacy markerObjs are torn down."""
    html = html_for("HarnessScene")
    ann_i = html.index("//  AnnotationModule (Phase 5")
    # 18 runs the render loop -- presence + ordering checked here
    fl_i = html.index("css2d.render(scene, camera);")
    assert ann_i < fl_i, (
        "15c (AnnotationModule) must concatenate BEFORE 18_frame_loop "
        "so its registration is complete by the time the render loop "
        "starts driving css2d.render() each frame"
    )


def test_annotation_module_section_replaces_drawer_placeholder():
    """The Phase-2D Scene Settings drawer (17b) emits a placeholder
    annotations section. The AnnotationModule's renderSceneSettings
    hook is registered via EditorModuleRegistry.on('register', ...)
    so the placeholder is replaced with the real section. The static
    structure asserts: the renderSceneSettings function (a) looks
    for and removes the existing placeholder, then (b) appends the
    new section with the same `data-section="annotations"` attribute
    so the spec §12.2 section ORDER is preserved."""
    html = html_for("HarnessScene")
    # Find the AnnotationModule's renderSceneSettings body
    # specifically (the rendered HTML may contain other modules'
    # renderSceneSettings -- start the search inside the 15c block).
    ann_i = html.index("//  AnnotationModule (Phase 5")
    rss_i = html.index("renderSceneSettings: function (parentEl)", ann_i)
    rss_end = html.index("testSurface:", rss_i)
    body = html[rss_i:rss_end]
    # Placeholder-replacement signature: querySelector for the
    # existing details + removeChild it before appending the new one.
    assert "details[data-section=\"annotations\"]" in body, (
        "AnnotationModule renderSceneSettings must target the "
        "placeholder by its data-section id so spec section order "
        "is preserved"
    )
    assert "removeChild" in body
    assert "dataset.section = 'annotations'" in body, (
        "the replacement section MUST carry the same data-section id"
    )


def test_legacy_08_guard_present_and_safe():
    """The minimal guard added to 08_input.js_tmpl wraps the legacy
    `for (const a of annotationsData)` block so a future load-order
    change (15c before 08) cleanly no-ops the legacy renderer
    without the AnnotationModule's _teardownLegacy needing to fire.
    The guard MUST evaluate against window.__sceneview.modules at
    runtime so it tolerates the case where the registry is not yet
    wired (defensive); a missing registry => the legacy code runs."""
    html = html_for("HarnessScene")
    # Guard text exists.
    assert "_annotationsOwnedByModule" in html
    # The guard is wrapped in `if (!_annotationsOwnedByModule) { for (`
    # which is the safe form (legacy runs when module is NOT
    # registered; module's _teardownLegacy handles the present case).
    assert "if (!_annotationsOwnedByModule)" in html
    # The legacy `for` loop must still be inside the guarded block --
    # we removed the unconditional loop and replaced it with the
    # guarded one.
    g_i = html.index("if (!_annotationsOwnedByModule)")
    # The block ends at the next top-level closing brace + blank line
    # before the next section (// ---- Camera-path playback ----).
    g_end = html.index("// ---- Camera-path playback ----", g_i)
    block = html[g_i:g_end]
    assert "for (const a of annotationsData)" in block, (
        "the legacy CSS2DObject construction must stay inside the "
        "guarded block so it runs when the AnnotationModule is absent"
    )
    assert "new CSS2DObject(el)" in block, (
        "the legacy CSS2DObject(el) construction must still be inside "
        "the guard so a module-less viewer still renders annotations"
    )
    assert "markerObjs.push" in block, (
        "the legacy markerObjs.push must still be inside the guard"
    )
    # And the array bindings must still exist OUTSIDE the guard so
    # 10_camera_select + 18_frame_loop's references stay valid.
    pre_i = html.index("// ---- Annotations (CSS2DObject) ----")
    pre_block = html[pre_i:g_i]
    assert "const annotationsData = cfg.annotations || [];" in pre_block
    assert "const markerObjs = [];" in pre_block


def test_annotation_module_visible_in_all_modes():
    """The AnnotationModule renders in author, user AND embed modes.
    The OverlayScene tick registration carries the same ['author',
    'user', 'embed'] modes filter -- so the per-frame distance check
    (and the dot's appear/disappear off [t_in, t_out]) runs in every
    mode the viewer ever boots in."""
    html = html_for("HarnessScene")
    # Find the mount() body of the module.
    m_i = html.index("mount: function (overlay, hud, interaction, modes) {",
                    html.index("//  AnnotationModule (Phase 5"))
    m_end = html.index("unmount: function () {", m_i)
    body = html[m_i:m_end]
    # OverlayScene.register call inside mount with the all-modes filter.
    assert "overlay.register(" in body
    assert "id: 'annotations-tick'," in body
    assert "modes: ['author', 'user', 'embed']" in body
    # And the module's own defaultModes is the same triplet.
    dm_i = html.index("defaultModes: ['author', 'user', 'embed']",
                     html.index("//  AnnotationModule (Phase 5"))
    assert dm_i > 0


def test_annotation_module_timeline_lane_renders_t_in_t_out_bars():
    """The Phase 2D multi-lane bottom-timeline pulls each module's
    `timelineLane.render(ctx, x, y, w, h, t)`. AnnotationModule's
    lane draws ONE horizontal bar per annotation, mapped from
    [t_in..t_out] to the lane's pixel rect."""
    html = html_for("HarnessScene")
    # Locate the timelineLane in 15c.
    tl_i = html.index("timelineLane: {",
                    html.index("//  AnnotationModule (Phase 5"))
    # The render function uses t_in / t_out + the master playhead
    # duration (_player.duration) to map time->x.
    tl_body = html[tl_i:tl_i + 2500]
    assert "label: 'ann'" in tl_body
    assert "rows: 1," in tl_body
    assert "render: function (ctx, x, y, w, h, tCur)" in tl_body
    # Map time-to-x uses the master playhead's duration via
    # _player.duration; bars use t_in / t_out per annotation.
    assert "ann.t_in" in tl_body
    assert "ann.t_out" in tl_body
    assert "_player.duration" in tl_body
    # Cyclic colour palette
    assert "fillRect(" in tl_body


# --------------------------------------------------------------------------
# (b) DYNAMIC: run the AnnotationModule's pure helpers under Node
# --------------------------------------------------------------------------

pytestmark_dynamic = pytest.mark.skipif(
    _NODE is None, reason="node not available (CI provides it)"
)


def _extract_helpers_js() -> str:
    """Pull the per-annotation helpers (_upgradeAnnotation +
    _timelineOpacity + ANNOTATION_DEFAULTS + _smoothstep) out of the
    rendered HTML and wrap them in a Node-runnable shim. Returns a
    self-contained JS string.

    The actual module IIFE has dependencies (EditorModuleRegistry,
    CSS2DObject, OverlayScene, ...) that don't load cleanly under
    Node; for the pure-helper byte-runtime parity tests we re-extract
    the JS literals + function definitions we care about and re-host
    them in a small shim, the same pattern test_spcp_js_port.py uses.
    """
    html = html_for("HarnessScene")
    # Find the ANNOTATION_DEFAULTS block (object literal start ->
    # close brace at the same indent level + 4 spaces).
    ad_a = html.index("const ANNOTATION_DEFAULTS = {")
    ad_b = html.index("};", ad_a) + 2
    ad_block = html[ad_a:ad_b]
    # _newAnnotationId
    nai_a = html.index("function _newAnnotationId() {")
    nai_b = html.index("\n    }\n", nai_a) + len("\n    }\n")
    nai_block = html[nai_a:nai_b]
    # _upgradeAnnotation
    ua_a = html.index("function _upgradeAnnotation(ann) {")
    ua_b = html.index("\n    }\n", ua_a) + len("\n    }\n")
    ua_block = html[ua_a:ua_b]
    # _smoothstep
    ss_a = html.index("function _smoothstep(a, b, x) {")
    ss_b = html.index("\n    }\n", ss_a) + len("\n    }\n")
    ss_block = html[ss_a:ss_b]
    # _timelineOpacity
    to_a = html.index("function _timelineOpacity(ann, tNow) {")
    to_b = html.index("\n    }\n", to_a) + len("\n    }\n")
    to_block = html[to_a:to_b]
    return ad_block + "\n" + nai_block + "\n" + ua_block + "\n" + \
        ss_block + "\n" + to_block


def _run_node(script: str) -> dict:
    """Run ``script`` under Node and parse its stdout as JSON. The
    script must end with ``process.stdout.write(JSON.stringify(...))``.
    """
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "annmod_test.mjs"
        f.write_text(script, encoding="utf-8")
        out = subprocess.run(
            [_NODE, str(f)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=60,
        )
    if out.returncode != 0:
        raise AssertionError(
            "node failed (rc=%d):\n--- stderr ---\n%s\n--- stdout ---\n%s"
            % (out.returncode, out.stderr.decode("utf-8", "replace"),
               out.stdout.decode("utf-8", "replace"))
        )
    return json.loads(out.stdout.decode("utf-8"))


def _shim_preamble() -> str:
    """Provide a window object so the helpers can read window.crypto.
    Node 19+ exposes globalThis.crypto with a getter-only property,
    so we install `window` as a side container and let the JS fall
    back to its built-in catch path (Math.random) if crypto is
    inaccessible -- the _newAnnotationId is not under test here
    (the upgrade + opacity helpers are)."""
    return (
        "globalThis.window = {\n"
        "  // Node may have globalThis.crypto as a getter-only property;\n"
        "  // a plain assignment to window.crypto here is safe (window is\n"
        "  // a fresh object), and the JS helper falls back to Math.random\n"
        "  // if crypto.getRandomValues throws.\n"
        "  crypto: {\n"
        "    getRandomValues(arr) {\n"
        "      for (let i = 0; i < arr.length; i++) arr[i] = i * 17;\n"
        "      return arr;\n"
        "    },\n"
        "  },\n"
        "};\n"
    )


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_js_annotation_defaults_match_python_source_of_truth():
    """The JS-side ANNOTATION_DEFAULTS literal in 15c must mirror
    the Python core/path_io.ANNOTATION_DEFAULTS (the source of truth
    shipped in 9fa1405). The two sides are kept in lockstep at
    review-time; this test catches a drift."""
    js = _shim_preamble() + _extract_helpers_js() + r"""
process.stdout.write(JSON.stringify(ANNOTATION_DEFAULTS));
"""
    r = _run_node(js)
    # Each key + value matches the Python defaults byte-for-byte.
    for key, py_val in ANNOTATION_DEFAULTS.items():
        assert key in r, f"JS ANNOTATION_DEFAULTS missing key: {key}"
        assert r[key] == py_val, (
            f"JS/Python ANNOTATION_DEFAULTS drift for {key}: "
            f"JS={r[key]!r} vs Python={py_val!r}"
        )
    # No extra keys either way -- exact match.
    assert set(r.keys()) == set(ANNOTATION_DEFAULTS.keys()), (
        "JS ANNOTATION_DEFAULTS key set diverges from Python: "
        f"JS={sorted(r.keys())} vs Python={sorted(ANNOTATION_DEFAULTS.keys())}"
    )


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_js_upgrade_annotation_fills_defaults_for_legacy_entry():
    """Mirror of test_annotation_schema.py::
    test_upgrade_annotation_legacy_adds_all_new_fields under Node --
    a legacy 4-field annotation gets every Q6 default filled. The JS
    helper is what the AnnotationModule's _buildFromCfg consumes; if
    it diverges from the Python upgrade_annotation, a re-published
    scene's authored annotations could lose fields the editor
    expected."""
    js = _shim_preamble() + _extract_helpers_js() + r"""
const legacy = {
  label: '1',
  title: 'Detail view',
  text: 'Body copy here.',
  pos: [1.0, 2.0, 3.0],
};
const out = _upgradeAnnotation(legacy);
// id is auto-generated -- check shape but not exact value
const idShape = (typeof out.id === 'string') && out.id.startsWith('ann_');
process.stdout.write(JSON.stringify({ out, idShape }));
"""
    r = _run_node(js)
    o = r["out"]
    assert o["kind"] == "dot_unfold"
    assert o["unfold_radius_m"] == 5.0
    assert o["t_in"] == 0.0
    assert o["t_out"] == 999.0
    assert o["fade_ms"] == 300
    assert o["media_url"] is None
    assert o["billboard"] is True
    # Legacy fields preserved verbatim
    assert o["label"] == "1"
    assert o["title"] == "Detail view"
    assert o["text"] == "Body copy here."
    assert o["pos"] == [1.0, 2.0, 3.0]
    # id auto-generated with the canonical "ann_" prefix
    assert r["idShape"] is True


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_js_upgrade_annotation_preserves_existing_kind_field():
    """An entry already carrying `kind: title3d_overlay` is NOT
    overwritten by the default `dot_unfold`. Mirror of
    test_annotation_schema.py::
    test_upgrade_annotation_kind_field_preserved_when_set."""
    js = _shim_preamble() + _extract_helpers_js() + r"""
const out = _upgradeAnnotation({ kind: 'title3d_overlay',
  pos: [0, 0, 0] });
process.stdout.write(JSON.stringify(out));
"""
    o = _run_node(js)
    assert o["kind"] == "title3d_overlay"


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_js_timeline_opacity_appears_and_fades():
    """The _timelineOpacity helper returns:
       * 0  before t_in - eps
       * 1  at t_in + fade_s (full opacity)
       * 1  in the middle of the window
       * 0  past t_out
    This is the cinematic appear/disappear contract from spec §4.2.
    """
    js = _shim_preamble() + _extract_helpers_js() + r"""
const ann = { t_in: 5, t_out: 10, fade_ms: 1000 };  // 1s fade in/out
const r = {
  before: _timelineOpacity(ann, 4.0),   // before -> 0
  atIn:   _timelineOpacity(ann, 5.0),   // at t_in -> rising edge starts at 0
  midFade: _timelineOpacity(ann, 5.5),  // halfway through fade-in
  inside: _timelineOpacity(ann, 7.0),   // fully on (middle of window)
  atOut:  _timelineOpacity(ann, 10.0),  // at t_out -> falling edge ends at 0
  after:  _timelineOpacity(ann, 11.0),  // past t_out -> 0
};
process.stdout.write(JSON.stringify(r));
"""
    r = _run_node(js)
    assert r["before"] == 0
    # midFade should be > 0 and < 1
    assert 0 < r["midFade"] < 1
    # Inside (well past fade-in, well before fade-out) is fully on.
    assert abs(r["inside"] - 1.0) < 0.01, (
        f"opacity at t=7 (inside window with 1s fades from t=5..10) "
        f"should be ~1.0, got {r['inside']}"
    )
    assert r["after"] == 0


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_js_timeline_opacity_zero_fade_ms_is_step_function():
    """With fade_ms=0 the opacity is a pure step: 0 outside the
    window, 1 inside. No NaN, no division-by-zero (the helper
    short-circuits the linear-interp when fade_s == 0)."""
    js = _shim_preamble() + _extract_helpers_js() + r"""
const ann = { t_in: 5, t_out: 10, fade_ms: 0 };
const r = {
  before: _timelineOpacity(ann, 4.99),
  atIn:   _timelineOpacity(ann, 5.0),
  inside: _timelineOpacity(ann, 7.5),
  atOut:  _timelineOpacity(ann, 10.0),
  after:  _timelineOpacity(ann, 10.01),
};
process.stdout.write(JSON.stringify(r));
"""
    r = _run_node(js)
    assert r["before"] == 0
    assert r["inside"] == 1
    assert r["after"] == 0
