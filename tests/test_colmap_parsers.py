"""Tests for streaming COLMAP parsers."""



from splatpipe.colmap.parsers import (
    parse_cameras_txt,
    parse_images_txt,
    parse_points3d_txt,
    count_cameras,
    count_images,
    count_points3d,
    stream_comment_lines,
)


def test_parse_cameras_txt(tiny_cameras_path):
    """Verify camera model, params, count."""
    cameras = list(parse_cameras_txt(tiny_cameras_path))
    assert len(cameras) == 3

    cam = cameras[0]
    assert cam["camera_id"] == 1
    assert cam["model"] == "RADIAL"
    assert cam["width"] == 4000
    assert cam["height"] == 3000
    assert cam["params"][0] == 3500.0  # focal length
    assert len(cam["params"]) == 5


def test_parse_images_txt_streaming(tiny_images_path):
    """Verify paired-line parsing (pose + POINTS2D)."""
    images = list(parse_images_txt(tiny_images_path))
    assert len(images) == 5

    # First image
    img = images[0]
    assert img["image_id"] == 1
    assert img["name"] == "image001.jpg"
    assert abs(img["tx"] - (-0.8)) < 0.001
    assert abs(img["ty"] - 0.3) < 0.001
    assert abs(img["tz"] - 1.8) < 0.001
    assert img["camera_id"] == 1

    # POINTS2D parsing
    pts = img["points2d"]
    assert len(pts) == 5  # 5 triplets on line 6
    assert pts[0]["point3d_id"] == 5
    assert pts[2]["point3d_id"] == -1
    assert pts[3]["point3d_id"] == 999  # dangling ref

    # Outlier camera 4
    cam4 = images[3]
    assert cam4["name"] == "image004.jpg"
    assert abs(cam4["tx"] - 5000.0) < 0.001

    # Outlier camera 5
    cam5 = images[4]
    assert cam5["name"] == "image005.jpg"
    assert abs(cam5["tx"] - (-2000.0)) < 0.001


def test_parse_points3d_streaming(tiny_points3d_path):
    """Verify ID, XYZ, RGB, track extraction."""
    points = list(parse_points3d_txt(tiny_points3d_path))
    assert len(points) == 50

    pt = points[0]
    assert pt["point3d_id"] == 1
    assert abs(pt["x"] - (-1.234)) < 0.001
    assert abs(pt["y"] - 0.567) < 0.001
    assert abs(pt["z"] - 1.890) < 0.001
    assert pt["r"] == 128
    assert pt["g"] == 64
    assert pt["b"] == 192
    assert abs(pt["error"] - 0.521) < 0.001
    assert len(pt["track"]) == 2
    assert pt["track"][0] == {"image_id": 1, "point2d_idx": 0}


def test_comment_lines_preserved(tiny_cameras_path):
    """Comment lines are extracted correctly."""
    comments = stream_comment_lines(tiny_cameras_path)
    assert len(comments) == 3
    assert comments[0].startswith("# Camera list")


def test_count_cameras(tiny_cameras_path):
    assert count_cameras(tiny_cameras_path) == 3


def test_count_images(tiny_images_path):
    assert count_images(tiny_images_path) == 5


def test_count_points3d(tiny_points3d_path):
    assert count_points3d(tiny_points3d_path) == 50
