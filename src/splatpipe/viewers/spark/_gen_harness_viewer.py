"""Generate + serve the Spark viewer-under-test for the Playwright harness.

Companion to ``tests/manual/keyframe-editor.html`` (the shared in-viewer
verification harness for the camera-keyframe-editor plan, Tasks 0 and 6-14).

Same "locally-served generated index.html + browser automation pass" pattern
the repo already uses for viewer verification (cf. ``splatpipe serve`` and the
other ``tests/manual/*.html`` comparison pages) — just scripted so the
harness is reproducible.

  # regenerate the viewer-under-test into tests/manual/_viewer/
  python -m splatpipe.viewers.spark._gen_harness_viewer

  # …and serve tests/manual/ with HTTP Range support (Spark needs Range)
  python -m splatpipe.viewers.spark._gen_harness_viewer --serve 8777
  #   -> http://localhost:8777/keyframe-editor.html

The Task-0 framework (``window.__sceneview``) is built during the viewer
module's synchronous init, BEFORE the async ``scene.rad`` load — so the
harness needs no real ``.rad`` and a 404 on it is expected/irrelevant.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .template import html_for

# tests/manual/ relative to the repo root (…/src/splatpipe/viewers/spark/ → up 4).
_MANUAL_DIR = Path(__file__).resolve().parents[4] / "tests" / "manual"
_VIEWER_DIR = _MANUAL_DIR / "_viewer"
# Task-10 variant: same generated viewer, but its viewer-config.json carries a
# 2-keyframe camera path with `default_path_id` set so the path PLAYER
# auto-starts on init. The shared harness drives this iframe to verify the
# tab-background pause (visibilitychange rebase of the path-player clock).
# Separate dir so Task-0's `_viewer/` (its 15 framework checks) is byte-
# identical and unaffected.
_VIEWER_PATH_DIR = _MANUAL_DIR / "_viewer_path"

# ── Task-11 variants: per-keyframe spline interpolation ──────────────────
# Three more "same generated viewer, only the camera-path config differs"
# dirs. Each auto-starts (default_path_id) a 3-keyframe path whose MIDDLE
# keyframe is pulled OFF the A→C straight line so a curved spline visibly
# bulges through the mid segment. The shared harness drives the REAL
# generated path-player (virtual clock → reads `_spDebug.camera.position`)
# and asserts:
#   • _viewer_lin   (mid `interp:"linear"`)  → mid-segment samples COLINEAR
#   • _viewer_nolin (mid interp ABSENT)      → SAME samples NOT colinear
#                                              (curved == today's behavior;
#                                               proves per-key override +
#                                               absent==unchanged)
#   • _viewer_step  (mid `interp:"stepped"`) → sample just before the next
#                                              keyframe t HOLDS the middle
#                                              keyframe's value (a step)
# Separate dirs so Task-0's `_viewer/` (15 checks) + Task-10's
# `_viewer_path/` stay byte-identical and unaffected.
_VIEWER_LIN_DIR = _MANUAL_DIR / "_viewer_lin"
_VIEWER_NOLIN_DIR = _MANUAL_DIR / "_viewer_nolin"
_VIEWER_STEP_DIR = _MANUAL_DIR / "_viewer_step"

# ── Task-13 variants: cinematic loading-blur + intro fade ────────────────
# Two more "same generated viewer, only the camera-path/intro config differs"
# dirs. Both carry an auto-start path (default_path_id) so the harness can
# assert the tour fires AFTER the intro fade (or immediately for type:none).
#   • _viewer_intro     (intro {type:"fade", ms:<short>}) → on the REAL
#       ready signal (#loading gets `.hidden`) #intro-fade fades opacity
#       1→0 over intro.ms then becomes non-blocking (pointer-events:none
#       + display:none) and the tour auto-starts.
#   • _viewer_intronone (intro {type:"none"})            → #intro-fade is
#       NEVER shown; the tour auto-starts immediately on ready.
# The fade-out duration is kept SHORT (the harness wants a fast, bounded
# observation, not a 900 ms wait) — the algorithm is identical regardless
# of intro.ms; only the timing constant differs.
# Separate dirs so Task-0's `_viewer/` (its 15 framework checks) + the
# Task-10/11 path dirs stay byte-identical and unaffected.
_VIEWER_INTRO_DIR = _MANUAL_DIR / "_viewer_intro"
_VIEWER_INTRONONE_DIR = _MANUAL_DIR / "_viewer_intronone"

# Short fade so the Playwright observation window is bounded. The intro
# algorithm (fade-then-start, fail-safe clear) is independent of this value.
_T13_INTRO_MS = 250

# --- Task-14 variants: multi-camera Camera-Cuts tour + next-cut prewarm -
# Two more "same generated viewer, only the scene config differs" dirs:
#   * _viewer_clips  -- TWO cameras (each its own 2-keyframe straight path,
#       at clearly-separated world positions) + TWO clips. The shared
#       harness drives the REAL generated ClipPlayer (virtual clock ->
#       reads `_spDebug.camera.position` + `window.__clip`) and asserts:
#       clip A plays its camera's path, HARD-CUTS to camera B's path at
#       the clip boundary (instant pose discontinuity, no tween), the tour
#       completes, and the next-cut prewarm SCHEDULING + guard lifecycle
#       are observable (override parked at the next clip's start pose on
#       the ~400 ms cadence within PREFETCH_LEAD_S of the cut; released
#       immediately after). `intro:{type:"none"}` is the SAME deliberate
#       TEST ISOLATION as the Task-10/11 fixtures (the Task-13 fade-out is
#       separately tested; the clip-sequence check measures ClipPlayer
#       mechanics, not the intro gate).
#   * _viewer_noclips -- `default_path_id` set, NO cameras/clips: proves
#       the generalised _introStartTour falls back to the EXACT pre-Task-14
#       single-tour behaviour (the hard-required no-clips regression).
# `?tier=phone` is appended to the _viewer_clips iframe URL in the harness
# (the scoped Task-14 phone test hook) to exercise the mobile prewarm
# mitigations without a real device.
# Separate dirs so the Task-0/10/11/13 fixture dirs stay byte-identical.
_VIEWER_CLIPS_DIR = _MANUAL_DIR / "_viewer_clips"
_VIEWER_NOCLIPS_DIR = _MANUAL_DIR / "_viewer_noclips"

# --- Task-15 variant: end-user transport (interrupt/resume/idle-orbit) --
# A 2-camera/2-clip Camera-Cuts scene like _viewer_clips, but each camera
# carries a DISTINCT, clearly non-origin `orbit_pivot` so the per-shot
# idle auto-orbit's pivot anchoring is observable (the orbit must circle
# the AUTHORED pivot, NOT the world origin -- a derived-number trap the
# spec explicitly calls out). The harness drives the REAL generated
# transport under the SAME controllable virtual clock the Task-10/11/14
# checks proved out + the TEST-ONLY `window.__transport` surface:
#   * synthesise an interrupt mid-tour -> the tour stops,
#     controls.enabled === true, #user-play becomes visible;
#   * click #user-play (via __transport.resume()) -> the tour resumes
#     from the NEAREST CUT <= the playhead captured at interrupt (assert
#     the resumed clip idx);
#   * force the per-shot idle clock past a SHORT IDLE_MS (?idleMs=300 +
#     __transport.idleNow()) -> the slow orbit starts and the camera
#     circles camera A's authored orbit_pivot (distance to the pivot ~=
#     const while distance to origin VARIES -- proves it is the pivot,
#     not origin); any input cancels it.
# `intro:{type:"none"}` is the SAME deliberate TEST ISOLATION as the
# Task-10/11/14 fixtures. Separate dir so all prior fixture dirs stay
# byte-identical.
_VIEWER_TRANSPORT_DIR = _MANUAL_DIR / "_viewer_transport"

# --- Task-16 variant: author editor trajectory/frustums/speed-dots -----
# Same generated viewer, driven with ``?author=1`` (=> ModeManager
# resolves author mode -> the Task-16 trajectory overlay + window.__editor
# build). The scene config carries a 3-keyframe camera path with TWO
# segments of deliberately different speed so the inverse-speed dot
# relationship is unambiguous in the scene-less harness:
#   * segment 0 (kf0 t=0 -> kf1 t=100): a LONG-DURATION, short-distance
#     leg = SLOW. A fixed-time-step dot pass therefore drops MANY dots
#     here (it spans ~91% of the path duration).
#   * segment 1 (kf1 t=100 -> kf2 t=110): a SHORT-DURATION, long-distance
#     leg = FAST. Same fixed time step => FEW dots (it spans ~9% of the
#     duration) even though it covers more ground.
# => dots(slow seg) >> dots(fast seg) for the SAME dt: the spec's
# "spacing scales inversely with segment speed" (dense=slow, sparse=fast),
# asserted as a RATIO DIRECTION (slow > fast), never a magic number.
# Each keyframe carries a DISTINCT quat (identity / a +Y yaw / a +X
# pitch) so the harness can assert each frustum is oriented by ITS OWN
# keyframe quat (not a shared/global orientation). `default_path_id`
# selects it so selEl.value (the active path the overlay tracks) is
# deterministic without a click. No clips/cameras: author mode is NOT
# the multi-camera end-user tour -- the overlay tracks the single
# authored path the editor is editing.
_VIEWER_AUTHOR_DIR = _MANUAL_DIR / "_viewer_author"

# Distinct keyframe quats (xyzw). kf0 = identity (looks down -Z). kf1 =
# +90 deg yaw about world +Y. kf2 = +90 deg pitch about world +X. All
# unit quaternions; clearly pairwise-different so the per-keyframe
# frustum-orientation assertion cannot pass on a shared orientation.
_T16_Q_IDENT = [0.0, 0.0, 0.0, 1.0]
_T16_Q_YAW90 = [0.0, 0.7071067811865476, 0.0, 0.7071067811865476]
_T16_Q_PITCH90 = [0.7071067811865476, 0.0, 0.0, 0.7071067811865476]


# --- Task-17 variant: author editor BOTTOM TIMELINE -------------------
# Same generated viewer, driven with ``?author=1`` (=> ModeManager
# resolves author mode -> the Task-16 overlay AND the Task-17 bottom
# timeline strip + the Object.assign-extended window.__editor build).
# The scene config carries a FOUR-keyframe single camera path with
# DELIBERATELY DISTINCT segment durations so the timeline's diamond
# drag / box-select-edge scale / wheel zoom / X-delete are all
# exercisable and unambiguous in the scene-less harness:
#   * kf0 t=0   -> kf1 t=2    : SHORT leg
#   * kf1 t=2   -> kf2 t=20   : LONG leg (a clearly different span)
#   * kf2 t=20  -> kf3 t=24   : SHORT leg
# 4 keyframes lets a delete still leave a valid (>= 2) spline and lets
# a box-select pick a contiguous 2-of-4 sub-span whose proportional
# edge-scale ratio is unambiguous. ``default_path_id`` selects it so
# selEl.value (the active path the timeline edits) is deterministic
# without a click. NO clips/cameras: author mode is the single-path
# editor, not the multi-camera end-user tour. ``intro:{type:"none"}``
# is the SAME deliberate TEST ISOLATION as the Task-10/11/14/16
# fixtures (the timeline mechanics are orthogonal to the intro fade).
# A 600 s would be overkill; the short total duration (24 s) keeps the
# auto-tour playhead inside the path for the whole bounded observation
# AND makes the playhead-vs-auto-tour robustness assertion fast.
_VIEWER_T17_DIR = _MANUAL_DIR / "_viewer_t17"

# Distinct per-keyframe quats (xyzw) -- reuse the Task-16 set so a
# diamond/scale edit that (wrongly) perturbed pos/quat instead of ONLY
# t would be caught (the harness asserts pos/quat are byte-unchanged
# across a pure temporal edit).
_T17_Q0 = [0.0, 0.0, 0.0, 1.0]
_T17_Q1 = [0.0, 0.7071067811865476, 0.0, 0.7071067811865476]
_T17_Q2 = [0.7071067811865476, 0.0, 0.0, 0.7071067811865476]
_T17_Q3 = [0.0, 0.0, 0.7071067811865476, 0.7071067811865476]


def _t17_timeline_config() -> dict:
    """4-keyframe single path with distinct segment durations (short /
    long / short) -- the Task-17 bottom-timeline fixture. ``?author=1``
    on the iframe builds the Task-16 overlay + the Task-17 timeline +
    the extended window.__editor surface."""
    return {
        "annotations": [],
        "default_path_id": "tlPath",
        "intro": {"type": "none"},
        "camera_paths": [
            {
                "id": "tlPath",
                "name": "Task-17 timeline path",
                "loop": False,
                "smoothness": 1.0,
                "play_speed": 1.0,
                "keyframes": [
                    {"t": 0.0, "pos": [0.0, 0.0, 0.0],
                     "quat": list(_T17_Q0), "fov": 60.0},
                    {"t": 2.0, "pos": [3.0, 0.0, 0.0],
                     "quat": list(_T17_Q1), "fov": 60.0},
                    {"t": 20.0, "pos": [3.0, 0.0, -40.0],
                     "quat": list(_T17_Q2), "fov": 55.0},
                    {"t": 24.0, "pos": [10.0, 5.0, -40.0],
                     "quat": list(_T17_Q3), "fov": 50.0},
                ],
            }
        ],
    }


# --- Task-18 variant: author select-key gizmo + interp popover + ------
# Record(K) + Save/Emit SPCP1. Same generated viewer, driven with
# ``?author=1`` (=> ModeManager resolves author mode -> the Task-16
# overlay + Task-17 timeline + the Task-18 ``_gzInit`` gizmo block + the
# Object.defineProperties-EXTENDED window.__editor build). ALL of this
# is DOM + THREE geometry + the SPCP codec -- NO real .rad needed,
# fully scene-less-verifiable (no honest deferral): the frusta the
# gizmo picks are the Task-16 _trajFrusta THREE.LineSegments (built off
# sampleAt, no splats); TransformControls is a pure THREE addon; the
# interp popover is DOM; Record reads the live camera + the real-
# elapsed _trajPlayhead; Save is the in-memory payload -> the JS
# encode_spcp port (a string).
# The scene config carries a THREE-keyframe single camera path with
# DISTINCT per-keyframe quats (identity / +Y yaw 90 / +X pitch 90) so:
#   * each frustum is at a distinct, well-separated world position
#     (so a raycast pick selects an UNAMBIGUOUS keyframe), and
#   * a gizmo rotate-drag write-back to kf.quat is detectable against
#     the keyframe's own distinct base quat.
# ``default_path_id`` selects it so selEl.value (the active path the
# gizmo edits) is deterministic without a click. NO clips/cameras:
# author mode is the single-path editor. ``intro:{type:"none"}`` is
# the SAME deliberate TEST ISOLATION as the Task-10/11/14/16/17
# fixtures. The path is SHORT (24 s) so the auto-tour playhead stays
# inside it for the whole bounded observation AND the Record-uses-
# real-elapsed-t assertion is fast + deterministic.
_VIEWER_T18_DIR = _MANUAL_DIR / "_viewer_t18"
# A SECOND Task-18 dir whose generated HTML bakes
# ``save_mode="http"`` + a ``save_endpoint`` (via the html_for
# kwargs Task-8 added -- CONSUMED here, not re-implemented). Same
# scene config as _viewer_t18; only SAVE_MODE/SAVE_ENDPOINT differ.
# The harness wraps this iframe's ``fetch`` and asserts the opt-in
# http Save POSTs the camera-scope patch to SAVE_ENDPOINT with the
# Bearer secret from the URL #author=<secret> fragment and NO
# primary_asset -- scene-independently, NO real server.
_VIEWER_T18_HTTP_DIR = _MANUAL_DIR / "_viewer_t18_http"
_T18_HTTP_ENDPOINT = "https://save.example.test/api/save-camera"

_T18_Q0 = [0.0, 0.0, 0.0, 1.0]
_T18_Q1 = [0.0, 0.7071067811865476, 0.0, 0.7071067811865476]
_T18_Q2 = [0.7071067811865476, 0.0, 0.0, 0.7071067811865476]


def _t18_gizmo_config() -> dict:
    """3-keyframe single path with distinct per-keyframe quats +
    well-separated positions -- the Task-18 gizmo/interp/record/save
    fixture. ``?author=1`` builds the Task-16 overlay + Task-17
    timeline + the Task-18 gizmo block + the extended
    window.__editor surface. ``spark_render``/``start_view`` are
    present so the Save payload exercises the full Contract-C
    allow-list (and the harness can assert NO primary_asset)."""
    return {
        "annotations": [],
        "default_path_id": "gzPath",
        "intro": {"type": "none"},
        "start_view": {
            "pos": [0.0, 0.0, 8.0],
            "quat": [0.0, 0.0, 0.0, 1.0],
            "target": [0.0, 0.0, 0.0],
            "fov": 60.0,
        },
        "spark_render": {"clip_xy": 1.4},
        "camera_paths": [
            {
                "id": "gzPath",
                "name": "Task-18 gizmo path",
                "loop": False,
                "smoothness": 1.0,
                "play_speed": 1.0,
                "keyframes": [
                    {"t": 0.0, "pos": [0.0, 0.0, 0.0],
                     "quat": list(_T18_Q0), "fov": 60.0},
                    {"t": 12.0, "pos": [20.0, 0.0, 0.0],
                     "quat": list(_T18_Q1), "fov": 60.0},
                    {"t": 24.0, "pos": [20.0, 0.0, -40.0],
                     "quat": list(_T18_Q2), "fov": 55.0},
                ],
            }
        ],
    }


def _t16_author_config() -> dict:
    """3-keyframe single path; segment 0 SLOW (long-duration), segment 1
    FAST (short-duration); distinct per-keyframe quats. ``?author=1`` on
    the iframe makes the viewer build the Task-16 trajectory overlay."""
    return {
        "annotations": [],
        "default_path_id": "authorPath",
        "intro": {"type": "none"},
        "camera_paths": [
            {
                "id": "authorPath",
                "name": "Author editor path",
                "loop": False,
                "smoothness": 1.0,
                "play_speed": 1.0,
                "keyframes": [
                    # kf0 -> kf1: t spans 0..100 (SLOW) over a short hop.
                    {"t": 0.0, "pos": [0.0, 0.0, 0.0],
                     "quat": list(_T16_Q_IDENT), "fov": 60.0},
                    {"t": 100.0, "pos": [4.0, 0.0, 0.0],
                     "quat": list(_T16_Q_YAW90), "fov": 60.0},
                    # kf1 -> kf2: t spans 100..110 (FAST) over a long hop.
                    {"t": 110.0, "pos": [4.0, 0.0, -80.0],
                     "quat": list(_T16_Q_PITCH90), "fov": 50.0},
                ],
            }
        ],
    }


# Camera A's authored orbit pivot -- deliberately FAR from both the world
# origin AND camera B's path (x=500) so "orbits the authored pivot, not
# origin" is unambiguous in the scene-less harness.
_T15_CAM_A_PIVOT = [100.0, 0.0, 0.0]
_T15_CAM_B_PIVOT = [500.0, 30.0, 0.0]


def _t15_transport_config() -> dict:
    """2 cameras (each with a distinct authored ``orbit_pivot``) + 2
    clips -- the Task-15 interrupt/resume/idle-orbit fixture. Same shape
    as ``_t14_clips_config`` plus the per-camera ``orbit_pivot`` the idle
    auto-orbit anchors to."""
    return {
        "annotations": [],
        "intro": {"type": "none"},
        "cameras": [
            {"id": "camA", "name": "Camera A", "path_id": "pathA",
             "orbit_pivot": list(_T15_CAM_A_PIVOT)},
            {"id": "camB", "name": "Camera B", "path_id": "pathB",
             "orbit_pivot": list(_T15_CAM_B_PIVOT)},
        ],
        "clips": [
            {"id": "clipA", "camera_id": "camA",
             "clip_start": 0.0, "duration": _T14_CLIP_A_DUR, "in": 0.0},
            {"id": "clipB", "camera_id": "camB",
             "clip_start": _T14_CLIP_A_DUR,
             "duration": _T14_CLIP_B_DUR, "in": 0.0},
        ],
        "camera_paths": [
            {
                "id": "pathA", "name": "Path A", "loop": False,
                "smoothness": 1.0, "play_speed": 1.0,
                "keyframes": [
                    {"t": 0.0, "pos": list(_T14_CAM_A_P0),
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                    {"t": 600.0, "pos": list(_T14_CAM_A_P1),
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                ],
            },
            {
                "id": "pathB", "name": "Path B", "loop": False,
                "smoothness": 1.0, "play_speed": 1.0,
                "keyframes": [
                    {"t": 0.0, "pos": list(_T14_CAM_B_P0),
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                    {"t": 600.0, "pos": list(_T14_CAM_B_P1),
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                ],
            },
        ],
    }

# Two cameras, two clips. Camera A path = a long straight line near the
# origin; camera B path = a long straight line far away on +X so the
# A->B hard-cut is an unmistakable position discontinuity (no spline
# could tween between them within the harness sampling). Clip A plays
# camera A's path from in=0 for CLIP_A_DUR s; clip B (clip_start after
# A) plays camera B's path. Both underlying paths are long (600 s) so a
# clip's [in, in+duration] window is always inside the path. Durations
# are short so the Playwright observation (virtual clock) is bounded.
_T14_CLIP_A_DUR = 8.0
_T14_CLIP_B_DUR = 8.0
_T14_CAM_A_P0 = [0.0, 0.0, 0.0]
_T14_CAM_A_P1 = [0.0, 0.0, -60.0]
_T14_CAM_B_P0 = [500.0, 0.0, 0.0]
_T14_CAM_B_P1 = [500.0, 0.0, -60.0]


def _t14_clips_config() -> dict:
    """2 cameras + 2 clips (ordered by clip_start) auto-start sequence."""
    return {
        "annotations": [],
        "intro": {"type": "none"},
        "cameras": [
            {"id": "camA", "name": "Camera A", "path_id": "pathA"},
            {"id": "camB", "name": "Camera B", "path_id": "pathB"},
        ],
        "clips": [
            {"id": "clipA", "camera_id": "camA",
             "clip_start": 0.0, "duration": _T14_CLIP_A_DUR, "in": 0.0},
            {"id": "clipB", "camera_id": "camB",
             "clip_start": _T14_CLIP_A_DUR,
             "duration": _T14_CLIP_B_DUR, "in": 0.0},
        ],
        "camera_paths": [
            {
                "id": "pathA", "name": "Path A", "loop": False,
                "smoothness": 1.0, "play_speed": 1.0,
                "keyframes": [
                    {"t": 0.0, "pos": list(_T14_CAM_A_P0),
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                    {"t": 600.0, "pos": list(_T14_CAM_A_P1),
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                ],
            },
            {
                "id": "pathB", "name": "Path B", "loop": False,
                "smoothness": 1.0, "play_speed": 1.0,
                "keyframes": [
                    {"t": 0.0, "pos": list(_T14_CAM_B_P0),
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                    {"t": 600.0, "pos": list(_T14_CAM_B_P1),
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                ],
            },
        ],
    }


def _t14_noclips_config() -> dict:
    """`default_path_id` only, NO cameras/clips -> must behave EXACTLY
    like the pre-Task-14 single-tour autostart (no-clips regression)."""
    return {
        "annotations": [],
        "default_path_id": "solo-path",
        "intro": {"type": "none"},
        "camera_paths": [
            {
                "id": "solo-path", "name": "Solo straight line",
                "loop": False, "smoothness": 1.0, "play_speed": 1.0,
                "keyframes": [
                    {"t": 0.0, "pos": [0.0, 0.0, 0.0],
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                    {"t": 600.0, "pos": [0.0, 0.0, -100.0],
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                ],
            }
        ],
    }

# A trivial straight-line 2-keyframe path. `duration` = max kf.t = 600 s, so
# the player keeps ticking for the whole test (no early stopPath). Schema
# matches buildPlayer (sortedKfs needs >= 2 kfs, each with pos[3]; quat[4]
# optional). `default_path_id` makes init auto-start the path player.
#
# `intro:{type:"none"}` is deliberate TEST ISOLATION (Task 13): the Task-13
# cinematic intro defers the auto-start tour until AFTER the fade-out, which
# is the intended end-user behaviour but is ORTHOGONAL to what the Task-10
# tab-background-pause check measures (path-player clock mechanics). Opting
# this fixture out of the fade (a real, supported scene config) restores the
# immediate auto-start the Task-10 check calibrates against -- the deferred-
# tour behaviour itself has its OWN fixture (`_viewer_intro`, Task-13(b)).
_HARNESS_PATH_CONFIG = {
    "annotations": [],
    "default_path_id": "harness-path",
    "intro": {"type": "none"},
    "camera_paths": [
        {
            "id": "harness-path",
            "name": "Harness straight line",
            "loop": False,
            "smoothness": 1.0,
            "play_speed": 1.0,
            "keyframes": [
                {"t": 0.0, "pos": [0.0, 0.0, 0.0],
                 "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                {"t": 600.0, "pos": [0.0, 0.0, -100.0],
                 "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
            ],
        }
    ],
}

# Task-11 3-keyframe path. Middle key (t=60) is at y=16 — well OFF the
# straight A([0,0,0])→C([20,0,0]) line — so a Catmull/global-smoothness
# spline bulges through the mid segment (t∈(60,120)) and is demonstrably
# NOT colinear, while `interp:"linear"` forces that segment to the straight
# p1→p2 LERP. Long duration (120 s) keeps the auto-started player ticking
# for the whole virtual-clock walk.
_T11_A = [0.0, 0.0, 0.0]
_T11_B = [10.0, 16.0, 0.0]
_T11_C = [20.0, 0.0, 0.0]


def _t11_config(mid_interp: str | None) -> dict:
    """A 3-keyframe auto-start path; ``mid_interp`` (or absent) on key 2.

    ``intro:{type:"none"}`` is deliberate TEST ISOLATION (Task 13) -- same
    reasoning as ``_HARNESS_PATH_CONFIG``: the per-keyframe-interpolation
    check measures the spline the auto-started player writes; it must not be
    gated behind the (separately-tested) Task-13 intro fade-out.
    """
    mid = {"t": 60.0, "pos": list(_T11_B),
           "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0}
    if mid_interp is not None:
        mid["interp"] = mid_interp
    return {
        "annotations": [],
        "default_path_id": "t11-path",
        "intro": {"type": "none"},
        "camera_paths": [
            {
                "id": "t11-path",
                "name": "Task-11 per-keyframe interp",
                "loop": False,
                "smoothness": 1.0,
                "play_speed": 1.0,
                "keyframes": [
                    {"t": 0.0, "pos": list(_T11_A),
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                    mid,
                    {"t": 120.0, "pos": list(_T11_C),
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                ],
            }
        ],
    }


def _t13_config(intro: dict | None) -> dict:
    """Auto-start 2-keyframe path + an optional ``intro`` override.

    ``intro`` is written verbatim as the scene's ``intro`` key (or omitted
    when None → the viewer must fall back to ``DEFAULT_INTRO``). The path is
    a long (600 s) straight line like ``_HARNESS_PATH_CONFIG`` so the
    auto-started player keeps ticking for the whole observation; the harness
    asserts the tour starts only AFTER the intro fade (or immediately for
    ``type:"none"``).
    """
    cfg: dict = {
        "annotations": [],
        "default_path_id": "t13-path",
        "camera_paths": [
            {
                "id": "t13-path",
                "name": "Task-13 intro auto-start",
                "loop": False,
                "smoothness": 1.0,
                "play_speed": 1.0,
                "keyframes": [
                    {"t": 0.0, "pos": [0.0, 0.0, 0.0],
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                    {"t": 600.0, "pos": [0.0, 0.0, -100.0],
                     "quat": [0.0, 0.0, 0.0, 1.0], "fov": 60.0},
                ],
            }
        ],
    }
    if intro is not None:
        cfg["intro"] = intro
    return cfg


def generate() -> Path:
    """Write the viewer-under-test (index.html + stub config) and return its dir.

    Also writes sibling variant dirs (all the SAME generated HTML; only the
    viewer-config.json differs):
      * ``_viewer_path/`` — auto-starting 2-keyframe path; Task-10
        tab-background check.
      * ``_viewer_lin/`` / ``_viewer_nolin/`` / ``_viewer_step/`` —
        auto-starting 3-keyframe path with a `linear` / absent / `stepped`
        middle keyframe; Task-11 per-keyframe-interpolation check.
      * ``_viewer_intro/`` / ``_viewer_intronone/`` — auto-starting path
        with an ``intro`` of ``{type:"fade"}`` / ``{type:"none"}``; Task-13
        cinematic loading-blur + intro-fade check.
      * ``_viewer_clips/`` / ``_viewer_noclips/`` -- a 2-camera/2-clip
        Camera-Cuts sequence / a `default_path_id`-only no-clips scene;
        Task-14 multi-camera tour + next-cut prewarm + the no-clips
        single-tour regression.
      * ``_viewer_transport/`` -- a 2-camera/2-clip scene whose cameras
        carry distinct authored ``orbit_pivot``s; Task-15 end-user
        interrupt + resume-from-nearest-cut + per-shot idle auto-orbit.
      * ``_viewer_author/`` -- a 3-keyframe single-path scene (driven
        with ``?author=1`` by the harness); Task-16 author trajectory
        polyline + per-keyframe frusta + inverse-speed dots + toggle.
      * ``_viewer_t17/`` -- a 4-keyframe single-path scene with
        distinct segment durations (driven with ``?author=1``);
        Task-17 bottom timeline: diamonds at each kf.t, live-scrub
        playhead via the real #path-scrub mechanism (robust to the
        author-mode auto-tour), diamond-drag temporal edit, wheel
        zoom, box-multiselect + edge-drag span scale, X-delete, the
        fps-RELABEL-only grid -- all IN-MEMORY (no persistence).
      * ``_viewer_t18/`` -- a 3-keyframe single-path scene with
        distinct per-keyframe quats + well-separated positions
        (driven with ``?author=1``); Task-18 author select-key
        gizmo (TransformControls frustum-pick attach + drag
        write-back to kf.pos/kf.quat + World<->Screen + R/T), the
        5-type interp popover (writes kf.interp), Record(K) (live
        camera pose + the REAL elapsed playhead t), and the cli
        SPCP1 Save (byte-identical encode_spcp port) + the opt-in
        http POST -- all IN-MEMORY until the explicit Save.
    Returns the Task-0 ``_viewer/`` dir (the harness page resolves the rest
    relatively).
    """
    _VIEWER_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_PATH_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_LIN_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_NOLIN_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_STEP_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_INTRO_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_INTRONONE_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_NOCLIPS_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_TRANSPORT_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_AUTHOR_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_T17_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_T18_DIR.mkdir(parents=True, exist_ok=True)
    _VIEWER_T18_HTTP_DIR.mkdir(parents=True, exist_ok=True)
    # Same generated viewer for ALL variants — only the config differs.
    html = html_for("HarnessScene")
    (_VIEWER_DIR / "index.html").write_text(html, encoding="utf-8", newline="")
    (_VIEWER_PATH_DIR / "index.html").write_text(html, encoding="utf-8", newline="")
    (_VIEWER_LIN_DIR / "index.html").write_text(html, encoding="utf-8", newline="")
    (_VIEWER_NOLIN_DIR / "index.html").write_text(html, encoding="utf-8", newline="")
    (_VIEWER_STEP_DIR / "index.html").write_text(html, encoding="utf-8", newline="")
    (_VIEWER_INTRO_DIR / "index.html").write_text(html, encoding="utf-8", newline="")
    (_VIEWER_INTRONONE_DIR / "index.html").write_text(html, encoding="utf-8", newline="")
    (_VIEWER_CLIPS_DIR / "index.html").write_text(html, encoding="utf-8", newline="")
    (_VIEWER_NOCLIPS_DIR / "index.html").write_text(html, encoding="utf-8", newline="")
    (_VIEWER_TRANSPORT_DIR / "index.html").write_text(html, encoding="utf-8", newline="")
    (_VIEWER_AUTHOR_DIR / "index.html").write_text(html, encoding="utf-8", newline="")
    (_VIEWER_T17_DIR / "index.html").write_text(html, encoding="utf-8", newline="")
    (_VIEWER_T18_DIR / "index.html").write_text(html, encoding="utf-8", newline="")
    # The Task-18 http-mode variant uses a DIFFERENT generated HTML:
    # html_for bakes SAVE_MODE/SAVE_ENDPOINT via the Task-8 kwargs
    # (consumed, not re-added). Everything else is identical.
    html_http = html_for(
        "HarnessScene", save_mode="http",
        save_endpoint=_T18_HTTP_ENDPOINT,
    )
    (_VIEWER_T18_HTTP_DIR / "index.html").write_text(
        html_http, encoding="utf-8", newline=""
    )
    # A stub config so the no-store fetch succeeds and the viewer takes its
    # normal (non-error) path; no scene.rad is referenced/needed for the
    # framework-init assertions.
    (_VIEWER_DIR / "viewer-config.json").write_text(
        json.dumps({"annotations": [], "camera_paths": []}), encoding="utf-8", newline=""
    )
    (_VIEWER_PATH_DIR / "viewer-config.json").write_text(
        json.dumps(_HARNESS_PATH_CONFIG), encoding="utf-8", newline=""
    )
    # Task-11: linear / absent(no-interp) / stepped middle-keyframe variants.
    (_VIEWER_LIN_DIR / "viewer-config.json").write_text(
        json.dumps(_t11_config("linear")), encoding="utf-8", newline=""
    )
    (_VIEWER_NOLIN_DIR / "viewer-config.json").write_text(
        json.dumps(_t11_config(None)), encoding="utf-8", newline=""
    )
    (_VIEWER_STEP_DIR / "viewer-config.json").write_text(
        json.dumps(_t11_config("stepped")), encoding="utf-8", newline=""
    )
    # Task-13: fade (short ms) / none intro variants, each with an
    # auto-start path so the harness can assert tour-after-fade vs
    # tour-immediately.
    (_VIEWER_INTRO_DIR / "viewer-config.json").write_text(
        json.dumps(_t13_config({"type": "fade", "ms": _T13_INTRO_MS})),
        encoding="utf-8", newline="",
    )
    (_VIEWER_INTRONONE_DIR / "viewer-config.json").write_text(
        json.dumps(_t13_config({"type": "none"})), encoding="utf-8", newline=""
    )
    # Task-14: a 2-camera/2-clip Camera-Cuts sequence, and the
    # `default_path_id`-only no-clips regression scene.
    (_VIEWER_CLIPS_DIR / "viewer-config.json").write_text(
        json.dumps(_t14_clips_config()), encoding="utf-8", newline=""
    )
    (_VIEWER_NOCLIPS_DIR / "viewer-config.json").write_text(
        json.dumps(_t14_noclips_config()), encoding="utf-8", newline=""
    )
    # Task-15: a 2-camera/2-clip scene whose cameras carry distinct
    # authored orbit_pivots (the interrupt/resume/idle-orbit fixture).
    (_VIEWER_TRANSPORT_DIR / "viewer-config.json").write_text(
        json.dumps(_t15_transport_config()), encoding="utf-8", newline=""
    )
    # Task-16: a 3-keyframe single path (slow seg 0 / fast seg 1, distinct
    # per-keyframe quats); the harness drives this iframe with ?author=1.
    (_VIEWER_AUTHOR_DIR / "viewer-config.json").write_text(
        json.dumps(_t16_author_config()), encoding="utf-8", newline=""
    )
    # Task-17: a 4-keyframe single path with distinct segment durations
    # (short/long/short); the harness drives this iframe with ?author=1
    # so the Task-17 bottom timeline + the extended window.__editor
    # build (diamonds/scrub/drag/zoom/box-scale/delete/fps-relabel).
    (_VIEWER_T17_DIR / "viewer-config.json").write_text(
        json.dumps(_t17_timeline_config()), encoding="utf-8", newline=""
    )
    # Task-18: a 3-keyframe single path with distinct per-keyframe
    # quats + well-separated positions; the harness drives this
    # iframe with ?author=1 so the Task-16 overlay + Task-17 timeline
    # + the Task-18 gizmo/interp-popover/Record/Save-emit block + the
    # extended window.__editor build (frustum-pick gizmo attach +
    # drag write-back, World<->Screen, R/T, V interp popover, K
    # record at the real-elapsed playhead, cli SPCP1 emit + http
    # POST).
    (_VIEWER_T18_DIR / "viewer-config.json").write_text(
        json.dumps(_t18_gizmo_config()), encoding="utf-8", newline=""
    )
    # Task-18 http variant: SAME scene config (only the baked
    # SAVE_MODE/SAVE_ENDPOINT in its index.html differ).
    (_VIEWER_T18_HTTP_DIR / "viewer-config.json").write_text(
        json.dumps(_t18_gizmo_config()), encoding="utf-8", newline=""
    )
    return _VIEWER_DIR


def serve(port: int) -> None:
    """Serve tests/manual/ with Range support (mirrors serve_cmd.py)."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse
    import uvicorn

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )
    root = _MANUAL_DIR.resolve()

    @app.get("/{file_path:path}")
    def serve_file(file_path: str):
        rel = file_path or "keyframe-editor.html"
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            return HTMLResponse("Forbidden", status_code=403)
        if not target.is_file():
            return HTMLResponse("Not found", status_code=404)
        return FileResponse(target)

    print(f"Serving {root} on http://localhost:{port}")
    print(f"Harness: http://localhost:{port}/keyframe-editor.html")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--serve", type=int, metavar="PORT", default=None,
        help="After generating, serve tests/manual/ on PORT (Range-capable).",
    )
    args = ap.parse_args(argv)
    d = generate()
    print(f"generated {d / 'index.html'} ({(d / 'index.html').stat().st_size} bytes)")
    for _vd in (_VIEWER_PATH_DIR, _VIEWER_LIN_DIR, _VIEWER_NOLIN_DIR,
                _VIEWER_STEP_DIR, _VIEWER_INTRO_DIR, _VIEWER_INTRONONE_DIR,
                _VIEWER_CLIPS_DIR, _VIEWER_NOCLIPS_DIR,
                _VIEWER_TRANSPORT_DIR, _VIEWER_AUTHOR_DIR,
                _VIEWER_T17_DIR, _VIEWER_T18_DIR,
                _VIEWER_T18_HTTP_DIR):
        print(f"generated {_vd / 'index.html'} "
              f"({(_vd / 'index.html').stat().st_size} bytes)")
    if args.serve is not None:
        serve(args.serve)
    return 0


if __name__ == "__main__":
    sys.exit(main())
