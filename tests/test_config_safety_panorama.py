"""Tests for ``panorama_backdrop`` allow-list extension (§3.2 + §5.2).

Per the editor architecture spec §3.2 / §5.2 the new ``panorama_backdrop``
block carries pure render parameters (equirect texture URL, rotation
degrees, intensity scalar). It is shaped as a small flat dict with no
secret risk -- so it ships through the sanitiser **wholesale** (R3), no
sub-key gate, no whitelist-of-leaves.

The full ``save_backend.secret`` regression sentinel from
`test_publish_config_sanitize.py` lives next door; this file pins the
panorama_backdrop allow-list contract + the existing-sentinel-still-stripped
discipline (so the new entry cannot accidentally widen the secret-leak
surface).
"""

from __future__ import annotations

import json

from splatpipe.core.config_safety import (
    PUBLIC_VIEWER_CONFIG_KEYS,
    sanitize_public_viewer_config,
)


_SECRET = "BUNNY_KEY_SHOULD_NEVER_LEAK"


def test_panorama_backdrop_is_in_public_allow_list():
    """The new ``panorama_backdrop`` block is allow-listed wholesale."""
    assert "panorama_backdrop" in PUBLIC_VIEWER_CONFIG_KEYS


def test_panorama_backdrop_block_survives_sanitization_wholesale():
    """A populated panorama_backdrop block passes through the sanitiser
    unchanged (no sub-key filtering — pure render params)."""
    cfg = {
        "primary_asset": "ok.rad",
        "panorama_backdrop": {
            "url": "https://cdn.example/sky.jpg",
            "rotation_deg": 90.0,
            "intensity": 1.5,
        },
    }
    out = sanitize_public_viewer_config(cfg)
    assert out["panorama_backdrop"] == cfg["panorama_backdrop"]
    # Distinct dict identity -- deep copy contract.
    assert out["panorama_backdrop"] is not cfg["panorama_backdrop"]


def test_empty_panorama_backdrop_null_survives():
    """``panorama_backdrop: None`` (the default-empty shape) and
    ``panorama_backdrop: {}`` both pass through unchanged. These are the
    legitimate 'no panorama set' shapes the editor emits."""
    for empty_value in (None, {}):
        cfg = {"primary_asset": "ok.rad", "panorama_backdrop": empty_value}
        out = sanitize_public_viewer_config(cfg)
        assert "panorama_backdrop" in out
        assert out["panorama_backdrop"] == empty_value


def test_hostile_save_backend_secret_still_stripped_alongside_panorama():
    """The existing centerpiece regression sentinel — ``save_backend.secret``
    never reaches the output — keeps holding when ``panorama_backdrop`` is
    set on the same config. (Belt-and-braces: ensures the new allow-list
    entry cannot accidentally widen the save_backend filter.)"""
    cfg = {
        "primary_asset": "ok.rad",
        "panorama_backdrop": {
            "url": "https://cdn.example/sky.jpg",
            "rotation_deg": 0.0,
            "intensity": 1.0,
        },
        "save_backend": {
            "type": "cli",
            "endpoint": "https://endpoint.example",
            "secret": _SECRET,
        },
    }
    out = sanitize_public_viewer_config(cfg)
    assert out["panorama_backdrop"]["url"] == "https://cdn.example/sky.jpg"
    assert out["save_backend"]["type"] == "cli"
    assert out["save_backend"]["endpoint"] == "https://endpoint.example"
    assert "secret" not in out["save_backend"]
    # And: the secret string is nowhere in the dump.
    assert _SECRET not in json.dumps(out)
