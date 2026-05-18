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
