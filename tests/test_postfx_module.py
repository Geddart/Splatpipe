"""PostFXModule contract tests (Phase 4 -- editor-arc-design #122 §4.X).

The PostFXModule is a pure-JS IIFE shipped in
``viewers/spark/template_parts/15e_postfx_module.js_tmpl`` and registered
with the Phase 2 ``EditorModuleRegistry``. Its job:

  * Own ``cfg.postprocessing`` (the schema slot -- tonemapping + exposure).
  * Re-apply ``renderer.toneMapping`` + ``renderer.toneMappingExposure``
    from the live ``cfg.postprocessing`` (the renderer wiring already
    lives in ``07_setup_three_spark.js_tmpl`` lines ~108-116; Phase 4
    only adds the EDIT-TIME control surface, NOT a renderer re-wire).
  * Populate the "Post-FX" section of the Scene Settings drawer (17b)
    with: tonemap preset dropdown (linear / neutral / aces / aces2 /
    filmic) + exposure slider (0.5..4.0, step 0.05, default 1.5) +
    a tooltip explaining why splats are pre-lit (R7 §3.3).
  * Push ONE ``EditHistory`` snapshot per gesture (R8 §4.2 -- not
    per-frame during a slider drag).
  * Register a ``defaultModes`` that includes ALL three modes -- the
    post-fx renderer wiring is mode-agnostic; the editor UI is gated
    separately by the drawer's HudLayer mode filter in 17b.
  * Carry NO timelineLane -- post-fx is scene-global, not animatable.

Static-only tests: the rendered HTML carries the documented surface
markers and the editor wiring. Mirrors the static-only test layout in
``test_panorama_module.py`` (the closest analogue -- another
scene-global render module that lives in the drawer).
"""

from __future__ import annotations

from pathlib import Path

from splatpipe.viewers.spark.template import html_for


def _rendered_html() -> str:
    """Render the Spark viewer with a generic project name. The
    PostFXModule fragment is mode-agnostic -- it always registers --
    so the static-marker assertions hold regardless of any kwarg here."""
    return html_for("HarnessScene")


# --------------------------------------------------------------------------
# (a) Fragment file is present + at the documented location
# --------------------------------------------------------------------------


def test_postfx_module_fragment_file_exists():
    """The 15e fragment is on disk at the expected location. Lexical
    ordering puts it between 15d (CutsModule) and 16 (editor timeline)
    so the renderer from 07 is in scope when its IIFE runs."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    frag = parts / "15e_postfx_module.js_tmpl"
    assert frag.exists(), f"missing fragment: {frag}"
    raw = frag.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM corruption"
    # CRLF check: the orchestrator concatenates fragments byte-for-byte
    # and a stray CR in a JS template literal can corrupt the IIFE body.
    assert b"\r" not in raw, "CRLF corruption"
    txt = raw.decode("utf-8")
    assert "PostFXModule" in txt
    assert "postprocessing" in txt


def test_postfx_default_is_in_cfg_defaults():
    """``cfg.postprocessing`` defaults to ``{tonemapping:'neutral',
    exposure:1.5}`` (the canonical baseline that the renderer's
    ``07_setup_three_spark`` lines ~108-116 already consume). The
    default lives in 06_cfg's _DEFAULTS block."""
    html = _rendered_html()
    # The line in 06_cfg.js_tmpl reads
    #   postprocessing: { tonemapping: 'neutral', exposure: 1.5 },
    # which MUST appear in the generated HTML (no surprise removal by
    # a downstream concat / sub).
    assert "postprocessing: { tonemapping: 'neutral', exposure: 1.5 }" in html, (
        "cfg.postprocessing default must remain in 06_cfg.js_tmpl"
    )


# --------------------------------------------------------------------------
# (b) Module contract: shape + stateKey + mode visibility
# --------------------------------------------------------------------------

# Surface markers that lock the EditorModule contract for the PostFXModule
# (per spec §4.X + R6). Each marker pins one promise: presence of the
# module instance, its stateKey, its mode visibility, its lifecycle hooks,
# and its registration with the shared coordinator.
_CONTRACT_MARKERS = (
    # IIFE entry + module local declaration
    "PostFXModule",
    "function _pfxInit()",
    "name: 'postfx',",
    "stateKey: 'postprocessing',",
    # defaultModes -- postfx renderer wiring applies in EVERY mode; the
    # editor UI is gated separately by the drawer's HudLayer registration.
    "defaultModes: ['author', 'user', 'embed'],",
    # Required lifecycle hooks
    "mount: function (overlay, hud, interaction, modes)",
    "unmount: function ()",
    "getDirtyState: function ()",
    "markClean: function ()",
    "renderSceneSettings: function (parentEl)",
    # Registration with the Phase-2 coordinator
    "EditorModuleRegistry.register(postfxModule);",
)


def test_postfx_module_contract_markers_present():
    """The rendered viewer HTML carries every EditorModule-contract marker
    that the spec §4.X + R6 + the Phase 2 registry require."""
    html = _rendered_html()
    for mk in _CONTRACT_MARKERS:
        assert mk in html, f"PostFXModule contract marker missing: {mk!r}"


def test_postfx_module_does_not_modify_07_setup_three_spark():
    """Per R6: modules own their own THREE setup via ``mount()``. The
    PostFXModule MUST capture ``renderer`` via the IIFE scope from
    15e's ``mount()``, NOT by editing 07_setup_three_spark to expose it.
    We pin the IIFE-scope capture: ``if (typeof renderer !== 'undefined'
    && renderer) _renderer = renderer;`` is the canonical phrasing."""
    html = _rendered_html()
    # The canonical capture line.
    assert "if (typeof renderer !== 'undefined' && renderer) _renderer = renderer;" in html, (
        "PostFXModule must capture the THREE.WebGLRenderer from the "
        "IIFE-scoped `renderer` const set up in 07_setup_three_spark -- "
        "per R6, modules own their own THREE setup via mount() and MUST "
        "NOT modify 07_setup_three_spark to wire a separate hook."
    )
    # Negative: 07_setup_three_spark must not contain any postfx-module
    # wiring. The existing ``_TONEMAP`` dict + ``renderer.toneMapping``
    # / ``renderer.toneMappingExposure`` assignments (the schema's
    # pre-existing renderer side) remain UNCHANGED -- Phase 4 only adds
    # the edit-time control surface.
    setup_frag = (
        Path(__file__).parent.parent / "src" / "splatpipe" / "viewers" /
        "spark" / "template_parts" / "07_setup_three_spark.js_tmpl"
    ).read_text(encoding="utf-8")
    # Belt-and-braces: 07 still wires the renderer; PostFXModule cannot
    # be referenced from 07 (it lives in 15e).
    assert "PostFXModule" not in setup_frag, (
        "07_setup_three_spark.js_tmpl must NOT reference PostFXModule "
        "(Phase 4 only adds the edit-time surface; the renderer wiring "
        "already exists in 07 -- modules-own-their-THREE-setup R6)."
    )
    # 07's existing wiring must remain intact (the pre-existing render
    # path that Phase 4 builds atop).
    assert "renderer.toneMapping = _TONEMAP[" in setup_frag, (
        "07_setup_three_spark.js_tmpl must still wire renderer.toneMapping"
    )
    assert "renderer.toneMappingExposure = cfg.postprocessing?.exposure ?? 1.5;" in setup_frag, (
        "07_setup_three_spark.js_tmpl must still wire renderer.toneMappingExposure"
    )


# --------------------------------------------------------------------------
# (c) THREE.js render integration -- re-apply preserves 07 setup semantics
# --------------------------------------------------------------------------

# The PostFXModule's _reapply() mirrors the same _TONEMAP dict shape that
# 07_setup_three_spark uses. It's redeclared inside the IIFE (not shared
# with 07's _TONEMAP -- the closure barrier means we cannot reach 07's
# constant; redeclaring keeps the module self-contained per R6) and the
# same five tonemap keys are accepted.
_THREE_INTEGRATION_MARKERS = (
    # The five accepted tonemap presets (must match 07_setup_three_spark
    # so re-applying produces byte-identical THREE behaviour).
    "linear: THREE.LinearToneMapping",
    "neutral: THREE.NeutralToneMapping",
    "aces: THREE.ACESFilmicToneMapping",
    "aces2: THREE.ACESFilmicToneMapping",
    "filmic: THREE.AgXToneMapping",
    # The two renderer fields we write.
    "_renderer.toneMapping",
    "_renderer.toneMappingExposure",
    # The default-fallback for an unknown tonemap key -- mirrors 07's
    # default of NeutralToneMapping (with NoToneMapping as the
    # secondary fallback for old THREE.js builds, same as 07).
    "THREE.NeutralToneMapping",
)


def test_postfx_three_integration_markers_present():
    """The PostFXModule re-applies the same renderer.toneMapping +
    toneMappingExposure that 07_setup_three_spark wires once at init.
    It uses the same _TONEMAP key set so the runtime apply is
    byte-identical to 07's initial wiring."""
    html = _rendered_html()
    for mk in _THREE_INTEGRATION_MARKERS:
        assert mk in html, f"THREE integration marker missing: {mk!r}"


# --------------------------------------------------------------------------
# (d) Editor UI: tonemap dropdown + exposure slider + tooltip
# --------------------------------------------------------------------------

_UI_MARKERS = (
    # CSS class names per task spec
    "pfx-controls",
    "pfx-tm",
    "pfx-ex",
    "pfx-ex-val",
    # Tonemap dropdown options (each present as an <option value="X"> with
    # a human label -- we lock both the option values and the display labels)
    "value=\"linear\"",
    "value=\"neutral\"",
    "value=\"aces\"",
    "value=\"aces2\"",
    "value=\"filmic\"",
    # Exposure slider range (0.5..4.0, step 0.05, default 1.5)
    "exSlider.min = '0.5';",
    "exSlider.max = '4';",
    "exSlider.step = '0.05';",
)


def test_postfx_editor_ui_markers_present():
    """The drawer-rendered UI has the tonemap dropdown (5 options),
    the exposure slider (0.5..4.0, step 0.05), and a tooltip explaining
    why splats are pre-lit. All wired off the documented class names
    so the harness can drive them."""
    html = _rendered_html()
    for mk in _UI_MARKERS:
        assert mk in html, f"editor UI marker missing: {mk!r}"


def test_postfx_default_exposure_is_one_point_five():
    """The default exposure value is ``1.5`` -- matches the cfg default
    in 06_cfg.js_tmpl + the renderer's existing 07_setup fallback. The
    slider's ``value`` attribute is bound to ``cfg.postprocessing.exposure``
    so a fresh boot with the default cfg shows ``1.5``."""
    html = _rendered_html()
    # The default exposure is read into the JS code via the cfg defaults
    # (06_cfg.js_tmpl). We pin the cfg default + assert the module
    # consumes ``cfg.postprocessing.exposure ?? 1.5`` as its fallback.
    assert "exposure: 1.5" in html, "cfg.postprocessing.exposure default 1.5"
    # The module's fallback when the cfg slot is missing -- matches 07's
    # fallback (`?? 1.5`).
    assert "exposure ?? 1.5" in html or "exposure || 1.5" in html, (
        "PostFXModule must default to exposure 1.5 when the cfg slot is missing"
    )


# --------------------------------------------------------------------------
# (e) Gesture-end snapshot push (R8 §4.2)
# --------------------------------------------------------------------------

# The PostFXModule pushes EditHistory snapshots ONCE per gesture
# (gesture-start convention), NEVER per-frame during a slider drag.
# Spec markers: pushUndo with the gesture label, on pointerdown (start)
# for the slider, on change (commit) for the dropdown.
_GESTURE_END_MARKERS = (
    # Labels per gesture
    "'postfx-tonemap'",
    "'postfx-exposure'",
    # pushUndo (the registry-delegated history push)
    "EditorModuleRegistry.pushUndo(",
    # Slider gesture-start binding (pointerdown -- NOT every input frame)
    "exSlider.addEventListener('pointerdown'",
)


def test_postfx_gesture_end_snapshot_push():
    """Every UI gesture pushes ONE EditHistory snapshot at gesture
    start (pointerdown for the slider, change for the dropdown).
    Per R8 §4.2 -- a per-frame snapshot would yield 60 entries/s
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
    bad = "exSlider.addEventListener('input', function () {"
    i = html.find(bad)
    if i > 0:
        # The 'input' handler body must NOT contain pushUndo (gesture-end
        # contract). Find the closing of the function -- a simple
        # heuristic: the next "addEventListener" call closes this block.
        end = html.find("addEventListener", i + len(bad))
        block = html[i:end] if end > 0 else html[i:i + 600]
        assert "pushUndo" not in block, (
            "exSlider 'input' handler must not call pushUndo (R8 §4.2 -- "
            "per-frame snapshots are forbidden; commit via pointerdown + "
            "change/blur)."
        )


# --------------------------------------------------------------------------
# (f) Scene Settings drawer integration (Phase 2D coupling)
# --------------------------------------------------------------------------


def test_postfx_attaches_to_scene_settings_drawer():
    """The PostFXModule renders inside the Scene Settings drawer
    placeholder section that 17b builds. The hook contract is via
    ``renderSceneSettings(parentEl)`` (the registry's optional hook,
    invoked from 17b's 'register' listener). The module also self-attaches
    via setTimeout(0) because 15e registers BEFORE 17b wires its
    listener (fragment-order 15e < 17b -- mirrors the 15b PanoramaModule
    pattern)."""
    html = _rendered_html()
    # The drawer placeholder section the module targets.
    assert "data-section=\"postfx\"" in html or "data-section='postfx'" in html, (
        "drawer placeholder section <details data-section=\"postfx\"> must "
        "exist (built by 17b's _SS_PLACEHOLDER_ORDER)"
    )
    # The DOM query the module uses to locate the placeholder.
    assert "details[data-section=\"postfx\"]" in html, (
        "PostFXModule must query the drawer for the postfx section by "
        "its documented data-section selector"
    )
    # The replacement target inside the placeholder (17b emits one of
    # these per section).
    assert ".spcp-scene-settings-section-body" in html, (
        "PostFXModule must locate the placeholder's body element by the "
        "class 17b uses (.spcp-scene-settings-section-body)"
    )
    # The setTimeout self-attach is the documented workaround for the
    # 15e-before-17b ordering -- it MUST be wired, otherwise the drawer
    # section never gets the real controls.
    assert "setTimeout(_attachToDrawer, 0)" in html, (
        "PostFXModule must schedule a setTimeout(_attachToDrawer, 0) "
        "from mount() so the drawer-section replacement runs AFTER 17b's "
        "IIFE has built the placeholders (mirrors the 15b Panorama "
        "pattern; 17b is Phase 2-owned and cannot be modified to add "
        "its own catch-up walk)."
    )


# --------------------------------------------------------------------------
# (g) Tooltip (per spec §4.X "splats are pre-lit from training")
# --------------------------------------------------------------------------


def test_postfx_tooltip_documents_splat_pre_lighting():
    """Per spec §4.X + §4.5 + R7 the editor MUST tell authors that
    post-fx affects the panorama backdrop only (splats are pre-lit
    from training data; the renderer toneMapping value runs at the
    framebuffer composite step, but every splat pixel was baked at
    training-time and is essentially unchanged by tonemap re-route)."""
    html = _rendered_html()
    # The tooltip text per the task spec verbatim.
    assert "Lighting affects the panorama background only." in html, (
        "PostFXModule tooltip must explain that lighting affects the "
        "panorama background only (spec §4.X)."
    )
    assert "Splats are pre-lit from training." in html, (
        "PostFXModule tooltip must explicitly state splats are pre-lit "
        "from training data (spec §4.X + R7 -- the same rationale as "
        "§3.3 R7 in the PanoramaModule tooltip)."
    )


# --------------------------------------------------------------------------
# (h) Test surface for the harness (window.__editor.postfxModule)
# --------------------------------------------------------------------------


def test_postfx_test_surface_present():
    """The module exposes its instance + a couple of getters at
    ``window.__editor.postfxModule`` (merged onto the existing
    test surface by the registry's testSurface auto-merge -- see 04a)."""
    html = _rendered_html()
    # The testSurface object the registry merges onto window.__editor.
    assert "testSurface: {" in html, (
        "PostFXModule must declare a testSurface for window.__editor"
    )
    assert "get postfxModule()" in html, (
        "testSurface must expose the postfxModule instance"
    )
    assert "get postfxDirty()" in html, (
        "testSurface must expose a postfxDirty getter for the harness"
    )


# --------------------------------------------------------------------------
# (i) No timeline lane -- post-fx is scene-global, not animatable
# --------------------------------------------------------------------------


def test_postfx_has_no_timeline_lane():
    """Per spec §4.X, post-fx is scene-global -- it does NOT contribute
    a lane to the multi-lane bottom-timeline registry. The module's
    ``timelineLane`` field must be ``null`` (or omitted; the registry
    tolerates either) so 16's _tlLaneRegister skips it."""
    html = _rendered_html()
    # The module declares ``timelineLane: null`` explicitly so the
    # contract is unambiguous (Phase 2D's registry filter skips both
    # null and missing).
    assert "timelineLane: null," in html, (
        "PostFXModule must explicitly declare timelineLane: null -- "
        "post-fx is scene-global and not animatable in v1."
    )


# --------------------------------------------------------------------------
# (j) Python-side allow-list: postprocessing in ALLOWED_PATCH_KEYS
# --------------------------------------------------------------------------


def test_postprocessing_is_in_allowed_patch_keys():
    """The editor save path (merge_camera_scope -> server-side merge) MUST
    accept a ``postprocessing`` patch slot, otherwise the PostFXModule's
    edits would be silently dropped on save. The shared core in
    ``splatpipe.core.config_merge`` is the SINGLE source of truth for
    the allow-list (the CLI relay + every save-backend share it)."""
    from splatpipe.core.config_merge import ALLOWED_PATCH_KEYS
    assert "postprocessing" in ALLOWED_PATCH_KEYS, (
        "core/config_merge.ALLOWED_PATCH_KEYS must include 'postprocessing' "
        "so the PostFXModule's edits survive the merge."
    )


def test_postprocessing_patch_whole_replaces_and_primary_asset_force_keep():
    """A postprocessing patch wholesale-replaces the existing block
    (no deep merge -- same contract as every other allow-listed key).
    The locked ``primary_asset`` force-keep invariant (the
    "Speicher-blank" production-failure class) still holds when
    postprocessing rides in the same patch.
    """
    from splatpipe.core.config_merge import merge_camera_scope

    existing = {
        "primary_asset": "bKEEP/scene.rad",
        "postprocessing": {"tonemapping": "neutral", "exposure": 1.5,
                           "stale_subkey": "must_be_dropped_by_whole_replace"},
        "start_view": {"pos": [1, 2, 3]},
    }
    patch = {
        "postprocessing": {"tonemapping": "aces", "exposure": 2.4},
        "primary_asset": "EVIL/attacker.rad",   # must NEVER be applied
    }
    out = merge_camera_scope(existing, patch)
    # Whole-replace: the stale_subkey is gone, not deep-merged in.
    assert out["postprocessing"] == {"tonemapping": "aces", "exposure": 2.4}
    assert "stale_subkey" not in out["postprocessing"]
    # LOCKED INVARIANT: pointer is always existing's, never the patch's.
    assert out["primary_asset"] == "bKEEP/scene.rad"
    # Untouched siblings preserved.
    assert out["start_view"] == {"pos": [1, 2, 3]}


def test_postprocessing_was_already_in_public_viewer_config_keys():
    """``postprocessing`` is already in PUBLIC_VIEWER_CONFIG_KEYS (the
    publish_scene sanitiser's allow-list) -- no #122 change needed. We
    pin its presence so a future refactor doesn't drop it (which would
    silently strip the slot from every published viewer-config.json)."""
    from splatpipe.core.config_safety import PUBLIC_VIEWER_CONFIG_KEYS
    assert "postprocessing" in PUBLIC_VIEWER_CONFIG_KEYS, (
        "core/config_safety.PUBLIC_VIEWER_CONFIG_KEYS must include "
        "'postprocessing' so publish_scene's sanitiser passes it through "
        "to the public viewer-config.json."
    )
