import pytest
from splatpipe.core.scene_cuts import validate_clips, ordered_clips, validate_titles, DEFAULT_INTRO

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

def test_validate_titles_accepts_valid_and_rejects_bad_span():
    validate_titles([{"text": "Hi", "pos": [0, 0, 0], "t_in": 1.0, "t_out": 3.0}])  # ok
    with pytest.raises(ValueError):  # t_in > t_out
        validate_titles([{"text": "Hi", "pos": [0, 0, 0], "t_in": 5.0, "t_out": 2.0}])
    with pytest.raises(ValueError):  # missing required field (text/pos)
        validate_titles([{"pos": [0, 0, 0], "t_in": 0.0, "t_out": 1.0}])
