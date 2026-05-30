"""openContextMenu primitive + right-click surface wiring (R2 Batch E2 #156).

The editor gained ONE reusable right-click context-menu primitive,
``openContextMenu(x, y, items, opts)``, in a new early fragment
``viewers/spark/template_parts/04b_context_menu.js_tmpl`` (a [role=menu]
popup of [role=menuitem] .quality-btn buttons, viewport-clamped, closed
by capture-phase outside-click / Escape / scroll / resize / item-select
with all listeners removed on close, single-instance, coordinated with
the modal cards via ``_closeAllEditorOverlays``, keyboard nav). It is
wired (all author-gated) to five surfaces: the bottom-timeline diamond
(16), the 3D keyframe frusta (17), the camera dropdown (10), and the
annotation (15c) / title (15g) / clip (15d) drawer rows.

These tests mirror ``test_intro_startview_modules.py``: STATIC
rendered-HTML markers (the primitive's contract surface + each
surface's contextmenu wiring + the preserved 08:223 non-author
suppressor) + a fragment-ordering / file-hygiene invariant. The dynamic
behaviour is covered by the live Playwright verification in the sprint
(see the CHANGELOG / output-pin entry); these locks catch a future
byte-inert refactor that drops a contract field.
"""

from __future__ import annotations

from pathlib import Path

from splatpipe.viewers.spark.template import html_for


# --------------------------------------------------------------------------
# The openContextMenu primitive (04b)
# --------------------------------------------------------------------------

_PRIMITIVE_MARKERS = (
    "//  openContextMenu -- the ONE reusable right-click menu primitive",
    "function openContextMenu(x, y, items, opts) {",
    "function _ctxCloseMenu() {",
    # The menu element is a real [role=menu] with [role=menuitem] buttons.
    "menu.setAttribute('role', 'menu');",
    "b.setAttribute('role', 'menuitem');",
    # Reuses the existing .quality-btn styling (no new CSS region).
    "b.className = 'quality-btn';",
    # Separator + danger + disabled item support.
    "if (it.separator) {",
    "it.danger ? 'color:#ff8a8a;'",
    "b.setAttribute('aria-disabled', 'true');",
    # Viewport clamp / flip.
    "if (left + mw > vw - 4)",
    "if (top + mh > vh - 4) {",
    # Single-instance + never-stack via the shared coordinator.
    "if (typeof _closeAllEditorOverlays === 'function') {",
    "_registerEditorOverlayCloser(_ctxCloseMenu);",
    # Lifecycle: capture-phase outside click + contextmenu, Escape +
    # arrow nav, scroll/resize/blur close. All removed on close.
    "document.addEventListener('click', _ctxOutsideHandler, true);",
    "document.addEventListener('contextmenu', _ctxOutsideHandler, true);",
    "document.addEventListener('keydown', _ctxKeyHandler, true);",
    "window.addEventListener('scroll', _ctxScrollHandler, true);",
    # Keyboard nav.
    "function _ctxFocusByOffset(delta) {",
    "if (e.key === 'ArrowDown') {",
    "if (e.key === 'ArrowUp') {",
    # z-index above the drawer/popover, below the modal cards.
    "z-index:62;",
    # Test surface.
    "window.__ctxMenu = {",
    "get isOpen() { return !!_ctxMenuEl; }",
)


def test_context_menu_primitive_markers_present_in_rendered_html():
    """The openContextMenu primitive + its full lifecycle contract render
    into the generated viewer HTML."""
    html = html_for("HarnessScene")
    for mk in _PRIMITIVE_MARKERS:
        assert mk in html, f"context-menu primitive marker missing: {mk!r}"


# --------------------------------------------------------------------------
# The five wired surfaces (all author-gated)
# --------------------------------------------------------------------------

_SURFACE_MARKERS = (
    # (1) Timeline diamond (16): contextmenu on the lane, hit-tested via
    #     _tlHitKf, opens Delete / flattened interp / Go to.
    "_tlLane.addEventListener('contextmenu', (ev) => {",
    "const ki = _tlHitKf(xy.x, xy.y);",
    "label: 'Delete keyframe',",
    "'Interp: ' + nm,",
    "label: 'Go to keyframe',",
    # (2) 3D frusta (17): contextmenu on the canvas reuses _gzPickFrustum
    #     + _gzAttach then the same items.
    "function _gzOnCanvasContextMenu(ev) {",
    "const idx = _gzPickFrustum(ev.clientX, ev.clientY);",
    "renderer.domElement.addEventListener(\n      'contextmenu', _gzOnCanvasContextMenu);",
    "function _gzDeleteKeyframe(idx) {",
    "function _gzGoToKeyframe(idx) {",
    # (3) Camera dropdown (10): contextmenu on #camera-select offers
    #     Rename / Set as default / Delete.
    "_camSel.addEventListener('contextmenu', (ev) => {",
    "function _camSelSetDefault() {",
    "label: 'Set as default',",
    # (4) Annotation rows (15c) + the fly-to helper.
    "row.addEventListener('contextmenu', (ev) => {",
    "function _ssGoToAnnotation(ann) {",
    # (5) Title rows (15g) + clip cards (15d).
    "function _ssGoToTitle(t3d) {",
    "card.addEventListener('contextmenu', (ev) => {",
    "label: 'Move earlier',",
)


def test_context_menu_surfaces_wired_in_rendered_html():
    """All five right-click surfaces wire the openContextMenu primitive."""
    html = html_for("HarnessScene")
    for mk in _SURFACE_MARKERS:
        assert mk in html, f"context-menu surface wiring missing: {mk!r}"


def test_canvas_contextmenu_suppressor_preserved_for_non_author():
    """The 08:223 ``canvas.addEventListener('contextmenu', ... preventDefault)``
    chokepoint is UNCHANGED -- it still suppresses the browser menu for
    every mode (the author menu in 17 is a SEPARATE listener)."""
    html = html_for("HarnessScene")
    assert "canvas.addEventListener('contextmenu', (e) => e.preventDefault());" in html


def test_context_menu_author_gated():
    """Each surface's contextmenu handler is author-gated -- a non-author /
    embed viewer never opens the editor menu. The timeline + camera +
    3D handlers all guard on ModeManager.is('author'); the drawer-row
    surfaces only exist in the author-only Scene Settings drawer."""
    html = html_for("HarnessScene")
    # The three canvas/chrome surfaces each gate explicitly.
    # Timeline lane contextmenu:
    tl = html.index("_tlLane.addEventListener('contextmenu', (ev) => {")
    assert "ModeManager.is('author')" in html[tl:tl + 200]
    # Camera dropdown contextmenu:
    cam = html.index("_camSel.addEventListener('contextmenu', (ev) => {")
    assert "ModeManager.is('author')" in html[cam:cam + 200]
    # 3D frustum contextmenu:
    gz = html.index("function _gzOnCanvasContextMenu(ev) {")
    assert "ModeManager.is('author')" in html[gz:gz + 200]


def test_context_menu_fragment_file_exists_and_clean():
    """The 04b fragment is on disk + free of BOM / CRLF."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    f = parts / "04b_context_menu.js_tmpl"
    assert f.exists(), f"missing fragment: {f}"
    raw = f.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "04b: BOM corruption"
    assert not raw.startswith(b"\xff\xfe"), "04b: UTF-16 BOM corruption"
    assert b"\r" not in raw, "04b: CRLF corruption"
    txt = raw.decode("utf-8")
    assert "function openContextMenu(" in txt
    assert "window.__ctxMenu" in txt


def test_context_menu_primitive_concatenates_after_prologue():
    """Fragment-ordering invariant: 04b (the primitive) must concatenate
    AFTER 04 (the prologue declaring ``_closeAllEditorOverlays`` /
    ``_registerEditorOverlayCloser`` it depends on) and BEFORE every
    surface that calls it (10/15c/15d/15g/16/17). The 04 < 04b < 10 < 15x
    < 16 < 17 lexical filename ordering enforces this in one shared
    <script type='module'> scope."""
    html = html_for("HarnessScene")
    prologue_i = html.index("function _closeAllEditorOverlays(except) {")
    primitive_i = html.index("function openContextMenu(x, y, items, opts) {")
    # First call site (the camera dropdown, fragment 10) comes after.
    camsel_i = html.index("_camSel.addEventListener('contextmenu', (ev) => {")
    gizmo_i = html.index("function _gzOnCanvasContextMenu(ev) {")
    assert prologue_i < primitive_i < camsel_i < gizmo_i, (
        "lexical ordering must be 04 (prologue) < 04b (primitive) < the "
        "wired surfaces so the primitive + its deps are hoisted before use"
    )
