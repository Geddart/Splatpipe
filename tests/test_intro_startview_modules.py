"""IntroModule + StartViewModule contract tests (Phase 11A Issue 9).

Two new editor module fragments shipped in the v0.8.0 UX bug-fix sprint
populate the last two placeholder sections of the Scene Settings drawer:

  * ``viewers/spark/template_parts/15h_intro_module.js_tmpl`` --
    IntroModule, the canonical owner of the ``cfg.intro`` stateKey. A
    type dropdown (fade | none) + ms numeric input in the drawer's
    "Intro" section. ``cfg.intro`` was already in
    :data:`splatpipe.core.config_merge.ALLOWED_PATCH_KEYS` /
    :data:`splatpipe.core.config_safety.PUBLIC_VIEWER_CONFIG_KEYS` so
    the SPCP1 patch carries the slot.

  * ``viewers/spark/template_parts/15i_startview_module.js_tmpl`` --
    StartViewModule, surfacing ``cfg.start_view`` in the drawer's
    "Start View" section. A "Save current camera as start view"
    button (calling the ``window.__editor.openStartViewCard`` helper
    that 18_frame_loop exposes after Phase 11A Issue 8 removed the
    top-bar #setstart-btn) + a read-only preview of the committed
    pos/target/fov.

These tests mirror ``test_titles_module.py`` / ``test_audio_module.py``:
STATIC rendered-HTML markers (the IIFE, the contract fields, the
registration call, the renderSceneSettings hook, the test surface, the
EditHistory snapshot labels) + a fragment-ordering / file-hygiene
invariant. The dynamic behaviour is covered by the live Playwright
verification in the sprint (see the CHANGELOG entry); these locks catch
a future byte-inert refactor that drops a contract field.
"""

from __future__ import annotations

from pathlib import Path

from splatpipe.viewers.spark.template import html_for

# --------------------------------------------------------------------------
# IntroModule (15h)
# --------------------------------------------------------------------------

_INTRO_MARKERS = (
    "//  IntroModule (Phase 11A Issue 9 -- editor-arc-design #122)",
    "(function _introModInit() {",
    "name: 'intro',",
    "stateKey: 'intro',",
    "defaultModes: ['author'],",
    "mount: function (overlay, hud, interaction, modes) {",
    "unmount: function () {",
    "getDirtyState: function () {",
    "markClean: function () {",
    "onCfgChange: function (prev, next, stateKey) {",
    "renderSceneSettings: function (parentEl) {",
    # The IntroDict defaults mirror core/scene_cuts.DEFAULT_INTRO
    "const _INTRO_DEFAULTS = { type: 'fade', ms: 900 };",
    # The type dropdown + ms input controls
    "function _writeType(next) {",
    "function _writeMs(next) {",
    # EditHistory snapshot labels (ONE per gesture)
    "'intro-type'",
    "'intro-ms'",
    # The placeholder section it populates
    "details[data-section=\"intro\"]",
    # Test surface (functions, NOT getters)
    "introGet() { return introModule; }",
    "introSetType(v) { return _writeType(v); }",
    "introSetMs(v) { return _writeMs(v); }",
    # Registration
    "EditorModuleRegistry.register(introModule);",
)

# --------------------------------------------------------------------------
# StartViewModule (15i)
# --------------------------------------------------------------------------

_STARTVIEW_MARKERS = (
    "//  StartViewModule (Phase 11A Issue 9 -- editor-arc-design #122)",
    "(function _svModInit() {",
    "name: 'start_view',",
    "stateKey: 'start_view',",
    "defaultModes: ['author'],",
    "mount: function (overlay, hud, interaction, modes) {",
    "unmount: function () {",
    "getDirtyState: function () {",
    "markClean: function () {",
    "renderSceneSettings: function (parentEl) {",
    # The "Save current as start view" button calls the 18_frame_loop
    # helper exposed by Issue 8.
    "window.__editor.openStartViewCard",
    "id = 'sv-mod-save-btn'",
    "id = 'sv-mod-preview'",
    # The placeholder section it populates
    "details[data-section=\"startview\"]",
    # Test surface
    "startViewGet() { return startViewModule; }",
    "startViewSaveBtnEl() { return _saveBtn; }",
    "startViewPreviewText()",
    # Registration
    "EditorModuleRegistry.register(startViewModule);",
)


def test_intro_module_markers_present_in_rendered_html():
    """The IntroModule IIFE + registration + contract fields render."""
    html = html_for("HarnessScene")
    for mk in _INTRO_MARKERS:
        assert mk in html, f"IntroModule marker missing: {mk!r}"


def test_startview_module_markers_present_in_rendered_html():
    """The StartViewModule IIFE + registration + contract fields render."""
    html = html_for("HarnessScene")
    for mk in _STARTVIEW_MARKERS:
        assert mk in html, f"StartViewModule marker missing: {mk!r}"


def test_intro_startview_fragment_files_exist_and_clean():
    """The 15h + 15i fragments are on disk + free of BOM / CRLF."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    for fname, mod_tok, reg_tok in (
        ("15h_intro_module.js_tmpl", "IntroModule",
         "EditorModuleRegistry.register(introModule)"),
        ("15i_startview_module.js_tmpl", "StartViewModule",
         "EditorModuleRegistry.register(startViewModule)"),
    ):
        f = parts / fname
        assert f.exists(), f"missing fragment: {f}"
        raw = f.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{fname}: BOM corruption"
        assert b"\r" not in raw, f"{fname}: CRLF corruption"
        txt = raw.decode("utf-8")
        assert mod_tok in txt
        assert reg_tok in txt


def test_intro_startview_concatenate_after_15a_before_17b():
    """Fragment-ordering invariant: 15h (Intro) + 15i (StartView) must
    concatenate AFTER 15a (CameraPathModule) and BEFORE 17b (the Scene
    Settings drawer scaffold whose placeholder sections they populate).
    The 15a < 15h < 15i < 17b lexical ordering enforces this. The
    modules' `setTimeout(_attachToDrawer, 0)` from mount() runs after
    17b's synchronous IIFE builds the placeholders."""
    html = html_for("HarnessScene")
    cam_i = html.index(
        "//  CameraPathModule (Phase 2B -- editor-arc-design"
    )
    intro_i = html.index(
        "//  IntroModule (Phase 11A Issue 9 -- editor-arc-design"
    )
    sv_i = html.index(
        "//  StartViewModule (Phase 11A Issue 9 -- editor-arc-design"
    )
    drawer_i = html.index(
        "//  Scene Settings drawer scaffold (Phase 2D"
    )
    assert cam_i < intro_i < sv_i < drawer_i, (
        "lexical ordering must be 15a < 15h < 15i < 17b so the modules' "
        "setTimeout(_attachToDrawer, 0) populates the 17b placeholders"
    )


def test_intro_startview_dont_touch_contested_fragments():
    """Phase 11A Issue 9 invariant: the two new modules own ONLY their
    own fragments. The contested fragments (06_cfg / 07_setup /
    08_input / 11_clip_player / 17a) must contain zero references to
    the new module symbols."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    for fname in (
        "06_cfg.js_tmpl",
        "07_setup_three_spark.js_tmpl",
        "08_input.js_tmpl",
        "11_clip_player.js_tmpl",
        "17a_edit_history.js_tmpl",
    ):
        f = parts / fname
        assert f.exists(), f"contested fragment missing: {f}"
        txt = f.read_text(encoding="utf-8")
        for tok in (
            "IntroModule", "_introModInit", "introModule",
            "StartViewModule", "_svModInit", "startViewModule",
        ):
            assert tok not in txt, (
                f"contested fragment {fname!r} should NOT reference "
                f"{tok!r} -- Phase 11A Issue 9 owns 15h/15i only"
            )


def test_startview_uses_openstartviewcard_helper_from_frame_loop():
    """The StartViewModule's save button delegates to
    window.__editor.openStartViewCard -- the helper 18_frame_loop
    exposes after Phase 11A Issue 8 removed the top-bar #setstart-btn.
    The frame loop must define + expose it."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    frame = (parts / "18_frame_loop.js_tmpl").read_text(encoding="utf-8")
    assert "function _openStartViewCard()" in frame, (
        "18_frame_loop must define the named _openStartViewCard helper"
    )
    assert "window.__editor.openStartViewCard = _openStartViewCard" in frame, (
        "18_frame_loop must expose openStartViewCard on window.__editor"
    )
    # The top-bar button is REMOVED (Issue 8).
    body_chrome = (parts / "03_body_chrome.html_tmpl").read_text(
        encoding="utf-8"
    )
    assert 'id="setstart-btn"' not in body_chrome, (
        "the top-bar #setstart-btn must be removed (Phase 11A Issue 8)"
    )
