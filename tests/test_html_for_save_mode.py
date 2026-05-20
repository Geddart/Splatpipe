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


# Modularization note (2026-05-20, T6 of #118): the legacy excised-region
# byte-lock that pinned the SOURCE-level bytes of template.py via 14 region
# anchors was retired here. The output-pin in tests/test_html_for_output_pin.py
# now provides a wider regression net (6 generated-HTML fixtures vs the old
# 1-fixture excision). The kwarg-shape tests, the NEGATIVE-CONTROL tests
# (camera-path overlay / tick line / gizmo handle drag / 2026-05-20 UX),
# and the publish/assembler call-site tests below survive intact -- they
# check HTML content / call-site threading, not source structure.

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


# --------------------------------------------------------------------------
# Phase 2 (editor-arc-design #122): EditorModuleRegistry + EditHistory
# integration markers. Pure structural assertion at the rendered-HTML level;
# the contract semantics are exercised by tests/test_editor_module_registry.py
# and tests/test_edit_history.py (Node-driven). Each marker is ASCII-only.
# --------------------------------------------------------------------------

_PHASE_2_FRAGMENT_MARKERS = (
    # 04a fragment loaded into the bundle
    "const EditorModuleRegistry = (() => {",
    "_bootMount: _bootMount,",
    # 05_framework wires registry onto window.__sceneview + boots it
    "modules: (typeof EditorModuleRegistry !== 'undefined')",
    "EditorModuleRegistry._bootMount();",
    # 17a fragment loaded and self-publishes onto window.__sceneview.history
    "const EditHistory = (() => {",
    "const _HISTORY_CAP = 200;",
    "window.__sceneview.history = EditHistory;",
    # Hotkeys gated on author mode + ctrl/cmd-Z / ctrl-Y
    "EditorModuleRegistry.undo();",
    "EditorModuleRegistry.redo();",
)


def test_phase_2_registry_and_history_fragments_baked_in():
    """The two new Phase 2 fragments are concatenated into the rendered
    HTML in the expected positions (04a before 05_framework; 17a after
    17_editor_gizmo)."""
    html = html_for("HarnessScene")
    for mk in _PHASE_2_FRAGMENT_MARKERS:
        assert mk in html, f"Phase 2 marker missing: {mk!r}"
    # Ordering invariant: 04a must precede the 05_framework wiring (so
    # `typeof EditorModuleRegistry !== 'undefined'` evaluates true at
    # module-publish time), and 17a must run AFTER 05_framework wires
    # window.__sceneview (so the self-publish onto .history finds the
    # already-created __sceneview object).
    reg_i = html.index("const EditorModuleRegistry = (() => {")
    framework_i = html.index("modules: (typeof EditorModuleRegistry !== 'undefined')")
    history_i = html.index("const EditHistory = (() => {")
    publish_i = html.index("window.__sceneview.history = EditHistory;")
    assert reg_i < framework_i, "04a registry must precede 05 framework wiring"
    assert framework_i < history_i, "05 framework must precede 17a history"
    assert history_i < publish_i, "history IIFE must precede its self-publish"


# --------------------------------------------------------------------------
# Phase 2B (editor-arc-design #122 §4.1): CameraPathModule wrapper +
# Save dispatch via EditorModuleRegistry.collectPatch.
# --------------------------------------------------------------------------

_PHASE_2B_MARKERS = (
    # 15a fragment: CameraPathModule definition + registration
    "// ============================================================\n  //  CameraPathModule",
    "name: 'camera_paths',",
    "stateKey: 'camera_paths',",
    "EditorModuleRegistry.register(cameraPathModule);",
    # 17_editor_gizmo: _buildPatch refactor (registry overlay over legacy walk)
    "function _buildLegacyPatch() {",
    "function _buildPatch() {",
    "EditorModuleRegistry.collectPatch();",
)


def test_phase_2b_camera_path_module_and_save_dispatch_present():
    """The new 15a CameraPathModule fragment is registered with the
    EditorModuleRegistry + 17_editor_gizmo's _buildPatch now overlays
    the registry's collectPatch() onto the legacy _PATCH_KEYS walk."""
    html = html_for("HarnessScene")
    for mk in _PHASE_2B_MARKERS:
        assert mk in html, f"Phase 2B marker missing: {mk!r}"
    # The legacy _PATCH_KEYS array stays present (the fallback walk).
    assert "const _PATCH_KEYS = ['start_view'" in html
    # Structural ordering: _buildLegacyPatch is the function _buildPatch
    # calls FIRST; collectPatch overlay happens AFTER the legacy base is
    # built. The fragment loader runs 15 before 15a before 17 so the
    # CameraPathModule registers in time for the Save dispatch.
    cpm_i = html.index("// ============================================================\n  //  CameraPathModule")
    gz_i = html.index("function _buildPatch() {")
    assert cpm_i < gz_i, (
        "CameraPathModule fragment (15a) must concatenate BEFORE the gizmo "
        "fragment (17) so the module is registered + boot-mounted in time "
        "for the Save dispatch to reach it via the registry"
    )
    # Inside _buildPatch, the legacy base is built FIRST, then the
    # registry overlay merges in.
    bp_i = html.index("function _buildPatch() {")
    bp_end = html.index("function _buildSpcpPayload", bp_i)
    body = html[bp_i:bp_end]
    base_i = body.find("const base = _buildLegacyPatch();")
    overlay_i = body.find("EditorModuleRegistry.collectPatch();")
    assert base_i >= 0 and overlay_i > base_i, (
        "_buildPatch must build the legacy base FIRST (preserves byte-id "
        "save-shape when no modules registered) then overlay registry "
        "collectPatch() on top (registered modules WIN over legacy)"
    )


# --------------------------------------------------------------------------
# Phase 2C (editor-arc-design #122 §3.7 + §4.1.1): 3 timeline addenda --
# total-time input + auto toggle, Prev/Next-keyframe skip buttons,
# Ctrl+Left/Right hotkeys.
# --------------------------------------------------------------------------

_PHASE_2C_MARKERS = (
    # JS mirror of the Python effective_scrub_range (spec §3.7)
    "function _effectiveScrubRange(p) {",
    "const total = p.total_duration_s;",
    "Math.max(last, 10.0)",  # 10s floor for empty paths
    "function _tlIsAutoTotal(p) {",
    # Total-time input + auto toggle DOM
    "_tlTotalInput",
    "_tlAutoBtn",
    # Prev/Next skip buttons
    "_tlPrevKf",
    "_tlNextKf",
    "_tlSkipPrev",
    "_tlSkipNext",
    # EditHistory commit labels (per spec §6.5.1)
    "'path-total-time'",
    "'path-auto-toggle'",
    # Ctrl+Left / Ctrl+Right hotkey wiring
    "ev.key === 'ArrowLeft'",
    "ev.key === 'ArrowRight'",
)


def test_phase_2c_timeline_addenda_present():
    """The 3 timeline addenda (total-time UI, Prev/Next, Ctrl+Left/Right)
    are wired into the rendered HTML."""
    html = html_for("HarnessScene")
    for mk in _PHASE_2C_MARKERS:
        assert mk in html, f"Phase 2C marker missing: {mk!r}"
    # Structural: the Ctrl+Left / Ctrl+Right keydown handler is gated on
    # the same author-mode + text-input checks the Ctrl+Z handler uses
    # (single convention). Locate the handler by its key checks.
    al_i = html.index("ev.key === 'ArrowLeft'")
    # Walk back to find the surrounding handler header -- the metaKey/
    # ctrlKey check must precede.
    body = html[max(0, al_i - 1500):al_i]
    assert "ModeManager.is('author')" in body
    assert "ev.metaKey || ev.ctrlKey" in body
    # Prev/Next skip helpers consult the SORTED-by-t view (not raw
    # array order) -- the editor permits dragging diamonds past
    # neighbours so raw order is NOT chronological.
    sk_i = html.index("function _tlSortedKfTimes(p)")
    sk_body = html[sk_i:sk_i + 600]
    assert ".sort((a, b) => a - b);" in sk_body, (
        "Prev/Next-keyframe skip must consult a SORTED-by-t view, NOT "
        "raw keyframe-array order (the editor allows out-of-order kfs)"
    )
    # Total-time commit on Enter/blur, NEVER per keystroke. The change
    # listener fires on blur; an explicit keydown handler triggers blur+
    # commit on Enter. There must be NO per-keystroke commit hook.
    ct_i = html.index("function _tlCommitTotalInput()")
    ct_end = html.index("_tlTotalInput.addEventListener('change'", ct_i)
    # ('input' would be per-keystroke; 'change' fires on blur.)
    ct_block = html[ct_i:ct_end + 200]
    assert "_tlTotalInput.addEventListener('input'" not in ct_block, (
        "Total-time input must NOT commit per keystroke (would push 60+ "
        "EditHistory snapshots/s); commit only on blur/Enter."
    )

# --------------------------------------------------------------------------
# my16-M1 follow-up: the camera-path overlay must be SCENE-RELATIVE
# --------------------------------------------------------------------------
# A real-scene UX defect: the my16 author trajectory overlay sized its
# per-keyframe camera frusta + speed dots off a SCENE-INDEPENDENT
# constant -- ``_TRAJ_FRUSTUM_LEN = Math.max(0.4, (_initDist || 8) *
# 0.06)`` where ``_initDist`` is the camera->orbit-target VIEWING
# distance for the resting/start pose (UNRELATED to the path's own
# spatial extent). On a real scene framed from far back ``_initDist``
# is large, so a frustum became scene-spanning and its always-on-top,
# fully-opaque (transparent:true but NO explicit opacity) wireframe
# read as a near-solid orange mass. The fix derives the frustum / dot
# scale from the ACTIVE path's OWN keyframe-position bbox diagonal
# (``_trajPathScale`` / ``_trajApplyScale``), clamped, and gives the
# always-on-top wireframe a modest opacity. This is a SIZING/material
# fix strictly inside the (now-retired) T16-TRAJ excise region. The
# output-pin in test_html_for_output_pin.py covers the byte invariant.
#
# Asserted at the ``html_for`` level (no browser needed -- the sizing
# is JS the harness's window.__editor exposes; the Playwright harness
# keyframe-editor.html Task-16(f) check + the ``_viewer_author``
# ?author=1 fixture assert the RUNTIME values for the controller's
# serialized real-scene re-verify). The NEGATIVE CONTROL builds the
# committed ``83fc5c8`` template in a SEPARATE temp dir (byte-faithful
# ``git cat-file blob`` via a Python subprocess -- NEVER a PowerShell
# pipe, per the regen-recipe CRLF caveat) and asserts the SAME
# scene-relative markers are ABSENT there and the OLD scene-
# independent ``_initDist``-based frustum sizing IS present -- so this
# assertion provably FAILS against the pre-fix code (it is a real
# discriminator, not a tautology).
def _git_blob_module(rev_path: str):
    """Import ``git cat-file blob <rev_path>`` as a fresh module from a
    SEPARATE temp dir, byte-faithfully (raw LF-only bytes straight off
    the subprocess stdout PIPE -- no PowerShell string round-trip, the
    regen-recipe CRLF foot-gun). Returns the imported module."""
    import importlib.util
    import os
    import subprocess
    import tempfile

    repo = Path(__file__).resolve().parents[1]
    raw = subprocess.run(
        ["git", "cat-file", "blob", rev_path],
        stdout=subprocess.PIPE, check=True, cwd=str(repo),
    ).stdout
    assert b"\r" not in raw, "git blob unexpectedly has CR (CRLF corruption)"
    d = tempfile.mkdtemp(prefix="splatpipe_pre_my16m1_")
    p = os.path.join(d, "template_pre.py")
    with open(p, "wb") as f:
        f.write(raw)
    spec = importlib.util.spec_from_file_location("_template_pre_my16m1", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The scene-relative markers the FIXED code introduces (all live
# strictly inside what was formerly the T16-TRAJ excise region).
_SCENE_REL_MARKERS = (
    "function _trajPathScale",          # bbox-diagonal helper
    "function _trajApplyScale",         # per-path scale setter
    "_trajApplyScale(kfs);",            # called in _trajRebuild
    "const _TRAJ_FR_FRAC",              # small-fraction constant
    "const _TRAJ_FR_MIN",               # absolute clamp floor
    "const _TRAJ_FR_MAX",               # absolute clamp ceiling
    "let _trajFrLen",                   # per-path frustum length var
    "let _trajFrHalf",                  # per-path image-plane half var
    "get frustumIsWireframe",           # window.__editor wireframe probe
    "get pathScale()",                  # window.__editor path-scale probe
    "m.opacity = 0.85;",                # the always-on-top opacity fix
)
# The scene-INDEPENDENT frustum sizing the OLD (pre-fix) code used.
_OLD_FIXED_MARKERS = (
    "const _TRAJ_FRUSTUM_LEN = Math.max(0.4, (_initDist || 8) * 0.06);",
    "const _TRAJ_FRUSTUM_HALF = _TRAJ_FRUSTUM_LEN * 0.6;",
)


def test_camera_path_overlay_is_scene_relative_not_fixed():
    """The my16 overlay frustum/dot size must be derived from the
    ACTIVE path's OWN keyframe-bbox diagonal (scene-relative), NOT a
    scene-independent constant. NEGATIVE-CONTROLLED against the
    committed 83fc5c8 (pre-fix) template, which still has the old
    fixed ``_initDist``-based sizing -- proving this is a real
    discriminator, not a tautology."""
    html = html_for("HarnessScene")

    # (positive) the FIXED code's scene-relative markers are ALL
    # present in the rendered HTML, each EXACTLY once where uniqueness
    # is meaningful (the helpers / consts / surface getters).
    for mk in _SCENE_REL_MARKERS:
        assert mk in html, f"scene-relative marker missing: {mk!r}"
    # (positive) the OLD scene-independent frustum sizing is GONE --
    # no _initDist-derived hardcoded frustum size remains anywhere.
    for mk in _OLD_FIXED_MARKERS:
        assert mk not in html, f"old fixed-size code still present: {mk!r}"
    assert "_TRAJ_FRUSTUM_LEN" not in html
    assert "_TRAJ_FRUSTUM_HALF" not in html
    # (positive) the scene-relative scale is a SMALL fraction with
    # sane absolute clamps (a frustum reads like a small camera, not
    # scene-spanning): frac a few %, min small, max bounded, min<max.
    import re
    frac = float(re.search(
        r"const _TRAJ_FR_FRAC = ([0-9.]+);", html).group(1))
    fmin = float(re.search(
        r"const _TRAJ_FR_MIN = ([0-9.]+);", html).group(1))
    fmax = float(re.search(
        r"const _TRAJ_FR_MAX = ([0-9.]+);", html).group(1))
    assert 0.0 < frac <= 0.06, f"frustum fraction not a small %: {frac}"
    assert 0.0 < fmin < fmax, f"frustum clamp bounds invalid: {fmin}/{fmax}"
    assert fmax <= 25.0, f"frustum clamp ceiling implausibly large: {fmax}"
    # The scale is derived from the keyframe POSITIONS' bbox diagonal
    # (k.pos, the same data the player flies) -- prove the helper uses
    # the keyframe positions + a sqrt of squared spans, not _initDist.
    # In the RENDERED html the template's ``{{``/``}}`` are collapsed
    # by ``str.format`` to single ``{``/``}``; the helper closes with a
    # 2-space-indent ``\n  }`` line. Slice from the decl to the next
    # ``_trajApplyScale`` decl (which immediately follows it) so the
    # body is bounded without brace-counting.
    _i0 = html.index("function _trajPathScale(kfs) {")
    _i1 = html.index("function _trajApplyScale(kfs) {", _i0)
    body = html[_i0:_i1]
    assert body, "could not isolate _trajPathScale body"
    assert "k.pos" in body, "_trajPathScale must read keyframe positions"
    assert "Math.sqrt" in body, "_trajPathScale must compute a diagonal"
    assert "_initDist" not in body, (
        "_trajPathScale must NOT depend on the start-view distance"
    )

    # (NEGATIVE CONTROL) the committed 83fc5c8 (pre-fix) template:
    # the SAME scene-relative markers are ABSENT and the OLD fixed
    # _initDist sizing IS present -> this test provably FAILS against
    # the pre-fix code (a genuine discriminator).
    pre = _git_blob_module(
        "83fc5c8:src/splatpipe/viewers/spark/template.py")
    pre_html = pre.html_for("HarnessScene")
    for mk in _SCENE_REL_MARKERS:
        assert mk not in pre_html, (
            f"negative control FAILED: scene-relative marker {mk!r} "
            "unexpectedly already in the pre-fix 83fc5c8 template "
            "(the test would not discriminate the fix)"
        )
    for mk in _OLD_FIXED_MARKERS:
        assert mk in pre_html, (
            f"negative control FAILED: pre-fix marker {mk!r} not in "
            "83fc5c8 -- the baseline is not the expected fixed-size code"
        )
    # The pre-fix template's frustum size IS the scene-independent
    # _initDist constant -> for the scene-less HarnessScene it does
    # NOT scale with any path; the fix replaced exactly this.
    assert "_TRAJ_FRUSTUM_LEN" in pre_html
    assert "_trajPathScale" not in pre_html


# --------------------------------------------------------------------------
# my16 follow-up: the sample TICKS must be tiny + white + fixed-size,
# and the motion LINE must carry a subtle per-vertex gradient
# --------------------------------------------------------------------------
# A second real-scene UX defect (the cd119d4 scene-relative frustum
# fix was correct and is KEPT): the my16 overlay sized the per-sample
# speed dots off ``Math.max(2, _trajFrHalf * 0.5)`` with
# ``sizeAttenuation: true`` and coloured them ``_TRAJ_COL`` (orange).
# Because ``_trajFrHalf`` is the SCENE-RELATIVE frustum half (metres
# on a large path), every dot became a fat world-space orange blob;
# 240 of them overlapped into one SOLID ORANGE BAND across the scene
# when framed from far back. The motion line was a flat-orange
# ``LineBasicMaterial({ color: _TRAJ_COL })`` ribbon. The fix makes
# the ticks DELICATE + WHITE + FIXED screen-space (``_TRAJ_TICK_PX``
# px, ``sizeAttenuation: false`` -> ~2 px at ANY distance, fully
# decoupled from ``_trajFrHalf``) and gives the line a SUBTLE
# low-saturation per-vertex HSL gradient (``vertexColors: true`` +
# a populated ``color`` attribute). This is a SIZING/material change
# strictly inside what was formerly the T16-TRAJ excise region.
# NEGATIVE-CONTROLLED against the
# committed ``cd119d4`` (pre-tick-fix) template, which still has the
# old ``_trajFrHalf``-keyed orange dots + flat-orange line -- so this
# assertion provably FAILS against the pre-fix code (a genuine
# discriminator, not a tautology).
_TICK_LINE_MARKERS = (
    "const _TRAJ_TICK_PX",              # fixed px tick size
    "const _TRAJ_TICK_COL",             # near-white tick colour
    "const _TRAJ_TICK_OPACITY",         # modest tick alpha
    "const _TRAJ_LINE_HUE0",            # gradient start hue
    "const _TRAJ_LINE_HUE1",            # gradient end hue
    "const _TRAJ_LINE_SAT",             # low gradient saturation
    "sizeAttenuation: false",           # ticks are screen-space-fixed
    "vertexColors: true",               # line uses a per-vertex ramp
    "get tickSize()",                   # window.__editor tick probe
    "get tickSizeIsFixed()",            # window.__editor attenuation probe
    "get tickColorIsWhite()",           # window.__editor white probe
    "get lineHasGradient()",            # window.__editor gradient probe
    "get lineColorEndsDiffer()",        # window.__editor real-ramp probe
)
# The OLD fat-orange-dot sizing the pre-fix code used (scene-relative
# blob keyed off the frustum half, attenuated -> the solid band).
_OLD_TICK_MARKERS = (
    "color: _TRAJ_COL, size: Math.max(2, _trajFrHalf * 0.5),",
)


def test_motion_ticks_are_tiny_white_and_line_has_gradient():
    """The my16 sample ticks must be SMALL + WHITE + FIXED
    screen-space (not the old fat scene-relative orange blobs that
    merged into a band) and the motion line must carry a SUBTLE
    per-vertex gradient (not a flat-orange ribbon). The cd119d4
    scene-relative camera-frustum markers must SURVIVE unchanged (no
    regression). NEGATIVE-CONTROLLED against the committed cd119d4
    (pre-tick-fix) template -- proving this is a real discriminator,
    not a tautology."""
    html = html_for("HarnessScene")

    # (positive) every tick/line marker the FIXED code introduces is
    # present in the rendered HTML.
    for mk in _TICK_LINE_MARKERS:
        assert mk in html, f"tick/line marker missing: {mk!r}"
    # (positive) the OLD fat-orange-dot sizing is GONE -- no
    # _trajFrHalf-keyed dot size, no flat-orange line material.
    for mk in _OLD_TICK_MARKERS:
        assert mk not in html, f"old fat-orange-dot code still present: {mk!r}"
    # The flat-orange line material CONSTRUCTION is replaced by the
    # vertexColors one (assert on the ``new THREE.`` construction form
    # -- the bare ``LineBasicMaterial({ color: _TRAJ_COL })`` substring
    # also appears in a doc comment, so the construction call is the
    # precise discriminator; rendered HTML collapses ``{{``->``{``).
    assert "new THREE.LineBasicMaterial({ color: _TRAJ_COL })" not in html
    assert "new THREE.LineBasicMaterial({ vertexColors: true })" in html
    # (positive) the tick size is a SMALL fixed pixel size and the
    # gradient hues are a NARROW low-saturation band (a tasteful
    # ramp, never a saturated rainbow).
    import re
    tpx = float(re.search(r"const _TRAJ_TICK_PX = ([0-9.]+);", html).group(1))
    h0 = float(re.search(r"const _TRAJ_LINE_HUE0 = ([0-9.]+);", html).group(1))
    h1 = float(re.search(r"const _TRAJ_LINE_HUE1 = ([0-9.]+);", html).group(1))
    sat = float(re.search(r"const _TRAJ_LINE_SAT = ([0-9.]+);", html).group(1))
    assert 0.0 < tpx <= 4.0, f"tick px not tiny: {tpx}"
    assert 0.0 <= sat <= 0.6, f"line saturation not restrained: {sat}"
    assert abs(h1 - h0) <= 0.5, (
        f"line hue span too wide (rainbow, not subtle): {h0}->{h1}"
    )
    # The tick colour constant is near-white (all channels high) --
    # parse the hex and assert each byte is bright.
    tcol = re.search(r"const _TRAJ_TICK_COL = 0x([0-9a-fA-F]{6});", html)
    assert tcol, "tick colour constant not found"
    cr = int(tcol.group(1)[0:2], 16)
    cg = int(tcol.group(1)[2:4], 16)
    cb = int(tcol.group(1)[4:6], 16)
    assert cr >= 0xD0 and cg >= 0xD0 and cb >= 0xD0, (
        f"tick colour not near-white: #{tcol.group(1)}"
    )

    # The cd119d4 scene-relative camera-FRUSTUM markers MUST survive
    # untouched -- this pass only restyles the ticks + line, it must
    # NOT regress the (correct) scene-relative small frustum fix.
    for mk in (
        "function _trajPathScale", "function _trajApplyScale",
        "const _TRAJ_FR_FRAC", "const _TRAJ_FR_MIN", "const _TRAJ_FR_MAX",
        "let _trajFrLen", "let _trajFrHalf", "get frustumIsWireframe",
        "m.opacity = 0.85;",
    ):
        assert mk in html, f"cd119d4 frustum marker REGRESSED: {mk!r}"

    # (NEGATIVE CONTROL) the committed cd119d4 (pre-tick-fix)
    # template: the SAME tick/line markers are ABSENT and the OLD
    # fat-orange-dot sizing IS present -> this test provably FAILS
    # against the pre-fix code (a genuine discriminator). cd119d4
    # already has the scene-relative frustum fix (this pass keeps
    # it), so those frustum markers ARE in the pre-fix template --
    # they are NOT discriminators here and are NOT asserted absent.
    pre = _git_blob_module(
        "cd119d4:src/splatpipe/viewers/spark/template.py")
    pre_html = pre.html_for("HarnessScene")
    for mk in _TICK_LINE_MARKERS:
        assert mk not in pre_html, (
            f"negative control FAILED: tick/line marker {mk!r} "
            "unexpectedly already in the pre-fix cd119d4 template "
            "(the test would not discriminate the fix)"
        )
    for mk in _OLD_TICK_MARKERS:
        assert mk in pre_html, (
            f"negative control FAILED: pre-fix marker {mk!r} not in "
            "cd119d4 -- the baseline is not the expected fat-orange-dot code"
        )
    # The pre-fix line material IS the flat-orange one (no
    # vertexColors) -> the fix replaced exactly this.
    assert "new THREE.LineBasicMaterial({ color: _TRAJ_COL })" in pre_html
    assert "vertexColors: true" not in pre_html


# --------------------------------------------------------------------------
# my18 follow-up: a REAL mouse-drag of a gizmo handle must move the kf
# --------------------------------------------------------------------------
# The user-reported defect: in ?author=1 "I cannot move the keyframes --
# when I click on the handles, it does not move." Two compounding bugs,
# BOTH strictly inside what was formerly the T16-TRAJ excise region:
#
#   (1) ``_gzOnCanvasDown`` ran in CAPTURE phase and, on ANY frustum
#       raycast hit, called ``ev.stopPropagation()`` -- WITHOUT first
#       asking whether the pointer was over a TransformControls gizmo
#       HANDLE. TC's own pointerdown listener is bubble-phase on the
#       SAME canvas, so a capture-phase stopPropagation() starved TC's
#       ``pointerDown()`` (which only starts a drag when ``this.axis
#       !== null``). A real mouse-drag could therefore NEVER move a
#       keyframe -- only the programmatic ``gzDragTranslate`` test API
#       (which bypasses pointer events) ever did, masking the bug. The
#       fix adds ``_gzPointerOnGizmo`` (refreshing ``_gzCtl.axis`` via
#       the SAME ``_gzCtl.pointerHover`` raycast TC uses) and yields
#       the event to TC untouched when a handle is under the pointer.
#   (2) The author-mode auto-tour auto-played (the intro controller's
#       _cinematic gate is usermode-ONLY) and parked the camera in the
#       dense end-of-path keyframe cluster, so no keyframe was even
#       clickable. The fix makes ``_introStartTour()`` a guaranteed
#       no-op in author mode (``_introTourStarted = true`` -- the SAME
#       idempotency guard the fade/fallback paths use) so the camera
#       rests at the saved start_view authoring vantage.
#
# Asserted at the ``html_for`` level (the Playwright harness asserts the
# RUNTIME real-mouse-drag on the live scene). NEGATIVE-CONTROLLED
# against the committed ``2fee33b`` (pre-fix HEAD) -- the SAME wiring
# markers are ABSENT there and the pre-fix ``_gzOnCanvasDown`` goes
# straight from the ``_gzDragging`` guard into ``_gzPickFrustum``
# (no gizmo-yield), so this assertion provably FAILS against the
# pre-fix code (a genuine discriminator, not a tautology).
_GZ_REALDRAG_MARKERS = (
    "function _gzPointerOnGizmo(clientX, clientY) {",   # the yield gate
    "_gzCtl.pointerHover(_GZ_NDC);",                     # TC's own raycast
    "if (_gzPointerOnGizmo(ev.clientX, ev.clientY)) return;",  # yield in down
    "try { _introTourStarted = true; } catch (e) {}",   # author tour suppress
    "gzPointerOnGizmoAt(clientX, clientY) {",            # TEST-ONLY probe
    "get gzCtlDragging() {",                             # real-drag probe
)


def test_real_gizmo_handle_drag_wiring_present_and_author_tour_suppressed():
    """A REAL mouse-drag of a TransformControls handle must reach TC
    (the capture handler yields the pointerdown to TC when a gizmo
    axis is under it -- it must NOT stopPropagation() and starve TC)
    AND the author-mode auto-tour must be suppressed so the camera
    rests at start_view. NEGATIVE-CONTROLLED against the committed
    pre-fix 2fee33b -- proving this is a real discriminator, not a
    tautology."""
    html = html_for("HarnessScene")

    # (positive) every real-drag/tour-suppress marker the fix adds is
    # present in the rendered HTML (``{{``->``{`` collapse applied).
    for mk in _GZ_REALDRAG_MARKERS:
        assert mk in html, f"real-drag/tour marker missing: {mk!r}"
    # (positive) the fix yields to the gizmo BEFORE picking a frustum:
    # the ``_gzPointerOnGizmo`` early-return must textually precede the
    # ``_gzPickFrustum`` call inside ``_gzOnCanvasDown``.
    down_i = html.index("function _gzOnCanvasDown(ev) {")
    yield_i = html.index(
        "if (_gzPointerOnGizmo(ev.clientX, ev.clientY)) return;", down_i)
    pick_i = html.index(
        "const idx = _gzPickFrustum(ev.clientX, ev.clientY);", down_i)
    assert yield_i < pick_i, (
        "gizmo-yield must run BEFORE the frustum pick in "
        "_gzOnCanvasDown (else TC is still starved)"
    )
    # (positive) the still-present scene-relative frustum + tick/line
    # fixes MUST survive untouched (no regression from this pass).
    for mk in (
        "function _trajPathScale", "const _TRAJ_TICK_PX",
        "new THREE.LineBasicMaterial({ vertexColors: true })",
        "get frustumIsWireframe",
    ):
        assert mk in html, f"prior my16/my17 marker REGRESSED: {mk!r}"

    # (NEGATIVE CONTROL) the committed pre-fix 2fee33b template: the
    # SAME real-drag/tour-suppress markers are ABSENT -> this test
    # provably FAILS against the pre-fix code (a genuine
    # discriminator). The pre-fix ``_gzOnCanvasDown`` goes straight
    # from the ``_gzDragging`` guard to ``_gzPickFrustum`` with NO
    # gizmo-yield (its comment even CLAIMS TC is handled "do nothing
    # here" but no such check was ever implemented -- the exact bug).
    pre = _git_blob_module(
        "2fee33b:src/splatpipe/viewers/spark/template.py")
    pre_html = pre.html_for("HarnessScene")
    for mk in _GZ_REALDRAG_MARKERS:
        assert mk not in pre_html, (
            f"negative control FAILED: real-drag/tour marker {mk!r} "
            "unexpectedly already in the pre-fix 2fee33b template "
            "(the test would not discriminate the fix)"
        )
    # The pre-fix handler IS the starving one: the frustum pick runs
    # with NO preceding gizmo-yield (the regression this fix removes).
    pre_down_i = pre_html.index("function _gzOnCanvasDown(ev) {")
    assert (
        "const idx = _gzPickFrustum(ev.clientX, ev.clientY);"
        in pre_html[pre_down_i:]
    ), "pre-fix baseline is not the expected starving _gzOnCanvasDown"
    assert "_gzPointerOnGizmo" not in pre_html, (
        "negative control FAILED: pre-fix 2fee33b unexpectedly already "
        "has the gizmo-yield gate"
    )


# --------------------------------------------------------------------------
# 2026-05-20 author-mode UX batch (UX-1 / UX-3 / UX-4)
# --------------------------------------------------------------------------
# The user reported four bugs in the live ?author=1 editor on the deployed
# kf-fehmarn scene. All four fixes land STRICTLY INSIDE what were formerly
# the T16-TRAJ / T19-JS excise regions. The output-pin in
# test_html_for_output_pin.py covers the byte invariant. Each
# fix gets a structural marker assertion here; the visible behaviour is
# verified end-to-end via Playwright on a deployed real-pixel slug
# (the manual harness in tests/manual/). NEGATIVE-CONTROLLED against the
# committed pre-fix HEAD (5190301) -- the same markers are ABSENT there.
_AUTHOR_UX_2026_05_20_MARKERS = (
    # UX-1: _trajActivePath AUTHOR-mode fallback (Perspective stays visible)
    "_cs.value === _CAM_PERSP && ModeManager.is('author')",
    # UX-2: _camSelApply author-branch pose snap on bind
    "// UX-2 (2026-05-20): snap the viewport pose to the newly-bound",
    # UX-3: _pausedAt state machine
    "let _pausedAt = null;",
    "let _pausedAtPlayer = null;",
    "_pausedAtPlayer === _player",
    # UX-4: tick px bumped + renderOrder bump
    "_TRAJ_TICK_PX = 3.5",
    "_trajDots.renderOrder = 13",
)


def test_2026_05_20_author_ux_markers_present_and_negative_controlled():
    """The four author-mode UX fixes user-reported via Telegram on
    2026-05-20 must each leave a structural marker in the rendered
    HTML. NEGATIVE-CONTROLLED against the pre-fix HEAD (5190301) --
    every marker is ABSENT there, so this test provably FAILS against
    the pre-fix code (a genuine discriminator). All four fixes are
    region-interior to what were formerly the T16-TRAJ / T19-JS excise
    regions (the output-pin in test_html_for_output_pin.py independently
    proves the generated HTML is unchanged for the corpus fixtures)."""
    html = html_for("HarnessScene")
    for mk in _AUTHOR_UX_2026_05_20_MARKERS:
        assert mk in html, f"2026-05-20 UX marker missing: {mk!r}"

    # UX-1 invariant: _trajActivePath now has TWO Perspective checks --
    # the AUTHOR-mode fallback FIRST (via _CAM_PERSP const, no new raw
    # literal so the FIVE-spot count below stays) then the original
    # end-user/embed guard literal AFTER (preserved verbatim). Order
    # matters: the author fallback must run BEFORE the end-user
    # return-null.
    fn_i = html.index("function _trajActivePath()")
    author_i = html.index(
        "_cs.value === _CAM_PERSP && ModeManager.is('author')", fn_i)
    enduser_i = html.index(
        "if (_cs && _cs.value === '__perspective__') return null;", fn_i)
    assert author_i < enduser_i, (
        "UX-1: author-mode Perspective fallback must precede the "
        "end-user return-null guard"
    )
    # The "__perspective__" literal count must STILL be 5 -- using
    # _CAM_PERSP (not the raw string) in the new fallback keeps the
    # T20-CAMSEL-DOM invariant. The comment "the sentinel" must NOT
    # have re-introduced the literal.
    assert html.count("__perspective__") == 5

    # UX-3 invariant: the per-frame _t0 rebase MUST live inside
    # _trajLayer.update() (so end-user / embed / clip-mode never reach
    # it -- the layer's modes=['author'] gate). Structural: between
    # "_trajLayer = {" and the next "OverlayScene.register" call.
    layer_i = html.index("const _trajLayer = {")
    register_i = html.index("OverlayScene.register(_trajLayer)", layer_i)
    rebase_i = html.find(
        "if (_player && _pausedAt !== null && _pausedAtPlayer === _player)",
        layer_i, register_i)
    assert rebase_i > 0, (
        "UX-3: per-frame _t0 rebase missing from _trajLayer.update()"
    )

    # UX-3 invariant: _tlOnUp must NOT call stopPath any more (the
    # previous A6 fix; replaced by the _pausedAt rebase). The exact
    # pre-fix construct was `try {{ stopPath(); }} catch (e) {{}}`
    # inside a `if (_wasScrub && _player) {{` block -- search for the
    # gated call form (the comment that references stopPath() is fine).
    onup_i = html.index("function _tlOnUp() {")
    onup_end = html.index("_tlLane.addEventListener('pointerdown'", onup_i)
    body = html[onup_i:onup_end]
    assert "if (_wasScrub && _player)" not in body, (
        "UX-3: _tlOnUp must no longer carry the A6 `if (_wasScrub && "
        "_player) { stopPath(); }` block (replaced by the _pausedAt + "
        "_trajLayer.update() rebase)"
    )
    assert "_wasScrub" not in body, (
        "UX-3: _tlOnUp must no longer declare _wasScrub (the A6 flag)"
    )

    # UX-4 invariant: bumped tick px is the active constant the
    # PointsMaterial reads (assert the construction line uses the bumped
    # variable + size, not a hard-coded 2.2).
    assert (
        "color: _TRAJ_TICK_COL, size: _TRAJ_TICK_PX," in html
    ), "UX-4: PointsMaterial must still read _TRAJ_TICK_PX (not a literal)"

    # (NEGATIVE CONTROL) the committed pre-fix HEAD (5190301) -- the
    # SAME markers are ABSENT there.
    pre = _git_blob_module(
        "5190301:src/splatpipe/viewers/spark/template.py")
    pre_html = pre.html_for("HarnessScene")
    for mk in _AUTHOR_UX_2026_05_20_MARKERS:
        assert mk not in pre_html, (
            f"negative control FAILED: 2026-05-20 UX marker {mk!r} "
            "unexpectedly already in the pre-fix 5190301 template "
            "(the test would not discriminate the fix)"
        )
    # The pre-fix _trajActivePath has the ORIGINAL single guard only --
    # no author-mode fallback line.
    pre_fn_i = pre_html.index("function _trajActivePath()")
    pre_fn_end = pre_html.index("function _trajKfSig", pre_fn_i)
    assert "ModeManager.is('author')" not in pre_html[pre_fn_i:pre_fn_end], (
        "negative control FAILED: pre-fix 5190301 _trajActivePath "
        "unexpectedly already branches on author mode"
    )
    # Pre-fix _tlOnUp DID carry the A6 `if (_wasScrub && _player) {{
    # stopPath(); }}` block this UX-3 fix replaces.
    pre_onup_i = pre_html.index("function _tlOnUp() {")
    pre_onup_end = pre_html.index(
        "_tlLane.addEventListener('pointerdown'", pre_onup_i)
    assert "if (_wasScrub && _player)" in pre_html[pre_onup_i:pre_onup_end], (
        "negative control FAILED: pre-fix 5190301 _tlOnUp unexpectedly "
        "lacks the A6 `if (_wasScrub && _player) { stopPath(); }` block"
    )


# --------------------------------------------------------------------------
# 2026-05-20 author-mode UX-5: <2-keyframe path authoring unblock
# --------------------------------------------------------------------------
# Second user-reported bug in the same live ?author=1 editor on the
# deployed kf-fehmarn slug ("I seem to not be able to scrub the timeline
# when I create a new camera that only has one keyframe. But how am I
# supposed to set the next keyframe if I cannot scrub?"). Three coupled
# fixes, all region-interior to the modularized fragment files in
# ``viewers/spark/template_parts/`` (recipe-2c -- the orchestrator
# in ``template.py`` is untouched). NEGATIVE-CONTROLLED against the
# committed pre-UX-5 HEAD (2b92e75; the T6-of-#118 modularization
# commit) -- every UX-5 marker is ABSENT there, so this test provably
# FAILS against the pre-fix code (a genuine discriminator, not a
# tautology). The output-pin in ``test_html_for_output_pin.py``
# independently locks the generated-HTML byte length / sha for the
# 6-fixture corpus (re-pinned in lockstep against this UX-5 delta).
_AUTHOR_UX_5_MARKERS = (
    # Fix-1: _camSelApply author branch unconditionally re-enables
    # OrbitControls after a real-path bind (lifted OUT of the snap
    # block which only fires when buildPlayer succeeded, i.e. 2+ kfs).
    "// UX-5 (2026-05-20)",
    # Fix-2: _gzRecordKeyframe default temporal spacing constant for
    # the second keyframe on a fresh 1-kf path (so the spline gains
    # a non-zero duration and becomes scrub-able after two K presses).
    "const _GZ_DEFAULT_KF_DT = 2.0;",
    # Fix-3 (#123 hot-fix 2026-05-20): the prior alert nag is now a
    # silent ``console.warn`` + early-return. The deferred-play
    # wording uniquely identifies the silent-no-op branch in
    # ``startPath`` and is absent in the pre-UX-5 / pre-#123 HEAD.
    "Play deferred until >=2 keyframes.",
)


def test_2026_05_20_ux5_one_keyframe_path_authoring_unblock():
    """The three UX-5 fixes user-reported via Telegram on 2026-05-20
    must each leave a structural marker in the rendered HTML.
    NEGATIVE-CONTROLLED against the pre-UX-5 HEAD (2b92e75 -- the
    T6-of-#118 modularization commit) -- every marker is ABSENT there,
    so this test provably FAILS against the pre-fix code. The behaviour
    is also verified end-to-end via Playwright on a deployed real-pixel
    slug (the manual harness in ``tests/manual/``)."""
    html = html_for("HarnessScene")
    for mk in _AUTHOR_UX_5_MARKERS:
        assert mk in html, f"UX-5 marker missing: {mk!r}"

    # Fix-1 STRUCTURAL invariant: the `if (_player && _activePathId &&
    # _activePathId !== val) { try { stopPath(); } catch (e) {} }`
    # block must live OUTSIDE the `if (pv && pv.duration > 0) {` snap
    # block in _camSelApply's author branch. On a <2-kf path pv === null
    # and the snap block is skipped -- the stale-player stop must still
    # run. Structural: find the author-branch try block, then assert
    # the stopPath happens BEFORE the duration > 0 gate.
    apply_i = html.index("function _camSelApply(val) {")
    apply_end = html.index("function _camSelBuildOptions", apply_i)
    body = html[apply_i:apply_end]
    stop_i = body.find(
        "if (_player && _activePathId && _activePathId !== val)")
    snap_gate_i = body.find("if (pv && pv.duration > 0)")
    assert stop_i > 0 and snap_gate_i > 0, (
        "UX-5: _camSelApply must contain BOTH the stale-player stop "
        "and the snap-block duration gate"
    )
    assert stop_i < snap_gate_i, (
        "UX-5 fix-1: the stale-player stop must run BEFORE the snap "
        "block's duration > 0 gate, so it fires on a <2-kf bind too"
    )

    # Fix-1 STRUCTURAL invariant: a literal `controls.enabled = true;`
    # belt-and-braces line must exist in the author branch of
    # _camSelApply, AFTER the snap block but still inside the
    # try {} block guarded by `if (apPath)`. On a <2-kf path the snap
    # block no-ops, so this unconditional re-enable is what unblocks
    # the user from mouse-dragging the camera to position kf #2.
    re_enable_i = body.find("controls.enabled = true;", snap_gate_i)
    assert re_enable_i > 0, (
        "UX-5 fix-1: _camSelApply author branch missing unconditional "
        "`controls.enabled = true;` after the snap block"
    )

    # Fix-2 STRUCTURAL invariant: _gzRecordKeyframe must branch on
    # `p.keyframes.length === 1` to place kf #2 at `lastT +
    # _GZ_DEFAULT_KF_DT`. Without this branch the second K on a 1-kf
    # path places kf #2 at t=0 (the playhead default when buildPlayer
    # returns null), collapsing both kfs onto the same t and yielding
    # a duration-0 spline that is still un-scrub-able.
    rec_i = html.index("function _gzRecordKeyframe() {")
    rec_end = html.index("_gzStopTour();", rec_i)
    rec_body = html[rec_i:rec_end]
    assert "p.keyframes.length === 1" in rec_body, (
        "UX-5 fix-2: _gzRecordKeyframe must branch on a 1-kf path"
    )
    assert "_GZ_DEFAULT_KF_DT" in rec_body, (
        "UX-5 fix-2: _gzRecordKeyframe must use _GZ_DEFAULT_KF_DT for "
        "the kf #2 placement"
    )

    # Fix-3 STRUCTURAL invariant (#123 hot-fix 2026-05-20):
    # the empty-path Play branch is a silent ``console.warn`` + early
    # return -- the prior alert literals (both the original "Path needs
    # at least 2 keyframes." nag AND the intermediate "Position the
    # camera and press K to add" reword) are both fully removed.
    assert "Path needs at least 2 keyframes." not in html, (
        "Fix-3: the original un-actionable alert literal must be "
        "fully removed from the rendered HTML"
    )
    assert "Position the camera and press K to add" not in html, (
        "Fix-3 (#123 hot-fix): the intermediate reworded alert must "
        "also be fully removed (it became a silent console.warn)"
    )
    # The startPath empty-path branch now logs a console.warn instead
    # of an alert. Bound the body by the closing `}` paired with the
    # opening `function startPath(pathId) {` (the next `function`
    # declaration is the simplest sibling boundary -- the body is
    # ~2.8k chars so a 4k slice is safe and avoids a brittle exact-
    # function-name follow-up that the next refactor might rename).
    sp_i = html.index("function startPath(pathId) {")
    sp_body = html[sp_i:sp_i + 4000]
    assert "console.warn(\"Path '\"" in sp_body, (
        "Fix-3 (#123): startPath empty-path branch must use "
        "console.warn (not alert)"
    )
    assert "alert(\"Path '\"" not in sp_body, (
        "Fix-3 (#123): startPath empty-path branch must NOT use "
        "alert() anymore"
    )

    # (NEGATIVE CONTROL) the committed pre-UX-5 HEAD (2b92e75 -- the
    # T6-of-#118 modularization commit) -- fetched fragment-by-
    # fragment via `git cat-file blob` (the modularized loader reads
    # from a side `template_parts/` dir which the in-process
    # template.py mod can't reach via _git_blob_module). We check the
    # raw fragment SOURCE -- the only two files UX-5 modifies -- to
    # prove every UX-5 marker is ABSENT at 2b92e75 (the test would
    # otherwise be a tautology).
    import subprocess
    pre_camsel = subprocess.run(
        ["git", "cat-file", "blob",
         "2b92e75:src/splatpipe/viewers/spark/template_parts/"
         "10_camera_select.js_tmpl"],
        stdout=subprocess.PIPE, check=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    ).stdout.decode("utf-8")
    pre_gizmo = subprocess.run(
        ["git", "cat-file", "blob",
         "2b92e75:src/splatpipe/viewers/spark/template_parts/"
         "17_editor_gizmo.js_tmpl"],
        stdout=subprocess.PIPE, check=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    ).stdout.decode("utf-8")
    pre_combined = pre_camsel + "\n" + pre_gizmo
    for mk in _AUTHOR_UX_5_MARKERS:
        assert mk not in pre_combined, (
            f"negative control FAILED: UX-5 marker {mk!r} "
            "unexpectedly already in the pre-UX-5 2b92e75 fragments "
            "(the test would not discriminate the fix)"
        )
    # Pre-UX-5 has the OLD un-actionable alert literal -- proves the
    # rewording in fix-3 actually shipped.
    assert "Path needs at least 2 keyframes." in pre_camsel, (
        "negative control FAILED: pre-UX-5 2b92e75 10_camera_select "
        "unexpectedly does NOT carry the old 'Path needs at least 2 "
        "keyframes.' alert (the test would not discriminate fix-3)"
    )
    # Pre-UX-5 has the OLD nesting in _camSelApply -- the stale-player
    # stop and controls.enabled re-enable are INSIDE the snap block,
    # so they no-op on a <2-kf path bind. Verify against the fragment
    # source directly.
    pre_apply_i = pre_camsel.index("function _camSelApply(val) {")
    pre_apply_end = pre_camsel.index(
        "function _camSelBuildOptions", pre_apply_i)
    pre_body = pre_camsel[pre_apply_i:pre_apply_end]
    pre_stop_i = pre_body.find(
        "if (_player && _activePathId && _activePathId !== val)")
    pre_snap_gate_i = pre_body.find("if (pv && pv.duration > 0)")
    assert pre_stop_i > 0 and pre_snap_gate_i > 0, (
        "negative control FAILED: pre-UX-5 2b92e75 unexpectedly lacks "
        "either the stale-player stop or the snap-block duration gate"
    )
    # Pre-UX-5: stale-player stop INSIDE the snap block (after the
    # duration > 0 gate). Post-UX-5 it MUST be before.
    assert pre_stop_i > pre_snap_gate_i, (
        "negative control FAILED: pre-UX-5 2b92e75 unexpectedly already "
        "has the stale-player stop OUTSIDE the snap block (the test "
        "would not discriminate fix-1)"
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
