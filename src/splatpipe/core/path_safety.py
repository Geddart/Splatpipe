"""Shared path-containment helpers for security-sensitive route handlers.

Bug-audit-2026-05-19 finding #6: ``str(path).startswith(str(root))`` is
NOT a safe containment check. A sibling directory with the same textual
prefix passes the check but is OUTSIDE the intended root:

* root: ``/foo/output``
* attacker path: ``/foo/output_evil/secrets``
* ``str("/foo/output_evil/secrets").startswith(str("/foo/output"))`` -> True
* but ``output_evil`` is a SIBLING of ``output`` -- it is NOT contained.

The fix is ``Path.resolve().relative_to(parent.resolve())``: ``relative_to``
raises ``ValueError`` when its argument is NOT a sub-path of the operand,
which is the strict containment check we actually want. The helpers below
wrap that primitive so every callsite gets identical semantics, including
graceful handling of cross-drive Windows paths (different drives also raise
``ValueError`` from ``resolve().relative_to()``, which the helper maps to
"not contained").

Two API shapes:

* :func:`is_contained` -- bool predicate (use when both branches are valid).
* :func:`ensure_contained` -- raises :class:`PathContainmentError`
  (use when escape is an explicit error condition, e.g. inside an HTTP
  route's try/except).

``PathContainmentError`` is a ``ValueError`` subclass so transitional
callsites that still catch ``ValueError`` keep working unchanged.
"""

from __future__ import annotations

from pathlib import Path


class PathContainmentError(ValueError):
    """Raised when a resolved child path escapes its intended parent root.

    Subclass of ``ValueError`` so legacy callsites that already wrap
    ``Path.relative_to`` with ``except ValueError`` keep catching the
    new error without a migration step.
    """


def is_contained(child: str | Path, parent: str | Path) -> bool:
    """Return ``True`` iff resolved ``child`` is the same as, or inside,
    resolved ``parent``.

    Uses ``Path.resolve().relative_to(parent.resolve())`` -- the only
    sibling-prefix-safe containment primitive in the standard library.

    The function NEVER raises: cross-drive paths on Windows, ``..``
    traversals that escape the parent, and sibling directories that share
    a textual prefix all return ``False``.

    Args:
        child: A path that may or may not live inside ``parent``. Accepts
            ``str`` or ``Path``. The path does NOT need to exist -- the
            caller often uses this on attacker-supplied untrusted input
            that may point at a phantom file.
        parent: The intended root directory. Accepts ``str`` or ``Path``.

    Returns:
        ``True`` if ``Path(child).resolve()`` is the same as or under
        ``Path(parent).resolve()``. ``False`` for sibling-prefix matches,
        ``..`` escapes, cross-drive paths, and unrelated locations.
    """
    try:
        Path(child).resolve().relative_to(Path(parent).resolve())
    except ValueError:
        return False
    return True


def ensure_contained(child: str | Path, parent: str | Path) -> Path:
    """Return the resolved ``child`` if safely contained in ``parent``.

    The raising variant of :func:`is_contained`. Use this when escape is
    an error condition the caller wants to surface explicitly (e.g.
    inside an HTTP route that returns 403 on escape).

    Args:
        child: A path candidate (``str`` or ``Path``). Does NOT need to
            exist on disk.
        parent: The intended root (``str`` or ``Path``).

    Returns:
        ``Path(child).resolve()`` -- the resolved, sibling-prefix-safe
        absolute path, ready to use as a filesystem operand.

    Raises:
        PathContainmentError: ``child`` resolves outside ``parent`` (or
            the operands are on different drives on Windows).
    """
    resolved_child = Path(child).resolve()
    resolved_parent = Path(parent).resolve()
    try:
        resolved_child.relative_to(resolved_parent)
    except ValueError as ex:
        raise PathContainmentError(
            f"Path {resolved_child!s} escapes root {resolved_parent!s}"
        ) from ex
    return resolved_child
