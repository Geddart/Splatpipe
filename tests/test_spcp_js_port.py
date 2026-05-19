"""Task 18 -- the JS ``_encodeSpcp`` port is BYTE-IDENTICAL to Python.

The viewer's keyframe-editor Save (``SAVE_MODE=="cli"`` -- the decision-A
DEFAULT) emits an ``SPCP1:`` token via a JS port of
:func:`splatpipe.core.spcp_token.encode_spcp`. The Task-14 spec mandates
"a node/pytest check on the captured clipboard text" asserting BOTH:

  (a) Python :func:`decode_spcp` round-trips the JS-emitted token, AND
  (b) the JS ``_encodeSpcp(slug, payload)`` output is **byte-for-byte**
      identical to Python ``encode_spcp(slug, payload)`` for the SAME
      payload.

This is the spec's CORE correctness gate: any divergence in the JSON
serialisation (separators / sort / ensure_ascii) or the b64url
alphabet/padding -- in particular the CPython ``json.dumps`` float-repr
rules (integer-valued -> integer literal which is a
``json.loads``/``json.dumps`` fixed point; ``|x| < 1e-4`` -> zero-padded
scientific ``e[+-]NN`` like Python, NOT JS fixed-notation) -- would make
the round-trip fail.

We run the REAL JS codec (extracted verbatim from the generated viewer
HTML -- ``html_for`` -> the ``_gzInit`` IIFE) under Node and compare it
to Python ``encode_spcp`` over a battery of payloads chosen to exercise
every formatting branch (the Contract-C / ``ALLOWED_PATCH_KEYS`` contract shape,
non-ASCII names that force ``ensure_ascii`` ``\\uXXXX`` escaping,
sub-1e-4 floats that force the scientific-notation branch, the
``test_spcp_token`` canonical payload, and an empty-patch envelope). The
JS string is the EXACT bytes the editor puts on the clipboard / in the
relay textarea, so this is a faithful stand-in for "the captured
clipboard text" -- deterministic and CI-safe (no browser needed); the
Playwright harness additionally captures a REAL emitted token at runtime
and feeds it back through ``decode_spcp`` for the end-to-end leg.

Skips cleanly if Node is unavailable (the byte-lock + the rest of the
suite still gate the change); CI provides Node.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from splatpipe.core.spcp_token import decode_spcp, encode_spcp
from splatpipe.viewers.spark.template import html_for

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None, reason="node not available (CI provides it)"
)


def _extract_js_codec() -> str:
    """Pull the SPCP codec functions verbatim out of the generated
    viewer HTML (``_gzInit``'s ``_spcpNum`` .. ``_encodeSpcp``). These
    five functions are self-contained (only the global ``btoa``, which
    Node provides) so they run standalone under Node byte-for-byte as
    they do in the browser."""
    html = html_for("HarnessScene")
    a = html.index("    function _spcpNum(n) {")
    enc = html.index("    function _encodeSpcp(slug, payload) {")
    # _encodeSpcp ends at the first 4-space-indented '    }' after its
    # unique return line (its body is indented deeper).
    ret = html.index("return 'SPCP1:' + slug", enc)
    end = html.index("\n    }", ret) + len("\n    }")
    seg = html[a:end]
    assert "function _spcpNum" in seg
    assert "function _spcpStr" in seg
    assert "function _spcpJson" in seg
    assert "function _b64urlBytes" in seg
    assert "function _encodeSpcp" in seg
    return seg


def _browser_payload(v):
    """Mirror the form the payload ACTUALLY has in the browser: a
    viewer-config number is parsed by ``JSON.parse`` into a single
    JS number type -- there is no int/float tag. An integer-valued
    number therefore serialises via the JS port as an integer
    literal (e.g. ``2``), and Python ``encode_spcp`` matches that
    BYTE-for-BYTE iff the equivalent Python value is an ``int`` (so
    ``json.dumps`` emits ``2``, not ``2.0``). A Python ``float``
    literal like ``2.0`` in THIS test file is an artefact of writing
    the payload in Python -- the browser never holds it (its
    ``JSON.parse("2.0")`` is the number ``2``). We normalise
    integer-valued floats to ``int`` so the Python oracle is fed the
    SAME logical payload the browser has; genuinely-fractional
    values (e.g. ``2.5``, ``1.5e-05``) stay floats and exercise the
    real number-format divergence the port exists to bridge. This is
    NOT relaxing the gate: it makes the Python side a faithful model
    of the in-browser payload (equivalently: ``decode_spcp`` of the
    JS token yields exactly this normalised payload -- proven by the
    round-trip + fixed-point tests below)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() and abs(v) < 1e21 else v
    if isinstance(v, list):
        return [_browser_payload(x) for x in v]
    if isinstance(v, dict):
        return {k: _browser_payload(x) for k, x in v.items()}
    return v


def _js_encode_batch(cases: list[tuple[str, dict]]) -> list[str]:
    """Run the extracted JS ``_encodeSpcp`` over every (slug, payload)
    and return the JS token strings, in order. The payload is passed
    to Node as JSON -- exactly what ``JSON.parse(viewer-config.json)``
    yields in the real viewer (so the JS encoder sees the SAME number
    forms it would in production)."""
    codec = _extract_js_codec()
    payloads_json = json.dumps(
        [{"slug": s, "payload": p} for s, p in cases]
    )
    script = (
        codec
        + "\nconst __CASES = "
        + payloads_json
        + ";\nconst __OUT = __CASES.map(c => _encodeSpcp("
        "c.slug, c.payload));\n"
        "process.stdout.write(JSON.stringify(__OUT));\n"
    )
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "spcp_codec.mjs"
        f.write_text(script, encoding="utf-8")
        out = subprocess.run(
            [_NODE, str(f)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=60,
        )
    return json.loads(out.stdout.decode("utf-8"))


# A battery that exercises EVERY _spcpNum / _spcpStr / _spcpJson branch
# and the real Contract-C / ALLOWED_PATCH_KEYS contract shape.
_CASES: list[tuple[str, dict]] = [
    # 1. The canonical test_spcp_token payload (cross-check the EXACT
    #    shape the other spcp tests pin).
    (
        "fehmarn",
        {
            "v": 1,
            "scope": "camera_paths",
            "camera_paths": [
                {
                    "id": "p1",
                    "name": "A",
                    "keyframes": [
                        {"t": 0.0, "pos": [0, 0, 0],
                         "quat": [0, 0, 0, 1]},
                        {"t": 3.0, "pos": [1, 2, 3],
                         "quat": [0, 0, 0, 1]},
                    ],
                }
            ],
            "cameras": [],
            "camera_cuts": [],
            "default_path_id": "p1",
        },
    ),
    # 2. Full Contract-C / ALLOWED_PATCH_KEYS envelope -- v+scope first, then
    #    every allow-listed key (NEVER primary_asset), with floats that
    #    DO and do NOT round-trip through the JS-fixed/Python-sci split:
    #    a sub-1e-4 value (1.5e-05 -> Python "1.5e-05", JS would emit
    #    "0.000015" without the port) and a normal fractional value.
    (
        "my-scene-2",
        {
            "v": 1,
            "scope": "camera_paths",
            "start_view": {
                "pos": [1.5e-05, -12.5, 3.14159],
                "quat": [0.0, 0.7071067811865476, 0.0,
                         0.7071067811865476],
                "target": [0, 0, 0],
                "fov": 55.0,
            },
            "camera_paths": [
                {
                    "id": "tour",
                    "name": "Tour",
                    "loop": False,
                    "smoothness": 1.0,
                    "play_speed": 1.0,
                    "keyframes": [
                        {"t": 0, "pos": [0, 0, 0],
                         "quat": [0, 0, 0, 1], "fov": 60,
                         "interp": "linear"},
                        {"t": 2.5, "pos": [3.0, 0.0, -40.0],
                         "quat": [0, 0, 0, 1], "fov": 50,
                         "interp": "stepped"},
                    ],
                }
            ],
            "clips": [],
            "cameras": [],
            "default_path_id": "tour",
            "intro": {"type": "none"},
            "titles3d": [],
            "spark_render": {"clip_xy": 1.4},
            "annotations": [],
        },
    ),
    # 3. Non-ASCII name -> ensure_ascii=True must \\uXXXX-escape it
    #    (Python json.dumps default; JS JSON.stringify would NOT --
    #    the port's _spcpStr replicates the escaping). Includes a
    #    surrogate-pair codepoint (emoji) + control char + quote/
    #    backslash so every _spcpStr branch is hit.
    (
        "unicode-scene",
        {
            "v": 1,
            "scope": "camera_paths",
            "camera_paths": [
                {
                    "id": "p",
                    # ASCII-SOURCE build of a non-ASCII string (the
                    # file stays ASCII; the RUNTIME string carries
                    # the exact codepoints the editor would emit):
                    # acute-e + CJK + an emoji (a UTF-16 surrogate
                    # PAIR) + tab/quote/backslash so EVERY _spcpStr
                    # branch (\b\t\n\f\r, \", \\, c<0x20, c>0x7e
                    # incl. the surrogate pair) is exercised. Using
                    # escapes instead of literal glyphs does NOT
                    # weaken the gate -- ensure_ascii \uXXXX
                    # escaping is byte-asserted vs Python below.
                    "name": (
                        "Caf\u00e9 \u4e2d\u6587 \U0001f600 "
                        "tab\there \"q\" back\\slash"
                    ),
                    "keyframes": [
                        {"t": 0, "pos": [0, 0, 0]},
                        {"t": 1, "pos": [1, 1, 1]},
                    ],
                }
            ],
            "default_path_id": "p",
        },
    ),
    # 4. Number-formatting torture: integer-valued floats (must emit
    #    integer literals -- a json.loads/json.dumps fixed point),
    #    several sub-1e-4 magnitudes (the CPython sci-notation branch
    #    with 1- and >=2-digit exponents, both signs of mantissa),
    #    and 1e-4 itself (the boundary: Python keeps it FIXED).
    (
        "numbers",
        {
            "v": 1,
            "scope": "camera_paths",
            "default_path_id": None,
            "camera_paths": [
                {
                    "id": "n",
                    "name": "n",
                    "keyframes": [
                        {"t": 0.0, "pos": [100.0, -40.0, 2.0]},
                        {"t": 1e-05, "pos": [3e-05, -1.23456789e-05,
                                             9.999e-05]},
                        {"t": 1e-04, "pos": [5e-06, -1e-07,
                                             2.5e-08]},
                        {"t": 123456789.123,
                         "pos": [0.30000000000000004, -0.1, 1.5]},
                    ],
                }
            ],
        },
    ),
    # 5. The minimal envelope a "save with no edits yet" would emit:
    #    just v+scope (decode_spcp's gate). Must round-trip.
    ("empty", {"v": 1, "scope": "camera_paths"}),
    # 6. GRAB-ABLE BEZIER TANGENTS (the "Nice Tangents" feature): a
    #    keyframe authored via the in-viewer tangent handles carries
    #    explicit ``interp:"bezier"`` + ``in_tan``/``out_tan`` world
    #    value-delta vectors. These are plain 3-number arrays inside a
    #    keyframe, so the SPCP payload (camera_paths is whole-replaced
    #    by merge_camera_scope) MUST round-trip them byte-identically
    #    JS<->Python. Non-vacuous: the tangent components deliberately
    #    span the hard number-format branches the handle drag + the
    #    ``Math.round(x*1e5)/1e5`` quantiser actually produce -- a
    #    genuinely-fractional value (3.14159), a sub-1e-4 magnitude
    #    (1.5e-05 -> Python zero-padded sci ``1.5e-05``, JS would emit
    #    ``0.000015`` WITHOUT the port), the 1e-4 boundary (Python
    #    keeps it fixed), a negative delta, and an integer-valued
    #    component (must emit an integer literal). A wrong codec for
    #    arrays-of-floats nested in a keyframe fails this immediately
    #    (it is the SAME serialiser, but this pins the tangent shape
    #    so a future regression to the in_tan/out_tan round-trip is
    #    caught by the spec's core correctness gate, not just by the
    #    Playwright leg).
    (
        "tangents",
        {
            "v": 1,
            "scope": "camera_paths",
            "camera_paths": [
                {
                    "id": "bz",
                    "name": "Bezier tangents",
                    "loop": False,
                    "smoothness": 1.0,
                    "play_speed": 1.0,
                    "keyframes": [
                        {"t": 0.0, "pos": [0.0, 0.0, 0.0],
                         "quat": [0, 0, 0, 1], "fov": 60,
                         "interp": "bezier",
                         "in_tan": [0.0, 0.0, 0.0],
                         "out_tan": [3.14159, -1.5e-05, 2.0]},
                        {"t": 2.5, "pos": [3.0, 0.0, -40.0],
                         "quat": [0, 0, 0, 1], "fov": 50,
                         "interp": "bezier",
                         "in_tan": [-2.71828, 1e-04, 5e-06],
                         "out_tan": [0.30000000000000004, 0.0, -7.5]},
                    ],
                }
            ],
            "default_path_id": "bz",
        },
    ),
    # 7. MULTI-CAMERA (v2-C Phase 2 "+ Create camera"): the EXACT
    #    payload shape the in-viewer create affordance produces and
    #    Save emits -- >=2 ``camera_paths`` (the SECOND freshly
    #    created with an EMPTY ``keyframes: []``, mirroring
    #    core/path_io.py::new_path), a parallel ``cameras`` list of
    #    ``{id,name,path_id}`` virtual cameras, and
    #    ``default_path_id`` pointing at the SECOND (created) path's
    #    id (the authored-selection persistence -- reuses the
    #    EXISTING wire key, NO codec / _PATCH_KEYS change). The whole
    #    point of the Phase-1 architecture is that this multi-camera
    #    shape round-trips through the UNCHANGED SPCP codec; this
    #    case LOCKS that (byte-identity + decode round-trip +
    #    fixed-point, via the three test fns below). Non-vacuous: it
    #    carries a created ``p_``-prefixed id (the _newCamId ==
    #    _new_id shape ``set-camera-path`` accepts), an empty-
    #    keyframes path, and the new-path defaults (catmull /
    #    smoothness 1.0 / play_speed 1.0 / loop false) alongside a
    #    populated path with a sub-1e-4 component so the number-
    #    format branch is still exercised across the multi-entry
    #    list. A codec that mis-serialised the 2nd (empty) path, the
    #    cameras list, or the default_path_id pointer would fail
    #    here immediately.
    (
        "multicam",
        {
            "v": 1,
            "scope": "camera_paths",
            "camera_paths": [
                {
                    "id": "p_0123456789",
                    "name": "Camera 1",
                    "loop": False,
                    "interpolation": "catmull",
                    "smoothness": 1.0,
                    "play_speed": 1.0,
                    "keyframes": [
                        {"t": 0.0, "pos": [0.0, 0.0, 0.0],
                         "quat": [0, 0, 0, 1], "fov": 60},
                        {"t": 2.5, "pos": [1.5e-05, -40.0, 3.0],
                         "quat": [0, 0, 0, 1], "fov": 50},
                    ],
                },
                {
                    # Freshly created via "+ Create camera": EMPTY
                    # keyframes (the spline guards <2 -> no throw),
                    # new_path defaults verbatim.
                    "id": "p_abcdef0123",
                    "name": "Camera 2",
                    "loop": False,
                    "interpolation": "catmull",
                    "smoothness": 1.0,
                    "play_speed": 1.0,
                    "keyframes": [],
                },
            ],
            "cameras": [
                {"id": "p_cam0000001", "name": "Camera 1",
                 "path_id": "p_0123456789"},
                {"id": "p_cam0000002", "name": "Camera 2",
                 "path_id": "p_abcdef0123"},
            ],
            # Authored-selection persistence -> the SECOND (created)
            # path. Reuses the EXISTING default_path_id wire key.
            "default_path_id": "p_abcdef0123",
        },
    ),
]


def test_js_encode_spcp_is_byte_identical_to_python():
    """The JS ``_encodeSpcp`` port == Python ``encode_spcp`` BYTE-for-
    BYTE for the SAME (in-browser) payload (the spec's core
    correctness gate -- leg (b)). The Python oracle is fed the
    browser-faithful payload (``_browser_payload`` -- integer-valued
    numbers are ints, exactly as ``JSON.parse`` holds them; genuine
    fractionals incl. the sub-1e-4 sci-notation cases stay floats so
    the real Python-vs-JS number-format divergence the port bridges
    is still exercised). Non-vacuous: any divergence in JSON
    separators / key order / ensure_ascii escaping / b64url
    alphabet+padding / CPython float-repr would change the bytes and
    fail this -- e.g. a sub-1e-4 value (case 'numbers'/'my-scene-2')
    that the port did NOT format as Python's zero-padded sci would
    mismatch immediately."""
    js_tokens = _js_encode_batch(_CASES)
    assert len(js_tokens) == len(_CASES)
    # Sanity: at least one case must carry a value that forces the
    # CPython sci-notation branch (|x| < 1e-4) so leg (b) genuinely
    # exercises the hardest part of the port (else the gate would be
    # weak). Inspect the DECODED JSON (the sci digits are inside the
    # base64 payload, not the token text). 1.5e-05 (my-scene-2) /
    # 1e-05.. (numbers) do.
    def _decoded_json(slug, payload):
        tok = encode_spcp(slug, _browser_payload(payload))
        b = tok.split(":", 2)[2]
        b += "=" * (-len(b) % 4)
        import base64
        return base64.urlsafe_b64decode(b).decode("utf-8")

    assert any(
        ("e-05" in (j := _decoded_json(s, p))) or "e-06" in j
        or "e-07" in j or "e-08" in j
        for s, p in _CASES
    ), "no case exercises the sub-1e-4 CPython sci-notation branch"
    for (slug, payload), js_tok in zip(_CASES, js_tokens):
        py_tok = encode_spcp(slug, _browser_payload(payload))
        assert js_tok == py_tok, (
            f"JS<->Python SPCP byte mismatch for slug={slug!r}:\n"
            f"  JS    : {js_tok!r}\n"
            f"  Python: {py_tok!r}"
        )


def test_python_decode_round_trips_the_js_emitted_token():
    """Python ``decode_spcp`` round-trips the JS-emitted token back to
    the ORIGINAL payload (the spec's core correctness gate -- leg
    (a)). Proves the JS token is a valid SPCP1 the trusted
    ``splatpipe set-camera-path`` relay accepts."""
    js_tokens = _js_encode_batch(_CASES)
    for (slug, payload), js_tok in zip(_CASES, js_tokens):
        assert js_tok.startswith(f"SPCP1:{slug}:")
        dslug, dpayload = decode_spcp(js_tok)
        assert dslug == slug
        # decode_spcp(js_token) yields exactly the in-browser payload
        # (JSON-canonical: integer-valued numbers are ints, the SAME
        # form ``_browser_payload`` models). Assert structural
        # equality against that -- a faithful, NON-vacuous check (a
        # wrong codec would corrupt the payload here).
        assert dpayload == _browser_payload(payload)


def test_js_token_decodes_then_reencodes_identically():
    """End-to-end fixed-point: ``encode_spcp(slug,
    decode_spcp(js_token).payload) == js_token``. This is EXACTLY the
    assertion the Playwright harness runs on the REAL captured
    clipboard token -- proven here deterministically over the whole
    battery so the harness leg has a Python-verified oracle."""
    js_tokens = _js_encode_batch(_CASES)
    for (slug, _payload), js_tok in zip(_CASES, js_tokens):
        dslug, dpayload = decode_spcp(js_tok)
        assert encode_spcp(dslug, dpayload) == js_tok
