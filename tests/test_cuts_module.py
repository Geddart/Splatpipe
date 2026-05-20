"""CutsModule contract tests (Phase 6 -- editor-arc-design #122 §4.3).

The CutsModule is a pure-JS IIFE shipped in
``viewers/spark/template_parts/15d_cuts_module.js_tmpl`` and registered
with the EditorModuleRegistry as the canonical owner of the ``clips``
stateKey. It is a THIN wrapper around the existing
``11_clip_player.js_tmpl`` end-user playback machinery -- behaviour-
preserving for the 6 live single-camera scenes -- adding only the
edit-time authoring surface (Scene Settings cuts CRUD + timeline lane).

Two test layers (mirrors ``test_editor_module_registry.py``):

(a) STATIC: the generated viewer HTML carries the documented surface
    markers (the IIFE, the registration call, the contract fields, the
    Scene Settings render hook, the timelineLane). Pure Python -- no
    browser, no Node.

(b) DYNAMIC (Node): extract the CutsModule IIFE + the registry IIFE +
    a minimal cfg/window/document shim, then assert the module is
    discoverable via EditorModuleRegistry.get('cuts'), the timelineLane
    render callback is callable with a stub canvas context, the
    getDirtyState behaviour flips on an edit, and the edit ops (add /
    delete / retime / reorder) mutate cfg.clips correctly. Skips
    cleanly if Node is unavailable (CI provides it).
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
# (a) STATIC: rendered HTML carries the surface markers
# --------------------------------------------------------------------------


_CUTS_MARKERS = (
    # IIFE wrapper + the documented contract block
    "//  CutsModule (Phase 6 -- editor-arc-design #122 §4.3)",
    "(function _cutsInit() {",
    # EditorModule contract fields per Phase 2 spec
    "name: 'cuts',",
    "stateKey: 'clips',",
    "defaultModes: ['author', 'user', 'embed'],",
    # The five required EditorModule methods
    "mount: function (overlay, hud, interaction, modes) {",
    "unmount: function () {",
    "getDirtyState: function () {",
    "markClean: function () {",
    "onCfgChange: function (prev, next, stateKey) {",
    # Timeline lane definition (per spec §4.10 multi-lane registry)
    "timelineLane: timelineLane,",
    "label: 'Cuts',",
    "render: function (ctx, x, y, w, h, playhead) {",
    # renderSceneSettings hook (per spec §12.2 drawer integration)
    "renderSceneSettings: function (parentEl) {",
    # Registration call (lands the module in the registry at boot)
    "EditorModuleRegistry.register(cutsModule);",
    # Edit ops (each pushes ONE EditHistory snapshot at gesture-end)
    "function _addClip(cameraId, duration, inPoint) {",
    "function _deleteClip(clipId) {",
    "function _reorderClipUp(clipId) {",
    "function _reorderClipDown(clipId) {",
    "function _retimeClip(clipId, fields) {",
    # Test surface (merged onto window.__editor at register-time --
    # function form sidesteps the Object.assign getter-freeze
    # documented in 16_editor_timeline at its Object.defineProperties
    # site)
    "cutsGet() { return cutsModule; }",
    "cutsAddClip(cameraId, duration, inPoint) {",
    "cutsDeleteClip(clipId) {",
    "cutsRetimeClip(clipId, fields) {",
    # EditHistory snapshot labels (per spec §6.5.1)
    "'cuts-add'",
    "'cuts-delete'",
    "'cuts-reorder'",
    "'cuts-retime'",
)


def test_cuts_module_markers_present_in_rendered_html():
    """The CutsModule IIFE + registration + every documented contract
    field is present in the generated viewer HTML."""
    html = html_for("HarnessScene")
    for mk in _CUTS_MARKERS:
        assert mk in html, f"CutsModule marker missing: {mk!r}"


def test_cuts_module_fragment_file_exists_and_clean():
    """The 15d fragment is on disk + at the expected location (the
    orchestrator loads it after 11_clip_player and 15a_camera_path_module
    in lexical order) and has no BOM / CRLF corruption."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    f = parts / "15d_cuts_module.js_tmpl"
    assert f.exists(), f"missing fragment: {f}"
    raw = f.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM corruption"
    assert b"\r" not in raw, "CRLF corruption"
    txt = raw.decode("utf-8")
    assert "CutsModule" in txt
    assert "EditorModuleRegistry.register(cutsModule)" in txt


def test_cuts_module_fragment_loads_after_clip_player_and_camera_path():
    """Fragment ordering invariant: 15d (CutsModule) must concatenate
    AFTER 11_clip_player (whose IIFE-scope globals like _clipState are
    referenced) AND AFTER 15a (CameraPathModule) so the registry boots
    the camera_paths owner FIRST (registration order maps to the
    Scene Settings drawer section + timeline-lane stack order per spec
    §4.9). The 15a < 15d lexical ordering enforces this."""
    html = html_for("HarnessScene")
    # The unique signatures of each fragment's lead comment.
    clip_player_i = html.index(
        "// JS mirror of core.scene_cuts.ordered_clips"
    )
    camera_path_i = html.index(
        "//  CameraPathModule (Phase 2B -- editor-arc-design"
    )
    cuts_module_i = html.index(
        "//  CutsModule (Phase 6 -- editor-arc-design"
    )
    assert clip_player_i < cuts_module_i, (
        "11_clip_player must concatenate BEFORE 15d_cuts_module so "
        "the CutsModule can reference _clipState / _clipMode / _clipSeq "
        "via closure-scope from the shared <script type=\"module\"> block"
    )
    assert camera_path_i < cuts_module_i, (
        "15a_camera_path_module must concatenate BEFORE 15d_cuts_module "
        "so the registry's section-order convention (CameraPathModule "
        "first per spec §4.9) is preserved"
    )


def test_cuts_module_does_not_redeclare_clip_player_globals():
    """Phase 6 invariant: the CutsModule is a THIN wrapper -- it MUST
    NOT redeclare the IIFE-shared globals owned by 11_clip_player
    (which would shadow them, break the live playback machinery, and
    regress the 6 live scenes' byte-runtime behaviour). The whole
    CutsModule IIFE body references them via closure-scope only --
    never with a `let _clipState` / `let _clipMode` / `let _clipSeq` /
    `let _clipCameras` declaration of its own."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    cuts = (parts / "15d_cuts_module.js_tmpl").read_text(encoding="utf-8")
    # Each ClipPlayer-owned global -- a redeclaration here would shadow
    # the real binding. The patterns cover the three common declaration
    # forms (`let`, `const`, `var`).
    for global_name in (
        "_clipState",
        "_clipMode",
        "_clipSeq",
        "_clipCameras",
        "_clipUserStopped",
        "_clipStart",
    ):
        for form in ("let " + global_name, "const " + global_name,
                     "var " + global_name):
            assert form not in cuts, (
                f"CutsModule must NOT redeclare ClipPlayer-owned global "
                f"{global_name!r} -- found {form!r} which would shadow "
                "the binding in 11_clip_player and break end-user playback"
            )


# --------------------------------------------------------------------------
# (b) DYNAMIC: run the registry IIFE + the CutsModule IIFE under Node
# --------------------------------------------------------------------------


pytestmark_dynamic = pytest.mark.skipif(
    _NODE is None, reason="node not available (CI provides it)"
)


def _extract_registry_js() -> str:
    """Pull the EditorModuleRegistry IIFE verbatim from the rendered
    HTML (mirrors ``test_editor_module_registry.py::_extract_registry_js``).
    """
    html = html_for("HarnessScene")
    a = html.index("const EditorModuleRegistry = (() => {")
    end_marker = "    _bootMount: _bootMount,\n    };\n  })();"
    end = html.index(end_marker, a) + len(end_marker)
    return html[a:end]


def _extract_cuts_iife_js() -> str:
    """Pull the CutsModule IIFE verbatim from the rendered HTML. The
    IIFE wraps the entire module in `(function _cutsInit() { ... })();`
    so the boundaries are unique single-occurrence anchors."""
    html = html_for("HarnessScene")
    a = html.index("(function _cutsInit() {")
    # The IIFE closes with `})();` after `EditorModuleRegistry.register(cutsModule);`.
    # Find the close from the end of the registration call so the slice
    # is unambiguous (the register call is the IIFE's last statement).
    reg = html.index(
        "EditorModuleRegistry.register(cutsModule);", a)
    # The wrapper close is `\n  })();` immediately after a closing brace.
    end_marker = "  })();"
    end = html.index(end_marker, reg) + len(end_marker)
    return html[a:end]


def _run_node(script: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "cuts_test.mjs"
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


def _preamble() -> str:
    """Minimal shim so the Cuts IIFE can execute under Node: a
    ``window`` (which the registry's testSurface merge writes to), a
    ``document`` (which renderSceneSettings reads to find the cuts
    section element + create cards), and a ``cfg`` const (the live
    scene config the module reads/writes). The DOM is the documented
    16/17b convention -- ``parentEl.querySelector`` finds the section
    placeholder; here we hand-craft a minimal placeholder."""
    return (
        "globalThis.window = globalThis;\n"
        "globalThis.console = globalThis.console || "
        "{ warn() {}, log() {}, info() {}, error() {} };\n"
        # Minimal DOM shim -- only the methods CutsModule actually calls.
        "function _makeEl(tag) {\n"
        "  return {\n"
        "    tag: tag, children: [], style: { cssText: '' },\n"
        "    dataset: {}, className: '', value: '',\n"
        "    disabled: false, innerHTML: '',\n"
        "    title: '', type: '', min: '', step: '',\n"
        "    textContent: '',\n"
        "    appendChild(c) { this.children.push(c); return c; },\n"
        "    addEventListener() {},\n"
        "    querySelector(sel) { return null; },\n"
        "    setAttribute() {}, removeAttribute() {},\n"
        "  };\n"
        "}\n"
        "globalThis.document = {\n"
        "  createElement: _makeEl,\n"
        "  getElementById() { return null; },\n"
        "};\n"
        # Live cfg (the module reads/writes this).
        "globalThis.cfg = { cameras: [], clips: [] };\n"
        # Bypass alert (renderSceneSettings does not call it but the\n"
        # delete button's onclick uses confirm -- the harness never\n"
        # fires that path, but defensive).
        "globalThis.confirm = () => true;\n"
        "globalThis.alert = () => {};\n"
    )


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_cuts_module_registers_and_is_discoverable():
    """The CutsModule IIFE registers itself with the registry; the
    module is then discoverable via EditorModuleRegistry.get('cuts')
    and its stateKey is the documented 'clips'."""
    js = _preamble() + _extract_registry_js() + "\n" \
        + _extract_cuts_iife_js() + r"""
process.stdout.write(JSON.stringify({
  found: !!EditorModuleRegistry.get('cuts'),
  name: EditorModuleRegistry.get('cuts').name,
  stateKey: EditorModuleRegistry.get('cuts').stateKey,
  defaultModes: EditorModuleRegistry.get('cuts').defaultModes,
  listCount: EditorModuleRegistry.list().length,
}));
"""
    r = _run_node(js)
    assert r["found"] is True
    assert r["name"] == "cuts"
    assert r["stateKey"] == "clips"
    assert r["defaultModes"] == ["author", "user", "embed"]
    assert r["listCount"] == 1


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_cuts_module_test_surface_merged_onto_window_editor():
    """The CutsModule's testSurface is merged onto window.__editor at
    register-time, exposing the deterministic CRUD hooks the Scene
    Settings buttons run -- mirrors the CameraPathModule convention.
    Every test-surface entry is a FUNCTION (not a getter) so it
    sidesteps the Object.assign getter-freeze the registry's merge
    pattern would otherwise trigger."""
    js = _preamble() + _extract_registry_js() + "\n" \
        + _extract_cuts_iife_js() + r"""
process.stdout.write(JSON.stringify({
  hasGet: typeof (window.__editor && window.__editor.cutsGet) === 'function',
  modFromGet: !!(window.__editor && window.__editor.cutsGet
    && window.__editor.cutsGet().name === 'cuts'),
  hasAdd: typeof (window.__editor && window.__editor.cutsAddClip) === 'function',
  hasDelete: typeof (window.__editor && window.__editor.cutsDeleteClip) === 'function',
  hasRetime: typeof (window.__editor && window.__editor.cutsRetimeClip) === 'function',
  hasReorderUp: typeof (window.__editor && window.__editor.cutsReorderUp) === 'function',
  hasReorderDown: typeof (window.__editor && window.__editor.cutsReorderDown) === 'function',
  hasRender: typeof (window.__editor && window.__editor.cutsRender) === 'function',
  hasDirty: typeof (window.__editor && window.__editor.cutsModuleDirty) === 'function',
}));
"""
    r = _run_node(js)
    assert r["hasGet"] is True
    assert r["modFromGet"] is True
    assert r["hasAdd"] is True
    assert r["hasDelete"] is True
    assert r["hasRetime"] is True
    assert r["hasReorderUp"] is True
    assert r["hasReorderDown"] is True
    assert r["hasRender"] is True
    assert r["hasDirty"] is True


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_cuts_module_add_clip_appends_and_marks_dirty():
    """cutsAddClip appends a new clip referencing the given camera,
    auto-assigns clip_start = sum of preceding durations (gap-free
    timeline), defaults duration=5.0s + in=0.0, and flips the dirty
    flag to true. The boot config snapshotted a clean baseline so the
    first edit transitions clean -> dirty."""
    js = _preamble() + _extract_registry_js() + "\n" \
        + _extract_cuts_iife_js() + r"""
// Pre-populate cameras the dropdown reads from.
cfg.cameras = [
  { id: 'cam1', name: 'Camera 1', path_id: 'p1' },
  { id: 'cam2', name: 'Camera 2', path_id: 'p2' },
];
// Boot-mount snapshots the empty clips as clean (no edits yet).
EditorModuleRegistry._bootMount();
const dirtyBefore = window.__editor.cutsModuleDirty();
const added = window.__editor.cutsAddClip('cam1');
const added2 = window.__editor.cutsAddClip('cam2', 8.0, 1.5);
process.stdout.write(JSON.stringify({
  dirtyBefore,
  dirtyAfter: window.__editor.cutsModuleDirty(),
  clipsCount: cfg.clips.length,
  clip1: cfg.clips[0],
  clip2: cfg.clips[1],
  addedId: added && added.id,
}));
"""
    r = _run_node(js)
    assert r["dirtyBefore"] is False
    assert r["dirtyAfter"] is True
    assert r["clipsCount"] == 2
    # First clip: defaults (5s duration, 0s in-point).
    assert r["clip1"]["camera_id"] == "cam1"
    assert r["clip1"]["clip_start"] == 0
    assert r["clip1"]["duration"] == 5.0
    assert r["clip1"]["in"] == 0.0
    # Second clip: 8s duration, 1.5s in-point, starts AFTER clip1 (5s).
    assert r["clip2"]["camera_id"] == "cam2"
    assert r["clip2"]["clip_start"] == 5.0
    assert r["clip2"]["duration"] == 8.0
    assert r["clip2"]["in"] == 1.5
    assert r["addedId"].startswith("clip_")


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_cuts_module_delete_clip_ripples_starts():
    """cutsDeleteClip removes the clip + re-packs clip_start values so
    the remaining sequence stays contiguous (NLE ripple-delete
    semantics, NOT leaving a hole). Deleting the middle clip of
    [0..5, 5..10, 10..15] yields [0..5, 5..10] with the third now at 5."""
    js = _preamble() + _extract_registry_js() + "\n" \
        + _extract_cuts_iife_js() + r"""
cfg.cameras = [{ id: 'c', name: 'C', path_id: 'p' }];
EditorModuleRegistry._bootMount();
window.__editor.cutsAddClip('c', 5.0, 0.0);
window.__editor.cutsAddClip('c', 5.0, 0.0);
window.__editor.cutsAddClip('c', 5.0, 0.0);
const middleId = cfg.clips[1].id;
const ok = window.__editor.cutsDeleteClip(middleId);
process.stdout.write(JSON.stringify({
  ok,
  clipsCount: cfg.clips.length,
  starts: cfg.clips.map(c => c.clip_start),
  ids: cfg.clips.map(c => c.id),
  missingMiddle: !cfg.clips.find(c => c.id === middleId),
}));
"""
    r = _run_node(js)
    assert r["ok"] is True
    assert r["clipsCount"] == 2
    # After ripple-delete, the two remaining clips are at 0 and 5 (not
    # 0 and 10 -- the gap is closed). Both durations were 5s, so the
    # canonicalised starts are [0, 5].
    assert sorted(r["starts"]) == [0, 5]
    assert r["missingMiddle"] is True


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_cuts_module_reorder_swaps_clip_starts():
    """cutsReorderUp swaps the clip's playback position with the
    previous clip (by clip_start). After swap + re-pack, the entry
    that was second now plays first. The reorder MUST NOT mutate
    durations (only the playback positions change)."""
    js = _preamble() + _extract_registry_js() + "\n" \
        + _extract_cuts_iife_js() + r"""
cfg.cameras = [
  { id: 'a', name: 'A', path_id: 'pa' },
  { id: 'b', name: 'B', path_id: 'pb' },
];
EditorModuleRegistry._bootMount();
window.__editor.cutsAddClip('a', 3.0, 0.0);   // clip 1: camera a, dur 3
window.__editor.cutsAddClip('b', 7.0, 0.0);   // clip 2: camera b, dur 7
const idB = cfg.clips[1].id;
const ok = window.__editor.cutsReorderUp(idB);
// After reorder + repack, B should play FIRST (starts at 0), A second.
const ordered = cfg.clips.slice().sort(
  (x, y) => x.clip_start - y.clip_start);
process.stdout.write(JSON.stringify({
  ok,
  orderedCameraIds: ordered.map(c => c.camera_id),
  orderedStarts: ordered.map(c => c.clip_start),
  orderedDurations: ordered.map(c => c.duration),
}));
"""
    r = _run_node(js)
    assert r["ok"] is True
    # B plays first, A second.
    assert r["orderedCameraIds"] == ["b", "a"]
    # B starts at 0 (dur 7), A starts at 7 (dur 3) -- gap-free.
    assert r["orderedStarts"] == [0, 7]
    # Durations untouched.
    assert r["orderedDurations"] == [7, 3]


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_cuts_module_retime_clip_updates_fields():
    """cutsRetimeClip updates duration / in / camera_id in place + re-
    packs subsequent clip_starts if duration changed. Each successful
    change mutates ONE clip; null/invalid values are rejected silently."""
    js = _preamble() + _extract_registry_js() + "\n" \
        + _extract_cuts_iife_js() + r"""
cfg.cameras = [
  { id: 'a', name: 'A', path_id: 'pa' },
  { id: 'b', name: 'B', path_id: 'pb' },
];
EditorModuleRegistry._bootMount();
window.__editor.cutsAddClip('a', 5.0, 0.0);
window.__editor.cutsAddClip('a', 5.0, 0.0);
const id1 = cfg.clips[0].id;
// Change duration of clip 1 to 10s -- clip 2's start should ripple.
const ok1 = window.__editor.cutsRetimeClip(id1, { duration: 10.0 });
// Change in-point of clip 1 to 2.5s -- positions don't change.
const ok2 = window.__editor.cutsRetimeClip(id1, { in: 2.5 });
// Change camera of clip 1 to 'b'.
const ok3 = window.__editor.cutsRetimeClip(id1, { camera_id: 'b' });
// Invalid: negative duration is rejected silently.
const okBad = window.__editor.cutsRetimeClip(id1, { duration: -5 });
process.stdout.write(JSON.stringify({
  ok1, ok2, ok3, okBad,
  clip1Dur: cfg.clips[0].duration,
  clip1In: cfg.clips[0].in,
  clip1Cam: cfg.clips[0].camera_id,
  clip2Start: cfg.clips[1].clip_start,
}));
"""
    r = _run_node(js)
    assert r["ok1"] is True
    assert r["ok2"] is True
    assert r["ok3"] is True
    assert r["okBad"] is False           # negative duration rejected
    assert r["clip1Dur"] == 10.0
    assert r["clip1In"] == 2.5
    assert r["clip1Cam"] == "b"
    # clip2 ripples to start at 10s (clip1's new duration).
    assert r["clip2Start"] == 10.0


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_cuts_module_collect_patch_returns_clips_slice():
    """When the CutsModule is dirty, EditorModuleRegistry.collectPatch
    returns the live clips slice under the 'clips' stateKey. This is
    the slot the Save dispatcher routes through the SPCP1 payload --
    proving the registry's one-key-per-stateKey model holds for cuts."""
    js = _preamble() + _extract_registry_js() + "\n" \
        + _extract_cuts_iife_js() + r"""
cfg.cameras = [{ id: 'a', name: 'A', path_id: 'pa' }];
EditorModuleRegistry._bootMount();
// Boot-clean baseline -> collectPatch is empty for cuts.
const patchBefore = EditorModuleRegistry.collectPatch();
window.__editor.cutsAddClip('a', 6.0, 0.0);
// After an edit -> patch carries the clips slice under 'clips' key.
const patchAfter = EditorModuleRegistry.collectPatch();
// markClean -> dirty drops back to false.
EditorModuleRegistry.get('cuts').markClean();
const patchClean = EditorModuleRegistry.collectPatch();
process.stdout.write(JSON.stringify({
  beforeDirtyNames: patchBefore.dirtyNames,
  afterDirtyNames: patchAfter.dirtyNames,
  afterClipsKeyPresent: 'clips' in patchAfter.patch,
  afterClipsLen: patchAfter.patch.clips
    ? patchAfter.patch.clips.length : null,
  cleanDirtyNames: patchClean.dirtyNames,
}));
"""
    r = _run_node(js)
    assert r["beforeDirtyNames"] == []       # boot-clean
    assert r["afterDirtyNames"] == ["cuts"]  # add flipped dirty
    assert r["afterClipsKeyPresent"] is True
    assert r["afterClipsLen"] == 1
    assert r["cleanDirtyNames"] == []        # markClean -> clean


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_cuts_module_timeline_lane_render_callable_with_stub_ctx():
    """The timelineLane.render callback per spec §4.10 multi-lane
    registry signature: render(ctx, x, y, w, h, playhead). With a
    stub canvas-2d context capturing every state mutation, the render
    must (a) be callable without throwing on an empty cfg.clips, and
    (b) draw rectangles per clip when clips are present + apply the
    documented label ('Cuts')."""
    js = _preamble() + _extract_registry_js() + "\n" \
        + _extract_cuts_iife_js() + r"""
cfg.cameras = [
  { id: 'cam1', name: 'Cam One', path_id: 'p1' },
  { id: 'cam2', name: 'Cam Two', path_id: 'p2' },
];
EditorModuleRegistry._bootMount();
const mod = EditorModuleRegistry.get('cuts');
// Stub canvas-2d ctx that records every mutation + draw call.
function makeCtx() {
  const ops = [];
  return {
    ops,
    save() { ops.push(['save']); },
    restore() { ops.push(['restore']); },
    fillRect(x, y, w, h) { ops.push(['fillRect', x, y, w, h]); },
    fillText(t, x, y) { ops.push(['fillText', t, x, y]); },
    set fillStyle(v) { ops.push(['fillStyle', v]); },
    set strokeStyle(v) { ops.push(['strokeStyle', v]); },
    set font(v) { ops.push(['font', v]); },
    set textBaseline(v) { ops.push(['textBaseline', v]); },
    set globalAlpha(v) { ops.push(['globalAlpha', v]); },
  };
}
// (a) Empty clips: render must not throw + still draws the lane
// background.
const ctxEmpty = makeCtx();
let throwsEmpty = false;
try { mod.timelineLane.render(ctxEmpty, 0, 0, 300, 24, 0); }
catch (e) { throwsEmpty = true; }
// (b) With clips: render draws 1 fillRect per clip + per-camera
// colour + the camera label inside if width allows.
window.__editor.cutsAddClip('cam1', 5.0, 0.0);
window.__editor.cutsAddClip('cam2', 5.0, 0.0);
const ctxClips = makeCtx();
mod.timelineLane.render(ctxClips, 0, 0, 600, 24, 0);
// Count fillRect calls (background + 2 clips = 3).
const fillRects = ctxClips.ops.filter(o => o[0] === 'fillRect').length;
// Count fillText calls (one label per clip when block is wide enough).
const fillTexts = ctxClips.ops.filter(o => o[0] === 'fillText').length;
// rows + label fields are part of the lane object.
process.stdout.write(JSON.stringify({
  throwsEmpty,
  laneRows: mod.timelineLane.rows,
  laneLabel: mod.timelineLane.label,
  emptyFillRects: ctxEmpty.ops.filter(o => o[0] === 'fillRect').length,
  clipsFillRects: fillRects,
  clipsFillTexts: fillTexts,
}));
"""
    r = _run_node(js)
    assert r["throwsEmpty"] is False
    assert r["laneRows"] == 1
    assert r["laneLabel"] == "Cuts"
    # Empty clips: at least the lane-background rect is drawn.
    assert r["emptyFillRects"] >= 1
    # With 2 clips: background + 2 clip rects = 3.
    assert r["clipsFillRects"] == 3
    # With 2 clips and 600px wide lane (300px per clip > 36px label
    # threshold), 2 camera labels are drawn.
    assert r["clipsFillTexts"] == 2


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_cuts_module_mark_clean_resets_dirty_signal():
    """After an edit, getDirtyState reports dirty; markClean snaps the
    new clean baseline so a subsequent getDirtyState (with no further
    edit) reports clean. This is the post-save bookkeeping path the
    EditorModuleRegistry.markAllClean dispatcher uses."""
    js = _preamble() + _extract_registry_js() + "\n" \
        + _extract_cuts_iife_js() + r"""
cfg.cameras = [{ id: 'a', name: 'A', path_id: 'pa' }];
EditorModuleRegistry._bootMount();
window.__editor.cutsAddClip('a', 4.0, 0.0);
const dirtyAfterEdit = EditorModuleRegistry.get('cuts')
  .getDirtyState().isDirty;
EditorModuleRegistry.get('cuts').markClean();
const dirtyAfterClean = EditorModuleRegistry.get('cuts')
  .getDirtyState().isDirty;
// A second edit re-flips dirty (the baseline is the post-markClean
// state, so any subsequent mutation is detected).
window.__editor.cutsAddClip('a', 4.0, 0.0);
const dirtyAfterSecond = EditorModuleRegistry.get('cuts')
  .getDirtyState().isDirty;
process.stdout.write(JSON.stringify({
  dirtyAfterEdit, dirtyAfterClean, dirtyAfterSecond,
}));
"""
    r = _run_node(js)
    assert r["dirtyAfterEdit"] is True
    assert r["dirtyAfterClean"] is False
    assert r["dirtyAfterSecond"] is True
