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

# --- Moving baseline (Task 14) -------------------------------------------
# The byte-identity guard pins the PREVIOUS task's COMMITTED generated
# output and asserts the only delta is THIS task's deliberate change. The
# baseline therefore moves forward one commit each task (see the regen
# recipe below). For Task 14 the pinned baseline is the committed template
# at HEAD ``842b50f`` (the commit BEFORE Task 14's edit -- i.e. Task 13
# committed) -- which ALREADY contains Task 8's inert SAVE_* block, Task
# 10's two visibilitychange blocks, Task 11's in-place spline change,
# Task 12's three dual-UI regions AND Task 13's three regions (loading-
# blur DOM, deferred autostart, intro IIFE). ``html_for("HarnessScene")``
# there is 183025 bytes.
#
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
    """Task 14 (multi-camera Camera-Cuts tour + next-cut LOD pre-warm,
    plus its review follow-up) generalises the single deferred default-
    path autostart into an ordered ``ClipPlayer`` sequence, adds a next-
    cut LOD prewarm guard-twin, and broadens ``_autoFocusTick``'s guard
    so the clip layer owns the LoD origin for the whole tour. It touches
    THREE regions: (T13-AS, MODIFIED-IN-PLACE again, recipe 2b) the
    deferred-autostart region -- the SAME unchanged
    ``if (cfg.default_path_id) {`` START / ``// ---- Bench launchers ...``
    END that bounded Task 13's deferred autostart now also bounds the
    whole ClipPlayer + the generalised ``_introStartTour`` + the Stop-
    button clip guard; (T14-PW, NEW additive region, recipe 2a) the next-
    cut LOD prewarm retention guard-twin, inserted strictly between the
    UNCHANGED root-chunk-guard ``console.info('... root-chunk eviction
    guard active ...')`` line and the UNCHANGED ``// ---- Front-load
    phase (pillar V) ----`` line; and (T14-AF, NEW modify-in-place
    region, recipe 2b -- the review follow-up) the broadened
    ``_autoFocusTick`` early-return guard, bounded by the UNCHANGED
    ``  function _autoFocusTick(now) {`` declaration line and the
    UNCHANGED ``    if (!_afReady) return;`` line. Excising every
    deliberately-touched region (the Task-11 spline + the three Task-12
    regions + the three Task-13 regions + the two new Task-14 regions,
    each bounded by anchors that pre-exist UNCHANGED and appear exactly
    once in BOTH the ``842b50f`` baseline and the current HTML) from the
    current generated HTML must reproduce the ``842b50f`` committed
    template's SAME nine-region excision byte-for-byte (same length, same
    SHA-256) -- hard proof every byte OUTSIDE those nine regions (the six
    live scenes' post-load RENDERING, Task 8's SAVE_* block, Task 10's
    two blocks, Task 11's spline, Task 12's dual-UI, Task 13's cinematic
    shell) is untouched. The six live single-camera scenes have NO
    cfg.clips/cfg.cameras so the generalised ``_introStartTour`` takes
    the byte-behaviourally-identical ``startPath(cfg.default_path_id)``
    fallback AND ``_clipMode`` is false there so the broadened
    ``_autoFocusTick`` disjunct is always false -- the multi-camera tour
    (and its auto-focus guard follow-up) is a DELIBERATE, byte-lock-
    excised change (plan SS-C), NOT a regression for them. Task 8's
    SAVE_* + Task 10's blocks live OUTSIDE all nine regions, so they
    survive the excision and are explicitly asserted-present here (their
    contracts stay pinned -- never relaxed).
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
    # pre-exists in BOTH ``842b50f`` and current (Task 14 did NOT add the
    # function -- the review follow-up only BROADENS its existing guard,
    # recipe 2b). Asserted present here (so the region excised below has
    # something to remove) then asserted gone after the excision. The
    # broadened-guard line CONTENT itself is Minor-1 RUNTIME behaviour and
    # is verified by the Playwright keyframe-editor harness (Task 14(d)),
    # NOT pinned here -- pinning it would wrongly fail the byte-lock when
    # template.py is reverted/stashed (the 2b region is what makes the
    # byte compare invariant to that change, by design).
    assert "function _autoFocusTick" in html               # Task 14 T14-AF

    # Excise the NINE deliberately-touched regions. The Task-11 spline
    # first (its ORIGINAL anchors, unchanged by Tasks 12/13/14 -- keeps
    # Task-11's contract asserted-surviving against the moved ``842b50f``
    # baseline), then each Task-12 region, then each Task-13 region
    # (T13-AS now GROWN by Task 14, same anchors), then the NEW Task-14
    # prewarm guard-twin region (T14-PW), then the NEW Task-14 review-
    # follow-up auto-focus guard region (T14-AF, recipe 2b modify-in-
    # place). Every START/END anchor pre-exists UNCHANGED and exactly once
    # in both the ``842b50f`` baseline and current, so the same
    # [START..END] removes the corresponding (smaller) baseline slice and
    # the grown/added/modified current slice; ``_excise`` asserts each
    # START unique + each non-close_after END unique-after-start (fail-
    # loud on a duplicate/missing anchor).
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

    # Byte-for-byte identical to the ``842b50f`` committed template with
    # the SAME nine regions excised -> NO unintended drift anywhere outside
    # the deliberate Task-8/10/11/12/13/14 changes (FAILS loudly if e.g. a
    # stray uncommitted block elsewhere in the template leaked in -- this
    # is exactly how the 4 unstaged strays are kept out of the Task-14
    # commit; the pagedExtSplats stray, OUTSIDE all nine regions, makes
    # this FAIL in the dirty tree BY DESIGN -> the guard still bites).
    assert len(stripped) == _PRE_TASK14_REMAINDER_LEN, (
        f"length drift: {len(stripped)} != {_PRE_TASK14_REMAINDER_LEN} "
        "(an UNINTENDED change leaked OUTSIDE the nine deliberate regions)"
    )
    assert (
        hashlib.sha256(stripped.encode()).hexdigest()
        == _PRE_TASK14_REMAINDER_SHA
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
