"""Multi-camera clip sequence — validation and ordering helpers.

The scene-cuts data model (plan §C) defines three top-level arrays that sit
alongside ``camera_paths`` in the scene config:

- ``cameras`` — virtual cameras, each referencing a ``path_id`` in
  ``camera_paths``: ``{id, name, path_id, orbit_pivot?}``
- ``clips`` — NLE timeline track; cuts are implicit at clip boundaries:
  ``{id, camera_id, clip_start, duration, in}``
- ``titles3d`` — world-space overlay titles:
  ``{text, pos, quat?, billboard, size, color, t_in, t_out, fade_ms}``

This module is **pure** (no file I/O, no side effects, stdlib/typing only).
Consumers (Task 14 clip-sequence tour player, save/merge core) import the
helpers here.

``DEFAULT_INTRO`` is the fallback intro transition applied at the start of a
clip sequence when no per-scene override is present.
"""

from __future__ import annotations

from typing import Any

# ---- constants ---------------------------------------------------------------

#: Default intro transition inserted at the start of every clip sequence.
DEFAULT_INTRO: dict[str, Any] = {"type": "fade", "ms": 900}


# ---- clip helpers ------------------------------------------------------------


def ordered_clips(clips: list[dict]) -> list[dict]:
    """Return *clips* sorted ascending by ``clip_start``.

    Does **not** mutate the input list.
    """
    return sorted(clips, key=lambda c: c.get("clip_start", 0.0))


def find_clips_referencing_camera(cfg: dict, camera_id: str) -> list[dict]:
    """Return every clip in *cfg* whose ``camera_id`` matches *camera_id*.

    v2-C Phase 3 -- the in-viewer "Delete camera" kebab refuses to remove
    a camera still bound to one or more clips in the cut sequence (so the
    cut timeline never points at a vanished camera id). The JS guard
    walks ``cfg.clips`` looking for matches; this helper is the SAME walk
    -- single source of truth, byte-for-byte agreement with the JS port,
    and the CLI / save-adapter side reuses it to validate incoming
    delete-camera patches.

    Defensive about an absent / non-list ``clips`` field: the 6 live
    single-camera scenes carry NO ``cfg.clips`` at all (degenerate single-
    tour case). Returning ``[]`` for that case means "no references --
    safe to proceed past this gate" (the last-camera gate is the next
    check in the delete flow). Mirrors the
    ``Array.isArray(cfg.clips) ? cfg.clips : []`` pattern ``ClipPlayer``
    already uses at template.py ~2979 -- structurally identical so the
    two never disagree.

    Skips malformed entries (``None`` / missing ``camera_id`` / explicit
    ``None`` camera_id) rather than raising; only clips with a present,
    equal ``camera_id`` are returned. Preserves input order (NOT
    ``ordered_clips`` sorted -- the guard's alert reads "referenced by
    N clips" and doesn't care about ordering; preserving order keeps
    the helper trivially testable and matches the JS ``Array.prototype
    .filter`` semantics).

    Pure: input *cfg* is never mutated; the returned list is a new
    list of references to the existing clip dicts (not deep-copied --
    the caller never mutates them either).
    """
    raw = cfg.get("clips") if isinstance(cfg, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for clip in raw:
        if not isinstance(clip, dict):
            continue
        cid = clip.get("camera_id")
        if cid is None:
            continue
        if cid == camera_id:
            out.append(clip)
    return out


def validate_clips(cameras: list[dict], clips: list[dict]) -> None:
    """Validate *clips* against the declared *cameras*.

    Raises :class:`ValueError` (with a descriptive message) if any clip:

    - references a ``camera_id`` not present in *cameras*,
    - has ``clip_start < 0``,
    - has ``duration <= 0``, or
    - has ``in < 0``.

    Returns ``None`` on success.
    """
    camera_ids = {c["id"] for c in cameras}
    for clip in clips:
        cid = clip.get("camera_id")
        if not cid:                       # None (absent) or "" (empty)
            raise ValueError(
                f"clip {clip.get('id')!r}: required field 'camera_id' is missing"
            )
        if cid not in camera_ids:
            raise ValueError(
                f"clip {clip.get('id')!r}: unknown camera_id {cid!r}; "
                f"valid ids: {sorted(camera_ids)}"
            )
        clip_start = clip.get("clip_start", 0.0)
        if clip_start < 0:
            raise ValueError(
                f"clip {clip.get('id')!r}: clip_start must be >= 0, got {clip_start}"
            )
        duration = clip.get("duration", 0.0)
        if duration <= 0:
            raise ValueError(
                f"clip {clip.get('id')!r}: duration must be > 0, got {duration}"
            )
        in_offset = clip.get("in", 0.0)
        if in_offset < 0:
            raise ValueError(
                f"clip {clip.get('id')!r}: 'in' must be >= 0, got {in_offset}"
            )


# ---- title helpers -----------------------------------------------------------


def validate_titles(titles: list[dict]) -> None:
    """Validate a list of 3-D title overlays.

    Raises :class:`ValueError` (with a descriptive message) if any title:

    - is missing the required ``text`` or ``pos`` field, or
    - has both ``t_in`` and ``t_out`` present with ``t_in > t_out``.

    If ``t_in`` or ``t_out`` is absent the time-bound is treated as open-ended
    and no error is raised for the absent field.

    Returns ``None`` on success.
    """
    for i, title in enumerate(titles):
        label = repr(title.get("text", f"<title[{i}]>"))
        if "text" not in title:
            raise ValueError(
                f"title[{i}]: required field 'text' is missing"
            )
        if "pos" not in title:
            raise ValueError(
                f"title {label}: required field 'pos' is missing"
            )
        t_in = title.get("t_in")
        t_out = title.get("t_out")
        if t_in is not None and t_out is not None and t_in > t_out:
            raise ValueError(
                f"title {label}: t_in ({t_in}) must be <= t_out ({t_out})"
            )
