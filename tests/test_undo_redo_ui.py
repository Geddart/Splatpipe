"""WF-H3 (#144): visible Undo/Redo affordance + drawer-friendly undo hotkey.

Phase 11C's workflow-trace found two related gaps:

  (a) the keyframe editor had Ctrl+Z/Y wired (17a) but NO clickable Undo/Redo
      button, so a user who never tried the hotkey could not undo at all.
  (b) the broad ``_editorHotkeyBlocked()`` guard (04_js_prologue, Phase 11F H6)
      blocks ALL hotkeys while a ``[role=dialog]`` owns focus -- but the Scene
      Settings drawer IS a ``[role=dialog]``, so Ctrl+Z was dead while editing
      in the drawer.

Fix:
  * 16_editor_timeline adds VISIBLE Undo (``↶``) + Redo (``↷``) buttons in the
    always-reachable transport row, delegating to ``EditorModuleRegistry.undo/
    redo`` and dimming/disabling per ``canUndo()``/``canRedo()`` (synced every
    frame off ``_tlSyncPlayhead`` + on every ``history:*`` event).
  * 04_js_prologue adds a NARROWER ``_editorUndoHotkeyBlocked()`` guard (blocks
    only real TEXT-ENTRY focus: INPUT text/number/etc, TEXTAREA, contenteditable
    -- NOT SELECT/range/checkbox/file/buttons, NOT [role=dialog]/[role=menu]),
    and 17a's Ctrl+Z/Y handler now uses it instead of the broad guard. The
    destructive single-key hotkeys (T/R/X/K/V/B) keep the broad guard so H6
    stays intact (K/X never fire behind the kebab menu or a dialog).

Two test layers (same pattern as test_edit_history.py):

(a) STATIC: rendered HTML carries the documented surface markers.
(b) DYNAMIC (Node): run the ``_editorUndoHotkeyBlocked()`` helper verbatim
    against a stub document to prove the text-entry-only block matrix.
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
# (a) STATIC markers
# --------------------------------------------------------------------------

_VISIBLE_BUTTON_MARKERS = (
    # The two transport buttons + their delegation + tooltips.
    "const _tlUndo = _tlBtn(",
    "const _tlRedo = _tlBtn(",
    "'Undo (Ctrl+Z)'",
    "'Redo (Ctrl+Y)'",
    "_tlBar.appendChild(_tlUndo); _tlBar.appendChild(_tlRedo);",
    "EditorModuleRegistry.undo();",
    "EditorModuleRegistry.redo();",
    # Enabled-state sync wired off the per-frame playhead sync + history events.
    "function _tlSyncUndoRedo()",
    "EditorModuleRegistry.canUndo()",
    "EditorModuleRegistry.canRedo()",
    "EditorModuleRegistry.on('history:push', _tlSyncUndoRedo);",
)

_NARROW_GUARD_MARKERS = (
    # The narrow undo-hotkey guard exists in 04...
    "function _editorUndoHotkeyBlocked()",
    "const _EDITOR_NON_TEXT_INPUT_TYPES = {",
    # ...and 17a's Ctrl+Z/Y handler routes through it (NOT the broad guard).
    "if (_editorUndoHotkeyBlocked()) return;",
    # The broad guard still exists (the destructive hotkeys use it -- H6).
    "function _editorHotkeyBlocked()",
)


def test_visible_undo_redo_buttons_present():
    """The transport row carries clickable Undo + Redo buttons delegating
    to the registry coordinator with reactive enabled state."""
    html = html_for("HarnessScene")
    for mk in _VISIBLE_BUTTON_MARKERS:
        assert mk in html, f"visible-undo-button marker missing: {mk!r}"


def test_narrow_undo_hotkey_guard_present():
    """The narrow undo-hotkey guard exists and 17a uses it; the broad H6
    guard is preserved for the destructive single-key hotkeys."""
    html = html_for("HarnessScene")
    for mk in _NARROW_GUARD_MARKERS:
        assert mk in html, f"narrow-guard marker missing: {mk!r}"


def test_17a_undo_handler_does_not_use_broad_guard():
    """The 17a Ctrl+Z/Y handler must NOT route through the broad
    _editorHotkeyBlocked() (which would re-block undo inside the Scene
    Settings [role=dialog]). It must use the narrow guard instead. Assert
    the broad-guard call appears 5x (08 WASD+H/F, 16 timeline X+Ctrl-arrows,
    17 gizmo) -- 17a's former 6th site is now the narrow guard."""
    html = html_for("HarnessScene")
    broad = html.count("if (_editorHotkeyBlocked()) return;")
    narrow = html.count("if (_editorUndoHotkeyBlocked()) return;")
    assert narrow == 1, f"expected exactly 1 narrow-guard site, found {narrow}"
    # The broad guard moved off 17a; the remaining destructive-hotkey sites
    # (08/16/17) keep it. Lower bound guards against an accidental removal.
    assert broad >= 4, (
        f"broad H6 guard sites dropped to {broad} -- the destructive hotkeys "
        f"(K/X/T/R/V/B) must still route through _editorHotkeyBlocked()"
    )


# --------------------------------------------------------------------------
# (b) DYNAMIC: the _editorUndoHotkeyBlocked() block matrix under Node
# --------------------------------------------------------------------------


def _extract_undo_guard_js() -> str:
    """Pull the _EDITOR_NON_TEXT_INPUT_TYPES table + the
    _editorUndoHotkeyBlocked() function verbatim out of the rendered HTML."""
    html = html_for("HarnessScene")
    a = html.index("const _EDITOR_NON_TEXT_INPUT_TYPES = {")
    end_marker = "function _editorUndoHotkeyBlocked()"
    end = html.index(end_marker, a)
    # Find the function's closing brace: the function body ends at the first
    # "\n  }" at the fragment's 2-space indent after the function start.
    end = html.index("\n  }", end) + len("\n  }")
    seg = html[a:end]
    assert "function _editorUndoHotkeyBlocked()" in seg
    return seg


def _run_node(script: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "undo_guard_test.mjs"
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


def _guard_preamble() -> str:
    """A mutable stub document.activeElement the test sets per-case."""
    return (
        "globalThis.document = { activeElement: null };\n"
        "function _setActive(el) { globalThis.document.activeElement = el; }\n"
        "function _input(type) {\n"
        "  return { tagName: 'INPUT', isContentEditable: false,\n"
        "    getAttribute(n) { return n === 'type' ? type : null; } };\n"
        "}\n"
        "function _el(tag, ce) {\n"
        "  return { tagName: tag, isContentEditable: !!ce,\n"
        "    getAttribute() { return null; } };\n"
        "}\n"
    )


@pytest.mark.skipif(_NODE is None, reason="node not available")
def test_undo_guard_blocks_only_text_entry():
    """The narrow guard blocks undo ONLY for real text-entry focus; it lets
    undo through for SELECT / range / checkbox / file / buttons / no-focus
    (incl. the case where focus is inside a [role=dialog] -- the guard never
    looks at roles, so a dialog with a non-text control focused allows undo)."""
    js = _guard_preamble() + _extract_undo_guard_js() + r"""
function blocked() { return _editorUndoHotkeyBlocked(); }
const out = {};
// No focus -> allow.
_setActive(null); out.none = blocked();
// Text-entry elements -> BLOCK (native text undo wins).
_setActive(_input('text'));     out.text = blocked();
_setActive(_input('number'));   out.number = blocked();
_setActive(_input('search'));   out.search = blocked();
_setActive(_input('email'));    out.email = blocked();
_setActive(_input('password')); out.password = blocked();
_setActive(_input(''));         out.inputDefault = blocked();  // default = text
_setActive(_el('TEXTAREA'));    out.textarea = blocked();
_setActive(_el('DIV', true));   out.contenteditable = blocked();
// Non-text controls -> ALLOW undo (no editable text).
_setActive(_input('range'));    out.range = blocked();
_setActive(_input('checkbox')); out.checkbox = blocked();
_setActive(_input('file'));     out.file = blocked();
_setActive(_input('button'));   out.button = blocked();
_setActive(_el('SELECT'));      out.select = blocked();
_setActive(_el('BUTTON'));      out.buttonEl = blocked();
_setActive(_el('DIV'));         out.div = blocked();
process.stdout.write(JSON.stringify(out));
"""
    r = _run_node(js)
    # Blocked (text entry):
    for k in ("text", "number", "search", "email", "password",
              "inputDefault", "textarea", "contenteditable"):
        assert r[k] is True, f"undo must be BLOCKED for {k} focus"
    # Allowed (non-text / no focus):
    for k in ("none", "range", "checkbox", "file", "button", "select",
              "buttonEl", "div"):
        assert r[k] is False, f"undo must be ALLOWED for {k} focus"
