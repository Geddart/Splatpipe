"""#170 -- annotation navigation (points-of-interest) + the minimal bar.

The deployed Spark viewer gains an end-user way to step prev/next through a
scene's annotations, each flying the camera with a smooth, SPEED-DEPENDENT
ease to FRAME that annotation so its panel unfolds. Schema studied from the
SuperSplat viewer (MIT) `camera-manager.ts::annotation.activate` ease-out
reposition; adapted to OUR viewer by feeding a 2-keyframe Hermite path to the
EXISTING `buildPlayer`/`_player` driver (one camera driver, no 2nd rAF).

Two test layers, mirroring the project convention:

  * **STATIC surface markers** -- the bar DOM (03), its CSS + embed-strip
    (02a), and the nav/fly/visibility wiring + the idle POI-visibility fix
    (15c) are all present in the assembled `html_for(...)`. These FAIL
    against the pre-#170 template (negative-control: the ids / functions
    did not exist), so a PASS is substantive, not vacuous.
  * **DYNAMIC math (Node)** -- the two PURE laws that encode the contract
    are extracted verbatim from the generated HTML and run under Node:
    `_annFlyDuration` (distance -> clamped, speed-dependent seconds) and
    `_annEndDist` (cam-distance + unfold radius -> a stop distance that is
    always INSIDE the radius so the panel opens, never outward, never on
    the point). The camera FEEL (real WebGL pixels) is honest-deferred to
    the user's live test on a deployed same-origin slug -- a scene-less /
    cross-origin harness cannot prove the rendered move (see CLAUDE.md
    "Viewer / Harness Verification").
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from splatpipe.viewers.spark.template import html_for

_NODE = shutil.which("node")


# --------------------------------------------------------------------------
# STATIC surface markers
# --------------------------------------------------------------------------
def test_ann_nav_bar_dom_present():
    """The minimal annotation navigator bar + its three controls + label
    live in the assembled HTML (fragment 03)."""
    html = html_for("AnnNavScene")
    assert 'id="ann-nav"' in html
    assert 'id="ann-nav-prev"' in html
    assert 'id="ann-nav-next"' in html
    assert 'id="ann-nav-label"' in html
    # The chevrons are ASCII-only inline SVG (no icon font dependency).
    assert "Previous point of interest" in html
    assert "Next point of interest" in html


def test_ann_nav_css_and_embed_strip():
    """The bar is styled in the same subtle language as #path-mini, has the
    .shown / .with-path state classes, and is stripped in embed mode."""
    html = html_for("AnnNavScene")
    assert "#ann-nav {" in html
    assert "#ann-nav.shown { display: flex; }" in html
    assert "#ann-nav.with-path" in html        # bumps above #path-mini
    assert "#ann-nav-label {" in html
    assert "body.embed #ann-nav," in html      # embed strips it like all chrome


def test_ann_nav_fly_reuses_existing_player():
    """The fly is a 2-keyframe path fed to the EXISTING buildPlayer/_player
    (the one camera driver) under the reserved 'ann-fly' path id -- NOT a
    new rAF / bespoke lerp."""
    html = html_for("AnnNavScene")
    assert "function _annFlyTo(" in html
    assert "id: 'ann-fly'" in html
    assert "buildPlayer(path)" in html
    # Pre-points the orbit pivot at the annotation so the post-fly
    # _syncControlsToCamera (inside stopPath) lands the pivot on it.
    assert "controls.target.copy(posV)" in html


def test_ann_nav_stepping_and_wiring():
    """prev/next stepping + the bar wiring + the user-mode visibility gate."""
    html = html_for("AnnNavScene")
    assert "function _annNavGo(" in html
    assert "function _annNavToId(" in html
    assert "function _annNavWire(" in html
    assert "function _annNavRefresh(" in html
    # Wired on mount (so the bar appears as soon as the module mounts).
    assert "_annNavWire();" in html
    # User-mode gate (author uses the drawer; embed strips chrome).
    assert "ModeManager.is('user')" in html


def test_ann_nav_click_far_dot_flies():
    """SuperSplat-parity: clicking a dot the camera is FAR from flies to it
    (close-up clicks still toggle in place; author always toggles)."""
    html = html_for("AnnNavScene")
    assert "function _annCamOutsideRadius(" in html
    assert "_annNavToId(ann.id)" in html


def test_ann_nav_idle_poi_visibility_fix():
    """The idle/POI visibility fix: with no cinematic tour, a default-window
    annotation shows at full opacity instead of being faded to 0 at t=0.
    This is what makes a navigable point-of-interest visible at all."""
    html = html_for("AnnNavScene")
    assert "function _hasCinematicPlayhead(" in html
    assert "if (!cinematic && tIn <= 1e-3 && tOut >= 998) return 1;" in html
    # The tick passes the cinematic flag through to the opacity evaluation.
    assert "_timelineOpacity(ann, tNow, cinematic)" in html


def test_ann_nav_review_fixes_present():
    """The four adversarial-review fixes are in the bundle:
    (HIGH) clip-aware pre-empt so an ann-fly does not get hard-cut to the
    next clip; (MED) near-vertical lookAt nudge (no roll); (MED) a
    manually-forced POI stays visible at idle even if windowed-out; (LOW)
    a canvas grab aborts an in-flight ann-fly."""
    html = html_for("AnnNavScene")
    # HIGH: clip-mode tours are torn down via the existing clip-aware _stopTour
    assert "_stopTour({ byUser: true })" in html
    assert "_clipState.active" in html
    # MED: near-vertical dolly is nudged off the pole before lookAt
    assert "Math.abs(dir.y) > 0.9998" in html
    # MED: manual-forced POI visible at idle even when windowed-out
    assert "if (opacity <= 0 && s.manual === true && !cinematic) opacity = 1;" in html
    # LOW: an in-flight ann-fly is interruptible from the canvas (fragment 12)
    assert "_activePathId === 'ann-fly'" in html


def test_ann_nav_test_surface():
    """The window.__editor.annotations nav helpers + pure math are exposed
    for harness + Node assertions."""
    html = html_for("AnnNavScene")
    for marker in (
        "navNext:", "navPrev:", "navTo:", "flyToId:", "navLabel:",
        "navShown:", "_annFlyDuration:", "_annEndDist:",
        "_hasCinematicPlayhead:",
    ):
        assert marker in html, marker


# --------------------------------------------------------------------------
# DYNAMIC math (Node) -- the two pure laws, run verbatim
# --------------------------------------------------------------------------
def _slice(html: str, start_marker: str, end_after: str) -> str:
    a = html.index(start_marker)
    ret = html.index(end_after, a)
    end = html.index("\n    }", ret) + len("\n    }")
    return html[a:end]


def _extract_math(html: str) -> str:
    """Const tuning block + `_annFlyDuration` + `_annEndDist`, verbatim.
    Self-contained (only Math.* / isFinite), so it runs under bare Node."""
    seg = _slice(
        html,
        "    const ANN_FLY_SPEED_MPS = 6.0;",
        "return Math.max(ANN_FRAME_MIN_M, Math.min(frame, cur));",
    )
    assert "function _annFlyDuration" in seg
    assert "function _annEndDist" in seg
    return seg


def _run_node(js: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "ann_nav_math.mjs"
        p.write_text(js, encoding="utf-8")
        out = subprocess.run(
            [_NODE, str(p)], capture_output=True, text=True, timeout=30,
        )
        assert out.returncode == 0, f"node failed:\n{out.stderr}\n{out.stdout}"
        return json.loads(out.stdout.strip().splitlines()[-1])


def _harness() -> dict:
    math_block = _extract_math(html_for("HarnessScene"))
    js = (
        math_block
        + "\n"
        + r"""
const out = {};

// (1) _annFlyDuration: clamped + speed-dependent.
out.durFloor = _annFlyDuration(0);        // 0 -> MIN
out.durFloorNeg = _annFlyDuration(-5);    // garbage -> MIN
out.dur6 = _annFlyDuration(6);            // 6 / 6 = 1.0 (unclamped)
out.dur12 = _annFlyDuration(12);          // 12 / 6 = 2.0
out.durCeil = _annFlyDuration(1000);      // -> MAX
// strictly non-decreasing across the range
let mono = true, prev = -1;
for (let d = 0; d <= 30; d += 0.5) { const s = _annFlyDuration(d); if (s < prev - 1e-12) mono = false; prev = s; }
out.durMonotonic = mono;
// speed-dependent in the linear band: 2x distance -> 2x duration
out.durLinear = Math.abs(_annFlyDuration(12) - 2 * _annFlyDuration(6)) < 1e-9;

// (2) _annEndDist: always inside radius, never outward, never on the point.
out.endFar = _annEndDist(10, 5);          // frame = 0.6*5 = 3 ; min(3,10)=3
out.endClose = _annEndDist(1, 5);         // min(3,1)=1 (reorient, no dolly out)
out.endOnPoint = _annEndDist(0.2, 5);     // floor 0.5
out.endFarInsideRadius = (_annEndDist(10, 5) < 5);   // panel will unfold
out.endNeverOutward = (_annEndDist(1, 5) <= 1 + 1e-9);
out.endFloor = (_annEndDist(0.01, 5) >= 0.5 - 1e-9);
out.endBadRadius = _annEndDist(10, 0);    // radius<=0 -> default 5 -> 3
// across radii the stop is always <= frac*radius and >= floor
let ok = true;
for (const r of [1, 5, 20]) {
  for (const c of [0.1, 2, 50]) {
    const e = _annEndDist(c, r);
    if (e > r * 0.6 + 1e-9 || e < 0.5 - 1e-9) ok = false;
  }
}
out.endInvariant = ok;

console.log(JSON.stringify(out));
"""
    )
    return _run_node(js)


@pytest.mark.skipif(_NODE is None, reason="node not available (CI provides it)")
def test_fly_duration_is_clamped_and_speed_dependent():
    r = _harness()
    assert abs(r["durFloor"] - 0.5) < 1e-9, r
    assert abs(r["durFloorNeg"] - 0.5) < 1e-9, r
    assert abs(r["dur6"] - 1.0) < 1e-9, r
    assert abs(r["dur12"] - 2.0) < 1e-9, r
    assert abs(r["durCeil"] - 2.4) < 1e-9, r
    assert r["durMonotonic"], r
    assert r["durLinear"], r


@pytest.mark.skipif(_NODE is None, reason="node not available (CI provides it)")
def test_end_distance_lands_inside_unfold_radius():
    r = _harness()
    assert abs(r["endFar"] - 3.0) < 1e-9, r
    assert abs(r["endClose"] - 1.0) < 1e-9, r
    assert abs(r["endOnPoint"] - 0.5) < 1e-9, r
    assert r["endFarInsideRadius"], r       # arrival inside radius -> unfold
    assert r["endNeverOutward"], r
    assert r["endFloor"], r
    assert abs(r["endBadRadius"] - 3.0) < 1e-9, r
    assert r["endInvariant"], r
