"""TitlesModule contract tests (Phase 8 -- editor-arc-design #122 §4.7).

The TitlesModule is a pure-JS IIFE shipped in
``viewers/spark/template_parts/15g_titles_module.js_tmpl`` and registered
with the EditorModuleRegistry as the canonical owner of the ``titles3d``
stateKey.

``titles3d`` has lived in :data:`splatpipe.core.config_safety.PUBLIC_VIEWER_CONFIG_KEYS`
+ :data:`splatpipe.core.config_merge.ALLOWED_PATCH_KEYS` for the whole
Phase-2 rollout; the gizmo's legacy ``_PATCH_KEYS`` walk has been bouncing
it through every save unchanged. Phase 8 ships BOTH the renderer (the
CSS2D billboard built from ``cfg.titles3d``) AND the editor (Scene
Settings drawer section + multi-lane timeline bar).

Two test layers (mirrors ``test_cuts_module.py``/``test_annotation_module.py``):

(a) STATIC: the generated viewer HTML carries the documented surface
    markers (the IIFE, the registration call, the contract fields, the
    Scene Settings render hook, the timelineLane, the test surface,
    the EditHistory snapshot labels). Pure Python -- no browser, no
    Node.

(b) DYNAMIC (Node): extract the TitlesModule's pure helpers
    (``TITLE_DEFAULTS`` + ``_upgradeTitle`` + ``_smoothstep`` +
    ``_timelineOpacity``) from the rendered HTML and run them under
    Node so the appear/disappear contract is byte-runtime-checked.
    Mirrors ``test_annotation_module.py::_extract_helpers_js`` -- the
    full module IIFE has THREE.js / CSS2DObject / EditorModuleRegistry
    dependencies that do not load cleanly under Node, but the pure
    helpers re-host trivially.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from splatpipe.viewers.spark.template import html_for

_NODE = shutil.which("node")


# --------------------------------------------------------------------------
# (a) STATIC: the rendered HTML carries the documented surface markers
# --------------------------------------------------------------------------


_TITLES_MARKERS = (
    # IIFE wrapper + the documented Phase-8 comment block
    "//  TitlesModule (Phase 8 -- editor-arc-design #122 §4.7)",
    "(function _titlesInit() {",
    # EditorModule contract fields per Phase 2 spec
    "name: 'titles3d',",
    "stateKey: 'titles3d',",
    "defaultModes: ['author', 'user', 'embed'],",
    # The required EditorModule lifecycle methods
    "mount: function (overlay, hud, interaction, modes) {",
    "unmount: function () {",
    "getDirtyState: function () {",
    "markClean: function () {",
    "onCfgChange: function (prev, next, stateKey) {",
    # JS-side TITLE_DEFAULTS literal (the source of truth for v1)
    "const TITLE_DEFAULTS = {",
    "text: '',",
    "billboard: true,",
    "size: 24,",
    "color: '#ffffff',",
    "t_in: 0.0,",
    "t_out: 999.0,",
    "fade_ms: 300,",
    "function _upgradeTitle(t) {",
    "function _newTitleId() {",
    # Per-frame tick infrastructure
    "function _titlesTick(",
    "function _timelineOpacity(",
    "function _smoothstep(",
    # CSS2DObject reuse (the existing 04_js_prologue import); NO
    # dynamic import + NO second CSS2DRenderer -- the AnnotationModule
    # pattern is reused so the 08_input `css2d.render(scene, camera)`
    # call in 18_frame_loop also handles titles.
    "new CSS2DObject(el)",
    "scene.add(obj3d)",
    # OverlayScene tick registration (all-modes)
    "id: 'titles3d-tick',",
    # Timeline lane contributes thin white bars (spec §4.10)
    "timelineLane: {",
    "label: 'titles',",
    "render: function (ctx, x, y, w, h, tCur)",
    "ctx.fillStyle = '#ffffff';",
    # Scene Settings drawer section + Add button (CutsModule pattern
    # -- titles3d is NOT in 17b's _SS_PLACEHOLDER_ORDER; we CREATE a
    # fresh section + append it)
    "renderSceneSettings: function (parentEl)",
    "'+ Add title'",
    "dataset.section = 'titles3d'",
    # Test surface (functions, NOT getters -- sidesteps the registry's
    # Object.assign getter-freeze pattern)
    "testSurface: {",
    "titlesGet() { return titlesModule; }",
    "titlesCount() { return _titleStates.length; }",
    "_TITLE_DEFAULTS: TITLE_DEFAULTS,",
    # EditHistory snapshot labels (ONE per gesture, NEVER per keystroke;
    # spec §6.3 + R8 §4.2)
    "'title-add'",
    "'title-delete'",
    "'title-text'",
    "'title-color'",
    "'title-size'",
    "'title-t-in'",
    "'title-t-out'",
    "'title-fade-ms'",
    # Registration call (lands the module in the registry at boot)
    "EditorModuleRegistry.register(titlesModule);",
)


def test_titles_module_markers_present_in_rendered_html():
    """The TitlesModule IIFE + registration + every documented contract
    field is present in the generated viewer HTML."""
    html = html_for("HarnessScene")
    for mk in _TITLES_MARKERS:
        assert mk in html, f"TitlesModule marker missing: {mk!r}"


def test_titles_module_fragment_file_exists_and_clean():
    """The 15g fragment is on disk + at the expected location (the
    orchestrator loads it after 15a/b/c/d in lexical order so the
    registry's section/lane registration order per spec §4.9 is
    preserved) and has no BOM / CRLF corruption."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    f = parts / "15g_titles_module.js_tmpl"
    assert f.exists(), f"missing fragment: {f}"
    raw = f.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM corruption"
    assert b"\r" not in raw, "CRLF corruption"
    txt = raw.decode("utf-8")
    assert "TitlesModule" in txt
    assert "EditorModuleRegistry.register(titlesModule)" in txt


def test_titles_module_concatenates_after_15a_and_before_18_frame_loop():
    """Fragment-ordering invariant: 15g (TitlesModule) must concatenate
    AFTER 15a (CameraPathModule -- the master playhead's owner) AND
    BEFORE 18_frame_loop (whose `css2d.render(scene, camera)` call is
    what renders our CSS2DObjects each frame). The 15a < 15g < 18
    lexical ordering enforces this."""
    html = html_for("HarnessScene")
    cam_i = html.index(
        "//  CameraPathModule (Phase 2B -- editor-arc-design"
    )
    titles_i = html.index(
        "//  TitlesModule (Phase 8 -- editor-arc-design"
    )
    frame_i = html.index("css2d.render(scene, camera);")
    assert cam_i < titles_i, (
        "15a_camera_path_module must concatenate BEFORE 15g_titles_module "
        "so the registry's section-order convention (CameraPathModule "
        "first per spec §4.9) is preserved"
    )
    assert titles_i < frame_i, (
        "15g (TitlesModule) must concatenate BEFORE 18_frame_loop so its "
        "OverlayScene tick layer is registered by the time the render "
        "loop's css2d.render() fires each frame"
    )


def test_titles_module_does_not_touch_contested_fragments():
    """Phase 8 invariant: titles3d ships its renderer INSIDE its own
    fragment via the existing `css2d` CSS2DRenderer (mounted by
    08_input). The contested fragments (07_setup_three_spark + 06_cfg
    + 08_input + 11_clip_player) are UNTOUCHED by this commit -- a
    grep of those files MUST contain zero references to ``titlesModule``
    / ``_titlesInit`` / ``TitlesModule``. Mirrors the Phase-5/6
    "don't touch other-phase territory" discipline."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    for fname in (
        "06_cfg.js_tmpl",
        "07_setup_three_spark.js_tmpl",
        "08_input.js_tmpl",
        "11_clip_player.js_tmpl",
        "17a_edit_history.js_tmpl",
        "17b_scene_settings_drawer.js_tmpl",
    ):
        f = parts / fname
        assert f.exists(), f"contested fragment missing: {f}"
        txt = f.read_text(encoding="utf-8")
        for tok in ("TitlesModule", "_titlesInit", "titlesModule"):
            assert tok not in txt, (
                f"contested fragment {fname!r} should NOT reference "
                f"{tok!r} -- Phase 8 owns 15g only, never touches "
                f"another phase's territory"
            )


def test_titles_module_visible_in_all_modes():
    """The TitlesModule renders in author, user AND embed modes.
    The OverlayScene tick registration carries the same ['author',
    'user', 'embed'] modes filter -- so the per-frame opacity tick
    (and the cinematic appear/disappear off [t_in, t_out]) runs in
    every mode the viewer ever boots in."""
    html = html_for("HarnessScene")
    # Find the mount() body of the module.
    titles_top = html.index("//  TitlesModule (Phase 8")
    m_i = html.index("mount: function (overlay, hud, interaction, modes) {",
                    titles_top)
    m_end = html.index("unmount: function () {", m_i)
    body = html[m_i:m_end]
    # OverlayScene.register call inside mount with the all-modes filter.
    assert "overlay.register(" in body
    assert "id: 'titles3d-tick'," in body
    assert "modes: ['author', 'user', 'embed']" in body
    # And the module's own defaultModes is the same triplet.
    dm_i = html.index("defaultModes: ['author', 'user', 'embed']",
                     titles_top)
    assert dm_i > 0


def test_titles_module_timeline_lane_uses_t_in_t_out():
    """The Phase 2D multi-lane bottom-timeline pulls each module's
    `timelineLane.render(ctx, x, y, w, h, t)`. TitlesModule's lane
    draws ONE thin white bar per title, mapped from [t_in..t_out] to
    the lane's pixel rect via the master playhead's `_player.duration`.
    Spec §4.10 lists this lane as "thin white bars"."""
    html = html_for("HarnessScene")
    titles_top = html.index("//  TitlesModule (Phase 8")
    tl_i = html.index("timelineLane: {", titles_top)
    tl_body = html[tl_i:tl_i + 2500]
    assert "label: 'titles'" in tl_body
    assert "rows: 1," in tl_body
    assert "render: function (ctx, x, y, w, h, tCur)" in tl_body
    # Time-to-x mapping uses the master playhead's duration via
    # _player.duration; bars use t_in / t_out per title.
    assert "t3d.t_in" in tl_body
    assert "t3d.t_out" in tl_body
    assert "_player.duration" in tl_body
    # White bar fill colour (spec §4.10).
    assert "ctx.fillStyle = '#ffffff';" in tl_body
    assert "fillRect(" in tl_body


def test_titles_module_creates_drawer_section_not_in_placeholder_order():
    """titles3d is NOT in 17b's `_SS_PLACEHOLDER_ORDER` (the six
    pre-listed placeholders cover Phase 3/4/5/7/2 sections). Phase 8
    CREATES a fresh `<details data-section="titles3d">` + appends it
    -- mirrors the Phase-6 CutsModule pattern exactly. The
    renderSceneSettings hook MUST: (a) check for an existing section
    with the same data-section id (idempotency for re-registration),
    (b) construct + append a fresh section if absent, and (c) build a
    `+ Add title` button + the per-title list container inside it."""
    html = html_for("HarnessScene")
    # Verify 17b's placeholder set does NOT include titles3d (the
    # spec lock that drives this whole pattern).
    pl_i = html.index("_SS_PLACEHOLDER_ORDER = [")
    pl_end = html.index("];", pl_i)
    pl_block = html[pl_i:pl_end]
    assert "'titles3d'" not in pl_block, (
        "17b's _SS_PLACEHOLDER_ORDER must NOT carry a titles3d entry -- "
        "TitlesModule (Phase 8) creates its own section, mirroring the "
        "Phase-6 CutsModule pattern (a 17b edit would be Phase 2D "
        "territory, NOT Phase 8)"
    )
    # Verify the TitlesModule's renderSceneSettings body creates the
    # section + appends it. Locate via the Phase-8 comment block.
    titles_top = html.index("//  TitlesModule (Phase 8")
    rss_i = html.index("renderSceneSettings: function (parentEl)",
                       titles_top)
    rss_end = html.index("testSurface:", rss_i)
    body = html[rss_i:rss_end]
    # Idempotency check via querySelector
    assert "details[data-section=\"titles3d\"]" in body
    # Section creation pattern (CutsModule lineage)
    assert "createElement('details')" in body
    assert "dataset.section = 'titles3d'" in body
    assert "parentEl.appendChild(_ssSection)" in body
    # "+ Add title" button text
    assert "'+ Add title'" in body
    # The per-title list container
    assert "'spcp-titles3d-list'" in body


def test_titles_module_v1_supports_billboard_true_only():
    """Per the prompt + spec §4.7: v1 SUPPORTS BILLBOARD=TRUE ONLY.
    Non-billboard CSS3D rendering is documented as a future
    extension. The renderer code MUST skip an entry with
    `billboard === false` so a hand-authored CSS3D-expecting entry
    does NOT silently render as a CSS2D billboard (which would be a
    UI lie). The `_buildFromCfg` function carries the explicit
    `if (t3d.billboard === false) continue;` guard."""
    html = html_for("HarnessScene")
    titles_top = html.index("//  TitlesModule (Phase 8")
    # Find the _buildFromCfg function inside the module.
    bf_i = html.index("function _buildFromCfg() {", titles_top)
    bf_end = html.index("\n    }\n", bf_i) + len("\n    }\n")
    bf_block = html[bf_i:bf_end]
    # The explicit skip-when-billboard-false guard
    assert "billboard === false" in bf_block
    # And the spec billboard:true default lives in TITLE_DEFAULTS.
    assert "billboard: true," in html[titles_top:titles_top + 8000], (
        "TITLE_DEFAULTS.billboard must default to true per spec §4.7 "
        "and the schema example in scene_cuts.py"
    )


# --------------------------------------------------------------------------
# (b) DYNAMIC: extract the pure helpers + run them under Node
# --------------------------------------------------------------------------

pytestmark_dynamic = pytest.mark.skipif(
    _NODE is None, reason="node not available (CI provides it)"
)


def _extract_helpers_js() -> str:
    """Pull the per-title helpers (``TITLE_DEFAULTS`` +
    ``_upgradeTitle`` + ``_smoothstep`` + ``_timelineOpacity`` +
    ``_newTitleId``) out of the rendered HTML and return them as a
    self-contained JS string. Mirrors
    ``test_annotation_module.py::_extract_helpers_js`` -- the full
    module IIFE has THREE.js / CSS2DObject / EditorModuleRegistry
    dependencies that don't load cleanly under Node; for the pure-
    helper byte-runtime parity tests we re-extract the JS literals +
    function definitions we care about and re-host them in a small
    shim. Same pattern test_spcp_js_port.py uses."""
    html = html_for("HarnessScene")
    # Walk from the Phase-8 comment block so we never accidentally
    # match a helper of the same name in another module (the
    # AnnotationModule has its own `_smoothstep` and
    # `_timelineOpacity` -- we want the TitlesModule pair).
    titles_top = html.index("//  TitlesModule (Phase 8")
    # TITLE_DEFAULTS literal
    ad_a = html.index("const TITLE_DEFAULTS = {", titles_top)
    ad_b = html.index("};", ad_a) + 2
    ad_block = html[ad_a:ad_b]
    # _newTitleId
    nai_a = html.index("function _newTitleId() {", titles_top)
    nai_b = html.index("\n    }\n", nai_a) + len("\n    }\n")
    nai_block = html[nai_a:nai_b]
    # _upgradeTitle
    ua_a = html.index("function _upgradeTitle(t) {", titles_top)
    ua_b = html.index("\n    }\n", ua_a) + len("\n    }\n")
    ua_block = html[ua_a:ua_b]
    # _smoothstep (TitlesModule's copy -- different from 15c's)
    ss_a = html.index("function _smoothstep(a, b, x) {", titles_top)
    ss_b = html.index("\n    }\n", ss_a) + len("\n    }\n")
    ss_block = html[ss_a:ss_b]
    # _timelineOpacity (TitlesModule's copy)
    to_a = html.index("function _timelineOpacity(t3d, tNow) {", titles_top)
    to_b = html.index("\n    }\n", to_a) + len("\n    }\n")
    to_block = html[to_a:to_b]
    return ad_block + "\n" + nai_block + "\n" + ua_block + "\n" + \
        ss_block + "\n" + to_block


def _run_node(script: str) -> dict:
    """Run ``script`` under Node and parse its stdout as JSON. The
    script must end with ``process.stdout.write(JSON.stringify(...))``.
    Mirrors test_annotation_module.py::_run_node."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "titles_test.mjs"
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
            % (
                out.returncode,
                out.stderr.decode("utf-8", "replace"),
                out.stdout.decode("utf-8", "replace"),
            )
        )
    return json.loads(out.stdout.decode("utf-8"))


def _shim_preamble() -> str:
    """Provide a window object so the helpers can read window.crypto.
    Node 19+ exposes globalThis.crypto with a getter-only property;
    a plain assignment to window.crypto here is safe (window is a
    fresh object), and _newTitleId falls back to Math.random if
    crypto.getRandomValues throws. Mirrors
    test_annotation_module.py::_shim_preamble."""
    return (
        "globalThis.window = {\n"
        "  crypto: {\n"
        "    getRandomValues(arr) {\n"
        "      for (let i = 0; i < arr.length; i++) arr[i] = i * 17;\n"
        "      return arr;\n"
        "    },\n"
        "  },\n"
        "};\n"
    )


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_js_title_defaults_match_documented_v1_schema():
    """The JS-side TITLE_DEFAULTS literal in 15g must match the
    documented v1 schema (spec §4.7 + ``core/scene_cuts.py`` titles3d
    docstring + the prompt's renderer-choice section): billboard=true
    default, size=24, color=#ffffff, t_in=0, t_out=999, fade_ms=300.
    A future Python-side `core/path_io.TITLE_DEFAULTS` will mirror
    these values; for v1 the JS side is authoritative."""
    js = _shim_preamble() + _extract_helpers_js() + r"""
process.stdout.write(JSON.stringify(TITLE_DEFAULTS));
"""
    r = _run_node(js)
    assert r["text"] == ""
    assert r["pos"] == [0, 0, 0]
    assert r["billboard"] is True
    assert r["size"] == 24
    assert r["color"] == "#ffffff"
    assert r["t_in"] == 0.0
    assert r["t_out"] == 999.0
    assert r["fade_ms"] == 300


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_js_upgrade_title_fills_defaults_for_legacy_entry():
    """A legacy hand-authored titles3d entry with only `text` + `pos`
    gets every TITLE_DEFAULTS field filled. The id is auto-generated
    with the canonical `t3d_<hex>` prefix (the
    `core/path_io._new_annotation_id` pattern, renamed for titles)."""
    js = _shim_preamble() + _extract_helpers_js() + r"""
const legacy = {
  text: 'Scene Title',
  pos: [1.5, 2.5, 3.5],
};
const out = _upgradeTitle(legacy);
const idShape = (typeof out.id === 'string') && out.id.startsWith('t3d_');
process.stdout.write(JSON.stringify({ out, idShape }));
"""
    r = _run_node(js)
    o = r["out"]
    # Legacy fields preserved verbatim
    assert o["text"] == "Scene Title"
    assert o["pos"] == [1.5, 2.5, 3.5]
    # Defaults filled in
    assert o["billboard"] is True
    assert o["size"] == 24
    assert o["color"] == "#ffffff"
    assert o["t_in"] == 0.0
    assert o["t_out"] == 999.0
    assert o["fade_ms"] == 300
    # id auto-generated with the canonical "t3d_" prefix
    assert r["idShape"] is True


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_js_upgrade_title_preserves_existing_fields_verbatim():
    """A title entry already carrying explicit `size` + `color` +
    `t_in/t_out` is NOT overwritten by the defaults. Mirrors the
    `_upgradeAnnotation` parity test in 15c."""
    js = _shim_preamble() + _extract_helpers_js() + r"""
const out = _upgradeTitle({
  id: 't3d_custom',
  text: 'My Title',
  pos: [0, 1, 2],
  size: 48,
  color: '#ff8a3d',
  billboard: true,
  t_in: 5.0,
  t_out: 12.0,
  fade_ms: 500,
});
process.stdout.write(JSON.stringify(out));
"""
    o = _run_node(js)
    assert o["id"] == "t3d_custom"
    assert o["text"] == "My Title"
    assert o["pos"] == [0, 1, 2]
    assert o["size"] == 48
    assert o["color"] == "#ff8a3d"
    assert o["t_in"] == 5.0
    assert o["t_out"] == 12.0
    assert o["fade_ms"] == 500


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_js_timeline_opacity_appears_and_fades():
    """The _timelineOpacity helper returns:
       * 0  before t_in - eps
       * 1  at t_in + fade_s (full opacity)
       * 1  in the middle of the window
       * 0  past t_out
    This is the cinematic appear/disappear contract from spec §4.7
    (same shape as the annotation contract in §4.2)."""
    js = _shim_preamble() + _extract_helpers_js() + r"""
const t3d = { t_in: 5, t_out: 10, fade_ms: 1000 };  // 1s fade in/out
const r = {
  before:  _timelineOpacity(t3d, 4.0),
  atIn:    _timelineOpacity(t3d, 5.0),
  midFade: _timelineOpacity(t3d, 5.5),
  inside:  _timelineOpacity(t3d, 7.0),
  atOut:   _timelineOpacity(t3d, 10.0),
  after:   _timelineOpacity(t3d, 11.0),
};
process.stdout.write(JSON.stringify(r));
"""
    r = _run_node(js)
    assert r["before"] == 0
    # midFade should be > 0 and < 1 (rising edge inside the 1s fade
    # window starting at t_in=5)
    assert 0 < r["midFade"] < 1, (
        f"opacity at t=5.5 (halfway through 1s fade-in from t=5) "
        f"should be in (0, 1), got {r['midFade']}"
    )
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
const t3d = { t_in: 5, t_out: 10, fade_ms: 0 };
const r = {
  before: _timelineOpacity(t3d, 4.99),
  atIn:   _timelineOpacity(t3d, 5.0),
  inside: _timelineOpacity(t3d, 7.5),
  atOut:  _timelineOpacity(t3d, 10.0),
  after:  _timelineOpacity(t3d, 10.01),
};
process.stdout.write(JSON.stringify(r));
"""
    r = _run_node(js)
    assert r["before"] == 0
    assert r["inside"] == 1
    assert r["after"] == 0
