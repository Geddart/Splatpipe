"""Tests for ``schema_version`` allow-list extension (§3.1 + spec §10).

Per the editor architecture spec §3.1, ``schema_version: <int>`` is a new
top-level key the deployed viewer reads to drive forward-compat shims.
It is **integer-literal-only** (no nested schema, no secret risk), so it
gets added to :data:`PUBLIC_VIEWER_CONFIG_KEYS` without a sub-key gate.

The full ``save_backend.secret`` regression sentinel from
`test_publish_config_sanitize.py` lives next door; this file pins JUST the
schema_version allow-list contract + the existing-sentinel-still-stripped
discipline (so a future allow-list addition cannot accidentally widen the
secret-leak surface).
"""

from __future__ import annotations

import json

from splatpipe.core.config_safety import (
    PUBLIC_VIEWER_CONFIG_KEYS,
    sanitize_public_viewer_config,
)


_SECRET = "BUNNY_KEY_SHOULD_NEVER_LEAK"


def test_schema_version_is_in_public_allow_list():
    """The new ``schema_version`` key is allow-listed for the public CDN."""
    assert "schema_version" in PUBLIC_VIEWER_CONFIG_KEYS


def test_schema_version_integer_survives_sanitization():
    """``schema_version: 1`` (an integer literal) passes the sanitiser
    unchanged. The viewer reads this to choose its forward-compat shim."""
    cfg = {
        "primary_asset": "ok.rad",
        "schema_version": 1,
    }
    out = sanitize_public_viewer_config(cfg)
    assert out["schema_version"] == 1
    assert out["primary_asset"] == "ok.rad"


def test_unknown_top_level_keys_still_rejected():
    """Adding ``schema_version`` to the allow-list does NOT widen any other
    surface — hostile / careless adjacent top-level keys are still dropped.

    Sentinel adjacent keys (``internal_notes``, ``_dev_flag``,
    ``BUNNY_STORAGE_PASSWORD``) are the same set test_publish_config_sanitize
    asserts for; this test re-locks them at the schema_version site so a
    future "just one more allow-listed key" change cannot loosen the gate."""
    cfg = {
        "primary_asset": "ok.rad",
        "schema_version": 1,
        "internal_notes": "private DB connection",
        "_dev_flag": True,
        "BUNNY_STORAGE_PASSWORD": "OOPS",
        "schema_version_unsafe": "fake nested key with the same prefix",
    }
    out = sanitize_public_viewer_config(cfg)
    assert "schema_version" in out
    assert out["schema_version"] == 1
    # Adjacent hostile keys still stripped.
    assert "internal_notes" not in out
    assert "_dev_flag" not in out
    assert "BUNNY_STORAGE_PASSWORD" not in out
    # Same-prefix-but-not-exact key not allow-listed.
    assert "schema_version_unsafe" not in out


def test_hostile_save_backend_secret_still_stripped_alongside_schema_version():
    """The existing centerpiece regression sentinel — ``save_backend.secret``
    never reaches the output — keeps holding when ``schema_version`` is set
    on the same config. (Belt-and-braces: ensures the new allow-list entry
    cannot accidentally widen the save_backend filter.)"""
    cfg = {
        "primary_asset": "ok.rad",
        "schema_version": 1,
        "save_backend": {
            "type": "cli",
            "endpoint": "https://endpoint.example",
            "secret": _SECRET,
        },
    }
    out = sanitize_public_viewer_config(cfg)
    assert out["schema_version"] == 1
    assert out["save_backend"]["type"] == "cli"
    assert out["save_backend"]["endpoint"] == "https://endpoint.example"
    assert "secret" not in out["save_backend"]
    # And: the secret string is nowhere in the dump.
    assert _SECRET not in json.dumps(out)
