"""R5 #172 -- the gizmo-drag MATH is deterministically correct (Node-run).

The keyframe/tangent gizmo handles drag via a three.js ``TransformControls``
whose handle is a WebGL object -- the Playwright MCP cannot issue a TRUSTED
raw-coordinate mouse-down/move/up on it (only element-to-element drags +
untrusted dispatched events), so a real handle DRAG is not harness-drivable.
The drag FEEL is therefore verified by the user (the trusted mouse); the
drag MATH is verified HERE, deterministically, by running the REAL JS
helpers (extracted verbatim from the generated viewer HTML) under Node.

Two pieces of new R5 math, both self-contained (only ``Math.*`` / a stub
``_trajFrLen``), are exercised:

  * **#1 handle-length clamp** -- ``_tanSquash`` / ``_tanUnsquash`` (the
    monotonic saturating remap of the drawn handle length). The load-bearing
    correctness property: ``_tanUnsquash(_tanSquash(x)) == x`` so the DRAWN
    length clamps while the STORED tangent magnitude (the spline input) is
    recovered EXACTLY -- the clamp never alters the curve. Plus the squash
    is monotonic, saturates below the cap, and is ~linear (speed-dependent)
    near the origin.
  * **#6 screen-plane free-drag** -- ``_kfPlaneHit`` (ray<->plane
    intersection; the keyframe follows the pointer in the camera-facing
    plane). Correct hit, parallel-ray miss, behind-ray (t<0) miss.

Skips cleanly if Node is unavailable (the rest of the suite still gates the
change); CI provides Node.
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

pytestmark = pytest.mark.skipif(
    _NODE is None, reason="node not available (CI provides it)"
)


def _slice(html: str, start_marker: str, end_after: str) -> str:
    """Return ``html[start .. end]`` where start is the first
    ``start_marker`` and end is the first 4-space ``\\n    }`` closing the
    function whose unique body line ``end_after`` was found after start."""
    a = html.index(start_marker)
    ret = html.index(end_after, a)
    end = html.index("\n    }", ret) + len("\n    }")
    return html[a:end]


def _extract_squash(html: str) -> str:
    """The soft-knee remap block: `const _TAN_KNEE_OF_FR` + `_tanKnee` +
    `_tanKScale` + `_tanSquash` + `_tanUnsquash` (verbatim). `_tanKnee`/
    `_tanKScale` read `_trajFrLen`, which the Node harness defines."""
    a = html.index("    const _TAN_KNEE_OF_FR = 1.0;")
    seg = _slice(html, "    const _TAN_KNEE_OF_FR = 1.0;",
                 "return knee + k * (Math.exp((d - knee) / k) - 1);")
    assert "function _tanKnee" in seg
    assert "function _tanKScale" in seg
    assert "function _tanSquash" in seg
    assert "function _tanUnsquash" in seg
    return html[a:html.index(seg) + len(seg)]


def _extract_plane_hit(html: str) -> str:
    seg = _slice(html, "    function _kfPlaneHit(", "return true;")
    assert "function _kfPlaneHit" in seg
    return seg


def _run_node(js: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "drag_math.mjs"
        p.write_text(js, encoding="utf-8")
        out = subprocess.run(
            [_NODE, str(p)], capture_output=True, text=True, timeout=30,
        )
        assert out.returncode == 0, f"node failed:\n{out.stderr}\n{out.stdout}"
        return json.loads(out.stdout.strip().splitlines()[-1])


def _harness() -> dict:
    html = html_for("HarnessScene")
    squash = _extract_squash(html)
    plane = _extract_plane_hit(html)
    js = (
        "let _trajFrLen = 2.0;\n"          # knee = 2.0*1.0 = 2.0; k = 2.0*0.6 = 1.2
        + squash + "\n"
        + plane + "\n"
        + r"""
const knee = _tanKnee();            // 2.0
const out = { knee };

// (1) round-trip: unsquash o squash == identity (magnitude preserved
//     EXACTLY across the whole range -- the unbounded log knee is
//     strictly invertible, unlike a saturating hard cap).
let maxErr = 0;
for (const x of [0, 0.01, 0.3, 1, 2.0, 5, 20, 100, 1000]) {
  const e = Math.abs(_tanUnsquash(_tanSquash(x)) - x);
  if (e > maxErr) maxErr = e;
}
out.roundtripMaxErr = maxErr;

// (2) full clamp round-trip at fr scale: m -> drawn=squash(m*fr) ->
//     recovered=unsquash(drawn)/fr == m (the editor's draw<->write).
const fr = 1.2;            // _tanFrac() = _trajFrLen * 0.6
let magErr = 0;
for (const m of [0.05, 0.5, 2, 8, 40, 200]) {
  const drawn = _tanSquash(m * fr);
  const rec = _tanUnsquash(drawn) / fr;
  magErr = Math.max(magErr, Math.abs(rec - m));
}
out.magRoundtripMaxErr = magErr;

// (3) soft-knee: IDENTITY below the knee (normal tangents undistorted ->
//     curve-faithful display), strong sub-linear compression above it,
//     strictly monotonic (still speed-dependent).
out.identityBelowKnee = (_tanSquash(0.5) === 0.5) && (_tanSquash(knee) === knee);
out.compressedAboveKnee = (_tanSquash(50) < 50) && (_tanSquash(50) < 8)
  && (_tanSquash(50) > knee);   // grows, but far below linear 50
let mono = true, prev = -1;
for (let x = 0; x <= 60; x += 0.25) { const s = _tanSquash(x); if (s <= prev) mono = false; prev = s; }
out.squashMonotonic = mono;
out.squashLinearNearZero = (_tanSquash(0.02) === 0.02); // exact identity below knee

// (4) _kfPlaneHit: ray straight down -Z from (0,0,10) onto the z=0
//     plane (normal +Z, point origin) hits (0,0,0).
const hit = [0, 0, 0];
out.planeHitOk = _kfPlaneHit(0, 0, 10, 0, 0, -1, 0, 0, 1, 0, 0, 0, hit)
  && Math.abs(hit[0]) < 1e-9 && Math.abs(hit[1]) < 1e-9 && Math.abs(hit[2]) < 1e-9;
// offset ray hits the plane at the offset x/y (depth fixed).
const hit2 = [0, 0, 0];
out.planeHitOffset = _kfPlaneHit(3, -2, 10, 0, 0, -1, 0, 0, 1, 0, 0, 0, hit2)
  && Math.abs(hit2[0] - 3) < 1e-9 && Math.abs(hit2[1] + 2) < 1e-9;
// parallel ray (dir in-plane) -> no hit.
out.planeParallelMiss = (_kfPlaneHit(0, 0, 10, 1, 0, 0, 0, 0, 1, 0, 0, 0, [0,0,0]) === false);
// behind ray (t<0): plane behind the ray origin's travel -> no hit.
out.planeBehindMiss = (_kfPlaneHit(0, 0, 10, 0, 0, 1, 0, 0, 1, 0, 0, 0, [0,0,0]) === false);

console.log(JSON.stringify(out));
"""
    )
    return _run_node(js)


def test_clamp_roundtrip_preserves_magnitude():
    """#1: unsquash o squash is the identity -> the displayed clamp never
    corrupts the stored tangent magnitude (the spline input)."""
    r = _harness()
    assert r["roundtripMaxErr"] < 1e-6, r
    assert r["magRoundtripMaxErr"] < 1e-5, r


def test_squash_softknee_identity_below_compress_above_monotonic():
    """#1: normal tangents draw at TRUE length (identity below the knee --
    no distortion of the curve's look), large tangents compress sub-
    linearly (the "way too long" fix), strictly monotonic (speed-
    dependent), exact identity for tiny tangents."""
    r = _harness()
    assert r["identityBelowKnee"], r
    assert r["compressedAboveKnee"], r
    assert r["squashMonotonic"], r
    assert r["squashLinearNearZero"], r
    assert abs(r["knee"] - 2.0) < 1e-9, r


def test_plane_hit_screen_plane_drag_math():
    """#6: the keyframe follows the pointer ray in the camera-facing plane
    (correct hit incl. offset; parallel + behind rays miss)."""
    r = _harness()
    assert r["planeHitOk"], r
    assert r["planeHitOffset"], r
    assert r["planeParallelMiss"], r
    assert r["planeBehindMiss"], r
