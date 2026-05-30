"""UX-Phase11D H1: the Save dispatcher must mark every editor module
clean on a SUCCESSFUL save.

Phase 11B finding: ``_gzSaveCli()`` (cli token emit) and ``_gzSaveHttp()``
(http POST) in ``17_editor_gizmo.js_tmpl`` both built the patch + emitted /
POSTed then returned. NEITHER called ``EditorModuleRegistry.markAllClean()``.
Each module's ``markClean()`` resets its own dirty flag; without the call
the modules stay dirty forever -> every subsequent Save re-emits the FULL
payload and the dirty surface never settles.

Fix: call ``EditorModuleRegistry.markAllClean()`` at the end of
``_gzSaveCli()`` (after the token is emitted) AND on the 200-OK path of
``_gzSaveHttp()``. NOT on the error path (a failed save is still dirty,
correctly).

Two layers:
  (a) STATIC marker -- both save paths contain the markAllClean call, and
      it is gated behind the ok-status branch in the http path (NOT on the
      reject/error path).
  (b) DYNAMIC (Node) -- exercise the registry's dirty -> clean transition
      end-to-end (markAllClean flips a registered dirty module clean).
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
# (a) STATIC: both save paths call _gzMarkAllClean(); http gates on resp.ok
# --------------------------------------------------------------------------


def test_mark_all_clean_helper_present():
    """A guarded ``_gzMarkAllClean()`` helper exists and calls the
    registry's markAllClean behind a typeof guard."""
    html = html_for("HarnessScene")
    assert "function _gzMarkAllClean()" in html
    assert "EditorModuleRegistry.markAllClean()" in html
    # Guarded so it is safe before the registry exists.
    assert (
        "typeof EditorModuleRegistry.markAllClean === 'function'" in html
    )


def test_cli_save_marks_clean():
    """``_gzSaveCli()`` calls ``_gzMarkAllClean()`` after emitting the
    token (and before the return)."""
    html = html_for("HarnessScene")
    start = html.index("function _gzSaveCli()")
    end = html.index("function _gzSaveHttp()", start)
    body = html[start:end]
    assert "_gzShowTokenCard(token);" in body
    assert "_gzMarkAllClean();" in body, (
        "_gzSaveCli must mark modules clean after emitting the token"
    )


def test_http_save_marks_clean_only_on_ok():
    """``_gzSaveHttp()`` calls ``_gzMarkAllClean()`` only on the 200-OK
    branch (``if (resp && resp.ok) _gzMarkAllClean();``) and passes the
    response through unchanged so the caller's feedback chain is intact."""
    html = html_for("HarnessScene")
    start = html.index("function _gzSaveHttp()")
    # The function body ends at the next top-level _gzSave dispatcher.
    end = html.index("function _gzSave()", start)
    body = html[start:end]
    assert "if (resp && resp.ok) _gzMarkAllClean();" in body, (
        "http save must mark clean only on the ok path"
    )
    # The response is returned (contract unchanged for the caller's chain).
    assert "return resp;" in body
    # markAllClean must NOT be on an unconditional / error path: the only
    # occurrence in this function is the ok-gated one above.
    assert body.count("_gzMarkAllClean()") == 1


# --------------------------------------------------------------------------
# (b) DYNAMIC (Node): registry dirty -> clean transition
# --------------------------------------------------------------------------


def _extract_registry_js() -> str:
    html = html_for("HarnessScene")
    a = html.index("const EditorModuleRegistry = (() => {")
    end_marker = "    _bootMount: _bootMount,\n    };\n  })();"
    end = html.index(end_marker, a) + len(end_marker)
    return html[a:end]


def _run_node(script: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "h1_test.mjs"
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


_PREAMBLE = (
    "globalThis.window = globalThis;\n"
    "globalThis.console = globalThis.console || { warn() {}, log() {} };\n"
)


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_mark_all_clean_flips_dirty_module_clean():
    """A registered module reporting isDirty:true reports clean after
    markAllClean() -- the exact dirty->clean transition the H1 fix relies
    on so a subsequent collectPatch() returns nothing."""
    js = _PREAMBLE + _extract_registry_js() + r"""
let dirty = true;
const m = {
  name: 'cam', stateKey: 'camera_paths',
  mount(){}, unmount(){},
  getDirtyState(){ return { isDirty: dirty, patchObject: [{id:'p1'}] }; },
  markClean(){ dirty = false; },
};
EditorModuleRegistry.register(m);
const before = EditorModuleRegistry.collectPatch();
EditorModuleRegistry.markAllClean();
const after = EditorModuleRegistry.collectPatch();
process.stdout.write(JSON.stringify({
  beforeDirty: before.dirtyNames,
  afterDirty: after.dirtyNames,
  beforeHasKey: Object.keys(before.patch),
  afterHasKey: Object.keys(after.patch),
}));
"""
    r = _run_node(js)
    assert r["beforeDirty"] == ["cam"]
    assert r["afterDirty"] == []          # markAllClean settled it
    assert r["beforeHasKey"] == ["camera_paths"]
    assert r["afterHasKey"] == []
