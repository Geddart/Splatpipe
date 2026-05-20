import base64
import json

import pytest

from splatpipe.core.spcp_token import SpcpError, decode_spcp, encode_spcp

PAYLOAD = {
    "v": 1,
    "scope": "camera_paths",
    "camera_paths": [
        {
            "id": "p1",
            "name": "A",
            "keyframes": [
                {"t": 0.0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1]},
                {"t": 3.0, "pos": [1, 2, 3], "quat": [0, 0, 0, 1]},
            ],
        }
    ],
    "cameras": [],
    "camera_cuts": [],
    "default_path_id": "p1",
}


def test_round_trip():
    tok = encode_spcp("fehmarn", PAYLOAD)
    assert tok.startswith("SPCP1:fehmarn:")
    slug, p = decode_spcp(tok)
    assert slug == "fehmarn" and p == PAYLOAD


def test_decode_rejects_bad_prefix():
    with pytest.raises(SpcpError):
        decode_spcp("SPV1:x:abc")


def test_decode_rejects_corrupt_b64():
    with pytest.raises(SpcpError):
        decode_spcp("SPCP1:fehmarn:!!!notb64!!!")


def test_decode_rejects_wrong_version():
    bad = base64.urlsafe_b64encode(json.dumps({"v": 2}).encode()).decode().rstrip("=")
    with pytest.raises(SpcpError):
        decode_spcp(f"SPCP1:fehmarn:{bad}")


def test_encode_rejects_slug_with_colon():
    with pytest.raises(SpcpError):
        encode_spcp("a:b", PAYLOAD)


def test_decode_rejects_wrong_scope():
    bad = (
        base64.urlsafe_b64encode(
            json.dumps({"v": 1, "scope": "start_view"}).encode()
        )
        .decode()
        .rstrip("=")
    )
    with pytest.raises(SpcpError):
        decode_spcp(f"SPCP1:fehmarn:{bad}")


def test_spcp_round_trip_handles_camera_deletion():
    """v2-C Phase 3 "Delete camera": after deletion the Save patch is a
    shrunk camera_paths + cameras envelope (the deleted entry simply
    ABSENT). The codec must round-trip that shape byte-identically --
    NO new wire key, NO codec change, the patch shape Phase 3 emits
    is just "the surviving cameras" (NOT "the diff" or "a delete
    marker"). Proves the Phase-3 delete flow needs ZERO codec change.

    Non-vacuous: the payload has exactly the shape _camSelDelete
    emits (camera_paths/cameras lists each shrunk to one entry, the
    surviving camera, plus a default_path_id re-pointed at it). A
    codec that mis-handled an empty middle slot, dropped an entry,
    or accidentally injected the deleted id would fail this."""
    # State BEFORE delete: 3 cameras. After deleting "p_b" the patch
    # carries the surviving 2 (p_a, p_c) and default_path_id = p_a
    # (current-camera fallback: deleted cam was selected, fall back
    # to the FIRST remaining camera).
    payload = {
        "v": 1,
        "scope": "camera_paths",
        "camera_paths": [
            {
                "id": "p_a",
                "name": "Camera 1",
                "keyframes": [
                    {"t": 0.0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1]},
                    {"t": 1.0, "pos": [1, 0, 0], "quat": [0, 0, 0, 1]},
                ],
            },
            # NOTE: no "p_b" entry -- the deleted camera is ABSENT
            {
                "id": "p_c",
                "name": "Camera 3",
                "keyframes": [
                    {"t": 0.0, "pos": [0, 0, 2], "quat": [0, 0, 0, 1]},
                    {"t": 2.5, "pos": [3, 0, 2], "quat": [0, 0, 0, 1]},
                ],
            },
        ],
        "cameras": [
            {"id": "cam_a", "name": "Camera 1", "path_id": "p_a"},
            {"id": "cam_c", "name": "Camera 3", "path_id": "p_c"},
        ],
        "default_path_id": "p_a",
    }
    tok = encode_spcp("fehmarn", payload)
    assert tok.startswith("SPCP1:fehmarn:")
    slug, decoded = decode_spcp(tok)
    assert slug == "fehmarn"
    assert decoded == payload
    # The deleted id is structurally absent (NOT a "tombstone" key).
    decoded_ids = {p["id"] for p in decoded["camera_paths"]}
    assert "p_b" not in decoded_ids
    assert decoded_ids == {"p_a", "p_c"}
    decoded_cam_ids = {c["id"] for c in decoded["cameras"]}
    assert "cam_b" not in decoded_cam_ids
    assert decoded_cam_ids == {"cam_a", "cam_c"}
