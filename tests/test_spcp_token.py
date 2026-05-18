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
