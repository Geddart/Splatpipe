"""EditorModuleRegistry contract tests (Phase 2 -- editor-arc-design #122).

The registry is a pure-JS IIFE shipped in
``viewers/spark/template_parts/04a_editor_module_registry.js_tmpl`` and
exposed at ``window.__sceneview.modules``. It is the SINGLE coordinator
over the editor modules: every later Phase (3-8) registers exactly ONE
module per stateKey and the Save dispatcher walks ``collectPatch()``.

Two test layers:

(a) STATIC: the generated viewer HTML carries the documented surface
    markers + the registry IIFE is wired into ``window.__sceneview``
    by 05_framework. Pure Python -- no browser, no Node.

(b) DYNAMIC (Node): extract the registry IIFE verbatim from the
    rendered HTML and run it under Node to exercise the actual
    state-machine behaviour: register, unregister, get, list,
    notifyCfgChange, collectPatch, markAllClean, the undo delegation,
    and the emit/on event bus. Mirrors the pattern in
    ``test_spcp_js_port.py``.

Skips cleanly if Node is unavailable (CI provides it).
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

# Markers the FIXED code adds in the 04a fragment and the 05 wiring patch.
_REGISTRY_MARKERS = (
    "const EditorModuleRegistry = (() => {",  # the IIFE declaration
    "[EditorModuleRegistry] ",                 # the _warn prefix
    "register: register,",                     # exported method
    "unregister: unregister,",
    "collectPatch: collectPatch,",
    "notifyCfgChange: notifyCfgChange,",
    "markAllClean: markAllClean,",
    "pushUndo: pushUndo,",
    "_bootMount: _bootMount,",
    # 05_framework wiring
    "modules: (typeof EditorModuleRegistry !== 'undefined')",
    "EditorModuleRegistry._bootMount();",
)


def test_registry_markers_present_in_rendered_html():
    """The registry IIFE + the 05_framework wiring patch are both
    present in the generated viewer HTML."""
    html = html_for("HarnessScene")
    for mk in _REGISTRY_MARKERS:
        assert mk in html, f"registry marker missing: {mk!r}"


def test_registry_fragment_file_exists():
    """The 04a fragment is on disk + at the expected location (the
    orchestrator loads it in lexical order between 04 and 05)."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    f = parts / "04a_editor_module_registry.js_tmpl"
    assert f.exists(), f"missing fragment: {f}"
    raw = f.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "BOM corruption"
    assert b"\r" not in raw, "CRLF corruption"
    txt = raw.decode("utf-8")
    assert "EditorModuleRegistry" in txt
    assert "_bootMount" in txt


def test_registry_documents_module_contract():
    """The contract documentation (the EditorModule shape) is present
    as a comment in the fragment -- Phases 3-8 read this comment when
    implementing their modules so it MUST stay accurate."""
    html = html_for("HarnessScene")
    # Each required field documented in the comment block.
    for required_field in ("name", "stateKey", "mount", "unmount",
                           "getDirtyState", "markClean"):
        assert required_field in html, f"contract field missing: {required_field}"


# --------------------------------------------------------------------------
# (b) DYNAMIC: run the registry IIFE under Node
# --------------------------------------------------------------------------

pytestmark_dynamic = pytest.mark.skipif(
    _NODE is None, reason="node not available (CI provides it)"
)


def _extract_registry_js() -> str:
    """Pull the EditorModuleRegistry IIFE verbatim out of the generated
    viewer HTML. The IIFE is self-contained (no external imports apart
    from console.warn which Node provides). Returns the JS source that
    declares ``const EditorModuleRegistry = (() => {...})();``."""
    html = html_for("HarnessScene")
    a = html.index("const EditorModuleRegistry = (() => {")
    # The IIFE ends with the matching `})();` at the same indent. We
    # find the unique exit token after the return-block.
    end_marker = "    _bootMount: _bootMount,\n    };\n  })();"
    end = html.index(end_marker, a) + len(end_marker)
    seg = html[a:end]
    assert "register: register," in seg
    assert "collectPatch: collectPatch," in seg
    return seg


def _run_node(script: str) -> dict:
    """Run ``script`` under Node and parse its stdout as JSON. The
    script must end with ``process.stdout.write(JSON.stringify(...))``.
    """
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "registry_test.mjs"
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


def _registry_preamble() -> str:
    """Shim: provide a global ``window`` so the registry's test-surface
    publishing won't throw under Node; provide a stub ``console.warn``
    suppressor so warn lines don't pollute stderr."""
    return (
        "globalThis.window = globalThis;\n"
        "globalThis.console = globalThis.console || { warn() {}, log() {} };\n"
    )


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_register_and_get_module_by_name():
    js = _registry_preamble() + _extract_registry_js() + r"""
const m = {
  name: 'foo',
  stateKey: 'foo_key',
  mount() {},
  unmount() {},
  getDirtyState() { return { isDirty: false }; },
  markClean() {},
};
EditorModuleRegistry.register(m);
const result = {
  list: EditorModuleRegistry.list().map(x => x.name),
  byName: EditorModuleRegistry.get('foo').name,
  missing: EditorModuleRegistry.get('bar'),
};
process.stdout.write(JSON.stringify(result));
"""
    r = _run_node(js)
    assert r["list"] == ["foo"]
    assert r["byName"] == "foo"
    assert r["missing"] is None


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_register_rejects_duplicate_names():
    js = _registry_preamble() + _extract_registry_js() + r"""
const m1 = { name: 'foo', stateKey: 'k1',
  mount(){}, unmount(){}, getDirtyState(){return{isDirty:false}}, markClean(){} };
const m2 = { name: 'foo', stateKey: 'k2',
  mount(){}, unmount(){}, getDirtyState(){return{isDirty:false}}, markClean(){} };
const r1 = EditorModuleRegistry.register(m1);
const r2 = EditorModuleRegistry.register(m2);
process.stdout.write(JSON.stringify({
  r1: r1 && r1.stateKey,
  r2: r2,
  listCount: EditorModuleRegistry.list().length,
  stillFirst: EditorModuleRegistry.get('foo').stateKey,
}));
"""
    r = _run_node(js)
    assert r["r1"] == "k1"
    assert r["r2"] is None       # duplicate rejected
    assert r["listCount"] == 1
    assert r["stillFirst"] == "k1"


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_unregister_removes_and_calls_unmount():
    js = _registry_preamble() + _extract_registry_js() + r"""
let unmountCalled = false;
const m = {
  name: 'a', stateKey: 'k',
  mount(){}, unmount(){ unmountCalled = true; },
  getDirtyState(){return{isDirty:false}}, markClean(){},
};
EditorModuleRegistry.register(m);
const beforeCount = EditorModuleRegistry.list().length;
const removed = EditorModuleRegistry.unregister('a');
const afterCount = EditorModuleRegistry.list().length;
process.stdout.write(JSON.stringify({
  beforeCount, afterCount, removed, unmountCalled,
  getNull: EditorModuleRegistry.get('a'),
  unregisterMissing: EditorModuleRegistry.unregister('nope'),
}));
"""
    r = _run_node(js)
    assert r["beforeCount"] == 1
    assert r["afterCount"] == 0
    assert r["removed"] is True
    assert r["unmountCalled"] is True
    assert r["getNull"] is None
    assert r["unregisterMissing"] is False


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_collect_patch_walks_dirty_modules():
    js = _registry_preamble() + _extract_registry_js() + r"""
const mA = {
  name: 'a', stateKey: 'camera_paths',
  mount(){}, unmount(){},
  getDirtyState() { return { isDirty: true,
    patchObject: [{ id: 'p1', name: 'A' }] }; },
  markClean(){},
};
const mB = {
  name: 'b', stateKey: 'annotations',
  mount(){}, unmount(){},
  getDirtyState() { return { isDirty: false }; },  // clean - skip
  markClean(){},
};
const mC = {
  name: 'c', stateKey: 'audio',
  mount(){}, unmount(){},
  getDirtyState() { return { isDirty: true, patchObject: [] }; },
  markClean(){},
};
EditorModuleRegistry.register(mA);
EditorModuleRegistry.register(mB);
EditorModuleRegistry.register(mC);
const r = EditorModuleRegistry.collectPatch();
process.stdout.write(JSON.stringify(r));
"""
    r = _run_node(js)
    assert "camera_paths" in r["patch"]
    assert "audio" in r["patch"]
    assert "annotations" not in r["patch"]   # clean -> skipped
    assert sorted(r["dirtyNames"]) == ["a", "c"]
    assert r["patch"]["camera_paths"] == [{"id": "p1", "name": "A"}]


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_mark_all_clean_calls_every_module():
    js = _registry_preamble() + _extract_registry_js() + r"""
const called = [];
const m1 = { name: 'a', stateKey: 'k1',
  mount(){}, unmount(){}, getDirtyState(){return{isDirty:false}},
  markClean(){ called.push('a'); } };
const m2 = { name: 'b', stateKey: 'k2',
  mount(){}, unmount(){}, getDirtyState(){return{isDirty:false}},
  markClean(){ called.push('b'); } };
EditorModuleRegistry.register(m1);
EditorModuleRegistry.register(m2);
EditorModuleRegistry.markAllClean();
process.stdout.write(JSON.stringify({ called }));
"""
    r = _run_node(js)
    assert sorted(r["called"]) == ["a", "b"]


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_notify_cfg_change_broadcasts():
    js = _registry_preamble() + _extract_registry_js() + r"""
const seen = [];
const m = {
  name: 'a', stateKey: 'foo',
  mount(){}, unmount(){},
  getDirtyState(){return{isDirty:false}}, markClean(){},
  onCfgChange(prev, next, stateKey) {
    seen.push({prev, next, stateKey});
  },
};
EditorModuleRegistry.register(m);
EditorModuleRegistry.notifyCfgChange('foo', {old: 1}, {new: 2});
EditorModuleRegistry.notifyCfgChange('bar', null, null);
process.stdout.write(JSON.stringify({ seen, count: seen.length }));
"""
    r = _run_node(js)
    assert r["count"] == 2
    assert r["seen"][0]["stateKey"] == "foo"
    assert r["seen"][0]["prev"] == {"old": 1}
    assert r["seen"][0]["next"] == {"new": 2}
    assert r["seen"][1]["stateKey"] == "bar"


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_event_bus_emit_and_unsubscribe():
    js = _registry_preamble() + _extract_registry_js() + r"""
const events = [];
const off = EditorModuleRegistry.on('boot', (a, b) => {
  events.push({a, b});
});
EditorModuleRegistry.emit('boot', 1, 'two');
off();
EditorModuleRegistry.emit('boot', 999, 'after-off');  // not captured
process.stdout.write(JSON.stringify({ events }));
"""
    r = _run_node(js)
    assert r["events"] == [{"a": 1, "b": "two"}]


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_push_undo_no_ops_when_history_absent():
    """Until 17a_edit_history publishes window.__sceneview.history, the
    registry's pushUndo/undo/redo are silent no-ops (gracefully). The
    delegation is what wires them once history is present."""
    js = _registry_preamble() + _extract_registry_js() + r"""
// No history shim -> all delegators should return falsy.
const r = {
  pushUndo: EditorModuleRegistry.pushUndo({label: 'x'}),
  undo: EditorModuleRegistry.undo(),
  redo: EditorModuleRegistry.redo(),
  canUndo: EditorModuleRegistry.canUndo(),
  canRedo: EditorModuleRegistry.canRedo(),
};
process.stdout.write(JSON.stringify(r));
"""
    r = _run_node(js)
    assert r["pushUndo"] is False
    assert r["undo"] is None
    assert r["redo"] is None
    assert r["canUndo"] is False
    assert r["canRedo"] is False


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_push_undo_delegates_to_history_when_present():
    """When window.__sceneview.history is wired (a stub shim simulating
    the 17a fragment), the registry's pushUndo/undo/redo proxy through."""
    js = _registry_preamble() + _extract_registry_js() + r"""
// Shim history -- simulates 17a fragment having published itself.
let pushed = null;
let undoCalled = false;
window.__sceneview = { history: {
  push(e) { pushed = e; return 'pushed'; },
  undo() { undoCalled = true; return 'undid'; },
  redo() { return 'redid'; },
  canUndo() { return true; },
  canRedo() { return true; },
} };
const r = {
  pushUndo: EditorModuleRegistry.pushUndo({label: 'gz-drag'}),
  pushed,
  undo: EditorModuleRegistry.undo(),
  undoCalled,
  redo: EditorModuleRegistry.redo(),
  canUndo: EditorModuleRegistry.canUndo(),
  canRedo: EditorModuleRegistry.canRedo(),
};
process.stdout.write(JSON.stringify(r));
"""
    r = _run_node(js)
    assert r["pushUndo"] == "pushed"
    assert r["pushed"] == {"label": "gz-drag"}
    assert r["undoCalled"] is True
    assert r["undo"] == "undid"
    assert r["redo"] == "redid"
    assert r["canUndo"] is True
    assert r["canRedo"] is True


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_register_tolerates_missing_optional_fields():
    """A minimal module with only the required fields registers + lists
    cleanly (no throws). Optional fields (timelineLane, overlayGroup,
    onCfgChange, onModeChange, testSurface, renderSceneSettings,
    defaultModes) are duck-checked."""
    js = _registry_preamble() + _extract_registry_js() + r"""
const minimal = {
  name: 'min', stateKey: 'k',
  mount(){}, unmount(){},
  getDirtyState(){return{isDirty:false}},
  markClean(){},
};
EditorModuleRegistry.register(minimal);
process.stdout.write(JSON.stringify({
  registered: EditorModuleRegistry.get('min').name,
  patch: EditorModuleRegistry.collectPatch(),
}));
"""
    r = _run_node(js)
    assert r["registered"] == "min"
    assert r["patch"]["dirtyNames"] == []


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_test_surface_merged_onto_window_editor():
    """A module's testSurface is merged onto window.__editor at
    register-time (the existing CameraPath* fragments already populate
    that surface; new modules join it via this hook)."""
    js = _registry_preamble() + _extract_registry_js() + r"""
window.__editor = window.__editor || { existing: true };
const m = {
  name: 'a', stateKey: 'k',
  mount(){}, unmount(){},
  getDirtyState(){return{isDirty:false}}, markClean(){},
  testSurface: { foo: 42, bar() { return 7; } },
};
EditorModuleRegistry.register(m);
process.stdout.write(JSON.stringify({
  existing: window.__editor.existing,
  foo: window.__editor.foo,
  bar: window.__editor.bar(),
}));
"""
    r = _run_node(js)
    assert r["existing"] is True   # not clobbered
    assert r["foo"] == 42
    assert r["bar"] == 7


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_collect_patch_skips_modules_with_no_state_key():
    """A module that for some reason has no stateKey (a stub/probe
    module) is registered (with a warn) but is excluded from
    collectPatch since there's no key to slot the patch under."""
    js = _registry_preamble() + _extract_registry_js() + r"""
const m = {
  name: 'no-key',
  // intentionally no stateKey
  mount(){}, unmount(){},
  getDirtyState() { return { isDirty: true, patchObject: [1,2,3] }; },
  markClean(){},
};
EditorModuleRegistry.register(m);
const r = EditorModuleRegistry.collectPatch();
process.stdout.write(JSON.stringify({
  dirtyNames: r.dirtyNames,
  patchKeys: Object.keys(r.patch),
}));
"""
    r = _run_node(js)
    assert "no-key" in r["dirtyNames"]   # the module IS marked dirty
    assert r["patchKeys"] == []          # but nothing in the patch dict
