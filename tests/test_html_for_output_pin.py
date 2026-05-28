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
  * 2026-05-21 (Phase 11G WF-H3 #144): visible Undo/Redo affordance + a
    drawer-friendly undo hotkey. ``16_editor_timeline`` adds clickable
    ``↶`` Undo + ``↷`` Redo buttons to the always-reachable transport row
    (delegating to ``EditorModuleRegistry.undo/redo``, dimmed/disabled per
    ``canUndo()``/``canRedo()`` -- synced every frame off ``_tlSyncPlayhead``
    + on every ``history:*`` event). ``04_js_prologue`` adds a NARROWER
    ``_editorUndoHotkeyBlocked()`` guard (blocks only real text-entry focus:
    INPUT text/number/etc, TEXTAREA, contenteditable -- NOT SELECT/range/
    checkbox/file/buttons, NOT [role=dialog]/[role=menu]); ``17a``'s
    Ctrl+Z/Y handler now uses it instead of the broad ``_editorHotkeyBlocked()``
    so Ctrl+Z works inside the Scene Settings [role=dialog] drawer. The
    destructive single-key hotkeys (T/R/X/K/V/B) keep the broad guard so H6
    stays intact. All 6 fixtures shifted by the same +5959 code points in
    lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11G WF-M annotation text #145): the annotation drawer
    card (``15c_annotation_module``) gains an editable title ``<input>`` + a
    text ``<textarea>`` (commit on change -- ONE EditHistory snapshot per
    gesture via ``ann-title`` / ``ann-text``, NEVER per keystroke; a
    ``_rebuild()`` after the commit re-creates the dot's unfold panel so the
    new title/text shows). The card previously had kind/radius/t_in/t_out/
    fade_ms but NO text input, so every annotation was stuck "(untitled)"
    with an empty panel. All 6 fixtures shifted by the same +3248 code points
    in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11G WF-M cuts->paths #145): the Cuts clip dropdown now
    offers the UNION of ``cfg.cameras`` + ``cfg.camera_paths`` (``15d``'s new
    ``_unionCameras()`` mirrors 10_camera_select's union) so a clip can
    sequence a path that has no virtual-camera entry (e.g. the Fehmarn
    Cinematic). ``11_clip_player::_clipPath`` resolves ``clip.camera_id`` as
    EITHER a cfg.cameras entry (via path_id, unchanged) OR a cfg.camera_paths
    id DIRECTLY, and ``_clipMode`` counts camera_paths so a path-only cut
    sequence plays (the 6 live single-tour scenes have NO clips so they are
    byte-behaviourally unchanged). All 6 fixtures shifted by the same +3421
    code points in lockstep; pins re-pinned.
  * 2026-05-21 (Phase 11G WF-M annotation persist #145): ``15c``'s
    ``_upgradeAnnotation`` now upgrades the cfg annotation IN PLACE (mutate +
    return the SAME object) instead of returning an ``Object.assign`` copy.
    Live Playwright verify of the WF-M annotation-text fix exposed that the
    drawer card's ``s.ann`` was a COPY (the upgrade cloned), so a title/text
    edit mutated the copy while ``cfg.annotations[i]`` kept the old value ->
    the edit was lost on the next ``_rebuild()`` (empty panel) AND on save.
    In-place upgrade keeps ``s.ann === cfg.annotations[i]`` so the edit
    persists + survives a rebuild; idempotent (fills only missing defaults +
    a missing id). Also repairs the same latent loss for the pre-existing
    kind/radius/t_in/t_out/fade_ms card edits. All 6 fixtures shifted by the
    same +930 code points in lockstep; pins re-pinned.
  * 2026-05-21 (R2 Batch A #151 -- camera-state seam #7/#8/#9): ONE
    lifecycle seam fixed across THREE fragments. (#7 paused-camera
    drift) ``18_frame_loop``'s player block now samples
    ``sampleAt(_player, _pausedAt)`` DIRECTLY when paused, instead of
    the ``(now-_t0)*speed`` wall clock that read the previous frame's
    ``_t0`` (the ``15_editor_trajectory`` rebase runs LATER in the
    frame) -> a ~16 ms sawtooth that ballooned on frame-rate dips. The
    15 rebase is left inert (kept for ``_t0`` clock consistency + the
    structural marker test). (#9 stop/interp camera jump)
    ``10_camera_select`` adds ``_syncControlsToCamera()`` -- repoints
    ``controls.target`` directly ahead of the LIVE camera + calls
    ``controls.update()`` ONCE so OrbitControls' internal spherical is
    re-derived from the live pose (verified against three 0.180
    ``OrbitControls.update()``: it ``setFromVector3(camera.position -
    target)`` at the top + ``lookAt(target)`` at the end, so a stale
    target snapped the camera). Called inside ``stopPath()`` before
    ``controls.enabled=true`` AND at the end of
    ``09_playback_spline::_pathSeekHold`` (the held seek pose was also
    being clobbered by the next ``lookAt(stale target)``).
    (#8 can't drag/Alt-rotate out of pause) ``17_editor_gizmo``'s
    ``_gzOnCanvasDown`` (empty-space fallback) + ``_gzAltDown`` now
    ``stopPath()`` when ``_pathPlayState()==='paused'`` so the SAME
    drag / Alt+drag bubbles to OrbitControls (re-enabled+synced by #9)
    and orbits from the held pose. All 6 fixtures shifted by the same
    +6896 code points in lockstep -- additive only (isolated to the
    edited fragments). Pins re-pinned to the new baseline.
  * 2026-05-21 (R2 Batch B #152 -- undo snapshot gaps #3): FIVE keyframe
    mutations that pushed NO EditHistory snapshot (so they could not be
    undone + the undo button greyed out wrongly) now snapshot the
    pre-gesture cfg BEFORE the mutation, once per gesture. (1) keyframe
    DELETE -- ``16_editor_timeline``'s X/Delete keydown handler + the
    ``tlDeleteSelection`` test-surface both ``_tlPushHistorySnap(
    'kf-delete')`` past the >=2 clamp. (2) keyframe RECORD --
    ``17_editor_gizmo::_gzRecordKeyframe`` (reached by both the K hotkey
    and the Rec button) ``EditorModuleRegistry.pushUndo('kf-record')``
    before the ``p.keyframes.push(kf)``. (3) diamond time-DRAG --
    ``16``'s ``_tlOnDown`` snapshots ``kf-timeline-drag`` on the
    pointerdown that begins a diamond drag (ONCE at gesture start, never
    per pointermove) + the ``tlDragKf`` test-surface mirrors it. (4)
    scale-edge DRAG -- ``16``'s ``_tlOnDown`` snapshots ``kf-scale`` on
    the edge-handle pointerdown + the ``tlScaleSelection`` test-surface
    mirrors it. (5) single-keyframe INTERP -- ``17_editor_gizmo::
    _gzSetInterp``'s single-target branch ``pushUndo('kf-interp')`` before
    ``kf.interp = val`` (the multi-write branch already pushed
    'interp-multi', untouched). PLUS a clearer undo/redo affordance in
    ``16``'s transport row: the buttons gain a larger hit target (more
    padding + a short "undo"/"redo" text label beside the ``↶``/``↷``
    glyph) and a thin ``_tlDivider()`` flanking the pair so the history
    group reads visually apart from Play/Loop; the per-frame
    ``_tlSyncUndoRedo()`` enable/disable sync + the exact
    ``_tlBar.appendChild(_tlUndo); _tlBar.appendChild(_tlRedo);`` line are
    preserved. All 6 fixtures shifted by the same +4917 code points in
    lockstep -- additive only (isolated to the 16/17 fragments). Pins
    re-pinned to the new baseline.
  * 2026-05-21 (R2 Batch C #153 -- timeline #4/#5/#11): three cohesive
    timeline changes in ``16_editor_timeline.js_tmpl`` (+ a 2-line
    stale-label comment fixup in ``17a_edit_history``). (#5 Length
    field) the auto/manual toggle (``_tlAutoBtn`` + ``_tlIsAutoTotal`` +
    ``tlToggleAuto`` test hook + the 'path-auto-toggle' label) is
    REMOVED; the total-time input is now a single ALWAYS-editable
    "Length [N] s" field (caption ``_tlTotalLabel`` 'Length' + unit
    's'); ``_tlCommitTotalInput`` drops the auto guard, writes
    ``total_duration_s`` on a positive entry (never null -> the field
    never falls back to auto), one EditHistory snapshot labelled
    'path-length'. (#4 auto-fit) a new ``_tlFitToPath()`` recomputes
    ``_tlZoom = (laneW - 2*PAD)/effectiveScrubRange[1]`` + resets
    ``_tlScroll=0`` so the full 0..length range fills the lane width;
    called after a Length commit AND on initial path load (rAF layout)
    + path-select (``tlRedraw``) so diamonds reflow to fit (wheel-zoom
    still overrides afterwards). (#11 lane render) ``_tlDraw`` now calls
    a new ``_tlDrawLanes()`` that iterates ``_tlLaneList()`` + calls each
    registered lane's ``render(ctx, _LABEL_W, y, w, rows*ROW_H,
    playhead)`` in its own band below the diamond row with a left-gutter
    label; the strip grows by ``sum(lane.rows) * _TL_LANE_ROW_H`` via a
    new ``_tlSyncHeight()`` (re-run on lane register/unregister); the
    diamond row + playhead overlay are untouched. All 6 fixtures shifted
    by the same +6717 code points in lockstep -- additive only (isolated
    to the 16/17a edits). Pins re-pinned to the new baseline.
  * 2026-05-21 (R2 Batch D #154 -- polish #1/#13 + tooltip + upload hint +
    chunk-warning): five low-risk polish edits across five fragments.
    (#1 interp auto-target) ``17_editor_gizmo::_gzOpenPopover`` no longer
    silently bails when nothing is selected -- a new
    ``_gzNearestKfToPlayhead()`` re-derives ``_trajActiveKf`` via
    ``_trajRefreshActive()`` (else falls back to the nearest keyframe by
    ``|kf.t - playheadTime|``) and ``_gzAttach``es it so the popover opens
    for the playhead-nearest keyframe; only a genuinely empty path flashes
    a ``_gzFlashSelectHint()`` ("Select a keyframe first") in #controls-hint.
    (#13 annotation centering) ``02a_styles_main`` ``.ann-dot`` gains
    ``line-height: 1`` so single digits sit on the vertical centre instead
    of ~1-2px low. (Save tooltip) ``17_editor_gizmo``'s Save button title
    is reworded from "Save camera paths (cli: emit SPCP1 token; http: POST)"
    to plain "Save scene". (upload hint) ``15b_panorama_module`` +
    ``15f_audio_module`` each add a subtle dim static line ("Upload opens
    via your author link (#token=...).") near the file picker. (chunk-warning)
    ``18_frame_loop``'s root-chunk eviction guard now bounds the queued
    chunk count to ``min(16, meta.chunks.length)`` -- the real chunk count
    resolved ONCE off the existing ``splat.paged.radMetaPromise`` (no new
    fetch, no Spark-fork edit) and cached on the pager; a <16-chunk scene
    no longer queues non-existent chunks (the "Chunk index out of range"
    console warning storm + wasted fetches). The bound only ever REDUCES
    the request count, so zero streaming risk. All 6 fixtures shifted by
    the same +7886 code points in lockstep -- additive only (isolated to
    the edited fragments). Pins re-pinned to the new baseline.
  * 2026-05-21 (R2 Batch E1 #155 -- real extruded 3D text): the
    ``15g_titles_module`` renderer is replaced. Each ``cfg.titles3d[i]``
    is now a REAL ``TextGeometry`` mesh (bevelled glyphs, real
    extrusion depth) shaded by a fake-light rig (``AmbientLight`` +
    ``DirectionalLight`` added ONCE to ``scene``) and added to the same
    ``scene`` Spark renders into -- so the text foreshortens with the
    camera, is lit (gradient across the bevel, not a flat fill), and
    depth-sorts against the other depth-writing editor meshes, instead
    of the prior flat always-on-top CSS2D ``<div>`` billboard. The font
    is loaded ONCE (cached) via a dynamic ``import('three/addons/...')``
    of ``FontLoader`` + ``TextGeometry`` (the trajectory fat-lines
    async-load pattern; the typeface JSON is a new ``@@FONT_URL@@``
    template slot pinning the three examples' helvetiker_bold at the
    exact ``THREE_VERSION``). billboard=true faces the camera each
    frame; billboard=false orients the mesh in world space via the
    (finally-implemented) reserved ``quat``; fade is applied via
    ``material.opacity``; geometry+material are disposed on rebuild.
    ``_upgradeTitle`` now upgrades the cfg entry IN PLACE (so a drawer
    edit persists, mirroring the WF-M annotation fix). Isolated to the
    15g fragment: all 6 fixtures shifted by the same +9100 code points
    in lockstep -- additive only. Pins re-pinned to the new baseline.
  * 2026-05-21 (R2 Batch E2 #156 -- right-click context menus): ONE
    reusable ``openContextMenu(x, y, items, opts)`` primitive added as a
    new early fragment ``04b_context_menu.js_tmpl`` (a [role=menu] popup
    of [role=menuitem] .quality-btn buttons, viewport-clamped, closed by
    capture-phase outside-click / Escape / scroll / resize / item-select
    with all listeners removed on close, single-instance + coordinated
    with the Save / Set-start-view cards via _closeAllEditorOverlays,
    keyboard nav focus + ArrowUp/Down/Home/End/Enter). Wired to FIVE
    surfaces, ALL author-gated: (1) ``16_editor_timeline`` -- a
    contextmenu on _tlLane hit-tests _tlHitKf and opens Delete keyframe
    (X-delete mutation + 'kf-delete' snapshot, >=2 clamp) / flattened
    Set-interp (5 _VALID_INTERP keys, 'kf-interp' snapshot) / Go to
    keyframe (_tlScrubToTime). (2) ``17_editor_gizmo`` -- a contextmenu
    on renderer.domElement reuses _gzPickFrustum + _gzAttach to select
    the hit keyframe then offers the same Delete / Set-interp (via
    _gzSetInterp) / Go to (window.__editor.tlScrub). (3)
    ``10_camera_select`` -- a contextmenu on #camera-select offers
    Rename / Set-as-default / Delete for the selected camera (reuses
    _camSelRename/_camSelDelete + a new _camSelSetDefault writing
    cfg.default_path_id). (4) ``15c_annotation_module`` + (5)
    ``15g_titles_module`` rows -- Edit (expand <details>) / Go to (fly
    the orbit pivot to pos) / Delete (reuse the row delBtn); plus
    ``15d_cuts_module`` clip cards -- Edit / Move earlier / Move later /
    Delete. The canvas's 08:223 ``preventDefault`` is UNCHANGED (it
    still suppresses the browser menu for non-author + on a frustum
    miss). All 6 fixtures shifted by the same +33997 code points in
    lockstep -- additive only (new 04b fragment + region-interior wiring
    in 10/15c/15d/15g/16/17; includes a +553 follow-up that fixed the
    primitive's Home/End keyboard nav -- a huge wrapping offset
    mis-wrapped to a negative index so End left focus on the first item,
    caught in the live Playwright verify; replaced with a direct
    _ctxFocusEdge first/last jump). Pins re-pinned to the new baseline.
  * 2026-05-21 (R2 Batch F #157 -- layout): four UX layout edits across
    five fragments. (Layout 1, author hints -> Settings) ``02a_styles_main``
    adds ``body.authormode #controls-hint{display:none}`` so the on-canvas
    nav-hint strip is hidden in AUTHOR mode (it crowded the merged
    transport row + the bottom timeline); the SAME hint chords move into a
    new static "Navigation" ``<details>`` section appended to the
    ``17b_scene_settings_drawer`` body (``data-section='navigation'``).
    USER / embed are byte-behaviourally identical -- end-users have no
    drawer so the strip stays on-screen (the existing ``body.embed`` rule
    still hides it for iframes). ``17_editor_gizmo::_gzFlashSelectHint``
    now temporarily un-hides ``#controls-hint`` (inline ``display:block``)
    for its ~1.8 s flash + restores ``display:''`` on the same timer, so
    the R2-Batch-D "Select a keyframe first" flash is NOT a silent no-op
    under the new author rule. (Layout 2, Show-trajectory off the timeline)
    ``15_editor_trajectory``'s ``#editor-traj-toggle`` moves from
    ``bottom:82px;right:12px`` (which sat OVER the multi-lane timeline as
    it grew) to ``top:62px;left:20px`` (under the header band, clear of the
    bottom strip + the top-right dropdown cluster). (Layout 3, float
    undo/redo) ``16_editor_timeline``'s undo / redo buttons are FLOATED
    out of the dark ``_tlBar`` transport row into a new
    ``#editor-undo-float`` div (a SIBLING of ``_tlStrip`` under
    ``#author-root``, positioned ``bottom:(_TL_H + 8)px`` so it sits just
    above the strip's top edge + is re-synced by ``_tlSyncHeight`` as the
    strip grows; ``_tlStrip``'s ``overflow:hidden`` would clip a child).
    The ``_tlSyncUndoRedo`` per-frame enable/disable + the ``history:*``
    event sync + the click handlers reference the buttons by variable, so
    they are parent-agnostic + intact. (#4, right-click interp on a
    multi-selection) ``16``'s ``_tlLane`` contextmenu handler no longer
    unconditionally clears the box-selection: when the right-clicked
    diamond is part of a ``_tlSel.size >= 2`` selection it KEEPS the whole
    selection + the interp item applies the chosen mode to EVERY selected
    index with ONE ``interp-multi`` snapshot (mirrors ``_gzSetInterp``'s
    multi branch); otherwise it replaces with the clicked kf + a single
    ``kf-interp`` snapshot (prior behaviour). All 6 fixtures shifted by the
    same +8659 code points in lockstep -- additive only (isolated to the
    02a/15/16/17/17b edits). Pins re-pinned to the new baseline.
  * 2026-05-21 (R2 Batch G #159 -- HUD layout): two small visual edits.
    (cog into top bar) ``17b_scene_settings_drawer``'s ``#scene-settings-cog``
    moves from a corner-float (``position:absolute;top:8px;right:8px`` on
    ``#author-root``) into the top-bar header row (``#quality-buttons``) as
    a proper sibling button reusing the ``.quality-btn`` class; its CLOSED
    state now clears the inline background (lets the class pill show) while
    OPEN keeps the cyan tint; a new ``body:not(.authormode)
    #scene-settings-cog{display:none}`` rule in ``02b_styles_editor`` is the
    no-flash author-only gate (the cog left ``#author-root``'s
    usermode/embed hide). (undo/redo more opaque) ``16_editor_timeline``'s
    ``_UNDO_BTN_CSS`` (the floating ``#editor-undo-float`` undo/redo
    buttons, Batch F) gains a SOLID near-opaque dark pill
    (``rgba(20,20,22,0.94)``) matching the transport block + a brighter
    border/text + a subtle drop shadow so the ENABLED state reads clearly
    over the scene; the DISABLED dim (``opacity:0.35`` via
    ``_tlApplyBtnEnabled``) is UNCHANGED. All 6 fixtures shifted by the same
    +2399 code points in lockstep -- additive only (isolated to the
    02b/16/17b edits). Pins re-pinned to the new baseline.
  * 2026-05-21 (R3 #6 -- scrub in Perspective): the ``#path-scrub`` ``input``
    handler in ``10_camera_select`` now bails BEFORE any camera-drive code
    when the visible camera dropdown is on the ``_CAM_PERSP`` sentinel
    (free-fly). Previously a scrub in Perspective built a ``_player`` off
    ``selEl.value``, set ``_t0``/``_pausedAt``, disabled OrbitControls and let
    the ``18_frame_loop`` ``if (_player)`` block + the ``15`` rebase TELEPORT
    the free-fly view onto the path's sampled pose (dropdown still said
    "Perspective") -- user-reported. The guard leaves ``_player`` null so the
    view camera is never written; the trajectory active-key frustum/ring
    (``_trajRefreshActive`` in 15) and the bottom-timeline playhead
    (``_tlSyncPlayhead`` in 16) BOTH read ``scrubEl.value`` directly in their
    not-playing branch every frame, so the marker still slides along the path
    (previewing the tour position from outside). Binding a real path camera is
    UNCHANGED (the camera follows the scrub). All 6 fixtures shifted by the
    same +1942 code points in lockstep -- additive only (isolated to the 10
    edit). Pins re-pinned to the new baseline.
  * 2026-05-22 (R3 Bug C #163 -- Scene Settings drawer X-close): the
    ``17b_scene_settings_drawer`` HudLayer registration for the DRAWER now
    passes NO ``modes`` (the cog keeps ``modes:['author']``). HudLayer._apply
    writes ``el.style.display`` for any panel that declares modes -- but the
    drawer ALSO uses ``style.display`` for its open/closed state (_ssApply).
    With ``modes:['author']`` the two collided: in author mode _apply forced
    ``display:''`` (VISIBLE) at register time WITHOUT touching ``_ssIsOpen``,
    so the drawer rendered open while the state machine still read CLOSED, and
    the X / Esc / cog then early-returned at ``if (!_ssIsOpen) return`` and
    appeared dead (user: "I can't close Scene Settings by clicking the X").
    No-modes makes ``matches()`` true in every mode so HudLayer never writes
    the drawer's display (the framework's documented no-modes contract) --
    _ssApply stays the SINGLE writer; the mode hide is the CSS body-class gate
    (``body.usermode #author-root{display:none}``). Isolated to the 17b edit:
    all 6 fixtures shifted by the same +1231 code points in lockstep --
    additive only (a removed ``modes`` line + the explanatory comment). Pins
    re-pinned to the new baseline.
  * 2026-05-22 (#164 -- multi-camera CLIP EDITOR MVP): the
    ``16_editor_timeline`` IIFE gains a STACKED, always-visible two-level
    bottom timeline -- a Cuts master track (sequence level) <-> per-clip
    camera keyframes (clip level). At sequence level the EXISTING
    ``CutsModule.timelineLane.render`` is promoted to the PRIMARY band
    (master-time ruler + master playhead + dimmed context diamonds);
    clicking a clip block loads that clip's camera via the EXISTING
    ``_camSelApply`` drill primitive (resolving the clip -> camera_paths
    entry via the EXISTING two-step ``_clipPath``, NEVER assuming
    camera_id===path_id) and drops to clip level (the unchanged per-path
    diamond editor). A "◂ Sequence" back button + a breadcrumb expose the
    levels; sequence Play drives the cut chain via ``window.__clip.restart``;
    the sequence master scrub reuses the EXISTING per-clip ``#path-scrub``
    path (NO parallel scrub clock -- the just-fixed R3 #6 camera-write gate
    holds) and cuts at clip boundaries via ``_camSelApply``. The DEFAULT
    level is 'sequence' WHEN ``cfg.clips`` is non-empty else 'clip', so the
    6 live single-camera / no-clip scenes stay at clip level and behave
    EXACTLY as today (the sequence-level branches are present in the bundle
    but inert at runtime). The change is ADDITIVE only -- all 6 fixtures
    shifted by the same +33261 code points in lockstep (no spooky action
    elsewhere; the fixtures carry no clips so the sequence paths never run).
    Pins re-pinned to the new baseline.
  * 2026-05-22 (#165 R4 -- core gestures always work): three CORE
    keyframe-editing gestures made state-independent across
    ``16_editor_timeline`` + ``17_editor_gizmo``. (1 Rec near-instant)
    ``_gzAfterEdit`` rebuilt the trajectory + the spline TWICE per
    Record/gizmo edit (a direct ``_trajRebuild`` + ``buildPlayer`` THEN a
    redundant ``window.__editor.rebuild()`` round-trip that rebuilt again);
    it now rebuilds ONCE + reuses the player it built (about half the
    synchronous work; the rebuild cost scales with keyframe count).
    (2 always-scrubbable full-range playhead) a new ``_tlScrubSeconds`` +
    ``_tlEffectiveDur`` decouple the PLAYHEAD time (over the effective
    ``max(last_kf, 10)`` / ``total_duration_s`` range) from the camera
    SAMPLE time; ``_tlScrubToTime`` no longer early-returns on a 0/1-kf
    path nor clamps to the last keyframe, and ``_tlPlayheadT`` reports
    ``_tlScrubSeconds`` whenever NOT truly-playing (incl. a paused-at-scrub
    freeze, gated on ``_pausedAt===null``) so the marker drags the full
    Length in every state (path-cam / Perspective / clip level). The
    camera-WRITE stays gated by the R3 #6 ``_CAM_PERSP`` check + the UX-3
    #7 ``_pausedAt``/``_pausedAtPlayer`` reuse is untouched. Record reads
    this effective playhead (so a scrub PAST the last kf records there to
    extend the path); the FIRST keyframe still anchors at t=0. (3 delete in
    every state) the X/Delete handler, which consulted ONLY ``_tlSel``,
    now falls back to a new ``window.__editor.gzDeleteSel()`` (deletes the
    GIZMO/frustum-selected keyframe via the existing ``_gzDeleteKeyframe``
    -- same >=2 clamp + ``kf-delete`` snapshot) when the timeline selection
    is empty; the H6 ``_editorHotkeyBlocked`` text-input guard is preserved.
    New test surface: ``tlScrubSeconds`` / ``tlEffectiveDur`` / ``gzDeleteSel``;
    ``tlScrub(frac)`` + ``_gzGoToKeyframe`` remapped onto the effective
    range. All 6 fixtures shifted by the same +11274 code points in
    lockstep -- additive only (isolated to the 16/17 edits). Pins re-pinned
    to the new baseline.
  * 2026-05-22 (R4 follow-up #167 + #166 -- clip drill-in + Rec overwrite):
    two editor fixes across ``16_editor_timeline`` + ``17_editor_gizmo``.
    (#167 clip-block click drills in) at CLIP level the cuts blocks render
    in the labelled "Cuts" MODULE LANE below the diamond row (``_tlDrawLanes``),
    but ``_tlOnDown`` had NO hit-test for that band -- a real pixel-click on a
    clip block there fell through to the empty-lane box-select and did NOTHING
    (so a scene that booted WITHOUT clips, then had clips added via the Scene
    Settings cuts card -- which keeps ``_tlLevel='clip'`` -- could never switch
    clips by clicking, the user-confirmed break). A new ``_tlHitCutsLaneClip``
    walks ``_tlLaneList()`` the SAME way ``_tlDrawLanes`` does to find the cuts
    band's y-range + maps x->clip via the EXACT ``[_LABEL_W, _tlW]`` / 0..Σdur
    mapping ``CutsModule.timelineLane.render`` uses; a new ``_tlOnDown`` (3b)
    branch calls the EXISTING ``_tlEnterClip`` drill verb for a hit (sequence-
    level primary-band clicks were already correct via ``_tlHitClip``). Plus a
    TEST-ONLY ``tlHitCutsLaneClipAt`` surface getter. (#166 Rec overwrites the
    parked keyframe) ``17_editor_gizmo::_gzRecordKeyframe`` always APPENDED;
    it now OVERWRITES in place (pos/quat/fov, keeping the matched keyframe's
    own t + easing/hold/annotation/interp) when the genuine playhead
    (``window.__editor.tlPlayheadT``, valid incl. exactly 0) is within
    ``_KF_OVERWRITE_EPS`` (0.05 s) of an existing keyframe's t, gated on a
    >=2-kf path (a 0/1-kf path is still bootstrapped via the UX-5 last_t+DT
    rule); off any keyframe it APPENDS as before. One EditHistory snapshot
    (``kf-overwrite`` overwriting, ``kf-record`` appending) via a shared
    ``_pushSnap`` helper. Both fixes REAL-click / real-Rec verified in the
    Playwright harness (clip drill-in at sequence AND clip level + the ◂
    Sequence back; overwrite count-unchanged-pose-updated + off-kf +1 + undo
    restores both). All 6 fixtures shifted by the same +8279 code points in
    lockstep -- additive only (isolated to the 16/17 edits + the test hook).
    Pins re-pinned to the new baseline.
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
# lockstep), then re-pinned 2026-05-21 (R2 Batch A #151: camera-state
# seam #7/#8/#9 -- paused player block samples _pausedAt directly (18),
# stopPath/_pathSeekHold re-sync OrbitControls to the live pose (10/09),
# canvas drag + Alt+drag while paused take over the camera (17); +6896
# code points in lockstep), then re-pinned 2026-05-21 (R2 Batch D #154:
# interp auto-targets playhead kf (17) + .ann-dot line-height:1 (02a) +
# "Save scene" tooltip (17) + upload author-link hint (15b/15f) +
# root-chunk guard bounded to min(16, meta.chunks.length) (18); +7886
# code points in lockstep). NOTE: expected_len counts len(html) CODE POINTS
# (Unicode scalar values), NOT UTF-8 bytes -- the assembled HTML carries
# multi-byte chars (em-dash, degree sign, etc.) so the byte length runs
# ~770 higher. Measure a re-pin with len(html), never len(html.encode()).
CORPUS: list[tuple[str, tuple, dict, int, str]] = [
    (
        "harness_defaults",
        ("HarnessScene",),
        {},
        939558,
        "5a104ff16c482454a638803d7ffbf583c9fd8f844194356f4dd075631133b5bf",
    ),
    (
        "http_basic",
        ("S",),
        {"save_mode": "http", "save_endpoint": "https://x.example/api/save"},
        939530,
        "f5cb5b494a979b66123628c182c367cdba66ef8883b2eca197fe50bdf1f98698",
    ),
    (
        "http_endpoint_quotes",
        ("S",),
        {"save_endpoint": 'https://x/"+evil()+"'},
        939525,
        "02932fa1bac50179aee5121b5093bf45c1114144e520c445b1ded026e87b83ae",
    ),
    (
        "none_endpoint",
        ("S",),
        {"save_mode": "http", "save_endpoint": None},
        939504,
        "b7ff50137b679604a8bfeb123e20c4ee07cc8e9d6d2881255b2927aca5b8b89c",
    ),
    (
        "sog_fallback",
        ("LegacySogScene",),
        {"primary_asset": "scene.sog", "paged": False},
        939569,
        "5f98a1af5629176ae7011d561fe1270db5c06f118b420cf7d2038f2b71394c81",
    ),
    (
        "share_card",
        ("ShareScene",),
        {
            "share_url": "https://splatpipe-cdn.b-cdn.net/share/index.html",
            "share_image": "https://splatpipe-cdn.b-cdn.net/share/preview.jpg",
            "description": "Custom share description text.",
        },
        939428,
        "646361dab122e94e8abc5478e2f2c3ff85755f53d559f21818dfa1d984c9e9ef",
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
