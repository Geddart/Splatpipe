"""Oracle tests for the shared camera-scope merge core.

This is the single source of truth / cross-check oracle: the
``set-start-view`` CLI relay and every future HTTP save adapter (the
keyframe-editor save path) merge an untrusted patch onto a project's
``viewer-config.json`` through ``merge_camera_scope``. The locked,
security-critical invariant is that the patch can NEVER move the Bunny
``primary_asset`` pointer (that is the "Speicher-blank" production-failure
class). These tests pin the contract before — and forever after — the
inline merge in ``set_start_view_cmd.py`` was extracted here.
"""

import copy

import pytest

from splatpipe.core.config_merge import ALLOWED_PATCH_KEYS, merge_camera_scope


def test_allow_list_is_exactly_the_locked_keys():
    """Locked set: 9 v1 keys + ``panorama_backdrop`` (spec §3.2 + §5.2)
    + ``postprocessing`` (spec §3.5 / §4.X -- PostFXModule Phase 4)
    + ``audio`` (spec §4.4 -- AudioModule Phase 7).

    ``schema_version`` is INTENTIONALLY excluded -- it is server-managed
    publish-time, never patched. See ``test_config_merge_panorama.py``."""
    assert ALLOWED_PATCH_KEYS == {
        "start_view", "camera_paths", "clips", "cameras",
        "default_path_id", "intro", "titles3d", "spark_render", "annotations",
        "panorama_backdrop",
        "postprocessing",
        "audio",
    }


def test_primary_asset_is_force_kept_and_patch_pointer_is_never_applied():
    existing = {
        "primary_asset": "bKEEP/scene.rad",
        "start_view": {"pos": [1, 2, 3]},
        "foo": "bar",
    }
    patch = {
        "camera_paths": [{"id": "p1", "keyframes": []}],
        "default_path_id": "p1",
        "primary_asset": "EVIL/attacker.rad",   # must NEVER be applied
    }
    out = merge_camera_scope(existing, patch)

    # the allowed camera-scope keys land
    assert out["camera_paths"] == [{"id": "p1", "keyframes": []}]
    assert out["default_path_id"] == "p1"
    # LOCKED INVARIANT: pointer is always existing's, never the patch's
    assert out["primary_asset"] == "bKEEP/scene.rad"
    # non-allow-listed existing keys preserved untouched
    assert out["start_view"] == {"pos": [1, 2, 3]}
    assert out["foo"] == "bar"


def test_inputs_are_not_mutated():
    existing = {"primary_asset": "bK/scene.rad", "start_view": {"pos": [0]}}
    patch = {"start_view": {"pos": [9, 9, 9]}, "camera_paths": [{"id": "p"}]}
    existing_snapshot = copy.deepcopy(existing)
    patch_snapshot = copy.deepcopy(patch)

    out = merge_camera_scope(existing, patch)

    assert existing == existing_snapshot, "merge mutated `existing`"
    assert patch == patch_snapshot, "merge mutated `patch`"
    # and the result is a distinct object (deep-copy based)
    assert out is not existing
    out["start_view"]["pos"].append(123)
    assert existing == existing_snapshot, "result aliases `existing`'s nested data"
    assert patch == patch_snapshot, "result aliases `patch`'s nested data"


def test_shallow_replace_semantics_match_set_start_view():
    """Extracted semantics: an allowed key is *replaced* wholesale
    (``cfg[key] = patch[key]``), not deep-merged — exactly what
    set_start_view_cmd.py did with ``cfg["start_view"] = start_view``.
    """
    existing = {
        "primary_asset": "bK/s.rad",
        "start_view": {"pos": [1, 1, 1], "fov": 60, "extra": "old"},
    }
    patch = {"start_view": {"pos": [2, 2, 2]}}   # no "fov"/"extra"
    out = merge_camera_scope(existing, patch)
    # whole-key replace: the stale sub-keys are gone, not merged in
    assert out["start_view"] == {"pos": [2, 2, 2]}


def test_empty_patch_returns_equivalent_of_existing():
    existing = {
        "primary_asset": "bK/s.rad",
        "start_view": {"pos": [1]},
        "spark_render": {"clip_xy": 1.4},
        "unrelated": 42,
    }
    out = merge_camera_scope(existing, {})
    assert out == existing
    assert out is not existing


def test_patch_with_only_disallowed_keys_is_a_noop_over_existing():
    existing = {"primary_asset": "bK/s.rad", "start_view": {"pos": [1]}}
    patch = {
        "primary_asset": "EVIL/x.rad",
        "index.html": "<script>evil</script>",
        "splat_budget": 999_999_999,            # not in the 9-key allow-list
        "arbitrary": True,
    }
    out = merge_camera_scope(existing, patch)
    assert out == existing
    assert out["primary_asset"] == "bK/s.rad"
    assert "index.html" not in out
    assert "splat_budget" not in out
    assert "arbitrary" not in out


def test_idempotent_same_input_identical_output():
    existing = {
        "primary_asset": "bKEEP/scene.rad",
        "start_view": {"pos": [3, 4, 5]},
        "annotations": [{"id": "a1"}],
        "keep_me": {"nested": [1, 2]},
    }
    patch = {
        "camera_paths": [{"id": "p1"}],
        "annotations": [{"id": "a2"}, {"id": "a3"}],
        "primary_asset": "EVIL",
    }
    first = merge_camera_scope(existing, patch)
    second = merge_camera_scope(existing, patch)
    assert first == second
    # feeding the merged result back through an empty patch is a fixed point
    assert merge_camera_scope(first, {}) == first
    # re-applying the same patch to the merged result changes nothing
    assert merge_camera_scope(first, patch) == first


def test_all_nine_allowed_keys_are_applied():
    existing = {"primary_asset": "bK/s.rad", "preexisting": "x"}
    # primary_asset is intentionally absent from patch — it is NOT in
    # ALLOWED_PATCH_KEYS and the force-keep invariant is tested separately
    # (see test_primary_asset_is_force_kept...).
    patch = {
        "start_view": {"pos": [0]},
        "camera_paths": [{"id": "p"}],
        "clips": [{"id": "c"}],
        "cameras": [{"id": "cam"}],
        "default_path_id": "p",
        "intro": {"type": "fade", "ms": 900},
        "titles3d": [{"text": "T", "pos": [0, 0, 0]}],
        "spark_render": {"clip_xy": 3.0},
        "annotations": [{"id": "an"}],
    }
    out = merge_camera_scope(existing, patch)
    for k, v in patch.items():
        assert out[k] == v
    assert out["primary_asset"] == "bK/s.rad"
    assert out["preexisting"] == "x"


def test_multicamera_create_patch_whole_replaces_and_keeps_primary_asset():
    """v2-C Phase 2 "+ Create camera": the in-viewer create
    affordance grows ``camera_paths`` to >=2 (the new one with an
    EMPTY ``keyframes: []``), adds a parallel ``cameras``
    ``{id,name,path_id}`` list, and re-points ``default_path_id`` at
    the created path -- then Save sends that as the patch. This LOCKS
    that the UNCHANGED ``merge_camera_scope`` whole-replaces all
    three multi-entry keys (NOT a deep/append merge -- a created
    camera that vanished or duplicated on save would be a real
    regression) while the security-critical ``primary_asset``
    force-keep (the Speicher-blank production-failure class) still
    holds against a hostile pointer in the SAME patch. Proof the
    Phase-2 create flow needed ZERO core change."""
    existing = {
        "primary_asset": "bSPEICHER/scene.rad",
        # a pre-existing single camera + its path (the scene before
        # the author pressed "+ Create camera")
        "camera_paths": [{"id": "p_orig000001", "name": "Camera 1",
                          "keyframes": [{"t": 0.0, "pos": [0, 0, 0]}]}],
        "cameras": [{"id": "p_camorig001", "name": "Camera 1",
                     "path_id": "p_orig000001"}],
        "default_path_id": "p_orig000001",
        "spark_render": {"clip_xy": 3.0},
    }
    # The exact shape _camSelCreate emits: the original path PLUS a
    # freshly created one with EMPTY keyframes, a grown cameras list,
    # default_path_id moved to the created path -- and a hostile
    # primary_asset that must be ignored.
    patch = {
        "camera_paths": [
            {"id": "p_orig000001", "name": "Camera 1",
             "keyframes": [{"t": 0.0, "pos": [0, 0, 0]}]},
            {"id": "p_new0000001", "name": "Camera 2", "loop": False,
             "interpolation": "catmull", "smoothness": 1.0,
             "play_speed": 1.0, "keyframes": []},
        ],
        "cameras": [
            {"id": "p_camorig001", "name": "Camera 1",
             "path_id": "p_orig000001"},
            {"id": "p_camnew0001", "name": "Camera 2",
             "path_id": "p_new0000001"},
        ],
        "default_path_id": "p_new0000001",
        "primary_asset": "EVIL/attacker.rad",   # must NEVER apply
    }
    out = merge_camera_scope(existing, patch)

    # whole-replace (NOT append/deep-merge): exactly the patch's
    # two-entry lists, the 2nd path's empty keyframes preserved.
    assert out["camera_paths"] == patch["camera_paths"]
    assert len(out["camera_paths"]) == 2
    assert out["camera_paths"][1]["keyframes"] == []
    assert out["cameras"] == patch["cameras"]
    assert len(out["cameras"]) == 2
    # authored-selection persistence: default moved to the created
    # path (the EXISTING wire key, whole-replaced).
    assert out["default_path_id"] == "p_new0000001"
    # LOCKED INVARIANT: pointer is always existing's, never patch's.
    assert out["primary_asset"] == "bSPEICHER/scene.rad"
    # untouched siblings preserved.
    assert out["spark_render"] == {"clip_xy": 3.0}


def test_multicamera_rename_round_trips_through_merge():
    """v2-C Phase 2 REFINE "Rename": the in-viewer rename affordance
    mutates ``cameras[i].name`` AND the matching ``camera_paths[i].name``
    in place, then Save sends the patch through ``merge_camera_scope``.
    The UNCHANGED whole-replace semantics carry the new name through
    untouched (no codec change, no new wire key) -- this LOCKS that
    contract. The security-critical ``primary_asset`` force-keep still
    holds against a hostile pointer in the SAME patch. Proof the
    Phase-2 REFINE rename flow needed ZERO core change."""
    existing = {
        "primary_asset": "bSPEICHER/scene.rad",
        "camera_paths": [
            {"id": "p_orig000001", "name": "Camera 1",
             "keyframes": [{"t": 0.0, "pos": [0, 0, 0]}]},
            {"id": "p_orig000002", "name": "Camera 2",
             "keyframes": [{"t": 0.0, "pos": [1, 1, 1]}]},
        ],
        "cameras": [
            {"id": "p_camorig001", "name": "Camera 1",
             "path_id": "p_orig000001"},
            {"id": "p_camorig002", "name": "Camera 2",
             "path_id": "p_orig000002"},
        ],
        "default_path_id": "p_orig000001",
        "spark_render": {"clip_xy": 3.0},
    }
    # The exact shape _camSelRename emits: both cameras present but
    # the second one's name updated in BOTH cfg.cameras AND the
    # matching cameraPaths entry (same author UX -- rename in place).
    # The hostile primary_asset in the same patch must still be
    # ignored by the force-keep invariant.
    patch = {
        "camera_paths": [
            {"id": "p_orig000001", "name": "Camera 1",
             "keyframes": [{"t": 0.0, "pos": [0, 0, 0]}]},
            {"id": "p_orig000002", "name": "Hero",
             "keyframes": [{"t": 0.0, "pos": [1, 1, 1]}]},
        ],
        "cameras": [
            {"id": "p_camorig001", "name": "Camera 1",
             "path_id": "p_orig000001"},
            {"id": "p_camorig002", "name": "Hero",
             "path_id": "p_orig000002"},
        ],
        "default_path_id": "p_orig000001",
        "primary_asset": "EVIL/attacker.rad",   # must NEVER apply
    }
    out = merge_camera_scope(existing, patch)

    # whole-replace carries the renamed entries through unchanged.
    assert out["camera_paths"] == patch["camera_paths"]
    assert out["camera_paths"][1]["name"] == "Hero"
    assert out["cameras"] == patch["cameras"]
    assert out["cameras"][1]["name"] == "Hero"
    # untouched siblings preserved.
    assert out["default_path_id"] == "p_orig000001"
    assert out["spark_render"] == {"clip_xy": 3.0}
    # LOCKED INVARIANT: pointer is always existing's, never patch's.
    assert out["primary_asset"] == "bSPEICHER/scene.rad"


def test_multicamera_delete_camera_patch_removes_entry():
    """v2-C Phase 3 "Delete camera": the in-viewer kebab Delete action
    removes a camera from BOTH ``cfg.cameras`` AND its ``camera_paths``
    entry, then Save sends the surviving (N-1 entries) lists as the
    patch. The UNCHANGED whole-replace semantics of
    ``merge_camera_scope`` carry that delete through -- the result's
    ``cameras`` / ``camera_paths`` are EXACTLY the patch's (NOT a
    deep/append merge that would resurrect the deleted entry; that
    would be a real regression for delete UX). The security-critical
    ``primary_asset`` force-keep still holds against a hostile pointer
    in the SAME patch. Proof the Phase-3 delete flow needs ZERO core
    change -- same `Patch is the source of truth` contract as Create
    and Rename."""
    existing = {
        "primary_asset": "bSPEICHER/scene.rad",
        # a 2-camera scene -- the author is about to delete Camera 2
        "camera_paths": [
            {"id": "p_orig000001", "name": "Camera 1",
             "keyframes": [{"t": 0.0, "pos": [0, 0, 0]}]},
            {"id": "p_orig000002", "name": "Camera 2",
             "keyframes": [{"t": 0.0, "pos": [1, 1, 1]}]},
        ],
        "cameras": [
            {"id": "p_camorig001", "name": "Camera 1",
             "path_id": "p_orig000001"},
            {"id": "p_camorig002", "name": "Camera 2",
             "path_id": "p_orig000002"},
        ],
        "default_path_id": "p_orig000002",   # currently bound to soon-deleted cam
        "spark_render": {"clip_xy": 3.0},
    }
    # The EXACT patch shape the in-viewer _camSelDelete emits after the
    # user confirms deletion of Camera 2: both cameras + camera_paths
    # lists shrunk to one entry (the surviving Camera 1), and
    # default_path_id re-pointed at the surviving camera's path id
    # (current-camera fallback rule: if the deleted camera was
    # currently selected, fall back to the FIRST remaining camera).
    # The hostile primary_asset in the same patch MUST still be
    # ignored by the force-keep invariant.
    patch = {
        "camera_paths": [
            {"id": "p_orig000001", "name": "Camera 1",
             "keyframes": [{"t": 0.0, "pos": [0, 0, 0]}]},
        ],
        "cameras": [
            {"id": "p_camorig001", "name": "Camera 1",
             "path_id": "p_orig000001"},
        ],
        "default_path_id": "p_orig000001",
        "primary_asset": "EVIL/attacker.rad",   # must NEVER apply
    }
    out = merge_camera_scope(existing, patch)

    # WHOLE-REPLACE -- the deleted Camera 2 entries are absent from BOTH
    # lists. A deep/append merge would have left them in, which would
    # break the delete UX immediately (the dropdown rebuild on Save +
    # re-load would resurrect the camera).
    assert out["camera_paths"] == patch["camera_paths"]
    assert len(out["camera_paths"]) == 1
    assert out["camera_paths"][0]["id"] == "p_orig000001"
    assert out["cameras"] == patch["cameras"]
    assert len(out["cameras"]) == 1
    assert out["cameras"][0]["id"] == "p_camorig001"
    # No vestige of the deleted entries anywhere in the merged config
    for cp in out["camera_paths"]:
        assert cp["id"] != "p_orig000002"
    for cam in out["cameras"]:
        assert cam["id"] != "p_camorig002"
        assert cam["path_id"] != "p_orig000002"
    # Current-camera fallback: default_path_id moved to the surviving
    # camera's path id (EXISTING wire key, whole-replaced).
    assert out["default_path_id"] == "p_orig000001"
    # untouched siblings preserved.
    assert out["spark_render"] == {"clip_xy": 3.0}
    # LOCKED INVARIANT: pointer is always existing's, never patch's.
    assert out["primary_asset"] == "bSPEICHER/scene.rad"


def test_multicamera_delete_camera_patch_keeps_primary_asset_invariant():
    """Belt-and-braces: the Phase-3 delete flow must NEVER let a hostile
    ``primary_asset`` slip into the merged config -- including the
    scenario where the patch is a 0-camera ``cameras: []`` and a hostile
    pointer in the same envelope (a malicious editor trying to combine a
    delete-all-cameras patch with a redirected asset pointer). The
    locked Bunny invariant (force-keep ``existing.primary_asset``) does
    NOT depend on a survivor-count check -- the patch can be ANY shape
    and the pointer still stays the existing one. (The viewer-side
    last-camera guard prevents the empty-cameras patch from ever
    reaching Save in practice; this oracle ensures the core stays
    safe even if a future code path forgets that guard.)"""
    existing = {
        "primary_asset": "bSPEICHER/scene.rad",
        "camera_paths": [
            {"id": "p1", "name": "Solo", "keyframes": [{"t": 0.0, "pos": [0, 0, 0]}]},
        ],
        "cameras": [
            {"id": "cam1", "name": "Solo", "path_id": "p1"},
        ],
    }
    patch = {
        "camera_paths": [],
        "cameras": [],
        "default_path_id": None,
        "primary_asset": "EVIL/attacker.rad",   # MUST NEVER apply
    }
    out = merge_camera_scope(existing, patch)
    assert out["camera_paths"] == []
    assert out["cameras"] == []
    assert out["default_path_id"] is None
    assert out["primary_asset"] == "bSPEICHER/scene.rad"


def test_existing_without_primary_asset_does_not_synthesize_one():
    """Faithful extraction: set_start_view never *added* primary_asset; if
    the fetched config lacked it, it stayed absent (the older-deploy case).
    A patch still can't introduce it.
    """
    existing = {"start_view": {"pos": [1]}}
    patch = {"camera_paths": [{"id": "p"}], "primary_asset": "EVIL"}
    out = merge_camera_scope(existing, patch)
    assert "primary_asset" not in out
    assert out["camera_paths"] == [{"id": "p"}]
    assert out["start_view"] == {"pos": [1]}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
