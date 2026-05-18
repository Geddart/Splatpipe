"""SPCP1 camera-path token codec — the CLI/viewer wire contract.

The in-viewer editor's Save action emits an ``SPCP1:`` token that the author
pastes to ``splatpipe set-camera-path <token>``.  This module implements the
encode/decode side of that contract.

Wire format (all ASCII)::

    SPCP1:<slug>:<b64url-nopad>

where ``<b64url-nopad>`` is URL-safe base-64 (RFC 4648 §5) with trailing
``=`` stripped, encoding a compact JSON payload::

    {"v":1,"scope":"camera_paths","camera_paths":[...],...}

The compact ``json.dumps(separators=(",",":"))`` form is mandatory — the JS
port (Task 18) must produce byte-identical base-64.  Do **not** pretty-print.

The decoder re-pads via ``"=" * (-len(b) % 4)`` and gates on ``v == 1`` and
``scope == "camera_paths"`` before returning.  No further payload validation
is performed here; that belongs to the consumers (Task 7, Task 18).

**Slug invariant:** the slug must not contain ``:``.  Bunny slugs are
kebab-case and satisfy this.  The JS port uses ``split(':', 2)`` whose
semantics differ from Python's ``maxsplit`` — a colon in the slug would cause
silent mis-decode cross-language.  :func:`encode_spcp` enforces this at
encode time.
"""

from __future__ import annotations

import base64
import json

# ---- public exception -------------------------------------------------------

_PREFIX = "SPCP1:"


class SpcpError(ValueError):
    """Raised when a token cannot be decoded or fails a version/scope gate."""


# ---- codec ------------------------------------------------------------------


def encode_spcp(slug: str, payload: dict) -> str:
    """Encode *payload* as an ``SPCP1:`` token for scene *slug*.

    *slug* must not contain ``':'``.  Bunny slugs are kebab-case and satisfy
    this invariant.  The JS port (Task 18) relies on it — a colon in the slug
    would cause silent mis-decode cross-language.

    *payload* must already carry ``"v": 1`` and ``"scope": "camera_paths"``
    at the top level — no injection is performed here.

    Returns a plain ASCII string safe to embed in a URL query parameter or
    copy-paste on the command line.

    Raises :class:`SpcpError` if *slug* contains ``':'``.
    """
    if ":" in slug:
        raise SpcpError(f"slug must not contain ':' (got {slug!r})")
    raw = json.dumps(payload, separators=(",", ":")).encode()
    b = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{_PREFIX}{slug}:{b}"


def decode_spcp(token: str) -> tuple[str, dict]:
    """Decode an ``SPCP1:`` token and return ``(slug, payload)``.

    Raises :class:`SpcpError` if:

    - the token does not start with ``SPCP1:``,
    - the base-64 segment is corrupt,
    - ``payload["v"] != 1``, or
    - ``payload["scope"] != "camera_paths"``.
    """
    token = token.strip()
    if not token.startswith(_PREFIX):
        raise SpcpError("not an SPCP1 token")
    try:
        _, slug, b = token.split(":", 2)
    except ValueError as e:
        raise SpcpError(f"malformed token: {e}")
    b += "=" * (-len(b) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(b))
    except Exception as e:
        raise SpcpError(f"corrupt payload: {e}")
    if payload.get("v") != 1:
        raise SpcpError(f"unsupported version {payload.get('v')!r}")
    if payload.get("scope") != "camera_paths":
        raise SpcpError(f"unexpected scope {payload.get('scope')!r}")
    return slug, payload
