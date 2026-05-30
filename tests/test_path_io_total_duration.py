"""Tests for ``PathDict.total_duration_s`` + ``effective_scrub_range`` (§3.7
addendum, 2026-05-20).

Per the editor architecture spec §3.7 the timeline scrub range is derived as::

    if path.total_duration_s is not None and path.total_duration_s > 0:
        range = [0, path.total_duration_s]
    else:
        range = [0, max(last_kf.t, 10.0)]    # 10.0 fallback gives empty-path
                                              # UX a sensible default

Backwards-compat is HARD-LOCKED: an existing path without ``total_duration_s``
behaves identically to today (range derived from ``last_kf.t``, with a 10s
floor for the empty-path UX).

These tests lock both the helper and the JSON round-trip semantics BEFORE
the editor UI lands in Phase 2, so the schema contract is fixed across the
parallel-prep work.
"""

from __future__ import annotations

import json

from splatpipe.core.path_io import (
    PathDict,
    effective_scrub_range,
    new_path,
)


# --- effective_scrub_range: total_duration_s present + valid ---------------


def test_effective_scrub_range_uses_total_duration_s_when_set():
    """A path with ``total_duration_s = 30.0`` returns ``(0, 30.0)``
    regardless of where its last keyframe sits."""
    p = new_path("t")
    p["total_duration_s"] = 30.0
    p["keyframes"] = [
        {"t": 0.0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1]},
        {"t": 5.0, "pos": [1, 0, 0], "quat": [0, 0, 0, 1]},
    ]
    assert effective_scrub_range(p) == (0.0, 30.0)


def test_effective_scrub_range_total_duration_s_overrides_last_kf():
    """The total_duration_s value WINS even when it's smaller than last_kf.t.
    The editor UI handles "off-canvas" diamonds; the helper is purely a
    declarative scrub-range setter."""
    p = new_path("t")
    p["total_duration_s"] = 8.0
    p["keyframes"] = [
        {"t": 0.0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1]},
        {"t": 20.0, "pos": [1, 0, 0], "quat": [0, 0, 0, 1]},  # past total
    ]
    assert effective_scrub_range(p) == (0.0, 8.0)


# --- effective_scrub_range: total_duration_s absent / null / zero ---------


def test_effective_scrub_range_falls_back_to_last_kf_when_total_absent():
    """No ``total_duration_s`` key → derive from last keyframe (back-compat)."""
    p = new_path("t")
    p["keyframes"] = [
        {"t": 0.0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1]},
        {"t": 25.0, "pos": [1, 0, 0], "quat": [0, 0, 0, 1]},
    ]
    assert effective_scrub_range(p) == (0.0, 25.0)


def test_effective_scrub_range_falls_back_when_total_is_none():
    """An explicit ``total_duration_s = None`` is treated identically to
    'absent' — the field is optional."""
    p = new_path("t")
    p["total_duration_s"] = None
    p["keyframes"] = [
        {"t": 0.0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1]},
        {"t": 15.0, "pos": [1, 0, 0], "quat": [0, 0, 0, 1]},
    ]
    assert effective_scrub_range(p) == (0.0, 15.0)


def test_effective_scrub_range_falls_back_when_total_is_zero():
    """``total_duration_s = 0`` (or negative) is treated as 'use default'
    per the §3.7 ``> 0`` guard — a 0-length author-declared duration
    is meaningless and falls back to the auto rule."""
    p = new_path("t")
    p["total_duration_s"] = 0.0
    p["keyframes"] = [
        {"t": 0.0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1]},
        {"t": 7.0, "pos": [1, 0, 0], "quat": [0, 0, 0, 1]},
    ]
    # 7.0 < 10.0 floor, so floor wins
    assert effective_scrub_range(p) == (0.0, 10.0)


# --- effective_scrub_range: empty / single-keyframe paths ------------------


def test_effective_scrub_range_empty_path_uses_10s_floor():
    """An empty-keyframes path with no ``total_duration_s`` returns
    ``(0, 10.0)`` — the empty-path UX default per §3.7."""
    p = new_path("t")
    assert p["keyframes"] == []
    assert effective_scrub_range(p) == (0.0, 10.0)


def test_effective_scrub_range_single_keyframe_below_floor():
    """A path with one keyframe at ``t=5`` (< 10s floor) returns
    ``(0, 10.0)`` — the 10s floor protects the empty-path-ish UX."""
    p = new_path("t")
    p["keyframes"] = [{"t": 5.0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1]}]
    assert effective_scrub_range(p) == (0.0, 10.0)


def test_effective_scrub_range_single_keyframe_above_floor():
    """A path with one keyframe at ``t=25`` (> 10s floor) returns
    ``(0, 25.0)`` — last_kf.t wins when above the floor."""
    p = new_path("t")
    p["keyframes"] = [{"t": 25.0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1]}]
    assert effective_scrub_range(p) == (0.0, 25.0)


def test_effective_scrub_range_returns_floats():
    """Return type contract: the helper always returns a ``(float, float)``
    tuple (no int leak from an int-typed total_duration_s)."""
    p = new_path("t")
    p["total_duration_s"] = 30  # int input
    lo, hi = effective_scrub_range(p)
    assert lo == 0.0
    assert isinstance(lo, float)
    assert hi == 30.0
    assert isinstance(hi, float)


# --- JSON round-trip ------------------------------------------------------


def test_total_duration_s_round_trips_through_json():
    """When set, ``total_duration_s`` round-trips through JSON unchanged."""
    p: PathDict = new_path("t")
    p["total_duration_s"] = 42.5
    p["keyframes"] = [{"t": 0.0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1]}]
    reloaded = json.loads(json.dumps(p))
    assert reloaded["total_duration_s"] == 42.5
    assert effective_scrub_range(reloaded) == (0.0, 42.5)


def test_total_duration_s_absent_round_trip_does_not_fabricate():
    """When absent, JSON round-trip does NOT synthesise a ``total_duration_s``
    key (back-compat: older configs stay shape-identical)."""
    p: PathDict = new_path("t")
    p["keyframes"] = [
        {"t": 0.0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1]},
        {"t": 12.0, "pos": [1, 0, 0], "quat": [0, 0, 0, 1]},
    ]
    blob = json.dumps(p)
    reloaded = json.loads(blob)
    assert "total_duration_s" not in reloaded
    # Auto rule still applies; 12 > 10 floor, so last_kf.t wins.
    assert effective_scrub_range(reloaded) == (0.0, 12.0)
