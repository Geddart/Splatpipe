"""Tests for ``core/path_safety`` -- the shared path-containment helpers.

Bug-audit-2026-05-19 finding #6: ``str(path).startswith(str(root))`` is
NOT a safe containment check -- a sibling directory with the same textual
prefix passes the check but is OUTSIDE the intended root. The classic
attack: root ``/foo/output``, attacker path ``/foo/output_evil/secrets``.
``str(p).startswith(str(root))`` returns ``True`` (prefix match!) but
``output_evil`` is a sibling, not a child.

These tests lock the **safe** semantics for the replacement helpers:

* :func:`is_contained` -- bool predicate using
  ``Path.resolve().relative_to(...)``.
* :func:`ensure_contained` -- resolves ``child`` if safely contained
  in ``parent``, raises :class:`PathContainmentError` otherwise.

The sibling-prefix attack test (:meth:`TestIsContained.\
test_returns_false_for_sibling_with_shared_prefix`) is THE centerpiece
of this module -- it is the exact attack the audit warned about, and
the reason a string ``startswith`` is the wrong tool here.
"""

from __future__ import annotations

import os

import pytest

from splatpipe.core.path_safety import (
    PathContainmentError,
    ensure_contained,
    is_contained,
)


# ---------------------------------------------------------------------------
# is_contained() -- bool predicate
# ---------------------------------------------------------------------------

class TestIsContained:
    """``is_contained`` is the boolean primitive on which the security check
    rests. Every safe path inside the parent returns ``True``; every escape
    returns ``False``.
    """

    def test_returns_true_for_child_inside_parent(self, tmp_path):
        parent = tmp_path / "output"
        parent.mkdir()
        child = parent / "scene.rad"
        child.write_bytes(b"x")
        assert is_contained(child, parent) is True

    def test_returns_true_for_nested_child(self, tmp_path):
        parent = tmp_path / "output"
        parent.mkdir()
        nested = parent / "chunks" / "0" / "0.radc"
        nested.parent.mkdir(parents=True)
        nested.write_bytes(b"x")
        assert is_contained(nested, parent) is True

    def test_returns_true_for_parent_itself(self, tmp_path):
        """A path identical to the parent is contained (root == root)."""
        parent = tmp_path / "output"
        parent.mkdir()
        assert is_contained(parent, parent) is True

    def test_returns_false_for_sibling_with_shared_prefix(self, tmp_path):
        """THE attack: ``/foo/output_evil`` must NOT count as inside ``/foo/output``.

        This is what ``str(p).startswith(str(root))`` got WRONG -- a textual
        prefix match passes the check but a sibling directory is not the
        same as a child.
        """
        parent = tmp_path / "output"
        parent.mkdir()
        evil = tmp_path / "output_evil"
        evil.mkdir()
        secrets = evil / "secrets.txt"
        secrets.write_text("very secret")

        # The string-prefix attack vector -- both should be False.
        assert is_contained(evil, parent) is False
        assert is_contained(secrets, parent) is False

    def test_returns_false_for_traversal_dotdot(self, tmp_path):
        """A ``..`` traversal after resolution lands outside the parent."""
        parent = tmp_path / "output"
        parent.mkdir()
        # ``parent / ".." / "etc"`` resolves to ``tmp_path / "etc"`` which is
        # NOT inside ``parent``. Use a path that exists (or not -- .resolve()
        # works either way on modern Python).
        escape = parent / ".." / "etc" / "passwd"
        assert is_contained(escape, parent) is False

    def test_returns_false_for_unrelated_path(self, tmp_path):
        """A completely unrelated path is obviously not contained."""
        parent = tmp_path / "output"
        parent.mkdir()
        other = tmp_path / "unrelated"
        other.mkdir()
        assert is_contained(other, parent) is False

    def test_resolves_relative_paths(self, tmp_path, monkeypatch):
        """A relative ``child`` is resolved against CWD; behaviour is
        consistent with how the production callsites use it."""
        parent = tmp_path / "output"
        parent.mkdir()
        nested = parent / "scene.rad"
        nested.write_bytes(b"x")

        # CD into tmp_path; pass relative path "output/scene.rad".
        monkeypatch.chdir(tmp_path)
        assert is_contained("output/scene.rad", parent) is True
        assert is_contained("../somewhere_else", parent) is False

    def test_handles_nonexistent_paths(self, tmp_path):
        """``Path.resolve()`` works for paths that don't exist on disk.

        The route uses this defensively against an attacker-supplied path
        component that may not exist; the helper must not require the path
        to be present.
        """
        parent = tmp_path / "output"
        parent.mkdir()
        # ``ghost.bin`` doesn't exist; ``output_evil`` doesn't either.
        nonexistent_inside = parent / "ghost.bin"
        nonexistent_sibling = tmp_path / "output_evil" / "ghost.bin"

        assert is_contained(nonexistent_inside, parent) is True
        assert is_contained(nonexistent_sibling, parent) is False

    def test_str_paths_accepted(self, tmp_path):
        """The helper accepts ``str`` operands as well as ``Path`` for
        flexibility at the call site (FastAPI route params are ``str``)."""
        parent = tmp_path / "output"
        parent.mkdir()
        child = parent / "scene.rad"
        child.write_bytes(b"x")
        assert is_contained(str(child), str(parent)) is True

    def test_handles_cross_drive_on_windows_gracefully(self, tmp_path):
        """If the operands are on different drives (Windows) the helper
        must NOT crash with a ValueError -- it must return ``False``."""
        if os.name != "nt":
            pytest.skip("Windows-only cross-drive case")
        # Hard-coded cross-drive: a path that almost certainly resolves to
        # a different drive root than tmp_path. ``tmp_path`` is typically
        # ``C:\Users\<user>\AppData\Local\Temp\pytest-of-<user>\...`` so
        # ``D:\\`` (or any other letter not equal to tmp_path's drive) is
        # cross-drive. Pick the FIRST letter that does NOT match.
        drives = ["C:", "D:", "E:", "F:", "Z:"]
        tmp_drive = str(tmp_path)[:2].upper()
        cross = next((d for d in drives if d != tmp_drive), "Z:")
        # We don't need the path to EXIST -- only for resolve() to return a
        # different-drive absolute path -- so a synthetic ``Z:\foo`` is fine.
        assert is_contained(f"{cross}\\foo", tmp_path) is False


# ---------------------------------------------------------------------------
# ensure_contained() -- raising variant
# ---------------------------------------------------------------------------

class TestEnsureContained:
    """``ensure_contained`` is the raising variant used where the call site
    wants an explicit error (e.g. inside try/except in an HTTP route).
    """

    def test_returns_resolved_child_when_safe(self, tmp_path):
        parent = tmp_path / "output"
        parent.mkdir()
        child = parent / "scene.rad"
        child.write_bytes(b"x")
        out = ensure_contained(child, parent)
        # Resolved Path (so callers can use it directly).
        assert out == child.resolve()

    def test_raises_for_escape(self, tmp_path):
        parent = tmp_path / "output"
        parent.mkdir()
        outside = tmp_path / "elsewhere" / "secrets"
        with pytest.raises(PathContainmentError):
            ensure_contained(outside, parent)

    def test_raises_for_sibling_attack(self, tmp_path):
        """The exact sibling-prefix attack ``output_evil`` vs ``output``."""
        parent = tmp_path / "output"
        parent.mkdir()
        evil = tmp_path / "output_evil" / "secrets.txt"
        with pytest.raises(PathContainmentError):
            ensure_contained(evil, parent)

    def test_raises_for_dotdot_traversal(self, tmp_path):
        parent = tmp_path / "output"
        parent.mkdir()
        escape = parent / ".." / "etc" / "passwd"
        with pytest.raises(PathContainmentError):
            ensure_contained(escape, parent)

    def test_error_message_includes_paths(self, tmp_path):
        """The error message must include enough context to be debuggable."""
        parent = tmp_path / "output"
        parent.mkdir()
        outside = tmp_path / "elsewhere"
        with pytest.raises(PathContainmentError) as ex:
            ensure_contained(outside, parent)
        # No strict format -- just a sanity check that "outside" or its
        # name appears somewhere in the error.
        assert "elsewhere" in str(ex.value) or "outside" in str(ex.value).lower()

    def test_returns_resolved_parent_itself(self, tmp_path):
        """``ensure_contained(parent, parent)`` returns the resolved parent
        (root == root is a legal containment)."""
        parent = tmp_path / "output"
        parent.mkdir()
        out = ensure_contained(parent, parent)
        assert out == parent.resolve()


# ---------------------------------------------------------------------------
# PathContainmentError -- public API surface
# ---------------------------------------------------------------------------

class TestPathContainmentError:
    """``PathContainmentError`` is a ``ValueError`` subclass so existing
    ``except ValueError:`` blocks at older callsites still catch it during
    a transitional migration."""

    def test_is_value_error(self):
        assert issubclass(PathContainmentError, ValueError)
