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
def test_push_then_canundo_true():
    """Two pushes wired around a mutation make canUndo true; canRedo stays false."""
    # An initial baseline snapshot is needed for canUndo to work; a single
    # push leaves cursor=1 which fails the `cursor > 1` canUndo predicate
    # (there is no prior state to roll back to).
    js = _history_preamble() + _extract_history_js() + r"""
EditHistory.push('baseline');   // pre-gesture state
cfg.camera_paths.push({id: 'p1'});
EditHistory.push('add-path');   // pre-second-gesture state
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
    """undo() restores the cfg to the snapshot captured BEFORE the most
    recent gesture. The live cfg object is mutated in place (callers
    hold a reference)."""
    js = _history_preamble() + _extract_history_js() + r"""
const origRef = cfg;
EditHistory.push('baseline');         // snap = { camera_paths:[], annotations:[] }
cfg.camera_paths.push({id: 'p1'});    // gesture mutation
EditHistory.push('add-path');         // snap = AFTER mutation? NO -- push captures CURRENT
                                       // state which is the POST-gesture state.
                                       // Per the IIFE design: gesture handlers push BEFORE
                                       // they mutate, so the entry pushed before mutation
                                       // IS the pre-state. The test mirrors that ordering.
                                       // To test undo cleanly we follow the documented
                                       // pattern: push BEFORE the next mutation.
cfg.camera_paths.push({id: 'p2'});
// Now undo should restore the state captured at 'add-path' push:
// camera_paths = [{id:'p1'}], i.e. before the p2 mutation.
const undone = EditHistory.undo();
process.stdout.write(JSON.stringify({
  sameRef: cfg === origRef,
  camera_paths: cfg.camera_paths,
  undoneLabel: undone ? undone.label : null,
}));
"""
    r = _run_node(js)
    assert r["sameRef"] is True, "undo must MUTATE cfg in place, not swap it"
    # After undo from 2 -> 1, we restore the snapshot at index 0 = baseline.
    # camera_paths should be empty (baseline state).
    assert r["camera_paths"] == []
    assert r["undoneLabel"] == "baseline"


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_redo_walks_forward_through_history():
    """redo() walks the cursor forward through previously-undone snapshots."""
    js = _history_preamble() + _extract_history_js() + r"""
EditHistory.push('s0');
cfg.camera_paths.push({id: 'p1'});
EditHistory.push('s1');
cfg.camera_paths.push({id: 'p2'});
EditHistory.push('s2');
// length 3, cursor 3, canUndo true, canRedo false
const before = {
  length: EditHistory.length, cursor: EditHistory.cursor,
  canUndo: EditHistory.canUndo(), canRedo: EditHistory.canRedo(),
  paths: cfg.camera_paths.map(p => p.id),
};
EditHistory.undo();    // cursor=2; cfg reverted to s1 state ([p1])
const afterUndo = {
  cursor: EditHistory.cursor,
  paths: cfg.camera_paths.map(p => p.id),
  canRedo: EditHistory.canRedo(),
};
EditHistory.redo();   // cursor=3; cfg back to s2 state ([])
                       // wait -- s2 snapshot was taken AFTER both pushes...
                       // actually the snapshot at s2 was {p1,p2}. Undo to s1
                       // restores {p1}. Redo to s2 restores {p1,p2}.
const afterRedo = {
  cursor: EditHistory.cursor,
  paths: cfg.camera_paths.map(p => p.id),
  canRedo: EditHistory.canRedo(),
};
process.stdout.write(JSON.stringify({ before, afterUndo, afterRedo }));
"""
    r = _run_node(js)
    # The snapshot at s2 was captured AFTER both pushes; it contains both p1+p2.
    assert r["before"]["paths"] == ["p1", "p2"]
    assert r["afterUndo"]["paths"] == ["p1"]
    assert r["afterUndo"]["canRedo"] is True
    assert r["afterRedo"]["paths"] == ["p1", "p2"]


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_push_after_undo_truncates_redo_tail():
    """A fresh push after an undo invalidates any redo path (truncates the tail)."""
    js = _history_preamble() + _extract_history_js() + r"""
EditHistory.push('s0');
cfg.camera_paths.push({id: 'p1'});
EditHistory.push('s1');
cfg.camera_paths.push({id: 'p2'});
EditHistory.push('s2');
// length 3, cursor 3
EditHistory.undo();    // cursor 2, canRedo true
EditHistory.push('s3-branch');   // truncates the s2 tail
process.stdout.write(JSON.stringify({
  length: EditHistory.length,    // should be 3 (s0, s1, s3-branch)
  cursor: EditHistory.cursor,
  canRedo: EditHistory.canRedo(), // false -- tail was truncated
  labels: EditHistory.labels().map(e => e.label),
}));
"""
    r = _run_node(js)
    assert r["length"] == 3
    assert r["cursor"] == 3
    assert r["canRedo"] is False
    assert r["labels"] == ["s0", "s1", "s3-branch"]


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
    *current* state and is a no-op)."""
    js = _history_preamble() + _extract_history_js() + r"""
EditHistory.push('s0');                     // snap = empty
cfg.camera_paths.push({id: 'mutate-me'});
cfg.camera_paths[0].id = 'mutated';
EditHistory.push('s1');                     // snap = [{id:'mutated'}]
cfg.camera_paths[0].id = 'mutated-again';   // post-snapshot mutation
const undone = EditHistory.undo();
// After undo (cursor 2 -> 1), cfg should reflect the s0 snap (= empty).
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
    """A no-op undo on an empty (or single-entry) history returns null + leaves cfg alone."""
    js = _history_preamble() + _extract_history_js() + r"""
const r0 = EditHistory.undo();              // empty -> null
EditHistory.push('only');
const r1 = EditHistory.undo();              // 1 entry -> can't undo back
process.stdout.write(JSON.stringify({
  r0, r1, canUndo: EditHistory.canUndo(),
}));
"""
    r = _run_node(js)
    assert r["r0"] is None
    assert r["r1"] is None
    assert r["canUndo"] is False


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
// Snapshot WITHOUT 'audio' key
EditHistory.push('s0');
// Mutate: add a new top-level key not in s0
cfg.audio = [{id: 'a1'}];
EditHistory.push('s1');             // snap NOW has audio
cfg.audio.push({id: 'a2'});         // further mutation
const undone = EditHistory.undo();  // restore s0
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
EditHistory.push('baseline');           // snapshot: camera_paths == []
cfg.camera_paths.push({id: 'p_new'});   // mutate in place (like _camSelCreate)
EditHistory.push('added');              // snapshot: camera_paths == [p_new]
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
