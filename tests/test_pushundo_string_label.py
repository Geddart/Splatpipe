"""UX-Phase11D H2: Annotation + Titles ``pushUndo`` must pass a BARE
string label, not an object.

Phase 11B finding: ``15c_annotation_module.js_tmpl`` and
``15g_titles_module.js_tmpl`` each had a local ``_pushUndo(label)`` wrapper
that called ``EditorModuleRegistry.pushUndo({ label: label })``. Every OTHER
module passes a bare string. ``17a_edit_history.js_tmpl``'s ``push(label)``
stores ``label || ''`` and re-emits it as a string in
``history:undo`` / ``history:redo`` + ``_broadcastCfgChange`` -- a
``{label}`` object is truthy so it was stored verbatim and stringified to
``"[object Object]"``.

Fix: both wrappers now call ``EditorModuleRegistry.pushUndo(label)``.

Static markers only -- no browser / Node needed (the bug is purely the
argument SHAPE at the call site, and the EditHistory string-handling is
already locked by ``test_edit_history.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from splatpipe.viewers.spark.template import html_for


def _fragment(name: str) -> str:
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    return (parts / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "fragment_name",
    ["15c_annotation_module.js_tmpl", "15g_titles_module.js_tmpl"],
)
def test_pushundo_wrapper_passes_bare_string(fragment_name: str):
    """Neither module wraps the label in an object; both call
    ``EditorModuleRegistry.pushUndo(label)`` with the bare string."""
    src = _fragment(fragment_name)
    assert "EditorModuleRegistry.pushUndo(label)" in src, (
        f"{fragment_name}: _pushUndo must pass the bare string label"
    )
    # The buggy object-wrapped form must be gone entirely.
    assert "EditorModuleRegistry.pushUndo({ label: label })" not in src, (
        f"{fragment_name}: still wraps the label in an object"
    )
    assert "pushUndo({label:" not in src.replace(" ", ""), (
        f"{fragment_name}: still wraps the label in an object (despaced)"
    )


def test_annotation_undo_labels_are_strings():
    """The AnnotationModule's EditHistory commit labels are reasonable
    bare-string literals (passed straight to _pushUndo)."""
    html = html_for("HarnessScene")
    for label in (
        "'ann-add'",
        "'ann-delete'",
        "'ann-set-kind'",
        "'ann-radius'",
        "'ann-t-in'",
        "'ann-t-out'",
        "'ann-fade-ms'",
    ):
        assert label in html, f"annotation undo label missing: {label}"


def test_titles_undo_labels_are_strings():
    """The TitlesModule's EditHistory commit labels are reasonable
    bare-string literals."""
    html = html_for("HarnessScene")
    for label in (
        "'title-add'",
        "'title-delete'",
        "'title-text'",
        "'title-color'",
        "'title-size'",
        "'title-t-in'",
        "'title-t-out'",
        "'title-fade-ms'",
    ):
        assert label in html, f"title undo label missing: {label}"


def test_no_object_wrapped_pushundo_anywhere():
    """Repo-wide guard: NO editor fragment wraps a pushUndo arg in a
    ``{ label: ... }`` object -- the bare-string convention is universal
    (so EditHistory always gets a string)."""
    from splatpipe.viewers.spark import template as tmpl

    parts = Path(tmpl.__file__).parent / "template_parts"
    for p in sorted(parts.iterdir()):
        if p.suffix != ".js_tmpl":
            continue
        src = p.read_text(encoding="utf-8")
        despaced = src.replace(" ", "")
        assert "EditorModuleRegistry.pushUndo({label:" not in despaced, (
            f"{p.name}: wraps a pushUndo arg in a {{label}} object"
        )
