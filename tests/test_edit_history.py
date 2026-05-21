"""EditHistory snapshot ring-buffer tests (Phase 2 -- editor-arc-design #122).

The EditHistory IIFE lives in
``viewers/spark/template_parts/17a_edit_history.js_tmpl`` and self-publishes
onto ``window.__sceneview.history`` (read by ``EditorModuleRegistry``'s
delegation methods). The contract: R8 snapshot pattern -- each *gesture*
pushes ONE ``JSON.parse(JSON.stringify(cfg))`` snapshot, undo restores the
prior snapshot wholesale by mutating the live cfg in place (callers hold
a reference, so we must not swap the object). 200-entry ring cap.

Two test layers (same pattern as ``test_editor_module_registry.py``):

(a) STATIC: rendered HTML carries the documented surface markers + the
    hotkey wiring. Pure Python -- no browser, no Node.

(b) DYNAMIC (Node): extract the IIFE verbatim from the rendered HTML and
    run it under Node to exercise the actual ring-buffer behaviour:
    push/undo/redo/canUndo/canRedo/clear, cap overflow, JSON-clone
    isolation, restore semantics, and the EditorModuleRegistry delegation
    contract. Skips cleanly if Node is unavailable.
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

_HISTORY_MARKERS = (
    "const EditHistory = (() => {",            # the IIFE declaration
    "[EditHistory] ",                          # _warn prefix
    "const _HISTORY_CAP = 200;",               # R8 §3 ring cap
    "window.__sceneview.history = EditHistory;",  # self-publish wiring
    "EditorModuleRegistry.undo();",            # hotkey -> registry delegation
    "EditorModuleRegistry.redo();",            # hotkey -> registry delegation
    # Hotkey wiring -- author-mode gate + Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z
    "if (!ModeManager.is('author')) return;",
    "ev.metaKey || ev.ctrlKey",
)


def test_history_markers_present_in_rendered_html():
    """The EditHistory IIFE + the keyboard wiring are both present."""
    html = html_for("HarnessScene")
    for mk in _HISTORY_MARKERS:
        assert mk in html, f"history marker missing: {mk!r}"


def test_history_fragment_file_exists_no_bom_no_crlf():
    """The 17a fragment is on disk + ASCII + LF-only (no BOM, no CRLF)."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    f = parts / "17a_edit_history.js_tmpl"
    assert f.exists(), f"missing fragment: {f}"
    raw = f.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM corruption"
    assert b"\r" not in raw, "CRLF corruption"
    txt = raw.decode("utf-8")
    assert "EditHistory" in txt
    assert "_HISTORY_CAP" in txt


def test_history_documents_snapshot_pattern():
    """The fragment header documents R8 snapshot semantics + the gesture
    rule (commit at gesture START, not per animation frame) -- the rule
    Phases 3-8 read when wiring their modules' gestures."""
    html = html_for("HarnessScene")
    # The R8 §4.2 gesture-start convention must be documented in-file.
    assert "GRANULAR-VS-COARSE" in html or "gesture" in html.lower()
    assert "Snapshot" in html or "snapshot" in html
    # Per the spec §6.4 ephemeral list, the comment block names the
    # clear triggers.
    assert "mode switch" in html
    assert "save" in html.lower()


def test_history_hotkey_handler_gates_on_inputs():
    """The hotkey handler must NOT hijack Ctrl+Z while focused inside a
    text input / textarea (native undo there)."""
    html = html_for("HarnessScene")
    # The skip-while-typing guard is present.
    assert "INPUT" in html
    assert "TEXTAREA" in html


# --------------------------------------------------------------------------
# (b) DYNAMIC: run the EditHistory IIFE under Node
# --------------------------------------------------------------------------

pytestmark_dynamic = pytest.mark.skipif(
    _NODE is None, reason="node not available (CI provides it)"
)


def _extract_history_js() -> str:
    """Pull the EditHistory IIFE + its self-publish block verbatim out of
    the rendered HTML. Returns the JS source from the
    ``const EditHistory = (() => {`` line through the publish trailer."""
    html = html_for("HarnessScene")
    a = html.index("const EditHistory = (() => {")
    # The publish trailer is the unique end marker.
    end_marker = "window.__sceneview.history = EditHistory;"
    end = html.index(end_marker, a) + len(end_marker)
    # Eat the closing `}` of the try-catch wrapper.
    end = html.index("} catch (e) {}", end) + len("} catch (e) {}")
    seg = html[a:end]
    assert "function push(label)" in seg
    assert "function undo()" in seg
    return seg


def _run_node(script: str) -> dict:
    """Run ``script`` under Node and parse its stdout as JSON."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "history_test.mjs"
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
            % (out.returncode, out.stderr.decode("utf-8", "replace"),
               out.stdout.decode("utf-8", "replace"))
        )
    return json.loads(out.stdout.decode("utf-8"))


def _history_preamble() -> str:
    """Provide the globals the IIFE assumes (window, console, cfg).
    A stub EditorModuleRegistry exposes ``emit`` + ``notifyCfgChange``
    so the IIFE's delegated calls do not throw -- the test asserts
    what got emitted."""
    return (
        "globalThis.window = globalThis;\n"
        "globalThis.console = globalThis.console || { warn() {}, log() {} };\n"
        "globalThis.cfg = { camera_paths: [], annotations: [] };\n"
        "let _emitted = [];\n"
        "globalThis.EditorModuleRegistry = {\n"
        "  emit(event, ...args) { _emitted.push([event, ...args]); },\n"
        "  notifyCfgChange(stateKey, prev, next) {\n"
        "    _emitted.push(['notify', stateKey]);\n"
        "  },\n"
        "};\n"
        "globalThis.ModeManager = { is(m) { return m === 'author'; } };\n"
        # Eat document/event-listener calls the trailer makes -- harness
        # only needs the IIFE, not the keydown wiring.
        "globalThis.document = globalThis.document || { activeElement: null };\n"
        "if (!globalThis.window.addEventListener) {\n"
        "  globalThis.window.addEventListener = function() {};\n"
        "}\n"
    )


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_single_edit_is_undoable():
    """WF-H2 (#143) regression. The FIRST user edit pushes ONE pre-gesture
    snapshot (no init-time baseline -- every module's pushUndo fires before
    its own mutation). canUndo MUST be true after that single push (cursor 1
    -> `_cursor > 0`), and the undo restores the pre-edit baseline."""
    js = _history_preamble() + _extract_history_js() + r"""
const before = {
  canUndo0: EditHistory.canUndo(),    // nothing pushed yet -> false
};
EditHistory.push('ann-add');          // pre-gesture snapshot (empty cfg)
cfg.camera_paths.push({id: 'p1'});    // the gesture mutation
const afterPush = {
  canUndo: EditHistory.canUndo(),     // MUST be true (the bug returned false)
  canRedo: EditHistory.canRedo(),
  length: EditHistory.length,
  cursor: EditHistory.cursor,
};
EditHistory.undo();                   // restore the pre-edit baseline
const afterUndo = {
  paths: cfg.camera_paths.map(p => p.id),  // back to [] (baseline)
  canUndo: EditHistory.canUndo(),
  canRedo: EditHistory.canRedo(),
};
process.stdout.write(JSON.stringify({ before, afterPush, afterUndo }));
"""
    r = _run_node(js)
    assert r["before"]["canUndo0"] is False
    assert r["afterPush"]["canUndo"] is True, (
        "the FIRST edit must be undoable -- canUndo was `_cursor > 1` which "
        "left the single-edit case (cursor=1) un-undoable"
    )
    assert r["afterPush"]["canRedo"] is False
    assert r["afterPush"]["length"] == 1
    assert r["afterPush"]["cursor"] == 1
    # The undo rolls the cfg back to the empty pre-edit baseline.
    assert r["afterUndo"]["paths"] == []
    assert r["afterUndo"]["canUndo"] is False
    assert r["afterUndo"]["canRedo"] is True


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_two_edits_canundo_canredo():
    """Two pushes (two edits, pre-gesture convention) make canUndo true;
    canRedo stays false until an undo materialises the redo head."""
    js = _history_preamble() + _extract_history_js() + r"""
EditHistory.push('e1');         // pre-gesture state (empty)
cfg.camera_paths.push({id: 'p1'});
EditHistory.push('e2');         // pre-second-gesture state ([p1])
cfg.camera_paths.push({id: 'p2'});
process.stdout.write(JSON.stringify({
  canUndo: EditHistory.canUndo(),
  canRedo: EditHistory.canRedo(),
  length: EditHistory.length,
  cursor: EditHistory.cursor,
}));
"""
    r = _run_node(js)
    assert r["canUndo"] is True
    assert r["canRedo"] is False
    assert r["length"] == 2
    assert r["cursor"] == 2


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_undo_restores_prior_cfg_state():
    """undo() steps back exactly ONE gesture. With the pre-gesture
    convention each push captures the state BEFORE its mutation, so one
    undo from a two-edit history lands on the intermediate state (the
    pre-state of the second gesture = the result of the first), NOT all
    the way back to the empty baseline. The live cfg is mutated in place
    (callers hold a reference)."""
    js = _history_preamble() + _extract_history_js() + r"""
const origRef = cfg;
EditHistory.push('e1');               // pre-gesture-1 snapshot: camera_paths == []
cfg.camera_paths.push({id: 'p1'});    // gesture-1 mutation -> [p1]
EditHistory.push('e2');               // pre-gesture-2 snapshot: camera_paths == [p1]
cfg.camera_paths.push({id: 'p2'});    // gesture-2 mutation -> [p1,p2]
// One undo steps back exactly one gesture: [p1,p2] -> [p1] (the e2
// pre-state). It must NOT skip to the empty baseline (the WF-H2 bug
// restored _stack[_cursor-2], skipping the intermediate state).
const undone = EditHistory.undo();
process.stdout.write(JSON.stringify({
  sameRef: cfg === origRef,
  camera_paths: cfg.camera_paths.map(p => p.id),
  undoneLabel: undone ? undone.label : null,
}));
"""
    r = _run_node(js)
    assert r["sameRef"] is True, "undo must MUTATE cfg in place, not swap it"
    # One undo lands on the intermediate state [p1], not the empty baseline.
    assert r["camera_paths"] == ["p1"]
    assert r["undoneLabel"] == "e2"


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_three_edits_undo_visits_each_intermediate_state():
    """WF-H2 (#143). Three distinct edits, then three undos: each undo
    steps back exactly ONE gesture, visiting every intermediate state in
    turn (no skipping), ending at the pre-first-edit baseline. Redo then
    walks forward symmetrically through the same states."""
    js = _history_preamble() + _extract_history_js() + r"""
const seq = [];
function ids() { return cfg.camera_paths.map(p => p.id); }
EditHistory.push('e1'); cfg.camera_paths.push({id: 'a'});   // -> [a]
EditHistory.push('e2'); cfg.camera_paths.push({id: 'b'});   // -> [a,b]
EditHistory.push('e3'); cfg.camera_paths.push({id: 'c'});   // -> [a,b,c]
const live = ids();                                          // [a,b,c]
const u1 = EditHistory.undo(); const s1 = ids();             // [a,b]
const u2 = EditHistory.undo(); const s2 = ids();             // [a]
const u3 = EditHistory.undo(); const s3 = ids();             // []
const canUndoAtBase = EditHistory.canUndo();                 // false
// Redo back up, one gesture each.
EditHistory.redo(); const r1 = ids();                        // [a]
EditHistory.redo(); const r2 = ids();                        // [a,b]
EditHistory.redo(); const r3 = ids();                        // [a,b,c]
const canRedoAtTop = EditHistory.canRedo();                  // false
process.stdout.write(JSON.stringify({
  live, s1, s2, s3, canUndoAtBase, r1, r2, r3, canRedoAtTop,
  labels: [u1 && u1.label, u2 && u2.label, u3 && u3.label],
}));
"""
    r = _run_node(js)
    assert r["live"] == ["a", "b", "c"]
    # Each undo visits exactly one intermediate state -- no skipping.
    assert r["s1"] == ["a", "b"]
    assert r["s2"] == ["a"]
    assert r["s3"] == []
    assert r["canUndoAtBase"] is False
    # Undo labels follow the gestures in reverse order.
    assert r["labels"] == ["e3", "e2", "e1"]
    # Redo walks forward symmetrically through the same states.
    assert r["r1"] == ["a"]
    assert r["r2"] == ["a", "b"]
    assert r["r3"] == ["a", "b", "c"]
    assert r["canRedoAtTop"] is False


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_redo_walks_forward_through_history():
    """redo() walks the cursor forward through previously-undone states.
    Pre-gesture convention: each push captures the state BEFORE its
    mutation; the first undo lazily materialises the live (redo) head."""
    js = _history_preamble() + _extract_history_js() + r"""
EditHistory.push('e1'); cfg.camera_paths.push({id: 'p1'});   // -> [p1]
EditHistory.push('e2'); cfg.camera_paths.push({id: 'p2'});   // -> [p1,p2]
// _stack = [ []  , [p1] ], cursor=2 (live [p1,p2] not yet snapshotted)
const before = {
  length: EditHistory.length, cursor: EditHistory.cursor,
  canUndo: EditHistory.canUndo(), canRedo: EditHistory.canRedo(),
  paths: cfg.camera_paths.map(p => p.id),
};
EditHistory.undo();    // materialise live head [p1,p2]; step to [p1]
const afterUndo = {
  cursor: EditHistory.cursor,
  paths: cfg.camera_paths.map(p => p.id),
  canRedo: EditHistory.canRedo(),
};
EditHistory.redo();    // forward one gesture -> back to [p1,p2]
const afterRedo = {
  cursor: EditHistory.cursor,
  paths: cfg.camera_paths.map(p => p.id),
  canRedo: EditHistory.canRedo(),
};
process.stdout.write(JSON.stringify({ before, afterUndo, afterRedo }));
"""
    r = _run_node(js)
    assert r["before"]["paths"] == ["p1", "p2"]
    assert r["before"]["canRedo"] is False
    assert r["afterUndo"]["paths"] == ["p1"]
    assert r["afterUndo"]["canRedo"] is True
    assert r["afterRedo"]["paths"] == ["p1", "p2"]
    assert r["afterRedo"]["canRedo"] is False


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_push_after_undo_truncates_redo_tail():
    """A fresh push after an undo invalidates any redo path (truncates the
    tail). Pre-gesture convention: two edits push two snapshots; an undo
    materialises the live head; a new edit drops the abandoned redo head."""
    js = _history_preamble() + _extract_history_js() + r"""
EditHistory.push('e1'); cfg.camera_paths.push({id: 'p1'});   // -> [p1]
EditHistory.push('e2'); cfg.camera_paths.push({id: 'p2'});   // -> [p1,p2]
EditHistory.undo();              // materialise head; cfg -> [p1], canRedo true
EditHistory.push('e3-branch');   // truncates the materialised redo head
cfg.camera_paths.push({id: 'p3'});
process.stdout.write(JSON.stringify({
  length: EditHistory.length,
  cursor: EditHistory.cursor,
  canRedo: EditHistory.canRedo(), // false -- tail was truncated
  canUndo: EditHistory.canUndo(),
  labels: EditHistory.labels().map(e => e.label),
  paths: cfg.camera_paths.map(p => p.id),
}));
"""
    r = _run_node(js)
    # After undo the stack was [ []  , [p1] , [p1,p2](materialised) ] cursor=1.
    # push('e3-branch') truncates to cursor (len=1 -> [ [] ]) then captures the
    # live [p1] state -> [ [] , [p1] ], cursor=2.
    assert r["canRedo"] is False
    assert r["canUndo"] is True
    assert r["labels"] == ["e1", "e3-branch"]
    assert r["length"] == 2
    assert r["cursor"] == 2
    assert r["paths"] == ["p1", "p3"]


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_capacity_overflow_evicts_oldest_and_warns():
    """When push count exceeds 200, the oldest snapshot is evicted (ring
    eviction) and a console.warn is emitted (spec instruction)."""
    js = _history_preamble() + _extract_history_js() + r"""
let warned = 0;
globalThis.console.warn = function (msg) {
  if (typeof msg === 'string' && msg.includes('overflow')) warned++;
};
// Push exactly 250 -- well above the 200 cap.
for (let i = 0; i < 250; i++) {
  cfg.camera_paths.push({id: 'p' + i});
  EditHistory.push('iter-' + i);
}
process.stdout.write(JSON.stringify({
  length: EditHistory.length,
  cursor: EditHistory.cursor,
  capacity: EditHistory.capacity,
  warned: warned > 0,
  // The first labels in the stack should be the most recent surviving ones,
  // not the original 'iter-0' (which got evicted).
  firstLabel: EditHistory.labels()[0].label,
  lastLabel: EditHistory.labels()[EditHistory.length - 1].label,
}));
"""
    r = _run_node(js)
    assert r["length"] == 200, f"ring cap should clamp to 200, got {r['length']}"
    assert r["capacity"] == 200
    assert r["cursor"] == 200
    assert r["warned"] is True
    # First surviving label is iter-50 (50 oldest were evicted),
    # last is iter-249 (the most recent).
    assert r["firstLabel"] == "iter-50"
    assert r["lastLabel"] == "iter-249"


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_clear_drops_all_snapshots():
    """clear() empties the ring + resets canUndo/canRedo."""
    js = _history_preamble() + _extract_history_js() + r"""
EditHistory.push('s0');
EditHistory.push('s1');
EditHistory.push('s2');
EditHistory.clear();
process.stdout.write(JSON.stringify({
  length: EditHistory.length,
  cursor: EditHistory.cursor,
  canUndo: EditHistory.canUndo(),
  canRedo: EditHistory.canRedo(),
}));
"""
    r = _run_node(js)
    assert r["length"] == 0
    assert r["cursor"] == 0
    assert r["canUndo"] is False
    assert r["canRedo"] is False


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_snapshot_is_a_deep_clone_not_a_reference():
    """A snapshot's contents are JSON-cloned -- later mutations to cfg
    must NOT alter the captured snapshot (otherwise undo restores the
    *current* state and is a no-op). Pre-gesture: ONE push captures the
    empty pre-state, the gesture mutates, undo restores the empty snap."""
    js = _history_preamble() + _extract_history_js() + r"""
EditHistory.push('s0');                     // snap = empty (pre-gesture)
cfg.camera_paths.push({id: 'mutate-me'});   // the gesture mutation
cfg.camera_paths[0].id = 'mutated-again';   // post-snapshot mutation
const undone = EditHistory.undo();          // restore the s0 (empty) snap
// After undo, cfg should reflect the s0 snap (= empty); the deep clone
// means the post-push mutations never touched the captured snapshot.
const len = cfg.camera_paths.length;
process.stdout.write(JSON.stringify({
  cameraLen: len, undoneLabel: undone ? undone.label : null,
}));
"""
    r = _run_node(js)
    assert r["cameraLen"] == 0, (
        "snapshot must be a deep clone -- live mutations of cfg post-push "
        "must not change the captured snap"
    )
    assert r["undoneLabel"] == "s0"


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_undo_with_empty_history_returns_null():
    """A no-op undo on an EMPTY history returns null + leaves cfg alone.
    After a single push (one edit) undo IS available (WF-H2 fix) and
    returns that entry -- the FIRST edit must be undoable."""
    js = _history_preamble() + _extract_history_js() + r"""
const r0 = EditHistory.undo();              // empty -> null
const canUndo0 = EditHistory.canUndo();     // false
EditHistory.push('only');                   // one pre-gesture snapshot
cfg.camera_paths.push({id: 'p1'});          // the gesture
const r1 = EditHistory.undo();              // 1 entry -> undoable now
process.stdout.write(JSON.stringify({
  r0,
  canUndo0,
  r1Label: r1 ? r1.label : null,
  pathsAfterUndo: cfg.camera_paths.map(p => p.id),
  canUndoAfter: EditHistory.canUndo(),
}));
"""
    r = _run_node(js)
    assert r["r0"] is None
    assert r["canUndo0"] is False
    # The single edit is undoable -- undo returns the pushed entry and
    # rolls the cfg back to the empty pre-edit baseline.
    assert r["r1Label"] == "only"
    assert r["pathsAfterUndo"] == []
    assert r["canUndoAfter"] is False


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_emit_history_events_on_push_undo_redo():
    """push/undo/redo each emit through EditorModuleRegistry.emit
    so a UI (toast / dirty marker) can subscribe."""
    js = _history_preamble() + _extract_history_js() + r"""
const events = [];
globalThis.EditorModuleRegistry.emit = function (event, ...args) {
  events.push([event, ...args]);
};
EditHistory.push('first');
cfg.camera_paths.push({id: 'p'});
EditHistory.push('second');
EditHistory.undo();
EditHistory.redo();
process.stdout.write(JSON.stringify({ events }));
"""
    r = _run_node(js)
    seen = [e[0] for e in r["events"]]
    assert "history:push" in seen
    assert "history:undo" in seen
    assert "history:redo" in seen


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_restore_clears_keys_added_after_snapshot():
    """When a snapshot did NOT contain a key but the live cfg later gained
    one, restore must DELETE that key (else restored state has stale keys)."""
    js = _history_preamble() + _extract_history_js() + r"""
// Snapshot WITHOUT 'audio' key (pre-gesture state of the "add audio" edit).
EditHistory.push('s0');
// The gesture: add a new top-level key not in s0, then mutate it.
cfg.audio = [{id: 'a1'}];
cfg.audio.push({id: 'a2'});
const undone = EditHistory.undo();  // restore s0 (no audio)
process.stdout.write(JSON.stringify({
  hasAudio: 'audio' in cfg,
  undoneLabel: undone ? undone.label : null,
}));
"""
    r = _run_node(js)
    assert r["hasAudio"] is False, (
        "restore must DELETE keys absent from the target snapshot, not just "
        "Object.assign over the existing keys (else the restored state has "
        "stale keys that were added after the snapshot)"
    )


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_restore_preserves_camera_paths_array_identity():
    """Phase 11A Issue 3 regression. The camera_paths array is captured BY
    REFERENCE at init by 09_playback_spline (``const cameraPaths =
    cfg.camera_paths``; read by the camera dropdown's _camSelCameras /
    startPath / buildPlayer). A plain Object.assign restore would set
    cfg.camera_paths to a NEW cloned array, leaving that alias STALE ->
    the dropdown loses/duplicates entries after undo. The fix mutates
    cfg.camera_paths IN PLACE so its OBJECT IDENTITY is preserved across
    undo/redo. This test holds a reference to the original array (the
    alias) and asserts: (a) it is the SAME object after undo, and (b) its
    contents reflect the restored snapshot."""
    js = _history_preamble() + _extract_history_js() + r"""
// Capture the live camera_paths array reference (== the 09 alias).
const aliasRef = cfg.camera_paths;
EditHistory.push('add-path');           // pre-gesture snapshot: camera_paths == []
cfg.camera_paths.push({id: 'p_new'});   // the gesture: mutate in place (like _camSelCreate)
EditHistory.undo();                     // restore baseline ([])
const afterUndo = {
  sameRef: cfg.camera_paths === aliasRef,
  len: cfg.camera_paths.length,
  ids: cfg.camera_paths.map(p => p.id),
};
EditHistory.redo();                     // restore [p_new]
const afterRedo = {
  sameRef: cfg.camera_paths === aliasRef,
  len: cfg.camera_paths.length,
  ids: cfg.camera_paths.map(p => p.id),
};
process.stdout.write(JSON.stringify({ afterUndo, afterRedo }));
"""
    r = _run_node(js)
    # (a) the alias survives undo -- the array object identity is preserved.
    assert r["afterUndo"]["sameRef"] is True, (
        "camera_paths array identity must be preserved across undo (the "
        "09_playback_spline `const cameraPaths` alias holds a reference)"
    )
    # (b) its contents reflect the restored baseline ([]).
    assert r["afterUndo"]["len"] == 0, "undo must restore the empty baseline"
    assert r["afterUndo"]["ids"] == []
    # redo: still the same object, contents back to [p_new].
    assert r["afterRedo"]["sameRef"] is True, (
        "camera_paths array identity must be preserved across redo too"
    )
    assert r["afterRedo"]["ids"] == ["p_new"], (
        "redo must restore the [p_new] state into the SAME array object"
    )


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_window_sceneview_history_is_published():
    """The IIFE self-publishes onto window.__sceneview.history so the
    EditorModuleRegistry's delegators can reach it."""
    js = _history_preamble() + _extract_history_js() + r"""
process.stdout.write(JSON.stringify({
  exposed: typeof window.__sceneview.history === 'object',
  hasPush: typeof window.__sceneview.history.push === 'function',
  hasUndo: typeof window.__sceneview.history.undo === 'function',
  hasRedo: typeof window.__sceneview.history.redo === 'function',
  hasClear: typeof window.__sceneview.history.clear === 'function',
}));
"""
    r = _run_node(js)
    assert r["exposed"] is True
    assert r["hasPush"] is True
    assert r["hasUndo"] is True
    assert r["hasRedo"] is True
    assert r["hasClear"] is True
