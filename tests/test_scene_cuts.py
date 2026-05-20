import pytest
from splatpipe.core.scene_cuts import (
    DEFAULT_INTRO,
    find_clips_referencing_camera,
    ordered_clips,
    validate_clips,
    validate_titles,
)

def test_default_intro():
    assert DEFAULT_INTRO == {"type": "fade", "ms": 900}

def test_ordered_clips_sorts_and_validates():
    cams = [{"id": "a", "name": "A", "path_id": "p1"},
            {"id": "b", "name": "B", "path_id": "p2"}]
    clips = [{"id": "c2", "camera_id": "b", "clip_start": 5.0, "duration": 3.0, "in": 0.0},
             {"id": "c1", "camera_id": "a", "clip_start": 0.0, "duration": 5.0, "in": 0.0}]
    assert [c["id"] for c in ordered_clips(clips)] == ["c1", "c2"]
    validate_clips(cams, clips)  # must not raise

def test_validate_clips_rejects_unknown_camera_and_bad_span():
    with pytest.raises(ValueError):
        validate_clips([{"id": "a", "name": "A", "path_id": "p1"}],
                       [{"id": "x", "camera_id": "zzz", "clip_start": 0.0, "duration": 1.0, "in": 0.0}])
    with pytest.raises(ValueError):  # duration <= 0
        validate_clips([{"id": "a", "name": "A", "path_id": "p1"}],
                       [{"id": "x", "camera_id": "a", "clip_start": 0.0, "duration": 0.0, "in": 0.0}])
    with pytest.raises(ValueError):  # clip_start < 0
        validate_clips([{"id": "a", "name": "A", "path_id": "p1"}],
                       [{"id": "x", "camera_id": "a", "clip_start": -1.0, "duration": 1.0, "in": 0.0}])
    with pytest.raises(ValueError):  # in < 0
        validate_clips([{"id": "a", "name": "A", "path_id": "p1"}],
                       [{"id": "x", "camera_id": "a", "clip_start": 0.0, "duration": 1.0, "in": -0.5}])

def test_validate_clips_allows_missing_in_defaults_zero():
    validate_clips([{"id": "a", "name": "A", "path_id": "p1"}],
                   [{"id": "c1", "camera_id": "a", "clip_start": 0.0, "duration": 1.0}])  # no "in" key → ok

def test_clip_sequence_references_a_created_camera_id():
    """v2-C Phase 2 "+ Create camera": a camera created in the
    viewer carries a ``p_``-prefixed id (mirror of
    core/path_io.py::_new_id) and is registered as a
    ``{id,name,path_id}`` virtual camera. A later clip sequence may
    reference that created camera by id -- assert the UNCHANGED
    ``validate_clips`` / ``ordered_clips`` accept it exactly as any
    other camera (proof the created-camera id shape is a first-class
    citizen of the cuts contract; ZERO core change needed)."""
    cams = [
        {"id": "p_origcam001", "name": "Camera 1", "path_id": "p_origpath01"},
        # freshly created via "+ Create camera"
        {"id": "p_newcam0001", "name": "Camera 2", "path_id": "p_newpath001"},
    ]
    clips = [
        {"id": "c2", "camera_id": "p_newcam0001", "clip_start": 4.0,
         "duration": 3.0, "in": 0.0},
        {"id": "c1", "camera_id": "p_origcam001", "clip_start": 0.0,
         "duration": 4.0, "in": 0.0},
    ]
    assert [c["id"] for c in ordered_clips(clips)] == ["c1", "c2"]
    validate_clips(cams, clips)  # must not raise (created cam id is valid)
    # and an unknown id still rejected even amid created cameras
    with pytest.raises(ValueError):
        validate_clips(cams, [{"id": "x", "camera_id": "p_doesnotexist",
                               "clip_start": 0.0, "duration": 1.0, "in": 0.0}])


def test_validate_titles_accepts_valid_and_rejects_bad_span():
    validate_titles([{"text": "Hi", "pos": [0, 0, 0], "t_in": 1.0, "t_out": 3.0}])  # ok
    with pytest.raises(ValueError):  # t_in > t_out
        validate_titles([{"text": "Hi", "pos": [0, 0, 0], "t_in": 5.0, "t_out": 2.0}])
    with pytest.raises(ValueError):  # missing required field (text/pos)
        validate_titles([{"pos": [0, 0, 0], "t_in": 0.0, "t_out": 1.0}])


# ----------------------------------------------------------------------------
# v2-C Phase 3 -- ``find_clips_referencing_camera`` clip-reference guard
# ----------------------------------------------------------------------------
# The in-viewer "Delete camera" kebab action refuses deletion of any camera
# still bound to a clip in the cut sequence (so the cut timeline never points
# at a vanished camera id). The JS implementation walks ``cfg.clips`` looking
# for entries whose ``camera_id`` matches the to-delete id; this Python
# helper is the SAME walk -- single source of truth -- so the CLI / save
# adapters / the in-viewer guard agree byte-for-byte on what constitutes a
# blocker. Pure (no I/O), input never mutated.

def test_find_clips_referencing_camera_returns_matching_clips():
    """Positive case: the helper returns every clip whose ``camera_id``
    matches the to-delete id, preserving input order. A camera referenced
    by multiple clips returns all of them (the count is what the guard's
    alert reads as "referenced by N clips")."""
    clips = [
        {"id": "c1", "camera_id": "cam_a", "clip_start": 0.0, "duration": 2.0, "in": 0.0},
        {"id": "c2", "camera_id": "cam_b", "clip_start": 2.0, "duration": 1.5, "in": 0.0},
        {"id": "c3", "camera_id": "cam_a", "clip_start": 3.5, "duration": 2.5, "in": 0.0},
    ]
    refs = find_clips_referencing_camera({"clips": clips}, "cam_a")
    assert [c["id"] for c in refs] == ["c1", "c3"]
    # input list not mutated
    assert len(clips) == 3
    # single match still returns a list (NOT the bare clip)
    refs_b = find_clips_referencing_camera({"clips": clips}, "cam_b")
    assert isinstance(refs_b, list)
    assert [c["id"] for c in refs_b] == ["c2"]


def test_find_clips_referencing_camera_empty_when_none_match():
    """Negative case: an id with no clip references returns an empty
    list (the guard reads len==0 as "safe to delete" -- the cut-ref
    block is over, then the last-camera guard runs)."""
    clips = [
        {"id": "c1", "camera_id": "cam_a", "clip_start": 0.0, "duration": 2.0, "in": 0.0},
        {"id": "c2", "camera_id": "cam_b", "clip_start": 2.0, "duration": 1.5, "in": 0.0},
    ]
    refs = find_clips_referencing_camera({"clips": clips}, "cam_unused")
    assert refs == []


def test_find_clips_referencing_camera_handles_missing_clips_field():
    """The 6 live single-camera scenes carry NO ``cfg.clips`` field
    (degenerate single-tour case). The helper MUST treat a missing /
    non-list ``clips`` as "no references" (NOT raise) so an author who
    deletes a camera in a clips-free scene is never falsely blocked.
    Mirrors the JS guard's ``Array.isArray(cfg.clips) ? cfg.clips : []``
    pattern (the same one ``ClipPlayer`` already uses at template.py
    ~2979)."""
    # missing key entirely
    assert find_clips_referencing_camera({}, "cam_a") == []
    # null
    assert find_clips_referencing_camera({"clips": None}, "cam_a") == []
    # non-list (defensive)
    assert find_clips_referencing_camera({"clips": "not-a-list"}, "cam_a") == []
    # empty list
    assert find_clips_referencing_camera({"clips": []}, "cam_a") == []


def test_find_clips_referencing_camera_skips_malformed_entries():
    """Defensive: a clip lacking ``camera_id`` (corrupted scene config /
    half-authored entry) MUST NOT match any id and MUST NOT raise --
    skip it. Only clips with a present, equal ``camera_id`` match."""
    clips = [
        {"id": "c1", "camera_id": "cam_a", "clip_start": 0.0, "duration": 2.0, "in": 0.0},
        {"id": "c2", "clip_start": 2.0, "duration": 1.5, "in": 0.0},          # no camera_id
        None,                                                                  # bogus entry
        {"id": "c3", "camera_id": None, "clip_start": 3.5, "duration": 2.5},  # explicit null
    ]
    refs = find_clips_referencing_camera({"clips": clips}, "cam_a")
    assert [c["id"] for c in refs] == ["c1"]
    # malformed entries do not match an arbitrary missing id either
    assert find_clips_referencing_camera({"clips": clips}, "missing") == []
