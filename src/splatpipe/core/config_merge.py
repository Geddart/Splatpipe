"""Shared camera-scope merge core — the single source of truth.

The deployed Spark viewers are static files on Bunny CDN with no backend
(the storage key must never live in client JS). A viewer's editor therefore
only *emits* an untrusted patch; the trusted side (the ``set-start-view``
CLI relay today, and every future HTTP save adapter for the keyframe
editor) fetches the project's current ``viewer-config.json``, merges the
patch onto it, and writes it back.

This module holds the **one** pure merge those consumers share, so the CLI
relay and the HTTP save path agree byte-for-byte. It is pure: no file I/O,
no network, stdlib only. The fetch / PUT / cache-purge stay in the
consumer.

The locked, security-critical invariant (this is the "Speicher-blank"
production-failure class — getting it wrong points a live scene's viewer at
a non-existent build): the patch can **never** move the Bunny
``primary_asset`` pointer. ``merge_camera_scope`` always force-keeps
``existing``'s ``primary_asset`` and only ever applies the small, fixed
camera-scope allow-list, making that failure structurally impossible.

Extracted semantics (faithful, not a redesign): the inline merge in
``cli/set_start_view_cmd.py`` was exactly ::

    cfg = _fetch_remote_config(...)   # the I/O — stays in the consumer
    cfg["start_view"] = start_view    # <- the pure merge extracted here

i.e. an allowed key is **replaced wholesale** (``cfg[key] = patch[key]``),
never deep-merged; ``primary_asset`` was preserved because the code never
touched it; non-camera keys were preserved because the code never touched
them. ``merge_camera_scope`` generalises that single ``start_view`` write
to the full §H2 allow-list with identical per-key (whole-replace)
semantics.
"""

from __future__ import annotations

import copy
from typing import Any

# ---- constants ---------------------------------------------------------------

#: The §H2 locked allow-list: the *only* keys an untrusted patch may set on
#: a viewer-config. ``primary_asset`` is deliberately absent — it is
#: force-kept from the existing config and can never be moved by a patch.
#:
#: ``panorama_backdrop`` joined the list per spec §3.2 / §5.2 so the
#: PanoramaModule (Phase 3) can save panorama edits through the same
#: shared core. Whole-replace semantics apply (no deep merge, no sub-key
#: gate -- pure render params).
#:
#: ``schema_version`` is INTENTIONALLY excluded -- it is a server-managed
#: schema-evolution field set at publish time, never patched by an
#: untrusted editor save.
ALLOWED_PATCH_KEYS: frozenset[str] = frozenset({
    "start_view",
    "camera_paths",
    "clips",
    "cameras",
    "default_path_id",
    "intro",
    "titles3d",
    "spark_render",
    "annotations",
    "panorama_backdrop",
})

# primary_asset is structurally excluded — NEVER add it here.
assert "primary_asset" not in ALLOWED_PATCH_KEYS, (
    "primary_asset must never be in ALLOWED_PATCH_KEYS: merge_camera_scope "
    "force-keeps existing's pointer; adding it here would let a patched "
    "pointer win before the guard fires (the 'Speicher-blank' failure class)."
)


# ---- merge core --------------------------------------------------------------


def merge_camera_scope(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge an untrusted *patch* onto an *existing* viewer-config.

    Returns a **new** dict (deep-copy based); neither *existing* nor *patch*
    is mutated.

    Semantics — a faithful extraction of the inline merge that lived in
    ``cli/set_start_view_cmd.py`` (``cfg["start_view"] = start_view``),
    generalised to the full allow-list:

    - Start from a deep copy of *existing* (so every non-allow-listed key —
      and any nested data — is preserved unchanged; the patch only ever
      touches camera-scope keys).
    - For each key of *patch* that is in :data:`ALLOWED_PATCH_KEYS`, replace
      that key on the result **wholesale** (``result[key] = patch[key]``);
      it is *not* deep-merged. Keys not in the allow-list are silently
      ignored — this matches the original, which simply never looked at any
      key other than ``start_view``.
    - **Force-keep** ``existing["primary_asset"]``: the result's
      ``primary_asset`` is always *existing*'s value, applied last so a
      ``primary_asset`` in *patch* can never take effect (it is not in the
      allow-list anyway; this is belt-and-braces for the locked Bunny
      invariant). If *existing* had no ``primary_asset`` (older deploy /
      missing file), none is synthesised — the original never added one.

    The deep copies of the applied patch values mean the result never
    aliases *patch*'s nested mutable data either.
    """
    result: dict[str, Any] = copy.deepcopy(existing)

    for key, value in patch.items():
        if key in ALLOWED_PATCH_KEYS:
            result[key] = copy.deepcopy(value)

    # Force-keep the existing pointer (locked invariant). Applied last and
    # independent of the loop above so a patched primary_asset can never win.
    if "primary_asset" in existing:
        result["primary_asset"] = copy.deepcopy(existing["primary_asset"])

    return result
