from splatpipe.core.path_io import new_path, KeyframeDict, VALID_INTERP  # noqa: F401


def test_valid_interp_constant():
    assert VALID_INTERP == ("auto_clamped", "automatic", "linear", "bezier", "stepped")


def test_keyframe_without_interp_is_valid_and_omitted():
    p = new_path("t", keyframes=[{"t": 0.0, "pos": [0, 0, 0], "quat": [0, 0, 0, 1]}])
    assert "interp" not in p["keyframes"][0]   # absent => global smoothness (back-compat)
