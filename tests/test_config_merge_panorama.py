"""Tests for ``panorama_backdrop`` merge contract (§3.2 + §3.5).

Per the editor architecture spec, ``panorama_backdrop`` joins the
:data:`ALLOWED_PATCH_KEYS` allow-list so the editor's PanoramaModule
(Phase 3) can save panorama edits through the same shared
``merge_camera_scope`` core every other camera-scope patch uses.

Semantics are identical to the other allow-listed keys: **whole-replace**
(``result[key] = patch[key]``), NOT a deep merge. The locked
``primary_asset`` force-keep invariant (the "Speicher-blank"
production-failure class) still holds when panorama_backdrop rides in the
same patch.

Note: ``schema_version`` is INTENTIONALLY not in ``ALLOWED_PATCH_KEYS`` --
it is a server-managed schema-evolution field set at publish time, never
patched by an untrusted editor save.
"""

from __future__ import annotations

from splatpipe.core.config_merge import ALLOWED_PATCH_KEYS, merge_camera_scope


def test_panorama_backdrop_is_in_allowed_patch_keys():
    """``panorama_backdrop`` joins the camera-scope allow-list."""
    assert "panorama_backdrop" in ALLOWED_PATCH_KEYS


def test_schema_version_is_NOT_in_allowed_patch_keys():
    """``schema_version`` is server-managed -- the patch path MUST NOT be
    able to set it (it would let an untrusted editor downgrade the viewer's
    forward-compat shim)."""
    assert "schema_version" not in ALLOWED_PATCH_KEYS


def test_panorama_backdrop_patch_whole_replaces():
    """A panorama_backdrop in the patch wholesale-replaces the existing
    block (no deep merge). This matches the contract for every other
    allow-listed key in ``ALLOWED_PATCH_KEYS``."""
    existing = {
        "primary_asset": "bSPEICHER/scene.rad",
        "panorama_backdrop": {
            "url": "https://cdn.example/old.jpg",
            "rotation_deg": 0.0,
            "intensity": 1.0,
            "stale_subkey": "must_be_dropped_by_whole_replace",
        },
    }
    patch = {
        "panorama_backdrop": {
            "url": "https://cdn.example/new.jpg",
            "rotation_deg": 180.0,
            "intensity": 2.0,
        },
    }
    out = merge_camera_scope(existing, patch)
    # Whole-replace: the stale_subkey is gone, not deep-merged in.
    assert out["panorama_backdrop"] == {
        "url": "https://cdn.example/new.jpg",
        "rotation_deg": 180.0,
        "intensity": 2.0,
    }
    assert "stale_subkey" not in out["panorama_backdrop"]
    # primary_asset force-kept.
    assert out["primary_asset"] == "bSPEICHER/scene.rad"


def test_panorama_backdrop_primary_asset_force_keep_invariant():
    """The Speicher-blank locked invariant holds: a hostile patch that
    also carries a ``primary_asset`` pointer can NEVER win, even when the
    patch's legitimate panorama edit is applied."""
    existing = {
        "primary_asset": "bSPEICHER/scene.rad",
        "panorama_backdrop": None,
        "start_view": {"pos": [1, 2, 3]},
    }
    patch = {
        "panorama_backdrop": {
            "url": "https://cdn.example/sky.jpg",
            "rotation_deg": 90.0,
            "intensity": 1.0,
        },
        "primary_asset": "EVIL/attacker.rad",   # MUST NEVER apply
    }
    out = merge_camera_scope(existing, patch)
    # Legitimate panorama edit applied.
    assert out["panorama_backdrop"]["url"] == "https://cdn.example/sky.jpg"
    # LOCKED INVARIANT: pointer is always existing's, never patch's.
    assert out["primary_asset"] == "bSPEICHER/scene.rad"
    # Untouched siblings preserved.
    assert out["start_view"] == {"pos": [1, 2, 3]}


def test_empty_panorama_backdrop_null_in_patch_round_trips():
    """A patch can clear panorama_backdrop by sending ``None`` (the
    'remove the panorama' shape). Whole-replace semantics mean the
    result simply mirrors the patch value (including null)."""
    existing = {
        "primary_asset": "bSPEICHER/scene.rad",
        "panorama_backdrop": {
            "url": "https://cdn.example/sky.jpg",
            "rotation_deg": 0.0,
            "intensity": 1.0,
        },
    }
    patch = {"panorama_backdrop": None}
    out = merge_camera_scope(existing, patch)
    assert out["panorama_backdrop"] is None
    assert out["primary_asset"] == "bSPEICHER/scene.rad"
