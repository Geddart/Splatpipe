"""Sanitize viewer-config dicts before they are written to the public CDN.

The CDN-public ``viewer-config.json`` is reachable by anyone with the scene
URL. Anything written into it is forever public. This module provides a
**strict allow-list** sanitizer so a careless / hostile / future-extended
``base_config`` (e.g. a JSON file fed via ``splatpipe publish --config``)
cannot leak a per-scene secret, internal note, or local-only path through
``publish_scene``.

Two allow-lists drive the sanitizer:

  * :data:`PUBLIC_VIEWER_CONFIG_KEYS` -- the top-level keys the deployed
    viewer JS actually reads from ``viewer-config.json`` (verified against
    the Spark template + the PlayCanvas viewer). Everything outside this
    set is silently dropped.

  * :data:`PUBLIC_SAVE_BACKEND_KEYS` -- ``save_backend`` is special: the
    deployed viewer needs ``type`` + ``endpoint`` for the Save button, but
    a per-scene ``secret`` (or any other auth material) must never reach
    the public file. This is a small explicit sub-allow-list -- no fuzzy
    name regex, no implicit nesting -- so a future "options" / "headers"
    sub-block (if ever added) lands here only after a deliberate decision.

The sanitizer always returns a **deep copy**: callers can mutate the
result freely without affecting their input, and a hostile input cannot
poison the output via shared mutable state. The Bunny ``primary_asset``
pointer is in :data:`PUBLIC_VIEWER_CONFIG_KEYS` because publish_scene
overwrites it AFTER sanitisation (the locked Bunny-slug invariant).
"""

from __future__ import annotations

import copy
from typing import Any

#: The full set of top-level keys the deployed viewers actually read from
#: ``viewer-config.json``. Verified against ``viewers/spark/template.py``
#: (every ``cfg.<key>``) and ``web/static/viewer.html`` (every
#: ``viewerConfig.<key>``). Anything outside this set is silently dropped
#: by :func:`sanitize_public_viewer_config`.
#:
#: ``primary_asset`` IS in this set: publish_scene overwrites it after
#: sanitisation with the immutable ``<bkey>/scene.rad`` pointer (the
#: locked Bunny slug invariant). The viewer template's ``cfg.primary_asset``
#: lookup is what makes the build-agnostic index work.
#:
#: ``save_backend`` IS in this set, but its sub-keys are further filtered
#: by :data:`PUBLIC_SAVE_BACKEND_KEYS` so a per-scene secret cannot leak
#: even when the parent block is allow-listed.
PUBLIC_VIEWER_CONFIG_KEYS: frozenset[str] = frozenset({
    # Build pointer (set by publish_scene; included so the sanitiser is a
    # straight pass-through for it, then publish overwrites with the real
    # `<bkey>/scene.rad` value).
    "primary_asset",

    # Camera-scope (also the shared `core/config_merge.ALLOWED_PATCH_KEYS`
    # for the editor save path).
    "start_view",
    "cameras",
    "camera_paths",
    "default_path_id",
    "clips",
    "intro",
    "titles3d",
    "annotations",

    # Renderer config (read by both viewers; nested structs are passed
    # through whole on the assumption their schemas are themselves trusted
    # publish-time data, not arbitrary user JSON).
    "spark_render",
    "background",
    "postprocessing",
    "camera",          # camera constraints (pitch/zoom/bounds/ground)
    "splat_budget",
    "probe_views",
    "audio",

    # Save plumbing (publish-time only; viewer needs `type`/`endpoint` to
    # wire the Save button -- sub-keys are filtered separately below).
    "save_backend",
})

#: The (small, explicit) allow-list of sub-keys the public save_backend
#: block may carry. Anything outside this set is silently dropped --
#: notably ``secret``, ``api_key``, ``token``, ``password``, ``auth``,
#: ``BUNNY_*`` and any future auth field land here ONLY after a
#: deliberate code change. No regex, no implicit nesting: belt-and-braces.
PUBLIC_SAVE_BACKEND_KEYS: frozenset[str] = frozenset({
    "type",            # "cli" / "http" -- read by the viewer template
    "endpoint",        # POST URL for "http" -- baked into index.html
})


def sanitize_public_viewer_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a deep-copy of *cfg* containing only allow-listed public keys.

    The Bunny CDN serves ``viewer-config.json`` to anyone with the scene
    URL, so anything in it is public forever. This sanitiser is the single
    chokepoint that gates what reaches the CDN:

    - Top-level keys outside :data:`PUBLIC_VIEWER_CONFIG_KEYS` are dropped.
    - The ``save_backend`` block (when present and dict-shaped) is filtered
      to :data:`PUBLIC_SAVE_BACKEND_KEYS`; a non-dict ``save_backend`` is
      silently dropped (corrupt / hostile input).
    - The result is a deep copy: mutating it cannot bleed into *cfg* (and
      vice versa). A hostile or careless caller cannot share nested
      mutable state across the boundary.

    publish_scene calls this BEFORE writing the staged
    ``viewer-config.json`` and BEFORE reading ``save_backend.{type,endpoint}``
    for ``index.html`` -- so a stray ``save_backend.secret`` cannot leak via
    either path.
    """
    if not isinstance(cfg, dict):
        return {}

    out: dict[str, Any] = {}
    for key in cfg:
        if key not in PUBLIC_VIEWER_CONFIG_KEYS:
            continue
        value = cfg[key]
        if key == "save_backend":
            if not isinstance(value, dict):
                # Corrupt / hostile shape -- silently drop the whole block.
                continue
            sb: dict[str, Any] = {}
            for sk in value:
                if sk in PUBLIC_SAVE_BACKEND_KEYS:
                    sb[sk] = copy.deepcopy(value[sk])
            out["save_backend"] = sb
            continue
        out[key] = copy.deepcopy(value)
    return out
