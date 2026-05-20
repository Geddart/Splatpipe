"""PanoramaModule contract tests (Phase 3 -- editor-arc-design #122 §4.5).

The PanoramaModule is a pure-JS IIFE shipped in
``viewers/spark/template_parts/15b_panorama_module.js_tmpl`` and registered
with the Phase 2 ``EditorModuleRegistry``. Its job:

  * Own ``cfg.panorama_backdrop`` (the schema slot).
  * Apply the configured equirectangular backdrop to ``THREE.Scene.background``
    in EVERY mode (author/user/embed) -- the backdrop is a public scene
    element, not an editor surface.
  * Populate the "Backdrop" section of the Scene Settings drawer (17b)
    with: file picker (POST ``../upload-image``), rotation slider
    (-180°..180° Y), intensity slider (0..3), clear button.
  * Push ONE ``EditHistory`` snapshot per gesture (R8 §4.2 -- not
    per-frame during a slider drag).
  * Register a ``defaultModes`` that includes ALL three modes -- the
    backdrop renders everywhere; the editor UI is gated separately by
    the drawer's HudLayer mode filter in 17b.

Static-only tests: the rendered HTML carries the documented surface
markers and the editor wiring. A future dynamic Node test could exercise
the IIFE in isolation (mirroring ``test_editor_module_registry.py``); for
Phase 3 the marker tests cover the contract pinning.
"""

from __future__ import annotations

from pathlib import Path

from splatpipe.viewers.spark.template import html_for


def _rendered_html() -> str:
    """Render the Spark viewer with a generic project name. The
    PanoramaModule fragment is mode-agnostic -- it always registers --
    so the static-marker assertions hold regardless of any kwarg here."""
    return html_for("HarnessScene")


# --------------------------------------------------------------------------
# (a) Fragment file is present + at the documented location
# --------------------------------------------------------------------------

def test_panorama_module_fragment_file_exists():
    """The 15b fragment is on disk at the expected location. Lexical
    ordering puts it between 15a (CameraPathModule) and 16 (editor
    timeline) so the THREE.Scene from 07 is in scope when its IIFE runs."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    frag = parts / "15b_panorama_module.js_tmpl"
    assert frag.exists(), f"missing fragment: {frag}"
    raw = frag.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM corruption"
    # CRLF check: the orchestrator concatenates fragments byte-for-byte
    # and a stray CR in a JS template literal can corrupt the IIFE body.
    assert b"\r" not in raw, "CRLF corruption"
    txt = raw.decode("utf-8")
    assert "PanoramaModule" in txt
    assert "panorama_backdrop" in txt


def test_panorama_default_is_null_in_cfg_defaults():
    """``cfg.panorama_backdrop`` defaults to ``null`` (the canonical
    "no backdrop" form). The default lives in 06_cfg's _DEFAULTS block."""
    html = _rendered_html()
    # The line in 06_cfg.js_tmpl reads `panorama_backdrop: null,` -- it
    # MUST appear in the generated HTML (no surprise removal by a
    # downstream concat / sub).
    assert "panorama_backdrop: null," in html


# --------------------------------------------------------------------------
# (b) Module contract: shape + stateKey + mode visibility
# --------------------------------------------------------------------------

# Surface markers that lock the EditorModule contract for the PanoramaModule
# (per spec §4.5 + R6). Each marker pins one promise: presence of the
# module instance, its stateKey, its mode visibility, its lifecycle hooks,
# and its registration with the shared coordinator.
_CONTRACT_MARKERS = (
    # IIFE entry + module local declaration
    "PanoramaModule",
    "function _pmInit()",
    "name: 'panorama_backdrop',",
    "stateKey: 'panorama_backdrop',",
    # defaultModes -- backdrop in EVERY mode (author/user/embed); the
    # editor UI is gated separately by the drawer's HudLayer registration.
    "defaultModes: ['author', 'user', 'embed'],",
    # Required lifecycle hooks
    "mount: function (overlay, hud, interaction, modes)",
    "unmount: function ()",
    "getDirtyState: function ()",
    "markClean: function ()",
    "renderSceneSettings: function (parentEl)",
    # Registration with the Phase-2 coordinator
    "EditorModuleRegistry.register(panoramaModule);",
)


def test_panorama_module_contract_markers_present():
    """The rendered viewer HTML carries every EditorModule-contract marker
    that the spec §4.5 + R6 + the Phase 2 registry require."""
    html = _rendered_html()
    for mk in _CONTRACT_MARKERS:
        assert mk in html, f"PanoramaModule contract marker missing: {mk!r}"


def test_panorama_module_does_not_modify_07_setup_three_spark():
    """Per R6: modules own their own THREE setup via ``mount()``. The
    PanoramaModule MUST capture ``scene`` via the IIFE scope from
    15b's ``mount()``, NOT by editing 07_setup_three_spark to expose it.
    We pin the IIFE-scope capture: ``if (typeof scene !== 'undefined' &&
    scene) _scene = scene;`` is the canonical phrasing."""
    html = _rendered_html()
    # The canonical capture line.
    assert "if (typeof scene !== 'undefined' && scene) _scene = scene;" in html, (
        "PanoramaModule must capture the THREE.Scene from the IIFE-scoped "
        "`scene` const set up in 07_setup_three_spark -- per R6, modules "
        "own their own THREE setup via mount() and MUST NOT modify "
        "07_setup_three_spark to wire a separate hook."
    )
    # Negative: 07_setup_three_spark must not contain any panorama wiring.
    setup_frag = (
        Path(__file__).parent.parent / "src" / "splatpipe" / "viewers" /
        "spark" / "template_parts" / "07_setup_three_spark.js_tmpl"
    ).read_text(encoding="utf-8")
    assert "panorama" not in setup_frag.lower(), (
        "07_setup_three_spark.js_tmpl must be untouched by Phase 3 -- "
        "PanoramaModule's THREE setup runs in its own fragment (15b)."
    )


# --------------------------------------------------------------------------
# (c) THREE.js render integration
# --------------------------------------------------------------------------

# The PanoramaModule sets THREE.EquirectangularReflectionMapping on the
# loaded texture and assigns it to scene.background (NOT scene.environment
# -- splats don't use IBL; spec §3.3 + R7). It also writes
# scene.backgroundIntensity + scene.backgroundRotation.
_THREE_INTEGRATION_MARKERS = (
    # Equirect mapping (NOT cube; NOT planar)
    "THREE.EquirectangularReflectionMapping",
    # sRGB colour space so the JPG round-trips correctly through the
    # tone mapper (renderer.toneMapping is wired in 07 off cfg.postprocessing).
    "THREE.SRGBColorSpace",
    # The THREE.Scene background slot itself (not scene.environment).
    "_scene.background = tex;",
    # Intensity multiplier + Y-axis rotation handling.
    "_scene.backgroundIntensity",
    "_scene.backgroundRotation",
    # TextureLoader is the standard equirect loading path (no PMREMGenerator
    # for v1 -- splats are not PBR so PMREM cube convolution is wasted work).
    "THREE.TextureLoader",
)


def test_panorama_three_integration_markers_present():
    """The PanoramaModule uses scene.background (NOT scene.environment),
    EquirectangularReflectionMapping, SRGBColorSpace, and writes
    scene.backgroundIntensity + scene.backgroundRotation."""
    html = _rendered_html()
    for mk in _THREE_INTEGRATION_MARKERS:
        assert mk in html, f"THREE integration marker missing: {mk!r}"
    # Negative-control: scene.environment must NOT be written by the
    # PanoramaModule. The spec §3.3 + R7 explicitly excludes scene.environment
    # because splats don't render via PBR -- writing it would be a UI lie.
    # We pin the absence via an exact phrase that would only appear if
    # someone wired it.
    assert "_scene.environment = tex" not in html, (
        "PanoramaModule must NOT set scene.environment (spec §3.3 + R7 -- "
        "splats are not PBR; IBL would be a UI lie)."
    )
    assert "scene.environment = tex" not in html.replace("_scene.environment", "_NOPE"), (
        "PanoramaModule must NOT set scene.environment (spec §3.3 + R7)."
    )


# --------------------------------------------------------------------------
# (d) Editor UI: file picker, sliders, clear button
# --------------------------------------------------------------------------

_UI_MARKERS = (
    # CSS class names per task spec
    "pan-controls",
    "pan-file",
    "pan-yaw",
    "pan-yaw-val",
    "pan-int",
    "pan-int-val",
    "pan-clear",
    # File picker accepts only LDR JPG/PNG (spec §3.2: LDR JPG only in v1
    # but the upload route also allows PNG -- we mirror its allow-list).
    "accept = 'image/jpeg,image/png';",
    # Rotation slider range (-180..180 °Y; step 1°)
    "yawSlider.min = '-180';",
    "yawSlider.max = '180';",
    "yawSlider.step = '1';",
    # Intensity slider range (0..3; step 0.05; default 1.0)
    "intSlider.min = '0';",
    "intSlider.max = '3';",
    "intSlider.step = '0.05';",
    # Upload route call: relative URL so the dashboard preview resolves it
    # to /projects/<path>/upload-image (the route shipped in ce3727f).
    "'../upload-image'",
)


def test_panorama_editor_ui_markers_present():
    """The drawer-rendered UI has the file picker, the rotation slider
    (-180..180°), the intensity slider (0..3), and the clear button.
    All wired off the documented class names so the harness can drive them."""
    html = _rendered_html()
    for mk in _UI_MARKERS:
        assert mk in html, f"editor UI marker missing: {mk!r}"


# --------------------------------------------------------------------------
# (e) Gesture-end snapshot push (R8 §4.2)
# --------------------------------------------------------------------------

# The PanoramaModule pushes EditHistory snapshots ONCE per gesture
# (gesture-start convention), NEVER per-frame during a slider drag.
# Spec markers: pushUndo with the gesture label, on pointerdown (start)
# for sliders, on change (commit) for the file picker.
_GESTURE_END_MARKERS = (
    # Labels per gesture
    "'panorama-upload'",
    "'panorama-clear'",
    "'panorama-rotate'",
    "'panorama-intensity'",
    # pushUndo (the registry-delegated history push)
    "EditorModuleRegistry.pushUndo(",
    # Slider gesture-start binding (pointerdown -- NOT every input frame)
    "yawSlider.addEventListener('pointerdown'",
    "intSlider.addEventListener('pointerdown'",
)


def test_panorama_gesture_end_snapshot_push():
    """Every UI gesture pushes ONE EditHistory snapshot at gesture
    start (pointerdown for sliders, change for the file picker / clear
    button). Per R8 §4.2 -- a per-frame snapshot would yield 60 entries/s
    + an unusable history."""
    html = _rendered_html()
    for mk in _GESTURE_END_MARKERS:
        assert mk in html, f"gesture-end snapshot marker missing: {mk!r}"
    # NEGATIVE: no pushUndo inside an 'input' handler (which fires per
    # frame during a drag). The IIFE contains the substring
    # ".addEventListener('input'" for live preview, but the only
    # pushUndo call sites must be in pointerdown / change / click
    # handlers, NEVER inside an input handler. We pin this by searching
    # for the bad pattern.
    bad = "yawSlider.addEventListener('input', function () {"
    i = html.find(bad)
    if i > 0:
        # The 'input' handler body must NOT contain pushUndo (gesture-end
        # contract). Find the closing of the function -- a simple
        # heuristic: the next "addEventListener" call closes this block.
        end = html.find("addEventListener", i + len(bad))
        block = html[i:end] if end > 0 else html[i:i + 600]
        assert "pushUndo" not in block, (
            "yawSlider 'input' handler must not call pushUndo (R8 §4.2 -- "
            "per-frame snapshots are forbidden; commit via pointerdown + "
            "change/blur)."
        )
    bad_i = "intSlider.addEventListener('input', function () {"
    i = html.find(bad_i)
    if i > 0:
        end = html.find("addEventListener", i + len(bad_i))
        block = html[i:end] if end > 0 else html[i:i + 600]
        assert "pushUndo" not in block, (
            "intSlider 'input' handler must not call pushUndo (R8 §4.2)."
        )


# --------------------------------------------------------------------------
# (f) Scene Settings drawer integration (Phase 2D coupling)
# --------------------------------------------------------------------------

def test_panorama_attaches_to_scene_settings_drawer():
    """The PanoramaModule renders inside the Scene Settings drawer
    placeholder section that 17b builds. The hook contract is via
    ``renderSceneSettings(parentEl)`` (the registry's optional hook,
    invoked from 17b's 'register' listener). The module also self-attaches
    via setTimeout(0) because 15b registers BEFORE 17b wires its
    listener (fragment-order 15b < 17b -- mirrors the explicit catch-up
    walk pattern used in 16 multi-lane timeline)."""
    html = _rendered_html()
    # The drawer placeholder section the module targets.
    assert "data-section=\"panorama\"" in html or "data-section='panorama'" in html, (
        "drawer placeholder section <details data-section=\"panorama\"> must "
        "exist (built by 17b's _SS_PLACEHOLDER_ORDER)"
    )
    # The DOM query the module uses to locate the placeholder.
    assert "details[data-section=\"panorama\"]" in html, (
        "PanoramaModule must query the drawer for the panorama section by "
        "its documented data-section selector"
    )
    # The replacement target inside the placeholder (17b emits one of
    # these per section).
    assert ".spcp-scene-settings-section-body" in html, (
        "PanoramaModule must locate the placeholder's body element by the "
        "class 17b uses (.spcp-scene-settings-section-body)"
    )
    # The setTimeout self-attach is the documented workaround for the
    # 15b-before-17b ordering -- it MUST be wired, otherwise the drawer
    # section never gets the real controls.
    assert "setTimeout(_attachToDrawer, 0)" in html, (
        "PanoramaModule must schedule a setTimeout(_attachToDrawer, 0) "
        "from mount() so the drawer-section replacement runs AFTER 17b's "
        "IIFE has built the placeholders (mirrors the 16 multi-lane "
        "catch-up walk pattern; 17b is Phase 2-owned and cannot be "
        "modified to add its own catch-up walk)."
    )


# --------------------------------------------------------------------------
# (g) Tooltip (per spec §4.5 "scene lights have no effect on splat pixels")
# --------------------------------------------------------------------------

def test_panorama_tooltip_documents_splat_pre_lighting():
    """Per spec §4.5 the editor MUST tell authors that scene lights have
    no effect on splat pixels (splats are pre-lit from training data;
    adding light/IBL knobs would be a UI lie per R7)."""
    html = _rendered_html()
    # The tooltip text from the spec, verbatim except for the en-dash
    # which we use (—) to match the actual UI copy.
    assert "Splats are pre-lit from training data" in html, (
        "PanoramaModule tooltip must explain that splats are pre-lit "
        "(spec §4.5 R7 -- no scene_lights for v1)."
    )
    assert "scene lights have no effect on splat pixels" in html, (
        "PanoramaModule tooltip must explicitly say scene lights have no "
        "effect on splat pixels (spec §4.5)."
    )


# --------------------------------------------------------------------------
# (h) Test surface for the harness (window.__editor.panoramaModule)
# --------------------------------------------------------------------------

def test_panorama_test_surface_present():
    """The module exposes its instance + a couple of getters at
    ``window.__editor.panoramaModule`` (merged onto the existing
    test surface by the registry's testSurface auto-merge -- see 04a)."""
    html = _rendered_html()
    # The testSurface object the registry merges onto window.__editor.
    assert "testSurface: {" in html, (
        "PanoramaModule must declare a testSurface for window.__editor"
    )
    assert "get panoramaModule()" in html, (
        "testSurface must expose the panoramaModule instance"
    )
    assert "get panoramaDirty()" in html, (
        "testSurface must expose a panoramaDirty getter for the harness"
    )
