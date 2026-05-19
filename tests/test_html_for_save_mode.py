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

# --- Moving baseline (Task 17) -------------------------------------------
# The byte-identity guard pins the PREVIOUS task's COMMITTED generated
# output and asserts the only delta is THIS task's deliberate change. The
# baseline therefore moves forward one commit each task. For Task 17 the
# pinned baseline is the committed template at HEAD ``c1d5801`` (the commit
# BEFORE Task 17's edit -- i.e. Task 16 committed: feat(editor) viewport
# trajectory + camera frustums + speed dots) -- which ALREADY contains
# every prior task's deliberate, anchored change (Task 8's inert SAVE_*
# block, Task 10's two visibilitychange blocks, Task 11's in-place spline
# change, Task 12's three dual-UI regions, Task 13's three regions, Task
# 14's grown T13-AS ClipPlayer + T14-PW + T14-AF, Task 15's grown T13-AS
# end-user transport + T15-OB, and Task 16's NEW T16-TRAJ author overlay).
# ``html_for("HarnessScene")`` there is 246869 bytes.
#
# Task 17 (author editor -- bottom timeline: scrub/diamonds/transport/
# zoom/multiselect/scale; plan H2/Task-13) is a PURE recipe-2c
# REGION-INTERIOR-ONLY change. Its entire deliberate delta -- the
# bottom timeline strip DOM/JS injected into the (already-existing,
# Task-12) ``#author-root`` (a seconds ruler + an OPTIONAL fps RELABEL
# grid that never mutates a stored ``t``, a draggable diamond per
# keyframe whose horizontal drag is an IN-MEMORY temporal edit, a
# live-scrub playhead routed through the EXISTING ``#path-scrub`` real
# input mechanism, transport reuse, wheel zoom, box-multiselect +
# selection-edge proportional ``t``-span scale, X-delete) PLUS the
# EXTENSION of the Task-16 TEST-ONLY ``window.__editor`` surface
# (``Object.assign``ed timeline getters + deterministic hooks) -- lands
# STRICTLY INSIDE the EXISTING Task-16 T16-TRAJ region (between the
# UNCHANGED ``  applySplatBudget(_initialBudget);`` START and the
# UNCHANGED ``  // ---- Frame loop ----`` END; the new code sits
# immediately AFTER the Task-16 ``window.__editor`` literal and BEFORE
# the END comment). It adds NO new region and NO delta OUTSIDE
# T16-TRAJ: no CSS region (the strip is inline-styled like #sp-hud /
# the Task-16 toggle), the ``#author-root`` root already exists (Task
# 12), and the spline / player / #path-scrub / clip / transport code is
# REUSED, never modified. The whole block is AUTHOR-MODE-gated (the
# SAME ``_EDITOR_AUTHOR`` = ``ModeManager.is('author')`` flag the
# Task-16 overlay uses + the strip DOM is only ever built in author
# mode + the OverlayScene ``_tlLayer`` is ``modes:['author']``) so for
# ``"HarnessScene"`` (NOT author mode -- like the 6 live single-camera
# scenes) it produces ZERO rendered-HTML delta OUTSIDE T16-TRAJ and is
# byte-runtime-inert: a DELIBERATE, byte-lock-excised change, NOT a
# regression. PERSISTENCE IS NOT TASK-17: nothing here writes/saves;
# edits mutate the IN-MEMORY active path + rebuild the spline (+ the
# Task-16 overlay consequently) and stop -- SAVE_MODE / SAVE_ENDPOINT /
# save_backends are untouched (asserted-surviving below).
#
# Per the regen recipe case 2c: a task whose template delta is PURELY
# 2c (lands strictly inside an already-excised region) does NOT advance
# ``_PRE_TASKnn_REMAINDER_*`` / ``_FULL_*`` REMAINDER pins -- the
# remainder is byte-IDENTICAL to the prior task's because the T16-TRAJ
# excision simply now removes a LARGER span (the prior author-overlay
# block PLUS the new timeline block). Excising the SAME ELEVEN regions
# (the Task-11 spline + the three Task-12 + the three Task-13 + the two
# Task-14 + the Task-15 T15-OB + the Task-16 T16-TRAJ -- every one with
# its ORIGINAL anchors so every prior contract stays asserted-surviving)
# from the current generated HTML reproduces the ``c1d5801`` committed
# template's SAME eleven-region excision byte-for-byte. The
# ``_PRE_TASK17_*`` pins below are computed from ``c1d5801`` byte-
# faithfully (via ``git cat-file blob`` -- NOT the dirty tree; the
# ``pagedExtSplats`` stray makes the dirty tree FAIL this BY DESIGN, so
# the guard still bites); numerically the REMAINDER pin EQUALS the
# Task-16 one (the 2c invariant -- a moved/changed remainder pin here
# would mean the timeline delta LEAKED outside T16-TRAJ; it does not).
# The FULL ``c1d5801`` fingerprint advances (it is the new committed
# baseline -- documentation / cross-check; the remainder pin is what
# the assertion uses). Every prior task's anchored content stays
# asserted-surviving below (the excision only ever NARROWS what is
# compared -- never relaxed); the Task-17 timeline surface is asserted
# present-in-full-html then gone-after-the-T16-TRAJ-excision (proving
# it really is wholly inside that region, not leaking).
_PRE_TASK17_REMAINDER_LEN = 155585
_PRE_TASK17_REMAINDER_SHA = (
    "f4cb11b385dedc2d018fc4342766285c0805f147c080b44d9de1fcd250370226"
)
# Full ``c1d5801`` baseline fingerprint (documentation / cross-check;
# the remainder pin above is what the assertion uses). The REMAINDER
# pin is byte-IDENTICAL to ``_PRE_TASK16_REMAINDER_*`` (the recipe-2c
# invariant: Task 17's delta is wholly inside the Task-16 T16-TRAJ
# region, so the eleven-region remainder is unchanged); only the FULL
# fingerprint advances (the new committed baseline has the Task-16
# author overlay inside T16-TRAJ).
_PRE_TASK17_FULL_LEN = 246869
_PRE_TASK17_FULL_SHA = (
    "7f9dcc500f1512c89f0f45523c3505edd406bb830bb52a363247fc1324790e52"
)

# --- Prior moving-baseline note (Task 16, kept for provenance) -----------
# The byte-identity guard pins the PREVIOUS task's COMMITTED generated
# output and asserts the only delta is THIS task's deliberate change. The
# baseline therefore moves forward one commit each task (see the regen
# recipe below). For Task 16 the pinned baseline is the committed template
# at HEAD ``cfb0835`` (the commit BEFORE Task 16's edit -- i.e. Task 15
# committed: feat(viewer) end-user interrupt + resume + per-cut idle
# auto-orbit) -- which ALREADY contains Task 8's inert SAVE_* block,
# Task 10's two visibilitychange blocks, Task 11's in-place spline change,
# Task 12's three dual-UI regions, Task 13's three regions (loading-blur
# DOM, deferred autostart, intro IIFE), Task 14's grown T13-AS ClipPlayer
# + the T14-PW prewarm guard-twin + the T14-AF broadened auto-focus
# guard, AND Task 15's end-user transport (grown T13-AS again + the
# T15-OB _buildOrbitPath delegation refactor).
# ``html_for("HarnessScene")`` there is 225847 bytes.
#
# Task 16 (author editor -- viewport trajectory + camera frustums +
# speed dots; the FIRST author-mode overlay, plan H2/Task-12) is PURELY
# ADDITIVE (recipe 2a): ONE NEW region (T16-TRAJ) that bounds ONLY the
# new author-overlay block (the trajectory THREE.Group + its
# _trajRebuild/_trajRefreshActive/_trajMakeFrustum helpers, the
# OverlayScene ``_trajLayer`` registration, the "Show trajectory"
# #author-root toggle, and the TEST-ONLY ``window.__editor`` surface).
# It adds NO other deltas (no CSS region -- the toggle is inline-styled
# like #sp-hud; the #author-root DOM root already exists from Task 12;
# the spline / player / clip / transport code is untouched). The whole
# block is AUTHOR-MODE-gated (ModeManager.is('author') + the
# OverlayScene layer's modes:['author']) so for ``"HarnessScene"``
# (NOT author mode) it produces ZERO rendered-HTML delta OUTSIDE the
# T16-TRAJ region -- the byte-lock proves the 6 live single-camera
# scenes (also NOT author mode) are byte-identical.
#
# T16-TRAJ (NEW additive region, recipe 2a): bounded by the UNCHANGED
# ``  applySplatBudget(_initialBudget);`` line (START) and the UNCHANGED
# ``  // ---- Frame loop ----`` comment (END). BOTH pre-exist EXACTLY
# ONCE in BOTH the ``cfb0835`` baseline and the current HTML, and in
# ``cfb0835`` the ONLY thing between them is a single blank line (zero
# foreign code -- a pure section boundary, exactly the T14-PW-style
# inert-scaffolding additive invariant). Every Task-16 line sits
# strictly between that blank line and the END comment, so excising the
# SAME [START..END] from ``cfb0835`` removes ONLY the two bounding lines
# + the blank, while excising it from the current HTML removes those
# SAME framing lines PLUS the whole new author-overlay block -> equal
# remainders (the additive-region invariant). ``_excise`` asserts the
# START unique + the (non-close_after) END unique-after-start, so a
# future template edit that duplicates/moves either fails LOUD rather
# than silently mis-excising.
#
# Task 15 (end-user transport -- click-interrupt + bottom resume +
# per-shot idle auto-orbit) is the cinematic end-user shell's interaction
# layer. It touches TWO regions:
#   (T13-AS, MODIFIED IN PLACE AGAIN, recipe 2b): the SAME unchanged
#     ``  if (cfg.default_path_id) {`` START / ``// ---- Bench launchers
#     ...`` END that has bounded Task 13's deferred autostart and Task
#     14's whole ClipPlayer now ALSO contains the end-user transport
#     block: ``IDLE_MS``, the SHARED ``_orbitPathAround`` orbit-math
#     helper (the bench's ``_buildOrbitPath`` is refactored to delegate to
#     it -- see T15-OB), ``_stopTour``/``_resumeTour``/``_startIdleOrbit``/
#     ``_cancelIdleOrbit``, the ``#user-play`` button (injected into the
#     Task-12 ``#user-transport`` root, inline-styled like ``#sp-hud`` so
#     there is NO new CSS region), the interrupt pointerdown + input-note
#     listeners, the ``_transportLayer`` (fanned out from the ONE
#     OverlayScene tick), and the ``window.__transport`` test surface. The
#     START anchor is STILL the first line of the region (unmoved) so it
#     pre-exists UNCHANGED in BOTH ``7acdd39`` and current; ALL Task-15
#     additions sit strictly between it and the UNCHANGED END comment. The
#     Task-10 visibilitychange handler sits ABOVE this START and is NOT
#     swallowed (its survival is asserted below).
#   (T15-OB, NEW modify-in-place region, recipe 2b): ``_buildOrbitPath``
#     is refactored from an inline Y-spin loop into a pure delegation to
#     the shared ``_orbitPathAround`` helper (declared in the grown T13-AS
#     region, hoisted -- same forward-reference-via-hoisting pattern the
#     existing ``_clipStart``/``_clipPrewarmRelease`` pair already uses).
#     It passes the SAME center (``_origTarget``), SAME base pose
#     (``_origCamPos``/``_origCamQuat``/``_origCamFov``), SAME ``n:36`` /
#     ``secs:30`` / ``loop:false`` the bench has always produced, so the
#     generated orbit is byte-BEHAVIOURALLY identical for the 6 live
#     scenes' ``Bench: Orbit`` -- a pure refactor, NOT a behaviour change.
#     Bounded by the UNCHANGED ``  function _buildOrbitPath() {``
#     declaration line (START) and the UNCHANGED ``  async function
#     _runOrbitBench() {`` declaration line (END) -- both pre-exist
#     EXACTLY ONCE in BOTH ``7acdd39`` and current, and the WHOLE
#     [START..END] span is the entire ``_buildOrbitPath`` definition
#     (deliberately-touched) APART from nothing else, so excising the SAME
#     [START..END] from BOTH removes the (larger) inline-loop baseline
#     definition and the (smaller) delegating current one -> equal
#     remainders (the 2b invariant). ``_excise`` asserts the START unique +
#     the (non-close_after) END unique-after-start, so a future template
#     edit that duplicates/moves either fails LOUD rather than mis-
#     excising.
# Excising BOTH Task-15 regions (PLUS the still-excised Task-11 spline +
# three Task-12 + three Task-13/14 + T14-PW + T14-AF regions, every one
# with its ORIGINAL anchors so its contract stays asserted-surviving)
# from the current generated HTML reproduces the ``7acdd39`` committed
# template's SAME nine-region excision byte-for-byte -- hard proof every
# byte OUTSIDE those nine regions (the six live scenes' post-load
# RENDERING, Task 8's SAVE_*, Task 10's two blocks, Task 11's spline,
# Task 12's dual-UI, Task 13's cinematic shell, Task 14's ClipPlayer +
# prewarm + auto-focus guard) is untouched. The end-user transport is a
# DELIBERATE, byte-lock-excised change (the multi-camera end-user UX,
# plan SS-A3 / D-Task-11) -- NOT a regression for the six live single-
# camera scenes: every Task-15 entry point bails immediately when
# ``ModeManager.is('user')`` is false OR (for the idle orbit) when
# ``_clipMode`` is false, so author/embed AND the 6 live scenes are
# byte-runtime-unchanged. Task 8's SAVE_* + Task 10's blocks live OUTSIDE
# all nine regions, so they are in the compared remainder and thus
# asserted-surviving (explicit ``in stripped`` checks below pin that
# contract too -- never relaxed).
#
# ``_PRE_TASK16_REMAINDER_*`` = LEN/SHA-256 of the ``cfb0835`` baseline
# AFTER excising the SAME TEN regions with the SAME anchors -- the nine
# prior-task regions PLUS the new T16-TRAJ region (computed from
# ``git cat-file blob cfb0835:.../template.py`` byte-faithfully -- NOT
# the dirty tree; the ``pagedExtSplats`` stray makes the dirty tree
# FAIL this BY DESIGN, so the guard still bites). This is what the
# assertion below uses.
_PRE_TASK16_REMAINDER_LEN = 155585
_PRE_TASK16_REMAINDER_SHA = (
    "f4cb11b385dedc2d018fc4342766285c0805f147c080b44d9de1fcd250370226"
)
# Full ``cfb0835`` baseline fingerprint (documentation / cross-check;
# the remainder pin above is what the assertion uses).
_PRE_TASK16_FULL_LEN = 225847
_PRE_TASK16_FULL_SHA = (
    "839214c828ac6dfe2b3b7e6e71f7dd278f4cc97db981176fe8188d8d6ae071a2"
)
# T16-TRAJ region anchors (NEW 2a additive: the author-overlay block).
# START + END both pre-exist UNCHANGED and EXACTLY ONCE in BOTH
# ``cfb0835`` and the current HTML; in ``cfb0835`` the only thing
# between them is one blank line (zero foreign code -- the additive
# invariant). ALL Task-16 lines sit strictly between them.
_T16_TRAJ_START = "  applySplatBudget(_initialBudget);\n"
_T16_TRAJ_END = "  // ---- Frame loop ----\n"

# --- Prior moving-baseline note (Task 15, kept for provenance) -----------
# ``_PRE_TASK15_REMAINDER_*`` = LEN/SHA-256 of the ``7acdd39`` baseline
# AFTER excising the SAME nine regions with the SAME anchors (computed
# from ``git cat-file blob 7acdd39:.../template.py`` byte-faithfully --
# NOT the dirty tree). Superseded by the ``cfb0835``-based Task-16 pin
# above (a moving baseline -- one commit forward); retained as
# provenance / cross-check.
_PRE_TASK15_REMAINDER_LEN = 155648
_PRE_TASK15_REMAINDER_SHA = (
    "82b384a80f406580dafd331d98112a40f6c044b466c202cf743836e440c634f0"
)
# Full ``7acdd39`` baseline fingerprint (documentation / cross-check; the
# remainder pin above is what the assertion uses).
_PRE_TASK15_FULL_LEN = 207431
_PRE_TASK15_FULL_SHA = (
    "4ed26f8e321ef3b5b85a1b2d1a7cf41a0de8337b00f3ae55acfc5e25eb11a3d5"
)
# T15-OB region anchors (NEW 2b modify-in-place: the whole
# ``_buildOrbitPath`` definition, refactored to delegate to the shared
# ``_orbitPathAround``). START + END both pre-exist UNCHANGED and exactly
# once in BOTH ``7acdd39`` and the current HTML; the span is exactly the
# function definition (deliberately-touched, nothing else).
_T15_OB_START = "  function _buildOrbitPath() {\n"
_T15_OB_END = "  async function _runOrbitBench() {\n"

# --- Prior moving-baseline note (Task 14, kept for provenance) -----------
# Task 14 (multi-camera Camera-Cuts tour + next-cut LOD pre-warm, plus
# its review follow-up) generalises the single deferred default-path
# autostart into an ordered ``ClipPlayer`` sequence, adds a next-cut LOD
# prewarm guard-twin, and broadens ``_autoFocusTick``'s early-return
# guard so the clip layer owns the LoD origin for the whole tour. It
# touches THREE regions:
#   (T13-AS, MODIFIED IN PLACE, recipe 2b): the deferred-autostart region
#     -- bounded by the UNCHANGED ``  if (cfg.default_path_id) {`` START
#     and the UNCHANGED ``// ---- Bench launchers ...`` END that pre-exist
#     in BOTH ``842b50f`` and the current HTML -- now also contains the
#     whole ClipPlayer (class-like block, _clipStart/_clipFinish, the
#     prewarm scheduler, the OverlayScene clip layer, the generalised
#     ``_introStartTour`` and the Stop-button guard). The SAME [START..END]
#     excises the (smaller) ``842b50f`` slice and the (Task-14-grown)
#     current slice. The 6 live scenes have NO cfg.clips/cfg.cameras so
#     they take the byte-behaviourally-identical ``startPath(
#     cfg.default_path_id)`` fallback -- the no-clips regression the spec
#     hard-requires.
#   (T14-PW, NEW additive region, recipe 2a): the next-cut LOD prewarm
#     retention guard-twin, a sibling of the root-chunk eviction guard,
#     inserted strictly BETWEEN the UNCHANGED root-guard ``console.info(
#     '[Splatpipe] root-chunk eviction guard active ...')`` line (START) and
#     the UNCHANGED ``    // ---- Front-load phase (pillar V) ----`` line
#     (END) -- both pre-exist exactly once in BOTH ``842b50f`` and the
#     current HTML, and ALL Task-14 prewarm-guard lines sit strictly
#     between them, so excising [START..END] from ``842b50f`` removes ONLY
#     the unchanged bounding lines while excising it from current removes
#     those SAME bounding lines PLUS the new guard-twin -> equal
#     remainders.
#   (T14-AF, NEW modify-in-place region, recipe 2b -- Task-14 review
#     follow-up): ``_autoFocusTick``'s opening early-return guard is
#     broadened to also skip while a clip tour is active so the clip
#     layer owns the LoD origin for the WHOLE tour incl. the single
#     inter-clip cut-transition frame (no 1-frame
#     ``spark.lodPosOverride`` churn). Bounded by the UNCHANGED
#     ``  function _autoFocusTick(now) {`` declaration line (START) and
#     the UNCHANGED ``    if (!_afReady) return;`` line (END) -- both
#     pre-exist exactly once in BOTH ``842b50f`` and current and the
#     whole [START..END] span is byte-identical between them APART FROM
#     this deliberate change, so excising the SAME [START..END] from BOTH
#     removes the (smaller) baseline guard block and the (broadened)
#     current one -> equal remainders.
# Excising ALL THREE Task-14 regions (PLUS the still-excised Task-11
# spline + three Task-12 + the other two Task-13/14 regions, every one
# with its ORIGINAL anchors so its contract stays asserted-surviving)
# from the current generated HTML reproduces the ``842b50f`` committed
# template's SAME nine-region excision byte-for-byte -- hard proof every
# byte OUTSIDE those nine regions (the six live scenes' post-load
# RENDERING, Task 8's SAVE_*, Task 10's two blocks, Task 11's spline,
# Task 12's dual-UI, Task 13's cinematic shell) is untouched. The
# Camera-Cuts tour (and its review-follow-up auto-focus guard) is a
# DELIBERATE, byte-lock-excised change (the multi-camera end-user UX,
# plan SS-C) -- NOT a regression for the six live single-camera scenes:
# they have no clips/cameras so their generated bytes take the identical
# pre-Task-14 single-tour fallback AND ``_clipMode`` is false there so
# the broadened auto-focus guard's new disjunct is always false. Task 8's
# SAVE_* + Task 10's blocks live OUTSIDE all nine regions, so they are in
# the compared remainder and thus asserted-surviving (explicit
# `in stripped` checks below pin that contract too -- never relaxed).
#
# ``_PRE_TASK14_REMAINDER_*`` = LEN/SHA-256 of the ``842b50f`` baseline
# AFTER excising the SAME nine regions with the SAME anchors (computed
# from ``git cat-file blob 842b50f:.../template.py`` byte-faithfully --
# NOT the dirty tree).
_PRE_TASK14_REMAINDER_LEN = 157387
_PRE_TASK14_REMAINDER_SHA = (
    "2de1dac717150cad22b9aaaf525c8503117acbf9669fe3345088c33135b1eea0"
)
# Full ``842b50f`` baseline fingerprint (documentation / cross-check; the
# remainder pin above is what the assertion uses).
_PRE_TASK14_FULL_LEN = 183025
_PRE_TASK14_FULL_SHA = (
    "57c4177c1664557274a253d951109b0233c0415d234e65da135bb937e0de3152"
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
# Task-11's in-source ``// LOCKSTEP:`` banner sits IMMEDIATELY AFTER this
# START anchor (i.e. INSIDE the excised spline region). Task 12 does NOT
# touch the spline region at all, so that banner and these spline anchors
# are UNCHANGED here. A future Tasks-13..18 editor MUST keep any spline-
# section banner BELOW this START anchor (a line absent from the pre-task
# reference cannot anchor the moving baseline's excision); ``_excise``
# still asserts every anchor below stays unique (start AND end), failing
# LOUD on a duplicate/missing anchor rather than silently mis-excising.
_SPLINE_REGION_START = (
    "  // camera_paths JSON plays back byte-for-byte in either."
)
_SPLINE_REGION_END_TOK = (
    "return { spline, times, sortedKfs, sourceKf, "
    "duration, loop: !!p.loop, playSpeed };"
)
_SPLINE_REGION_CLOSE_AFTER = "  }"

# ── Task-12 deliberately-touched regions (all OUTSIDE the spline) ───────
# Each is bounded by a START anchor + END token that pre-exist UNCHANGED
# in BOTH the ``0689e788`` baseline and the current HTML (so excising the
# same [START..END] from both removes the corresponding baseline slice
# and the Task-12-grown current slice; equal remainders ⇒ no OTHER drift).
# Task 13's CSS additions land strictly INSIDE region (1) and its
# #intro-fade DOM root strictly INSIDE region (2), so those two Task-13
# additions are absorbed by these EXISTING excisions (recipe 2c) -- the
# anchors here are unchanged, only the spans they bound grew.
#
# (1) CSS: the embed strip's last pre-existing selector line through the
#     terminal ``  </style>`` line. Excises the embed strip's tail (now
#     extended to also hide #author-root/#user-transport) + the two new
#     ``body.usermode``/``body.authormode`` rules + the ``  </style>``
#     close. In the baseline that span is just the old 2 selector lines +
#     ``  </style>``; both ends pre-exist unchanged.
_T12_CSS_START = "    body.embed #path-hud,\n"
_T12_CSS_END = "  </style>"
# (2) DOM: the (unchanged) #path-time span line -- the last line before
#     #path-hud's closing </div> -- through the (unchanged) importmap
#     <script> open. Excises the two new always-present empty dual-UI
#     roots (+ their comment) that Task 12 inserts between them.
_T12_DOM_START = '    <span class="time" id="path-time">0.00s</span>\n'
_T12_DOM_END = '  <script type="importmap">'
# (3) ModeManager: the (unchanged) generic ``mode-<x>`` class-set line
#     through the (unchanged) ``if (_mode === 'embed') {`` line. Excises
#     ONLY Task 12's added dual-UI comment + the single extra
#     ``classList.add(_mode === 'author' ? 'authormode' : 'usermode')``
#     -- proving the dual-UI is driven off the one resolved ``_mode``
#     (A4-unify) with no second ?author parse / parallel branch.
_T12_MM_START = "    document.body.classList.add('mode-' + _mode);\n"
_T12_MM_END = "if (_mode === 'embed') {"

# ── Task-13 deliberately-touched regions (all OUTSIDE the spline AND ─────
# OUTSIDE every Task-12 region; the CSS + #intro-fade DOM are instead
# absorbed by the Task-12 CSS/DOM regions above, recipe 2c). Each of the
# THREE below is bounded by a START + END anchor that pre-exists UNCHANGED
# in BOTH ``0689e788`` and the current HTML (verified: each appears
# exactly once in both), so the same [START..END] excises the
# corresponding (smaller) baseline slice and the (Task-13-grown) current
# slice; equal remainders ⇒ no OTHER drift.
#
# (T13-LB) DOM: the (unchanged) ``  <div id="loading">`` open through the
#     (unchanged) ``  <div id="css2d-root"></div>`` line that follows the
#     loading block. Excises the loading screen (now carrying the new
#     #loading-blur backdrop child) + the css2d-root line. In the baseline
#     that span is just the original loading block + css2d-root.
_T13_LB_START = '  <div id="loading">\n'
_T13_LB_END = '  <div id="css2d-root"></div>'
# (T13-AS / T14, MODIFIED IN PLACE again -- recipe 2b) JS: the (unchanged,
#     intentionally-kept-anchor-stable) default-path
#     ``  if (cfg.default_path_id) {`` line through the (unchanged)
#     ``// ---- Bench launchers ...`` comment. In ``0689e788`` this span was
#     the 4-line synchronous autostart + blank; Task 13 grew it in place
#     to the inert marker `if` + the deferred ``_introStartTour()``; TASK
#     14 grows it FURTHER, still in place, to also contain the whole
#     ClipPlayer (the class-like block + _clipStart/_clipFinish + the
#     next-cut prewarm scheduler + the OverlayScene clip layer), the
#     GENERALISED ``_introStartTour`` (clip-sequence when cfg.clips/
#     cfg.cameras present; the byte-behaviourally-identical
#     ``startPath(cfg.default_path_id)`` fallback otherwise -- the
#     no-clips regression) and the Stop-button clip guard. The START
#     anchor is STILL the FIRST line of the region (the `if` is unmoved)
#     so it pre-exists UNCHANGED in BOTH ``842b50f`` and current; ALL
#     Task-13 AND Task-14 additions sit strictly between it and the
#     UNCHANGED END comment. The Task-10 visibilitychange handler sits
#     ABOVE this START and is therefore NOT excised (its survival is
#     asserted below -- the region must never widen to swallow it).
#     NOTE: "inert" here means byte-lock-anchor-stable, NOT dead code --
#     the ``if`` body still runs a live ``selEl.value = cfg.default_path_id;``
#     (a harmless pre-existing duplicate of what the deferred
#     ``_introStartTour()`` also does; the Task-13 spec review independently
#     confirmed there is NO second ``startPath()`` at init, so it is a
#     benign double-set, not a second autostart). Do NOT delete / "clean
#     up" this line thinking it is dead: it is a pinned byte-lock anchor
#     (it is the START anchor itself) and removing/moving it changes the
#     generated HTML and breaks this excision.
_T13_AS_START = "  if (cfg.default_path_id) {\n"
_T13_AS_END = (
    "  // ---- Bench launchers (used by both the URL "
    "auto-trigger and the button) ----"
)
# (T13-IC) JS: the (unchanged) ``  // Resize`` comment through the
#     (unchanged) ``  tick();`` call. In ``0689e788`` this span is just
#     the resize handler + blank; Task 13 inserts the intro-controller
#     IIFE between the resize handler and ``tick()`` (the cinematic
#     loading-blur + #intro-fade fade-out + deferred tour start, fail-safe
#     so a stuck overlay can never trap the scene). Both ends pre-exist
#     unchanged (Task 14 does NOT touch this region).
_T13_IC_START = "  // Resize\n"
_T13_IC_END = "  tick();\n"
# (T14-PW) JS -- NEW additive region (recipe 2a): the next-cut LOD
#     prewarm RETENTION guard-twin (a sibling of the root-chunk eviction
#     guard). START = the (UNCHANGED) root-guard
#     ``console.info('[Splatpipe] root-chunk eviction guard active ...')``
#     line; END = the (UNCHANGED) ``    // ---- Front-load phase (pillar
#     V) ----`` comment. Both pre-exist EXACTLY ONCE in BOTH ``842b50f``
#     and the current HTML, and EVERY Task-14 prewarm-guard line sits
#     strictly between them, so excising [START..END] from ``842b50f``
#     removes ONLY the unchanged bounding lines (root-guard closer +
#     blank + the Front-load comment) while excising it from current
#     removes those SAME bounding lines PLUS the new guard-twin -> equal
#     remainders (the additive-region invariant). ``_excise`` asserts the
#     START unique + the (non-close_after) END unique-after-start, so a
#     future template edit that duplicates/moves either fails LOUD rather
#     than silently mis-excising.
_T14_PW_START = (
    "      console.info('[Splatpipe] root-chunk eviction "
    "guard active (no per-frame re-pin)');\n"
)
_T14_PW_END = "    // ---- Front-load phase (pillar V) ----"

# (T14-AF) JS -- NEW modify-in-place region (recipe 2b). Task-14 review
#     follow-up: ``_autoFocusTick``'s early-return guard is broadened to
#     also skip while a clip tour is active (``_clipMode &&
#     _clipState.active``), so the clip layer owns the LoD origin for the
#     WHOLE tour incl. the single inter-clip cut-transition frame (no
#     1-frame ``spark.lodPosOverride`` churn). The deliberately-touched
#     line(s) sit inside ``_autoFocusTick``'s opening guard block, bounded
#     by the UNCHANGED ``  function _autoFocusTick(now) {`` declaration
#     line (START) and the UNCHANGED ``    if (!_afReady) return;`` line
#     (END). Both pre-exist EXACTLY ONCE in BOTH the ``842b50f`` baseline
#     and the current HTML and the WHOLE [START..END] span is byte-
#     identical between them APART FROM this deliberate change, so excising
#     the SAME [START..END] from BOTH removes the (smaller) baseline guard
#     block and the (broadened) current one -> equal remainders (the 2b
#     invariant). The 6 live single-camera scenes have no cfg.cameras/
#     cfg.clips so ``_clipMode`` is false there: the new disjunct is always
#     false and ``_autoFocusTick`` is byte-runtime-identical to before for
#     them (this is a deliberate, byte-lock-excised change, NOT a
#     regression). ``_excise`` asserts the START unique + the
#     (non-close_after) END unique-after-start, so a future template edit
#     that duplicates/moves either fails LOUD rather than mis-excising.
_T14_AF_START = "  function _autoFocusTick(now) {\n"
_T14_AF_END = "    if (!_afReady) return;"

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
    if close_after is None:
        # Non-close_after path: end_token must be UNIQUE in the region
        # after start_anchor (a duplicate would cause silent under/over-
        # excision of the wrong span — fail loud so a future template
        # edit that adds a duplicate end_token is caught immediately).
        assert _after.count(end_token) == 1, (
            f"excision end_token not unique after start anchor: {end_token!r}"
        )
    else:
        # close_after path intentionally relies on first-match semantics
        # (walk to the first line == close_after after end_token) — only
        # assert presence, not uniqueness.
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
            if j >= len(text):
                raise AssertionError(
                    f"excision close_after {close_after!r} not found (EOF reached)"
                )
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
#      *committed* template (NOT your dirty working tree).
#      Bash (Linux/macOS):
#        git show <HEAD>:src/splatpipe/viewers/spark/template.py > /tmp/t.py
#        python - <<'PY'
#        import hashlib, importlib.util, tempfile, os
#        p=os.path.join(tempfile.gettempdir(),'t.py')
#        s=importlib.util.spec_from_file_location('t',p)
#        m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
#        h=m.html_for('HarnessScene')
#        print(len(h), hashlib.sha256(h.encode()).hexdigest())
#        PY
#      PowerShell (Windows — primary dev platform):
#        # WINDOWS CRLF FOOT-GUN -- READ THIS BEFORE YOU REGEN A PIN:
#        # NEVER do `git show <rev>:<path> > file.py` on Windows.
#        # PowerShell `>` redirection (and/or core.autocrlf=true on the
#        # checkout) injects CRLF into the dumped template -> html_for()
#        # then differs from the LF-only committed bytes -> a WRONG
#        # remainder/full fingerprint. A future Task-14..18 author would
#        # then silently re-pin this byte-lock to a CORRUPT value and the
#        # guard is permanently, silently disabled. The COMMITTED template
#        # is LF-only and this lock is CRLF-sensitive BY DESIGN.
#        #
#        # ROOT CAUSE (do NOT round-trip the template through ANY PowerShell
#        # pipeline): on Windows PowerShell, piping a native command's stdout
#        # (`git show ...`) splits it into an ARRAY OF LINES with their
#        # terminators STRIPPED. So both of these CORRUPT the bytes:
#        #   * `... | Set-Content [-NoNewline]` -- joins the line array with
#        #     NOTHING -> every newline destroyed, plus a UTF-8 BOM is added
#        #     (empirically 189648 -> 185892 bytes, 0 CR, 0 LF, +BOM: the
#        #     dumped module is one line -> import SyntaxError -> html_for()
#        #     cannot even be computed).
#        #   * `... | Out-String` -- re-joins the line array with CRLF, NOT
#        #     the LF-only committed bytes -> wrong fingerprint.
#        # Use a BYTE-FAITHFUL path instead (no PS line-array round-trip):
#        #   (a) PowerShell, byte-exact (process-level redirection):
#        #       Start-Process git -ArgumentList `
#        #         'cat-file blob <HEAD>:src/splatpipe/viewers/spark/template.py' `
#        #         -RedirectStandardOutput "$env:TEMP\t.py" -NoNewWindow -Wait
#        #   (b) or `cmd` (its `>` IS byte-exact, unlike PowerShell `>`):
#        #       cmd /c "git show <HEAD>:src/splatpipe/viewers/spark/template.py > %TEMP%\t.py"
#        #   then run the step-1 `python - ...` snippet against that file.
#        #   (c) or hash TRULY in-process -- read the raw bytes straight from
#        #       `git cat-file blob`/`git show` via a Python subprocess with
#        #       stdout=PIPE and hash those bytes; NEVER capture through any
#        #       PowerShell string handling:
#        #       python - <<'PY'
#        #       import subprocess, hashlib, importlib.util, tempfile, os
#        #       raw = subprocess.run(
#        #           ['git','cat-file','blob',
#        #            '<HEAD>:src/splatpipe/viewers/spark/template.py'],
#        #           stdout=subprocess.PIPE, check=True).stdout  # raw LF-only bytes
#        #       p=os.path.join(tempfile.gettempdir(),'t.py')
#        #       open(p,'wb').write(raw)
#        #       s=importlib.util.spec_from_file_location('t',p)
#        #       m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
#        #       h=m.html_for('HarnessScene')
#        #       print(len(h), hashlib.sha256(h.encode()).hexdigest())
#        #       PY
#        # (Do NOT add a .gitattributes to "fix" this -- repo-wide
#        # line-ending renormalization mid-build is unsafe around the
#        # template.py surgical-staging; this caveat IS the whole fix.)
#   2a. PURELY-ADDITIVE task (like Tasks 8/10): set the baseline LEN/SHA to
#       the step-1 fingerprint, add unique anchors for YOUR new block(s),
#       and EXCISE them from the current HTML; the excised result must equal
#       that pinned baseline byte-for-byte.
#   2b. MODIFY-IN-PLACE task (like Task 11's spline — it rewrites a region
#       rather than only adding lines, so deleting added lines can't
#       reproduce the old bytes): pick stable anchors that PRE-EXIST
#       UNCHANGED in BOTH the baseline and current and bound the WHOLE
#       deliberately-touched region, excise that SAME region from BOTH the
#       step-1 baseline AND the current HTML, and pin the *baseline's*
#       excised LEN/SHA (``_PRE_TASKnn_REMAINDER_*``). The assertion excises
#       the region from the current HTML and compares to that remainder pin
#       → proves every byte OUTSIDE the touched region is byte-identical.
#   2c. REGION-INTERIOR-ONLY change (e.g. the Task-11 ``// LOCKSTEP:``
#       banner; or Task 13's #loading-blur/#intro-fade CSS landing inside
#       the Task-12 CSS region + its #intro-fade DOM root inside the
#       Task-12 DOM region): if a delta lands strictly INSIDE an already-
#       excised region (between that region's START and END), the compared
#       remainder is unaffected BY THAT DELTA → keep that region's anchors
#       UNCHANGED; it is absorbed by the existing excision (the span it
#       bounds simply grew). VERIFY this (don't assume) by recomputing the
#       pin from the prev-HEAD with the SAME anchors and confirming the
#       clean post-task remainder equals it. Do NOT move the START anchor
#       onto a newly-added line: a line that does not exist in the pre-task
#       reference cannot anchor the moving baseline's excision (it would
#       also pull unchanged pre-anchor lines out of the remainder). Keep
#       any new banners/markers BELOW the region START anchor — and if a
#       task adds content that would otherwise sit ABOVE a region's START
#       (as Task 13's deferred-autostart wrapper nearly did), keep the
#       pre-existing START line FIRST and place ALL new content strictly
#       between it and the END (an inert-but-unmoved anchor line is fine).
#       A task whose template delta is PURELY 2c (lands strictly inside an
#       already-excised region) does NOT advance
#       ``_PRE_TASKnn_REMAINDER_*`` / ``_FULL_*`` -- the pins stay
#       byte-identical to the PRIOR task's. If your recomputed remainder
#       differs from the prior pin, your delta leaked OUTSIDE the region:
#       fix the code to stay in-region, do NOT update the pin to match (a
#       moved pin here just re-blesses the leak and disables the guard).
#   2d. MULTI-REGION task (like Task 12 — three regions; or Task 13 —
#       three NEW regions PLUS two deltas absorbed into Task-12 regions per
#       2c): apply the 2b recipe ONCE PER NEW REGION. For each pick a START
#       + END anchor that PRE-EXIST UNCHANGED in BOTH
#       ``git show <prev-HEAD>:…`` and the current HTML (verify each
#       appears exactly once in both — fail-loud is enforced by ``_excise``
#       for the START + non-close_after END). Excise ALL regions (every
#       prior task's region(s) STILL excised with their original anchors so
#       their contract stays asserted-surviving) from BOTH sides and pin
#       the baseline's fully-excised LEN/SHA. Equal remainders ⇒ no OTHER
#       drift. Adding a region only ever NARROWS what is compared, so it
#       must be paired with explicit ``in stripped`` survival asserts for
#       every prior task's anchored content (kept below) — never let the
#       excision swallow a prior contract silently. EMPIRICALLY prove the
#       guard still bites: clean-committed → byte-lock PASSES; dirty tree
#       (a stray uncommitted block OUTSIDE the regions) → byte-lock FAILS
#       (the stray's bytes leak into the remainder → length/SHA mismatch).
#   Each task's pins are the PREVIOUS task's committed output (a moving
#   baseline). Do NOT relax the assertion; the regression INTENT must
#   remain enforced, and prior tasks' anchored blocks must stay
#   asserted-surviving.
def test_defaults_are_regression_safe_existing_scenes_byte_identical():
    """Task 17 (author editor -- bottom timeline: scrub/diamonds/
    transport/zoom/multiselect/scale; plan H2/Task-13) is a PURE
    recipe-2c REGION-INTERIOR-ONLY change: its ENTIRE deliberate delta
    -- the bottom timeline strip DOM/JS injected into the (already-
    existing, Task-12) ``#author-root`` (seconds ruler + OPTIONAL
    fps-RELABEL-only grid + a draggable diamond per keyframe whose
    horizontal drag is an IN-MEMORY temporal edit + a live-scrub
    playhead routed through the EXISTING ``#path-scrub`` real input
    mechanism + transport reuse + wheel zoom + box-multiselect +
    selection-edge proportional ``t``-span scale + X-delete) PLUS the
    ``Object.assign`` EXTENSION of the Task-16 TEST-ONLY
    ``window.__editor`` surface -- lands STRICTLY INSIDE the EXISTING
    Task-16 T16-TRAJ region (between the UNCHANGED
    ``  applySplatBudget(_initialBudget);`` START and the UNCHANGED
    ``  // ---- Frame loop ----`` END, immediately AFTER the Task-16
    ``window.__editor`` literal). It adds NO new region and NO delta
    OUTSIDE T16-TRAJ (no CSS region -- inline-styled like #sp-hud / the
    Task-16 toggle; ``#author-root`` already exists; the spline /
    player / #path-scrub / clip / transport code is REUSED, never
    modified), so excising the SAME ELEVEN regions reproduces the
    ``c1d5801`` committed template's SAME eleven-region excision
    byte-for-byte and the ``_PRE_TASK17_REMAINDER_*`` pin is
    byte-IDENTICAL to ``_PRE_TASK16_REMAINDER_*`` (the 2c invariant --
    the T16-TRAJ excision simply now removes a LARGER span; a
    changed remainder would mean the timeline LEAKED outside). The
    whole block is AUTHOR-MODE-gated (the SAME ``_EDITOR_AUTHOR`` =
    ``ModeManager.is('author')`` flag the Task-16 overlay uses + the
    strip DOM only ever built in author mode + the OverlayScene
    ``_tlLayer`` ``modes:['author']``) so for ``"HarnessScene"`` (NOT
    author mode -- like the 6 live single-camera scenes) it produces
    ZERO rendered-HTML delta OUTSIDE T16-TRAJ and is byte-runtime-
    inert: a DELIBERATE, byte-lock-excised change, NOT a regression.
    PERSISTENCE IS NOT TASK-17: nothing here writes/saves; the Task-8
    SAVE_* contract is asserted-surviving (the timeline mutates only
    the IN-MEMORY active path + rebuilds the spline). The Task-17
    timeline surface is asserted present-in-full-html then
    gone-after-the-T16-TRAJ-excision (hard proof it is wholly inside
    that region, not leaking); every prior task's anchored content
    stays asserted-surviving (the excision only ever NARROWS what is
    compared -- never relaxed).

    Prior moving-baseline provenance (Task 16, kept): Task 16 (author
    editor -- viewport trajectory + camera frustums +
    speed dots; the FIRST author-mode overlay, plan H2/Task-12) is
    PURELY ADDITIVE: ONE NEW region (T16-TRAJ, recipe 2a) bounding ONLY
    the new author-overlay block (the trajectory THREE.Group + the
    _trajRebuild/_trajRefreshActive/_trajMakeFrustum helpers + the
    OverlayScene ``_trajLayer`` registration + the "Show trajectory"
    #author-root inline-styled toggle + the TEST-ONLY ``window.__editor``
    surface), bounded by the UNCHANGED
    ``  applySplatBudget(_initialBudget);`` line (START) and the
    UNCHANGED ``  // ---- Frame loop ----`` comment (END) -- BOTH
    pre-exist EXACTLY ONCE in BOTH the ``cfb0835`` baseline and the
    current HTML, and in ``cfb0835`` the ONLY content between them is a
    single blank line (zero foreign code -- the T14-PW-style additive
    invariant). Excising every deliberately-touched region (the Task-11
    spline + the three Task-12 + the three Task-13 + the two Task-14
    + the Task-15 T15-OB + the NEW Task-16 T16-TRAJ, each bounded by
    anchors that pre-exist UNCHANGED and appear exactly once in BOTH
    ``cfb0835`` and the current HTML) from the current generated HTML
    must reproduce the ``cfb0835`` committed template's SAME ten-region
    excision byte-for-byte (same length, same SHA-256). The whole
    Task-16 block is AUTHOR-MODE-gated (ModeManager.is('author') + the
    OverlayScene layer's modes:['author']) so for ``"HarnessScene"``
    (NOT author mode -- like the 6 live single-camera scenes) it
    produces ZERO rendered-HTML delta OUTSIDE T16-TRAJ and is
    byte-runtime-inert: a DELIBERATE, byte-lock-excised change, NOT a
    regression. Every prior task's anchored content (Task 8 SAVE_*,
    Task 10 blocks, Task 11-15 regions) stays asserted-surviving below
    (the new region only NARROWS what is compared -- never relaxed).

    Prior moving-baseline provenance (Task 15, kept): Task 15 (end-user
    transport -- click-interrupt + bottom resume + per-shot idle
    auto-orbit) is the cinematic end-user shell's
    interaction layer. It touches TWO regions: (T13-AS, MODIFIED-IN-PLACE
    AGAIN, recipe 2b) the SAME unchanged ``if (cfg.default_path_id) {``
    START / ``// ---- Bench launchers ...`` END that bounded Task 13's
    deferred autostart and Task 14's whole ClipPlayer now ALSO bounds the
    end-user transport block (``IDLE_MS`` + the shared
    ``_orbitPathAround`` orbit-math helper + ``_stopTour``/
    ``_resumeTour``/``_startIdleOrbit``/``_cancelIdleOrbit`` + the
    ``#user-play`` button injected into the Task-12 ``#user-transport``
    root + the interrupt/input listeners + the ``_transportLayer`` fanned
    out from the ONE OverlayScene tick + the ``window.__transport`` test
    surface); (T15-OB, NEW modify-in-place region, recipe 2b)
    ``_buildOrbitPath`` refactored from an inline Y-spin loop into a pure
    delegation to the shared ``_orbitPathAround`` helper (declared in the
    grown T13-AS region, hoisted), passing the SAME center
    (``_origTarget``) / base pose / ``n:36`` / ``secs:30`` /
    ``loop:false`` the bench has always produced so the generated orbit
    is byte-BEHAVIOURALLY identical for the 6 live scenes' Bench: Orbit
    -- a pure refactor; bounded by the UNCHANGED
    ``  function _buildOrbitPath() {`` declaration line (START) and the
    UNCHANGED ``  async function _runOrbitBench() {`` declaration line
    (END). Excising every deliberately-touched region (the Task-11 spline
    + the three Task-12 regions + the three Task-13 regions + the two
    Task-14 regions + the new Task-15 T15-OB region, each bounded by
    anchors that pre-exist UNCHANGED and appear exactly once in BOTH the
    ``7acdd39`` baseline and the current HTML) from the current generated
    HTML must reproduce the ``7acdd39`` committed template's SAME
    nine-region excision byte-for-byte (same length, same SHA-256) --
    hard proof every byte OUTSIDE those nine regions (the six live
    scenes' post-load RENDERING, Task 8's SAVE_* block, Task 10's two
    blocks, Task 11's spline, Task 12's dual-UI, Task 13's cinematic
    shell, Task 14's ClipPlayer + prewarm + auto-focus guard) is
    untouched. Every Task-15 entry point bails immediately when
    ``ModeManager.is('user')`` is false OR (for the idle orbit) when
    ``_clipMode`` is false, so author/embed AND the six live single-
    camera scenes are byte-runtime-unchanged -- the end-user transport is
    a DELIBERATE, byte-lock-excised change (plan SS-A3 / D-Task-11), NOT
    a regression for them. Task 8's SAVE_* + Task 10's blocks live
    OUTSIDE all nine regions, so they survive the excision and are
    explicitly asserted-present here (their contracts stay pinned --
    never relaxed).
    """
    import hashlib

    html = html_for("HarnessScene")

    # Sanity: prior tasks' anchored content must STILL be present and intact
    # in the FULL html before any excision.
    assert 'const SAVE_MODE = "cli";' in html          # Task 8
    assert 'const SAVE_ENDPOINT = "";' in html          # Task 8
    assert _INSERT_ANCHOR in html                        # Task 8
    assert "_hidAt" in html                              # Task 10 BLOCK A
    assert "visibilitychange" in html                    # Task 10 BLOCK B
    assert "class CubicSpline" in html                   # Task 11 spline
    # Task 12's deliberate additions ARE present (gated below by mode class).
    assert 'id="author-root"' in html                    # Task 12 DOM root
    assert 'id="user-transport"' in html                 # Task 12 DOM root
    assert "body.usermode #author-root" in html          # Task 12 CSS gate
    assert "body.authormode #user-transport" in html     # Task 12 CSS gate
    # Task 13's deliberate additions ARE present (gated below by mode class
    # / driven by the intro controller).
    assert 'id="loading-blur"' in html                    # Task 13 DOM
    assert 'id="intro-fade"' in html                       # Task 13 DOM
    assert "body.usermode #loading-blur" in html           # Task 13 CSS gate
    assert "function _introStartTour" in html              # Task 13/14 AS
    assert "Intro controller (Task 13" in html             # Task 13 IIFE
    # Task 14's deliberate additions ARE present (the ClipPlayer lives in
    # the grown T13-AS region; the prewarm guard-twin in the new T14-PW
    # region; the broadened auto-focus guard in the new T14-AF region --
    # all excised below, so they must be present here first).
    assert "ClipPlayer (Task 14" in html                   # Task 14 ClipPlayer
    assert "function _clipStart" in html                   # Task 14 ClipPlayer
    assert "window.__clip" in html                          # Task 14 surface
    assert "__spClipPrewarmGuard" in html                   # Task 14 prewarm
    assert "next-cut prewarm retention guard active" in html  # Task 14 T14-PW
    # T14-AF region boundary: ``_autoFocusTick``'s declaration line
    # pre-exists in BOTH ``7acdd39`` and current (Task 14 did NOT add the
    # function -- the review follow-up only BROADENS its existing guard,
    # recipe 2b). Asserted present here (so the region excised below has
    # something to remove) then asserted gone after the excision. The
    # broadened-guard line CONTENT itself is Minor-1 RUNTIME behaviour and
    # is verified by the Playwright keyframe-editor harness, NOT pinned
    # here -- pinning it would wrongly fail the byte-lock when template.py
    # is reverted/stashed (the 2b region is what makes the byte compare
    # invariant to that change, by design).
    assert "function _autoFocusTick" in html               # Task 14 T14-AF
    # Task 15's deliberate additions ARE present (the end-user transport
    # block lives in the grown T13-AS region; ``_buildOrbitPath`` is
    # refactored to delegate in the T15-OB region -- all excised below,
    # so they must be present here first). ``window.__transport`` is the
    # Task-15 test surface (mirrors ``window.__clip``); ``#user-play`` is
    # the bottom resume control; ``_orbitPathAround`` is the shared
    # orbit-math helper BOTH the bench and the idle auto-orbit reuse.
    assert "End-user transport (Task 15" in html           # Task 15 T13-AS
    assert "function _orbitPathAround" in html              # Task 15 shared math
    assert "function _stopTour" in html                     # Task 15 interrupt
    assert "function _resumeTour" in html                   # Task 15 resume
    assert "function _startIdleOrbit" in html               # Task 15 idle orbit
    assert "window.__transport" in html                     # Task 15 surface
    assert 'id="user-play"' not in html  # button id is set via JS .id (not literal markup)
    assert "_userPlayBtn.id = 'user-play'" in html          # Task 15 #user-play
    # ``_buildOrbitPath`` now DELEGATES to the shared helper (T15-OB). The
    # delegation CALL is the deliberately-touched content; asserted
    # present here, asserted gone after the T15-OB excision below.
    assert "return _orbitPathAround(" in html               # Task 15 T15-OB
    # Task 16's deliberate additions ARE present (the WHOLE author-overlay
    # block lives in the NEW T16-TRAJ region, recipe 2a -- excised below,
    # so it must be present here first). ``window.__editor`` is the
    # Task-16 TEST-ONLY surface (mirrors ``window.__clip`` /
    # ``__transport``); ``editor-trajectory`` is the OverlayScene layer
    # id / group name; ``_trajRebuild`` builds the polyline+frusta+dots;
    # ``Author editor -- viewport trajectory`` is the section banner.
    assert "Author editor -- viewport trajectory" in html   # Task 16 banner
    assert "function _trajRebuild" in html                   # Task 16 build
    assert "function _trajMakeFrustum" in html               # Task 16 frustum
    assert "OverlayScene.register(_trajLayer)" in html        # Task 16 layer
    assert "window.__editor" in html                          # Task 16 surface
    assert "editor-traj-toggle" in html                       # Task 16 toggle
    # Task 17's deliberate additions ARE present (the WHOLE bottom
    # timeline block lives STRICTLY INSIDE the Task-16 T16-TRAJ region,
    # recipe 2c -- it is excised together WITH T16-TRAJ below, so it
    # must be present here first then gone after that excision; that
    # present-then-gone pair is the hard proof the timeline is wholly
    # inside T16-TRAJ and leaks NOTHING outside it). ``editor-timeline``
    # is the strip's element id; ``function _tlInit`` is the timeline
    # IIFE; ``function _tlDraw`` renders the ruler+diamonds+playhead;
    # ``_tlScrubToTime`` routes the live scrub through the EXISTING
    # ``#path-scrub`` real input mechanism (single source of truth --
    # robust to the author-mode auto-tour); ``tlScaleSelection`` is the
    # box-select + edge-drag proportional span-rescale hook;
    # ``Author editor -- bottom timeline`` is the section banner.
    assert "Author editor -- bottom timeline" in html          # Task 17 banner
    assert "function _tlInit" in html                           # Task 17 IIFE
    assert "function _tlDraw" in html                           # Task 17 render
    assert "_tlScrubToTime" in html                             # Task 17 scrub
    assert "OverlayScene.register(_tlLayer)" in html            # Task 17 tick
    assert "editor-timeline" in html                            # Task 17 strip
    assert "tlScaleSelection" in html                           # Task 17 hook
    # Task-17 is PURE recipe-2c: it adds NO new region. The Task-8
    # SAVE_* contract is the persistence boundary the spec hard-draws
    # (Task-17 wires NO save) -- assert it is still present in the FULL
    # html (it survives the excision too; the OUTSIDE-all-regions
    # survival is re-asserted post-excision below -- never relaxed).
    assert 'const SAVE_MODE = "cli";' in html              # Task 8 (T17 no-save)
    assert 'const SAVE_ENDPOINT = "";' in html              # Task 8 (T17 no-save)

    # Excise the ELEVEN deliberately-touched regions. The Task-11 spline
    # first (its ORIGINAL anchors, unchanged by Tasks 12-16 -- keeps
    # Task-11's contract asserted-surviving against the moved ``cfb0835``
    # baseline), then each Task-12 region, then each Task-13 region
    # (T13-AS now GROWN by Task 14 AND 15, same anchors), then the
    # Task-14 prewarm guard-twin region (T14-PW), then the Task-14
    # review-follow-up auto-focus guard region (T14-AF, recipe 2b
    # modify-in-place), then the Task-15 ``_buildOrbitPath`` delegation
    # region (T15-OB, recipe 2b modify-in-place), then the NEW Task-16
    # author-overlay region (T16-TRAJ, recipe 2a additive). Every
    # START/END anchor pre-exists UNCHANGED and exactly once in both the
    # ``cfb0835`` baseline and current, so the same [START..END] removes
    # the corresponding baseline slice and the grown/added/modified
    # current slice; ``_excise`` asserts each START unique + each
    # non-close_after END unique-after-start (fail-loud on a
    # duplicate/missing anchor). The Task-15 transport block sits in the
    # grown T13-AS region (same anchors as Task 13/14, unmoved START);
    # T15-OB is disjoint from and textually AFTER T13-AS so excising
    # T13-AS first never disturbs T15-OB's anchors. T16-TRAJ is disjoint
    # from and textually AFTER both (its START
    # ``  applySplatBudget(_initialBudget);`` is in the splat-budget
    # init block, well below the bench/transport code) so the prior
    # excisions never disturb its anchors, and its bounded baseline
    # interior is a single blank line (the additive invariant).
    stripped = _excise(
        html, _SPLINE_REGION_START, _SPLINE_REGION_END_TOK,
        close_after=_SPLINE_REGION_CLOSE_AFTER,
    )
    stripped = _excise(stripped, _T12_CSS_START, _T12_CSS_END)
    stripped = _excise(stripped, _T12_DOM_START, _T12_DOM_END)
    stripped = _excise(stripped, _T12_MM_START, _T12_MM_END)
    stripped = _excise(stripped, _T13_LB_START, _T13_LB_END)
    stripped = _excise(stripped, _T13_AS_START, _T13_AS_END)
    stripped = _excise(stripped, _T13_IC_START, _T13_IC_END)
    stripped = _excise(stripped, _T14_PW_START, _T14_PW_END)
    stripped = _excise(stripped, _T14_AF_START, _T14_AF_END)
    stripped = _excise(stripped, _T15_OB_START, _T15_OB_END)
    stripped = _excise(stripped, _T16_TRAJ_START, _T16_TRAJ_END)

    # The ENTIRE spline region must be gone → that excision spanned exactly
    # the deliberately-touched code (a leftover means it under-cut and the
    # byte compare below would be meaningless / weakened).
    assert "class CubicSpline" not in stripped
    assert "function buildPlayer" not in stripped
    assert "calcKnots" not in stripped
    assert "_kfMeta" not in stripped
    assert "KF_AUTO_CLAMPED" not in stripped
    # The THREE Task-12 regions must also be fully gone (their excisions
    # spanned exactly the deliberately-touched code, not a byte more/less).
    assert 'id="author-root"' not in stripped            # Task 12 DOM gone
    assert 'id="user-transport"' not in stripped          # Task 12 DOM gone
    assert "body.usermode #author-root" not in stripped   # Task 12 CSS gone
    assert "body.authormode #user-transport" not in stripped
    assert "body.embed #author-root" not in stripped      # CSS strip tail
    assert "'authormode' : 'usermode'" not in stripped    # Task 12 MM gone
    # The THREE Task-13 regions + the two deltas absorbed into the Task-12
    # CSS/DOM regions must ALSO be fully gone (their excisions spanned
    # exactly the deliberately-touched code, not a byte more/less). If any
    # leftover remained the byte compare below would be weakened/meaningless.
    assert 'id="loading-blur"' not in stripped            # Task 13 DOM gone
    assert 'id="intro-fade"' not in stripped               # Task 13 DOM gone
    assert "body.usermode #loading-blur" not in stripped   # Task 13 CSS gone
    assert "#intro-fade.faded" not in stripped             # Task 13 CSS gone
    assert "function _introStartTour" not in stripped      # Task 13/14 AS gone
    assert "_introTourStarted" not in stripped             # Task 13/14 AS gone
    assert "Intro controller (Task 13" not in stripped     # Task 13 IIFE gone
    assert "_beginFade" not in stripped                    # Task 13 IIFE gone
    # The Task-14 ClipPlayer (inside the grown T13-AS region) + the
    # prewarm guard-twin (the new T14-PW region) must ALSO be fully gone --
    # their excisions spanned exactly the deliberately-touched code, not a
    # byte more/less (a leftover would weaken/void the byte compare below).
    assert "ClipPlayer (Task 14" not in stripped           # T13-AS grown gone
    assert "function _clipStart" not in stripped           # ClipPlayer gone
    assert "function _buildClipPlayer" not in stripped     # ClipPlayer gone
    assert "window.__clip" not in stripped                  # surface gone
    assert "_clipPrewarm" not in stripped                   # prewarm gone
    assert "__spClipPrewarmGuard" not in stripped           # T14-PW gone
    assert ("next-cut prewarm retention guard active"
            not in stripped)                                # T14-PW gone
    # The Task-14 review-follow-up auto-focus guard region (T14-AF) must
    # ALSO be fully gone -- its excision spanned exactly the
    # ``_autoFocusTick`` guard block (declaration line through the
    # unchanged ``if (!_afReady) return;`` END), not a byte more/less.
    # ``function _autoFocusTick`` (the START anchor line's content) is
    # unique to this region; its absence proves the region excised
    # cleanly. (The ``_autoFocusTick(...)`` CALL site in the render loop
    # is OUTSIDE T14-AF and correctly survives -- not asserted gone.)
    assert "function _autoFocusTick" not in stripped       # T14-AF gone
    # The Task-15 end-user transport (inside the grown T13-AS region) +
    # the T15-OB ``_buildOrbitPath`` delegation must ALSO be fully gone --
    # their excisions spanned exactly the deliberately-touched code, not a
    # byte more/less (a leftover would weaken/void the byte compare
    # below). ``function _orbitPathAround`` (declared in T13-AS),
    # ``window.__transport`` (the T13-AS test surface), the ``#user-play``
    # id assignment, and ``function _buildOrbitPath`` (the T15-OB
    # definition) + its ``return _orbitPathAround(`` delegation are each
    # unique to their region; their absence proves both excised cleanly.
    assert "End-user transport (Task 15" not in stripped   # T13-AS grown gone
    assert "function _orbitPathAround" not in stripped     # T13-AS shared math gone
    assert "function _stopTour" not in stripped            # T13-AS interrupt gone
    assert "function _resumeTour" not in stripped          # T13-AS resume gone
    assert "function _startIdleOrbit" not in stripped      # T13-AS idle gone
    assert "window.__transport" not in stripped             # T13-AS surface gone
    assert "_userPlayBtn.id = 'user-play'" not in stripped  # T13-AS #user-play gone
    assert "function _buildOrbitPath" not in stripped      # T15-OB defn gone
    assert "return _orbitPathAround(" not in stripped      # T15-OB delegation gone
    # The ``_buildOrbitPath()`` CALL sites (in _runOrbitBench / the
    # preload IIFE) are OUTSIDE T15-OB and correctly SURVIVE -- only the
    # definition was the deliberately-touched code (proves T15-OB did not
    # over-cut into the unrelated bench/preload call sites).
    assert "const orbitPath = _buildOrbitPath();" in stripped  # call site kept
    # The NEW Task-16 author-overlay region (T16-TRAJ, recipe 2a
    # additive) must ALSO be fully gone -- its excision spanned exactly
    # the deliberately-touched author-overlay block (the START line
    # ``applySplatBudget(_initialBudget);`` through the unchanged
    # ``// ---- Frame loop ----`` END), not a byte more/less.
    # ``window.__editor`` (the test surface), ``function _trajRebuild``
    # / ``function _trajMakeFrustum`` (the build helpers),
    # ``OverlayScene.register(_trajLayer)`` (the layer registration)
    # and the ``Author editor -- viewport trajectory`` banner are each
    # unique to this region; their absence proves it excised cleanly.
    assert "Author editor -- viewport trajectory" not in stripped  # T16 gone
    assert "function _trajRebuild" not in stripped         # T16 build gone
    assert "function _trajMakeFrustum" not in stripped     # T16 frustum gone
    assert ("OverlayScene.register(_trajLayer)"
            not in stripped)                                # T16 layer gone
    assert "window.__editor" not in stripped                # T16 surface gone
    assert "editor-traj-toggle" not in stripped             # T16 toggle gone
    # The Task-17 bottom-timeline block (recipe 2c -- it lands STRICTLY
    # INSIDE the SAME T16-TRAJ region, immediately after the Task-16
    # ``window.__editor`` literal and before the ``// ---- Frame loop
    # ----`` END) is therefore excised TOGETHER WITH T16-TRAJ above:
    # its surface MUST be gone too. ``editor-timeline`` (the strip id),
    # ``function _tlInit`` / ``function _tlDraw`` (the timeline IIFE +
    # renderer), ``_tlScrubToTime`` (the live-scrub-via-#path-scrub
    # router), ``OverlayScene.register(_tlLayer)`` (the per-frame
    # playhead-sync layer), ``tlScaleSelection`` (the span-rescale
    # hook) and the ``Author editor -- bottom timeline`` banner are
    # each UNIQUE to the Task-17 block; their absence proves the
    # timeline is WHOLLY inside T16-TRAJ and leaks NOTHING into the
    # compared remainder (the recipe-2c invariant -- if ANY Task-17
    # line had leaked outside T16-TRAJ it would still be in ``stripped``
    # here AND the LEN/SHA pin below would mismatch). This is the
    # present-then-gone pair that makes the 2c absorption hard-proven,
    # NOT assumed.
    assert "Author editor -- bottom timeline" not in stripped  # T17 gone
    assert "function _tlInit" not in stripped              # T17 IIFE gone
    assert "function _tlDraw" not in stripped              # T17 render gone
    assert "_tlScrubToTime" not in stripped                # T17 scrub gone
    assert ("OverlayScene.register(_tlLayer)"
            not in stripped)                                # T17 layer gone
    assert "editor-timeline" not in stripped               # T17 strip gone
    assert "tlScaleSelection" not in stripped              # T17 hook gone
    # The T16-TRAJ START anchor LINE is excised WITH the region, but
    # ``applySplatBudget`` (the FUNCTION, defined far above) and the
    # ``// ---- Frame loop ----`` END comment are themselves removed too
    # (START..END inclusive); the splat-budget machinery just ABOVE the
    # START (the URL_BUDGET / pickDefaultBudget wiring) is OUTSIDE
    # T16-TRAJ and MUST survive (proves T16-TRAJ did not widen upward
    # into the pre-existing splat-budget init).
    assert "function applySplatBudget" in stripped         # budget fn kept
    assert "pickDefaultBudget" in stripped                  # budget init kept
    # Regression-critical: the root-chunk eviction guard itself is the
    # T14-PW START anchor LINE, so it is excised WITH the region -- but its
    # SIBLING machinery just ABOVE the START (the PINNED_ROOT_CHUNK_COUNT
    # wrap) is OUTSIDE T14-PW and MUST survive (proves T14-PW did not widen
    # upward into the pre-existing root guard).
    assert "PINNED_ROOT_CHUNK_COUNT" in stripped           # root guard kept
    assert "__spRootGuard" in stripped                      # root guard kept
    # ...while prior tasks' anchored content (OUTSIDE all nine regions) is
    # UNTOUCHED by the excisions (proves we removed only the deliberate
    # regions, not Task 8's / Task 10's baseline content -- they must
    # survive; if a future excision widens to swallow one of these this
    # FAILS loudly rather than silently dropping a prior contract). The
    # Task-10 visibilitychange handler in particular sits ABOVE the Task-13
    # autostart region START and must NOT be swallowed by it.
    assert 'const SAVE_MODE = "cli";' in stripped        # Task 8 survives
    assert 'const SAVE_ENDPOINT = "";' in stripped        # Task 8 survives
    assert _INSERT_ANCHOR in stripped                     # Task 8 survives
    assert "_hidAt" in stripped                           # Task 10 survives
    assert "visibilitychange" in stripped                 # Task 10 survives

    # Byte-for-byte identical to the ``c1d5801`` committed template with
    # the SAME ELEVEN regions excised -> NO unintended drift anywhere
    # outside the deliberate Task-8/10/11/12/13/14/15/16/17 changes
    # (FAILS loudly if e.g. a stray uncommitted block elsewhere in the
    # template leaked in -- this is exactly how the 4 unstaged strays
    # are kept out of the Task-17 commit; the pagedExtSplats stray,
    # OUTSIDE all eleven regions, makes this FAIL in the dirty tree BY
    # DESIGN -> the guard still bites). Task 17 (the author bottom
    # timeline -- scrub/diamonds/transport/zoom/multiselect/scale) is a
    # PURE recipe-2c change: its ENTIRE deliberate delta lands STRICTLY
    # INSIDE the EXISTING Task-16 T16-TRAJ region (so that region's
    # excision now removes a LARGER span -- the Task-16 author overlay
    # PLUS the Task-17 timeline -- and the ELEVEN-region REMAINDER is
    # byte-IDENTICAL to the Task-16 one; ``_PRE_TASK17_REMAINDER_*`` ==
    # ``_PRE_TASK16_REMAINDER_*`` BY the 2c invariant, NOT by accident
    # -- a changed remainder here would mean the timeline LEAKED outside
    # T16-TRAJ). It is a DELIBERATE, byte-lock-excised change -- NOT a
    # regression for the 6 live single-camera scenes: they are NOT
    # author mode, so the SAME ``_EDITOR_AUTHOR`` /
    # ``ModeManager.is('author')`` gate the Task-16 overlay uses + the
    # strip DOM only ever built in author mode + the ``_tlLayer``
    # ``modes:['author']`` make the whole timeline byte-runtime-inert
    # for them (and the byte-lock proves their generated HTML is
    # byte-identical OUTSIDE T16-TRAJ). PERSISTENCE is NOT Task-17:
    # SAVE_MODE / SAVE_ENDPOINT are asserted-surviving (re-pinned just
    # above) -- the timeline mutates only the IN-MEMORY active path +
    # rebuilds the spline, it wires no save.
    assert len(stripped) == _PRE_TASK17_REMAINDER_LEN, (
        f"length drift: {len(stripped)} != {_PRE_TASK17_REMAINDER_LEN} "
        "(an UNINTENDED change leaked OUTSIDE the eleven deliberate "
        "regions -- e.g. a Task-17 timeline line escaped the Task-16 "
        "T16-TRAJ region the 2c recipe requires it to stay inside)"
    )
    assert (
        hashlib.sha256(stripped.encode()).hexdigest()
        == _PRE_TASK17_REMAINDER_SHA
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
