"""SH-encoding mode for the Spark build/publish pipeline.

The Spark viewer has two different decode paths for paged ``.rad`` files:

* **PackedSplats** (default): the legacy fast path. Spherical-harmonic
  coefficients are stored quantised to ``signed_norm * shN_max`` and the
  shader fetches them via integer texture reads. The header stores a
  single per-cluster ``shN_max`` value FLOORED at ``1.0`` during build,
  which on real captures (every live ``.rad`` we've measured has
  ``sh*Max == 1.0``) clips the actual SH range to ``±1`` and produces
  the well-documented "rainbow" view-dependent artifact.

* **ExtSplats** (clamp-free): an alternate decode path that fetches SH
  via dyno-graph float texture reads with no ``±shN_max`` clamp. This
  is what the live Fehmarn scene runs in. The cost is negligible at
  runtime (one extra texture per cluster) and there is no extra build
  cost — both paths share the SAME ``.rad``. The only knob is the
  per-scene ``spark_render.paged_ext_splats`` flag the viewer reads.

This enum is the typed entrypoint for that choice from the CLI
(``splatpipe build-lod --sh-encoding {auto,paged,clamped}``) and from
``publish_scene()``. Values:

* ``auto`` — default. Inherits whatever ``spark_render.paged_ext_splats``
  the base_config already carries (project ``scene_config`` or live
  slug). For new scenes with no inherited value the viewer template's
  default applies (clamped PackedSplats path).
* ``paged`` — force ``spark_render.paged_ext_splats = True``. Clamp-free
  ExtSplats path. Recommended for SH3 captures where view-dependent
  rendering matters.
* ``clamped`` — force ``spark_render.paged_ext_splats = False``.
  Traditional ±1-clamp PackedSplats path. Useful for explicitly
  reverting a scene that was previously published with paged.

The choice is also encoded in the build-lod cache key so a re-run with
a different mode does not silently serve a stale entry. Both the Rust
``build-lod`` binary AND the resulting ``.rad`` are byte-identical
across modes (the choice is a viewer-side decode-path toggle, not a
build-time data change), so changing modes does not require a real
rebuild — the cache-key namespacing is purely defensive against future
modes that DO change the build.
"""

from __future__ import annotations

from enum import Enum


class ShEncoding(str, Enum):
    """Typed choice for SH decode path in the Spark viewer.

    Subclasses ``str`` so Typer accepts it as a ``--sh-encoding`` choice
    flag and JSON-serialises the value natively.
    """

    auto = "auto"
    paged = "paged"
    clamped = "clamped"

    @property
    def cache_flag(self) -> str:
        """One-char flag for the build-lod cache key suffix.

        ``a`` (auto), ``p`` (paged), ``c`` (clamped). Combined with the
        existing ``q``/``n``/``c``/``s`` flag chars via a leading ``e``
        marker (``eo`` prefix) so the encoding char never collides with
        the existing chunked-``c`` flag.
        """
        return {"auto": "a", "paged": "p", "clamped": "c"}[self.value]

    def resolve_paged_ext_splats(self, inherited: bool | None = None) -> bool | None:
        """Resolve the ``spark_render.paged_ext_splats`` flag for this mode.

        * ``auto`` keeps the inherited value (returns it as-is, which may
          be ``None`` for a fresh scene — the viewer template's own
          default then applies).
        * ``paged`` always returns ``True``.
        * ``clamped`` always returns ``False``.
        """
        if self is ShEncoding.auto:
            return inherited
        if self is ShEncoding.paged:
            return True
        return False
