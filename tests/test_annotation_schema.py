"""Tests for the expanded annotation schema (#122 Phase 5 prep).

Per user-locked Q6 (2026-05-20 17:38 voice) and the editor architecture
spec §11.6, annotations gain six new optional fields:

- ``kind`` (Literal["dot_unfold", "title3d_overlay"], default "dot_unfold")
- ``unfold_radius_m`` (float, default 5.0)
- ``t_in`` / ``t_out`` (float, defaults 0.0 / 999.0)
- ``fade_ms`` (int, default 300)
- ``media_url`` (str | None, default None)
- ``billboard`` (bool, default True)

A ``id`` field is also auto-generated when missing (``"ann_<8hex>"`` form
via :func:`secrets.token_hex(4)`).

The :class:`AnnotationDict` TypedDict uses ``total=False`` so every field
is optional -- legacy 4-field annotations (``{label, title, text, pos}``)
continue to validate, and the :func:`upgrade_annotation` helper fills
defaults at read time without mutating the input.

These tests lock the contract BEFORE Phase 5 ships the JS-side renderer
+ editor; the Python-side schema is the source of truth.
"""

from __future__ import annotations

import json
from collections import Counter

from splatpipe.core.path_io import AnnotationDict, upgrade_annotation


# ---- legacy backwards-compat ----------------------------------------------


def test_upgrade_annotation_legacy_adds_all_new_fields():
    """A legacy 4-field annotation gets every new field with its default."""
    legacy = {
        "label": "1",
        "title": "Detail view",
        "text": "Body copy here.",
        "pos": [1.0, 2.0, 3.0],
    }
    out = upgrade_annotation(legacy)
    assert out["kind"] == "dot_unfold"
    assert out["unfold_radius_m"] == 5.0
    assert out["t_in"] == 0.0
    assert out["t_out"] == 999.0
    assert out["fade_ms"] == 300
    assert out["media_url"] is None
    assert out["billboard"] is True
    # Legacy fields preserved verbatim
    assert out["label"] == "1"
    assert out["title"] == "Detail view"
    assert out["text"] == "Body copy here."
    assert out["pos"] == [1.0, 2.0, 3.0]
    # id auto-generated
    assert out["id"].startswith("ann_")


def test_upgrade_annotation_legacy_minimal_pos_only():
    """An annotation with only ``pos`` (the editor's "click-to-place" minimum)
    still upgrades cleanly -- no field is required."""
    legacy = {"pos": [0.0, 0.0, 0.0]}
    out = upgrade_annotation(legacy)
    assert out["kind"] == "dot_unfold"
    assert out["unfold_radius_m"] == 5.0
    assert out["t_in"] == 0.0
    assert out["t_out"] == 999.0
    assert out["fade_ms"] == 300
    assert out["media_url"] is None
    assert out["billboard"] is True
    assert out["pos"] == [0.0, 0.0, 0.0]
    assert out["id"].startswith("ann_")


# ---- idempotency ----------------------------------------------------------


def test_upgrade_annotation_idempotent_preserves_existing_values():
    """An already-upgraded annotation passes through with all values preserved."""
    upgraded = {
        "id": "ann_abc12345",
        "kind": "title3d_overlay",
        "label": "2",
        "title": "Bamboo detail",
        "text": "Hand-cut.",
        "pos": [4.0, 5.0, 6.0],
        "unfold_radius_m": 3.0,
        "t_in": 5.0,
        "t_out": 15.0,
        "fade_ms": 500,
        "media_url": "https://example.com/img.jpg",
        "billboard": False,
    }
    out = upgrade_annotation(upgraded)
    for key, expected in upgraded.items():
        assert out[key] == expected, f"{key} drifted: {out[key]!r} != {expected!r}"


def test_upgrade_annotation_idempotent_twice():
    """upgrade_annotation(upgrade_annotation(x)) == upgrade_annotation(x) -- a
    second pass adds no new keys and does not overwrite the auto-generated id."""
    legacy = {"label": "1", "title": "t", "text": "x", "pos": [0, 0, 0]}
    once = upgrade_annotation(legacy)
    twice = upgrade_annotation(once)
    assert once == twice
    assert once["id"] == twice["id"]  # id preserved across the second pass


# ---- non-mutation ---------------------------------------------------------


def test_upgrade_annotation_does_not_mutate_input():
    """upgrade_annotation returns a NEW dict and leaves the input untouched
    (callers in routes/projects.py may pass the persisted entry directly)."""
    legacy = {"label": "1", "title": "t", "text": "x", "pos": [1.0, 2.0, 3.0]}
    snapshot = dict(legacy)
    snapshot_pos = list(legacy["pos"])
    _ = upgrade_annotation(legacy)
    assert legacy == snapshot
    assert legacy["pos"] == snapshot_pos
    # No upgrade keys leak back into the input
    assert "kind" not in legacy
    assert "unfold_radius_m" not in legacy
    assert "id" not in legacy


# ---- defaults -------------------------------------------------------------


def test_upgrade_annotation_kind_default_is_dot_unfold():
    """Per Q6: dot_unfold is the new default for legacy / no-kind entries."""
    out = upgrade_annotation({"pos": [0, 0, 0]})
    assert out["kind"] == "dot_unfold"


def test_upgrade_annotation_unfold_radius_default_is_5m():
    """Per Q6: 5.0 m is the unfold-radius default."""
    out = upgrade_annotation({"pos": [0, 0, 0]})
    assert out["unfold_radius_m"] == 5.0


def test_upgrade_annotation_t_out_default_is_999_seconds_always_on():
    """Per Q6: 999.0 s = "always-on" so legacy entries stay visible through
    any reasonable tour length without re-authoring."""
    out = upgrade_annotation({"pos": [0, 0, 0]})
    assert out["t_in"] == 0.0
    assert out["t_out"] == 999.0


def test_upgrade_annotation_billboard_default_is_true():
    """Per Q6: dot_unfold always faces the camera by default."""
    out = upgrade_annotation({"pos": [0, 0, 0]})
    assert out["billboard"] is True


def test_upgrade_annotation_media_url_default_is_none():
    """media_url defaults to None (no optional media); when present it's a URL str."""
    out = upgrade_annotation({"pos": [0, 0, 0]})
    assert out["media_url"] is None


def test_upgrade_annotation_kind_title3d_overlay_preserved():
    """The alternative ``kind="title3d_overlay"`` value passes through verbatim."""
    out = upgrade_annotation({"pos": [0, 0, 0], "kind": "title3d_overlay"})
    assert out["kind"] == "title3d_overlay"


# ---- id generation --------------------------------------------------------


def test_upgrade_annotation_generates_unique_ids_across_many_calls():
    """Auto-generated ids must not collide under bulk creation. We do
    1000 fresh upgrades and assert every id appears exactly once."""
    ids = [upgrade_annotation({"pos": [0, 0, 0]})["id"] for _ in range(1000)]
    counter = Counter(ids)
    duplicates = {i: c for i, c in counter.items() if c > 1}
    assert not duplicates, f"id collisions: {duplicates}"


def test_upgrade_annotation_id_format():
    """The auto-generated id is ``ann_<8 lowercase hex>`` (8 hex chars from
    secrets.token_hex(4))."""
    import re
    out = upgrade_annotation({"pos": [0, 0, 0]})
    assert re.match(r"^ann_[0-9a-f]{8}$", out["id"]), f"unexpected id: {out['id']!r}"


def test_upgrade_annotation_preserves_existing_id():
    """A caller-supplied id (e.g. the legacy ``a1`` / ``a2`` migration ids
    from project.py) is never overwritten."""
    out = upgrade_annotation({"id": "a1", "pos": [0, 0, 0]})
    assert out["id"] == "a1"


# ---- JSON round-trip ------------------------------------------------------


def test_upgrade_annotation_json_round_trip_preserves_all_fields():
    """The expanded schema serialises and deserialises through JSON without
    field loss -- the wire format for viewer-config.json is plain JSON."""
    upgraded = upgrade_annotation({
        "label": "1",
        "title": "Bamboo detail",
        "text": "Hand-cut bamboo, 1.2 m tall.",
        "pos": [4.5, 1.2, -3.7],
        "kind": "dot_unfold",
        "unfold_radius_m": 3.0,
        "t_in": 5.0,
        "t_out": 15.0,
        "fade_ms": 500,
        "media_url": "https://cdn.example.com/bamboo.jpg",
        "billboard": True,
    })
    blob = json.dumps(upgraded)
    decoded = json.loads(blob)
    assert decoded == upgraded


# ---- TypedDict structural acceptance -------------------------------------


def test_annotation_dict_accepts_legacy_4_field_combination():
    """The TypedDict admits a legacy 4-field entry at runtime (TypedDict is
    erased at runtime; this is structural-only -- but the assertion locks
    that the import is healthy and the schema does not require new fields)."""
    legacy: AnnotationDict = {  # type: ignore[typeddict-item]
        "label": "1",
        "title": "t",
        "text": "x",
        "pos": [0.0, 0.0, 0.0],
    }
    assert legacy["label"] == "1"


def test_annotation_dict_accepts_full_expanded_combination():
    """The TypedDict admits the FULL expanded entry without runtime error."""
    full: AnnotationDict = {  # type: ignore[typeddict-item]
        "id": "ann_deadbeef",
        "kind": "dot_unfold",
        "label": "2",
        "title": "Bamboo detail",
        "text": "Hand-cut bamboo.",
        "pos": [4.5, 1.2, -3.7],
        "unfold_radius_m": 3.0,
        "t_in": 5.0,
        "t_out": 15.0,
        "fade_ms": 500,
        "media_url": "https://example.com/img.jpg",
        "billboard": True,
    }
    assert full["kind"] == "dot_unfold"
    assert full["unfold_radius_m"] == 3.0
