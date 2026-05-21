"""Output-pin byte-lock for the Spark viewer template.

Added 2026-05-20 as the modularization-safe successor to the (now-retired)
excised-region source-level byte-lock in ``test_html_for_save_mode.py``.

GOAL: pin ``(length, sha256)`` of ``html_for(...)`` output for a corpus of
representative scene fixtures so the refactor (#118) -- which moved the
viewer body from a single 9.6k-line Python format string into
``viewers/spark/template_parts/`` fragment files assembled by an
``@@NAME@@`` orchestrator -- is provably byte-identical for every fixture,
and any future template change that should be byte-inert (e.g. a code
move that should preserve generated HTML) is locked here.

CORPUS DESIGN (6 fixtures, all kwargs branches of ``html_for``):

  * ``harness_defaults``       -- the same fixture the retired excised-region
                                  lock covered (defaults: cli + empty endpoint).
  * ``http_basic``             -- http save_mode + real endpoint.
  * ``http_endpoint_quotes``   -- endpoint with embedded quotes (JSON escape).
  * ``none_endpoint``          -- save_endpoint=None serialises to "".
  * ``sog_fallback``           -- primary_asset=scene.sog + paged=False.
  * ``share_card``             -- all three share-card kwargs supplied
                                  (share_url + share_image + description).

EXPECTED VALUES (length + sha256) were captured against the pre-refactor
``template.py`` at HEAD ``f46fa67`` (the commit before T1 landed; see the
v2 plan at
``docs/superpowers/plans/2026-05-20-modularize-spark-viewer-template-v2.md``).
T1's verification step asserted ALL 6 fixtures produce byte-identical
output from the orchestrator + fragments.

WHEN TO UPDATE THE PINS: only when a DELIBERATE generated-HTML change is
made (a real feature edit). Then update both the length and the sha256
in lockstep. Do NOT update for a "byte-inert" refactor -- that's exactly
the change this test should catch.

PIN UPDATES:
  * 2026-05-20 (UX-5): user-reported regression in the live ?author=1
    editor on kf-fehmarn -- "<2-keyframe path is unscrub-able + record
    overwrites at t=0". The fix in 10_camera_select / 17_editor_gizmo
    fragments deliberately changes the generated HTML (lifts the
    stale-player stop + controls re-enable OUT of the snap block in
    ``_camSelApply``, adds a ``_GZ_DEFAULT_KF_DT`` constant in the K
    recorder for the 1-kf -> 2-kf bridge, and rewords the
    ``startPath`` <2-kf alert). All 6 fixtures shifted by the same
    +4383 byte delta in lockstep; pins updated to the new baseline.
  * 2026-05-20 (Phase 1 Q5): #author=<secret> -> #token=<token> URL
    fragment param rename (decouples the bearer name from the
    ?author=1 mode flag). The fragment parser ``_gzAuthorSecret()``
    was renamed to ``_gzReadAuthToken()`` with a backwards-compat
    branch that still reads ``#author=`` and ``console.warn``s. The
    Save body shape was also corrected to ``{slug, ...patch}`` (flat
    top-level, matching the PHP adapter wire contract) from the prior
    ``{slug, patch}`` wrapper that was wrong for the live PHP
    round-trip. All 6 fixtures shifted by the same +1408 byte delta
    in lockstep; pins re-pinned to the new baseline.
  * 2026-05-20 (Phase 1 live-verify): ``_gzSlug`` is now lower-cased
    before the character-class sanitiser strips non-``[a-z0-9_-]``
    chars. The mixed-case display name "Fehmarn" was being sent as
    the slug to ``save-camera.php`` which validates with
    ``^[a-z0-9_-]{1,64}$`` -- so every http-mode Save 400'd with
    "invalid slug". Caught by the Phase-1 live-verify against the
    deployed ``fehmarn`` slug. The fix lower-cases the H1 text first
    so the JS slug matches the canonical Bunny CDN convention (which
    is itself lowercase). SPCP1's ``encode_spcp`` is case-tolerant,
    so the cli-mode token continues to work; only http-mode was
    broken. All 6 fixtures shifted by the same +430 byte delta in
    lockstep; pins re-pinned to the new baseline.
  * 2026-05-20 (#123 hot-fix): the ``startPath`` <2-keyframe alert
    is now a silent ``console.warn`` + early-return (user feedback:
    the modal interrupted the authoring loop). Identical behaviour
    other than the suppressed alert. All 6 fixtures shifted by the
    same -16 byte delta in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 2A #122): new ``EditorModuleRegistry`` (04a)
    and ``EditHistory`` (17a) fragments concatenated into the bundle,
    plus the ``05_framework`` wiring patch that exposes them at
    ``window.__sceneview.modules`` / ``.history`` and the keydown
    hotkey wiring (Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z) at the tail of
    17a. All 6 fixtures shifted by the same +23616 byte delta in
    lockstep; pins re-pinned to the new baseline.
  * 2026-05-21 (Phase 2B #122): new ``CameraPathModule`` thin-wrapper
    fragment (15a) that registers with the EditorModuleRegistry as the
    canonical owner of the ``camera_paths`` slot, plus the
    ``17_editor_gizmo`` ``_buildPatch`` refactor that overlays
    ``EditorModuleRegistry.collectPatch()`` over the legacy
    ``_PATCH_KEYS`` walk (registered module slots WIN over legacy
    duplicates; an empty registry is a clean fallback to legacy). All
    6 fixtures shifted by the same +9515 byte delta in lockstep; pins
    re-pinned to the new baseline.
  * 2026-05-21 (Phase 2C #122 §3.7 + §4.1.1): three timeline addenda
    in ``16_editor_timeline.js_tmpl`` -- (1) total-time numeric input
    + auto toggle (writes ``path.total_duration_s``; one EditHistory
    snapshot on commit, never per keystroke); (2) Prev/Next-keyframe
    skip buttons (navigation, no snapshot); (3) Ctrl+Left / Ctrl+Right
    hotkeys (NAVIGATION; same author-mode gate + text-input skip
    pattern the 17a Ctrl+Z handler uses). Plus the JS mirror of the
    Python ``effective_scrub_range`` helper. All 6 fixtures shifted by
    the same +10141 byte delta in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 2D #122 §12 + §4.10): new ``17b`` Scene Settings
    drawer scaffold (one HudLayer panel + cog toggle + sessionStorage
    persistence + 6 placeholder sections in registration order) plus
    a multi-lane timeline registry in ``16`` (infrastructure only;
    CameraPathModule's lane auto-registered via the EditorModuleRegistry
    'register' event). All 6 fixtures shifted by the same +16029 byte
    delta in lockstep; pins re-pinned.
  * 2026-05-21 (Phases 3-8 integration #122): six new editor module
    fragments concatenated into the bundle in one integration pass --
    PanoramaModule (equirect backdrop + rotation + intensity),
    PostFXModule (tonemapping + exposure sliders), AnnotationModule
    (dot_unfold + animatable + distance), CutsModule (edit-time NLE
    wrapping ClipPlayer), AudioModule (track CRUD + edit-time UI),
    TitlesModule (CSS2D renderer + editor for titles3d). Each phase
    deselected this output-pin during its individual commit to avoid
    double-baselining; this pin update re-baselines all 6 fixtures in
    ONE integration pass. All 6 fixtures shifted by the same +180878
    byte delta in lockstep -- perfect proof the module additions are
    additive only (no spooky-action elsewhere). Pins re-pinned to the
    new baseline.
  * 2026-05-21 (Phase 11A Issues 1+2): two UX fixes in the
    Perspective / camera-switch hot path. (1) ``_camSelApply``'s
    Perspective branch now UNCONDITIONALLY re-enables OrbitControls
    and clears any paused-scrub state -- the prior conditional
    re-enable only fired when ``_player`` was truthy, so a
    scrub-then-Perspective workflow left the controls dead and the
    user could not orbit-drag. (2) ``_trajActivePath`` (author
    mode, Perspective) now prefers paths with >=2 keyframes over an
    empty kf path in its fallback walk, so the trajectory overlay
    stays visible when the last-bound camera was a freshly-added
    empty one. Both regions are interior to existing T16-TRAJ-via-
    10-camera-select / T16-TRAJ excisions. All 6 fixtures shifted
    by the same +2720 byte delta in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11A Issue 6): ``total_duration_s`` now lifts
    the player + timeline ``duration`` past the last keyframe. The
    Phase 2C total-time UI wrote ``path.total_duration_s`` but only
    the Prev/Next ceiling consulted it; the scrub slider still
    mapped to ``_player.duration = last_kf_t``, so typing 40 s on a
    25 s kf range left the scrub stuck at 25. Fix in two places
    (one in ``09_playback_spline::buildPlayer`` where the player's
    ``duration`` is now ``max(kfDuration, total_duration_s)``;
    mirror in ``16_editor_timeline::_tlDuration`` so the strip
    ruler + playhead<->scrub mapping align with the player. Past
    the last knot the spline ``evaluate()`` clamp returns the last
    pose (09 line 30) -- the extension is a "hold at end" segment,
    safe + DCC-standard. All 6 fixtures shifted by the same +2091
    byte delta in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11A Issue 9 fixup): 17b now renders the drawer
    section for EVERY already-registered module, not just modules that
    register AFTER it. The 'register' listener only caught
    post-17b registrations, but every 15x module concatenates BEFORE
    17b -> 15c (Annotations) / 15d (Cuts) / 15g (Titles), which rely
    SOLELY on that listener (no own setTimeout self-attach), left their
    drawer sections as the "(Phase N) goes here" placeholder
    (user-reported: "the annotations ... that's all placeholders,
    right?"). Fix: after wiring the listener, ``17b`` walks
    ``EditorModuleRegistry.list()`` once + calls each module's
    ``renderSceneSettings`` (idempotent for the setTimeout-based
    modules). All 6 fixtures shifted by the same +1214 byte delta in
    lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11A Issue 3): EditHistory ``_restore`` no longer
    swaps out aliased array references. The undo/redo restore did a
    plain ``Object.assign(cfg, clone)`` which set ``cfg.camera_paths``
    to a NEW (cloned) array, leaving the ``const cameraPaths =
    cfg.camera_paths`` alias captured at init by 09_playback_spline
    (read by ``_camSelCameras`` / ``startPath`` / ``buildPlayer``)
    pointing at the STALE old array -> the camera dropdown lost /
    duplicated entries after an undo ("sometimes the Fehmarn cam is
    missing all of a sudden"). Fix in ``17a_edit_history::_restore``:
    for a known set of aliased array keys (camera_paths / cameras /
    clips / annotations / audio / titles3d) mutate the EXISTING array
    IN PLACE (length=0 + push the clone's elements) so the captured
    alias stays valid. Scoped DELIBERATELY to ``camera_paths`` only
    (the proven load-bearing const alias; cfg.cameras / audio /
    annotations / clips / titles3d are read live by their owner module
    so a restore that drops them must DELETE them per
    test_edit_history::test_restore_clears_keys_added_after_snapshot).
    ALSO wires ``10_camera_select::_camSelInit`` to rebuild the dropdown
    options on the EditHistory ``history:undo`` / ``history:redo``
    events (the in-place restore keeps the alias valid but the dropdown
    <option> list still needs a re-sync after the restored array's
    contents change). All 6 fixtures shifted by the same +5180 byte
    delta in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11A Issue 5): unified Play/Pause toggle. The
    separate timeline Pause button is REMOVED; ``_tlPlay`` is now a
    tri-state toggle (idle ▶ -> playing ⏸ -> paused ▶ -> resume).
    ``10_camera_select`` exposes ``window.__spTransport.{playState,
    playPauseToggle, pauseHere}`` (the pause reuses the EXISTING
    UX-3 ``_pausedAt``/``_pausedAtPlayer`` per-frame rebase; a pause
    freezes ``_player`` at the current playhead, NOT a stopPath);
    ``16_editor_timeline``'s ``_tlPlay`` click drives the toggle +
    syncs the glyph via ``_tlSyncPlayPauseIcon()`` (called from
    ``_tlSyncPlayhead`` so the icon follows the live state every
    frame, incl. a tour reaching its natural end). All 6 fixtures
    shifted by the same +6054 byte delta in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11A Issue 9): two new editor module fragments.
    ``15h_intro_module.js_tmpl`` (IntroModule -- type dropdown +
    ms input populating the Scene Settings drawer's Intro section)
    + ``15i_startview_module.js_tmpl`` (StartViewModule -- "Save
    current as start view" button calling
    ``window.__editor.openStartViewCard`` from the Issue 8 refactor,
    plus a read-only preview of cfg.start_view's pos/target/fov).
    Both modules use the standard 15a/15b/15f shape (mount sets
    ``setTimeout(_attachToDrawer, 0)``, ``renderSceneSettings`` is
    the fallback path) so the Scene Settings drawer's six
    placeholder sections finally populate end-to-end. All 6
    fixtures shifted by the same +19614 byte delta in lockstep;
    pins re-pinned.
  * 2026-05-21 (Phase 11A Issue 8): the top-bar "Set start view"
    button is REMOVED from ``03_body_chrome`` (it migrates to the
    Scene Settings drawer's Start View section in Phase 11A Issue
    9). The handler in ``18_frame_loop`` is now wired conditionally
    on ``#setstart-btn`` presence + exposes the open-card logic on
    ``window.__editor.openStartViewCard`` for the StartViewModule's
    "Save current as start view" button. Net byte delta is positive
    (the exposure helper + the comments add more than the removed
    button HTML): all 6 fixtures shifted by the same +1390 byte
    delta in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11A Issue 4): interp popover now applies to
    multi-selection. The V popover wrote only to the gizmo-selected
    kf; a box-select of 3 kfs followed by V + click was a no-op
    for kfs 2 and 3. Fix in ``17_editor_gizmo``:
    ``_gzSetInterp`` reads ``window.__editor.tlSelection`` (the
    Phase 2D timeline selection surface) and when it has >=2
    entries iterates over EVERY index, writing the chosen interp
    to each + pushes ONE ``EditorModuleRegistry.pushUndo('interp-
    multi')`` snapshot for the batch (R8 §4.2 anti-pattern: never
    per-target). Also ``_gzOpenPopover`` now opens when EITHER a
    gizmo target OR a multi-selection >= 2 exists (V on a box-
    select was a silent no-op before). All 6 fixtures shifted by
    the same +9027 byte delta in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11A Issue 7): Save button visible feedback.
    In http save mode the POST was silent (user clicked Save, no
    visible response, no idea if it succeeded). The cli mode at
    least pops up the token card; http had nothing. Fix in
    ``17_editor_gizmo::saveBtn`` handler: the button label +
    background now cycle Save -> Saving... -> OK Saved / Save
    failed -> Save (after 2 s). Driven by ``_gzSave()``'s return:
    cli mode (string token) flashes OK immediately, http mode
    (fetch Promise) flips OK on response.ok, Save failed on a
    non-ok status or fetch reject. All 6 fixtures shifted by the
    same +5389 byte delta in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11D H1): the Save dispatcher now calls
    ``EditorModuleRegistry.markAllClean()`` on a SUCCESSFUL save.
    A new guarded ``_gzMarkAllClean()`` helper in ``17_editor_gizmo``
    is invoked at the end of ``_gzSaveCli()`` (after the token is
    emitted) and on the 200-OK branch of ``_gzSaveHttp()`` (the
    fetch ``.then`` passes the response through UNCHANGED so the
    button-feedback chain is intact). NOT called on the error path
    (a failed save is still dirty, correctly). Without the call the
    modules stayed dirty forever -> every Save re-emitted the full
    payload. All 6 fixtures shifted by the same +1470 byte delta in
    lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11E UX-H3): panorama + audio file UPLOAD was
    DEAD on every deployed scene. The 15b PanoramaModule + 15f
    AudioModule file pickers POSTed to ``../upload-image`` /
    ``../upload-audio``, which only exist on the splatpipe web
    DASHBOARD (FastAPI) -- on a live Bunny CDN scene they 404
    silently. Fix: both modules now derive a SIBLING
    ``upload-asset.php`` endpoint from the baked SAVE_ENDPOINT (e.g.
    https://geddart.de/save-camera.php ->
    https://geddart.de/upload-asset.php) and POST the file there as
    multipart with the per-scene Bearer token (read from the
    ``#token=`` URL fragment, mirroring
    ``17_editor_gizmo::_gzReadAuthToken``) + the slug. cli-mode (no
    http endpoint) surfaces an actionable inline message; 401 / 413 /
    unsupported / network errors surface inline (NOT a silent
    console.warn). New per-IIFE helpers (_assetUploadEndpoint /
    _readAuthToken / _uploadSlug / _uploadAsset / _setStatus) + an
    inline status DOM line in each module. All 6 fixtures shifted by
    the same +13903 byte delta in lockstep (isolated to the 15b/15f
    edits; measured with any concurrent non-owned fragments held at
    HEAD) -- the change is additive only. Pins re-pinned.
  * 2026-05-21 (Phase 11F H5): EditHistory ``_broadcastCfgChange`` drops
    any active keyframe-gizmo selection on EVERY undo/redo. The Phase 11A
    Issue 3 in-place restore keeps ``cfg.camera_paths``'s array IDENTITY
    but REPLACES the keyframe OBJECTS inside it -- the gizmo
    (17_editor_gizmo TransformControls) stayed bound to a proxy parked at
    the pre-restore selected keyframe, so a drag after an undo wrote to a
    STALE proxy. Fix: ``17a_edit_history::_broadcastCfgChange`` calls the
    typeof-guarded ``window.__editor.gzDetach()`` (exposed by
    17_editor_gizmo) before the module-notify broadcast. All 6 fixtures
    shifted by the same +1249 code points in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11F H6): a SHARED ``_editorHotkeyBlocked()`` guard
    is added to ``04_js_prologue`` and routed into EVERY global editor
    keydown handler (08 WASD + H/F, 16 timeline X + Ctrl-arrows, 17 gizmo
    R/T/K/V/B/Space/Escape, 17a Ctrl+Z/Y). The handlers previously bailed
    only on INPUT/TEXTAREA/SELECT, so pressing K with the camera kebab
    (``[role=menu]``) button focused recorded a keyframe / X deleted one /
    V opened the interp popover behind the menu, and the H/F toggles had
    no guard at all. The shared helper SUPERSETS the old check and also
    blocks while a contenteditable or a ``[role=menu]``/``[role=dialog]``
    owns focus. All 6 fixtures shifted by the same +3056 code points in
    lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11F H7): the Save-camera card (#gz-save-overlay,
    17_editor_gizmo) + the Set-start-view card (#ss-overlay, 18_frame_loop)
    now (1) close on Escape via a ONE named window keydown listener
    attached on open + removed on close (no leak), (2) carry
    ``role="dialog"`` + ``tabindex="-1"`` + focus on open (so the H6 guard
    suppresses gizmo hotkeys behind them), (3) restore focus to the opener
    button on close, and (4) NEVER stack -- a new shared
    ``_closeAllEditorOverlays()`` coordinator in ``04_js_prologue`` closes
    the other card first (each card registers its idempotent closer). All
    6 fixtures shifted by the same +7025 code points in lockstep; pins
    re-pinned.
  * 2026-05-21 (Phase 11G WF-H2 #143): EditHistory undo off-by-one fix.
    The pre-gesture-snapshot convention (every module pushes ONE snapshot
    BEFORE its mutation; NO init-time baseline) was mismatched against
    ``canUndo()=`_cursor>1``` (so the FIRST edit, at cursor=1, was not
    undoable) and ``undo()`` restoring ``_stack[_cursor-2]`` (skipping the
    intermediate state). Fix in ``17a_edit_history``: ``canUndo`` is now
    ``_cursor>0``; ``undo`` lazily materialises the live (redo) head on the
    FIRST undo then steps back exactly one gesture restoring
    ``_stack[_cursor]``; ``canRedo`` is ``_cursor<length-1`` and ``redo``
    steps forward symmetrically; the ring cap is respected for the
    materialised head too. All 6 fixtures shifted by the same +2309 code
    points in lockstep; pins re-pinned.
"""

from __future__ import annotations

import hashlib

import pytest

from splatpipe.viewers.spark.template import html_for


# CORPUS: list of (name, args, kwargs, expected_len, expected_sha256).
# Pins captured 2026-05-20 at HEAD f46fa67 (before T1 of #118), then
# re-pinned 2026-05-20 (UX-5 fix; +4383 bytes in lockstep), then
# re-pinned 2026-05-20 again (Phase 1 Q5: #author= -> #token= rename +
# Save body shape correction; all 6 fixtures +1408 bytes in lockstep),
# then re-pinned 2026-05-20 a third time (Phase 1 live-verify slug
# lower-case fix; all 6 fixtures +430 bytes in lockstep), then re-pinned
# 2026-05-20 (#123 hot-fix: startPath empty-path alert -> silent
# console.warn; all 6 fixtures -16 bytes in lockstep), then re-pinned
# 2026-05-21 (Phase 2A #122: EditorModuleRegistry + EditHistory +
# framework wiring + Ctrl+Z hotkeys; all 6 fixtures +23616 bytes in
# lockstep), then re-pinned 2026-05-21 (Phase 2B #122: CameraPathModule
# 15a wrapper + Save dispatch via registry collectPatch; all 6 fixtures
# +9515 bytes in lockstep), then re-pinned 2026-05-21 (Phase 2C #122:
# 3 timeline addenda -- total-time UI, Prev/Next, Ctrl+Left/Right;
# all 6 fixtures +10141 bytes in lockstep), then re-pinned 2026-05-21
# (Phase 2D #122: Scene Settings 17b + multi-lane registry; all 6
# fixtures +16029 bytes in lockstep), then re-pinned 2026-05-21
# (Phases 3-8 integration #122: six editor module fragments --
# Panorama + PostFX + Annotations + Cuts + Audio + Titles3D -- all 6
# fixtures +180878 bytes in lockstep; modules are additive only), then
# re-pinned 2026-05-21 (Phase 11A Issues 1+2: Perspective controls
# re-enable + trajectory fallback skips empty paths; +2720 in lockstep),
# then re-pinned 2026-05-21 (Phase 11A Issue 6: total_duration_s now
# lifts player + timeline duration past last kf; +2091 in lockstep),
# then re-pinned 2026-05-21 (Phase 11A Issue 7: Save button visible
# feedback -- Saving.../OK Saved/Save failed states; +5389 in lockstep),
# then re-pinned 2026-05-21 (Phase 11A Issue 4: interp popover applies
# to multi-selection from the bottom timeline; +9027 in lockstep),
# then re-pinned 2026-05-21 (Phase 11A Issue 8: top-bar Set-start-view
# button removed + open-card helper exposed; +1390 in lockstep), then
# re-pinned 2026-05-21 (Phase 11A Issue 9: IntroModule 15h +
# StartViewModule 15i populate the drawer's last two placeholders;
# +19614 in lockstep), then re-pinned 2026-05-21 (Phase 11A Issue 5:
# unified Play/Pause toggle -- _tlPause removed, _tlPlay tri-state +
# window.__spTransport surface; +6054 in lockstep), then re-pinned
# 2026-05-21 (Phase 11A Issue 3: EditHistory _restore mutates the
# aliased camera_paths array in place + 10_camera_select rebuilds the
# dropdown on undo/redo so the dropdown survives undo; +5180), then
# re-pinned 2026-05-21 (Phase 11A Issue 9 fixup: 17b renders sections
# for already-registered modules so Annotations/Cuts/Titles populate;
# +1214 in lockstep), then re-pinned 2026-05-21 (Phase 11D H1: Save
# dispatcher calls EditorModuleRegistry.markAllClean() on success --
# _gzMarkAllClean() helper called from _gzSaveCli + _gzSaveHttp ok path;
# +1470 in lockstep), then re-pinned 2026-05-21 (Phase 11E UX-H3:
# panorama + audio upload POST to the derived upload-asset.php endpoint
# (was the dashboard-only ../upload-image|../upload-audio that 404'd on
# a live CDN scene) with a Bearer token + slug + inline error surface;
# +13903 in lockstep, isolated to the 15b/15f edits), then re-pinned
# 2026-05-21 (Phase 11D H2: 15c/15g pushUndo({label})->pushUndo(label)
# string fix + explanatory comments; +665 code points in lockstep over
# the 11E baseline), then re-pinned 2026-05-21 (Phase 11F H5: EditHistory
# _broadcastCfgChange drops the stale keyframe-gizmo selection on every
# undo/redo via window.__editor.gzDetach(); +1249 code points in lockstep),
# then re-pinned 2026-05-21 (Phase 11F H6: shared _editorHotkeyBlocked()
# guard in 04 routed into every global editor keydown handler so hotkeys
# do not fire with a [role=menu]/[role=dialog]/contenteditable focused;
# +3056 code points in lockstep), then re-pinned 2026-05-21 (Phase 11F H7:
# Save-camera + Set-start-view cards close on Escape (one-shot listener),
# carry role=dialog + focus, restore opener focus, and never stack via a
# shared _closeAllEditorOverlays() coordinator in 04; +7025 code points in
# lockstep). NOTE: expected_len counts len(html) CODE POINTS
# (Unicode scalar values), NOT UTF-8 bytes -- the assembled HTML carries
# multi-byte chars (em-dash, degree sign, etc.) so the byte length runs
# ~770 higher. Measure a re-pin with len(html), never len(html.encode()).
CORPUS: list[tuple[str, tuple, dict, int, str]] = [
    (
        "harness_defaults",
        ("HarnessScene",),
        {},
        788973,
        "11a5ad1bcd2005cb74bdefabdf033b802ddfe71190fb385c6716d4f7d4cc3fbd",
    ),
    (
        "http_basic",
        ("S",),
        {"save_mode": "http", "save_endpoint": "https://x.example/api/save"},
        788945,
        "5354ec5c0e9daf8b5deddd47998b928eaad5692ed230a537e38e057b50e560fc",
    ),
    (
        "http_endpoint_quotes",
        ("S",),
        {"save_endpoint": 'https://x/"+evil()+"'},
        788940,
        "047630ed90293e01f3fa6b178c1b7e8863d3a27177e9cfbc7d37ee38fd0f8ef3",
    ),
    (
        "none_endpoint",
        ("S",),
        {"save_mode": "http", "save_endpoint": None},
        788919,
        "b99e95d186940c49458049337c402bb57cc46e25f0928fa15e6fa94c17bd2991",
    ),
    (
        "sog_fallback",
        ("LegacySogScene",),
        {"primary_asset": "scene.sog", "paged": False},
        788984,
        "f2666bc5bd3a7ee7e98c2a3f7f7f771932e756c87ea94a8ad6906ceca199f46e",
    ),
    (
        "share_card",
        ("ShareScene",),
        {
            "share_url": "https://splatpipe-cdn.b-cdn.net/share/index.html",
            "share_image": "https://splatpipe-cdn.b-cdn.net/share/preview.jpg",
            "description": "Custom share description text.",
        },
        788843,
        "7afbf05c5f2aeb46ea3077f2810a41ff490c9df892cfb3b41feb8b7b84466984",
    ),
]


@pytest.mark.parametrize(
    "name,args,kwargs,expected_len,expected_sha",
    CORPUS,
    ids=[c[0] for c in CORPUS],
)
def test_output_pin(
    name: str,
    args: tuple,
    kwargs: dict,
    expected_len: int,
    expected_sha: str,
) -> None:
    """``html_for(*args, **kwargs)`` produces exactly ``expected_len`` code
    points (``len(html)``, NOT UTF-8 bytes) and ``expected_sha`` SHA-256 of
    the UTF-8 encoding. A drift here means the generated HTML has
    changed -- if that's deliberate, update the pin in CORPUS; if not,
    that's the regression this test exists to catch."""
    html = html_for(*args, **kwargs)
    actual_len = len(html)
    actual_sha = hashlib.sha256(html.encode("utf-8")).hexdigest()

    assert actual_len == expected_len, (
        f"[{name}] length drift: {actual_len} != {expected_len} "
        f"(delta {actual_len - expected_len:+d})"
    )
    assert actual_sha == expected_sha, (
        f"[{name}] sha256 drift: {actual_sha} != {expected_sha}"
    )


def test_corpus_count_sanity() -> None:
    """A floor on the corpus size so a future edit can't silently drop
    fixtures and have the byte-lock effectively disappear."""
    assert len(CORPUS) >= 4, (
        f"corpus drop-detection: only {len(CORPUS)} fixtures "
        f"(expected >=4 to cover the kwarg branches)"
    )


def test_no_bom_in_fragments() -> None:
    """Fragment files must be UTF-8 with no BOM and LF line endings.
    A Windows tool that wrote a BOM or CRLF would shift the output SHA;
    catch it here rather than at the output-pin level (clearer cause)."""
    from pathlib import Path

    from splatpipe.viewers.spark import template as tmpl

    parts_dir = Path(tmpl.__file__).parent / "template_parts"
    for p in sorted(parts_dir.iterdir()):
        if p.suffix not in (".html_tmpl", ".css_tmpl", ".js_tmpl"):
            continue
        raw = p.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), (
            f"{p.name}: UTF-8 BOM detected -- write with encoding='utf-8' "
            f"(no BOM) via Path.write_text"
        )
        assert not raw.startswith(b"\xff\xfe"), (
            f"{p.name}: UTF-16 LE BOM -- a Windows tool corrupted the file"
        )
        assert b"\r" not in raw, (
            f"{p.name}: CRLF line endings -- write with newline='\\n'"
        )
