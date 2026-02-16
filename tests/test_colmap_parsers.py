"""Tests for streaming COLMAP parsers (text + binary) and format detection."""

import struct

from splatpipe.colmap.parsers import (
    parse_cameras_txt,
    parse_images_txt,
    parse_points3d_txt,
    count_cameras,
    count_images,
    count_points3d,
    stream_comment_lines,
    detect_colmap_format,
    detect_alignment_format,
    detect_source_type,
    ALIGNMENT_FORMAT_LABELS,
)
from splatpipe.colmap.parsers_bin import (
    parse_cameras_bin,
    parse_images_bin,
    parse_points3d_bin,
    convert_colmap_bin_to_txt,
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


# ── Binary parser helpers ────────────────────────────────────────


def _write_tiny_cameras_bin(path):
    """Write 2 cameras: SIMPLE_PINHOLE (model 0, 3 params) + PINHOLE (model 1, 4 params)."""
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", 2))  # num_cameras
        # Camera 1: SIMPLE_PINHOLE
        f.write(struct.pack("<I", 1))  # camera_id
        f.write(struct.pack("<i", 0))  # model_id = SIMPLE_PINHOLE
        f.write(struct.pack("<Q", 1920))  # width
        f.write(struct.pack("<Q", 1080))  # height
        f.write(struct.pack("<3d", 1500.0, 960.0, 540.0))  # f, cx, cy
        # Camera 2: PINHOLE
        f.write(struct.pack("<I", 2))
        f.write(struct.pack("<i", 1))  # model_id = PINHOLE
        f.write(struct.pack("<Q", 4000))
        f.write(struct.pack("<Q", 3000))
        f.write(struct.pack("<4d", 3500.0, 3500.0, 2000.0, 1500.0))  # fx, fy, cx, cy


def _write_tiny_images_bin(path, num_images=3):
    """Write N images with 2 POINTS2D each."""
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", num_images))
        for i in range(num_images):
            f.write(struct.pack("<I", i + 1))  # image_id
            f.write(struct.pack("<4d", 0.5, 0.5, 0.5, 0.5))  # qw, qx, qy, qz
            f.write(struct.pack("<3d", float(i), float(i * 2), float(i * 3)))  # tx, ty, tz
            f.write(struct.pack("<I", 1))  # camera_id
            name = f"img_{i:03d}.jpg".encode() + b"\x00"
            f.write(name)
            # 2 POINTS2D per image
            f.write(struct.pack("<Q", 2))
            f.write(struct.pack("<2d", 100.0, 200.0))  # x, y
            f.write(struct.pack("<q", i * 10))  # point3d_id (signed)
            f.write(struct.pack("<2d", 300.0, 400.0))
            f.write(struct.pack("<q", -1))  # unmatched


def _write_tiny_points3d_bin(path, num_points=5):
    """Write N points with 1-entry tracks."""
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", num_points))
        for i in range(num_points):
            f.write(struct.pack("<Q", i + 1))  # point3d_id
            f.write(struct.pack("<3d", float(i), float(i + 1), float(i + 2)))  # x, y, z
            f.write(struct.pack("<3B", 128, 64, 32))  # r, g, b
            f.write(struct.pack("<d", 0.5))  # error
            f.write(struct.pack("<Q", 1))  # track_length
            f.write(struct.pack("<I", 1))  # image_id
            f.write(struct.pack("<I", i))  # point2d_idx


# ── Binary parser tests ──────────────────────────────────────────


def test_parse_cameras_bin(tmp_path):
    path = tmp_path / "cameras.bin"
    _write_tiny_cameras_bin(path)
    cameras = list(parse_cameras_bin(path))
    assert len(cameras) == 2
    assert cameras[0]["camera_id"] == 1
    assert cameras[0]["model"] == "SIMPLE_PINHOLE"
    assert cameras[0]["width"] == 1920
    assert cameras[0]["height"] == 1080
    assert len(cameras[0]["params"]) == 3
    assert cameras[0]["params"][0] == 1500.0
    assert cameras[1]["model"] == "PINHOLE"
    assert len(cameras[1]["params"]) == 4


def test_parse_images_bin(tmp_path):
    path = tmp_path / "images.bin"
    _write_tiny_images_bin(path, num_images=3)
    images = list(parse_images_bin(path))
    assert len(images) == 3
    assert images[0]["image_id"] == 1
    assert images[0]["name"] == "img_000.jpg"
    assert images[0]["camera_id"] == 1
    assert len(images[0]["points2d"]) == 2
    assert images[0]["points2d"][1]["point3d_id"] == -1  # unmatched
    assert images[2]["tx"] == 2.0
    assert images[2]["name"] == "img_002.jpg"


def test_parse_points3d_bin(tmp_path):
    path = tmp_path / "points3D.bin"
    _write_tiny_points3d_bin(path, num_points=5)
    points = list(parse_points3d_bin(path))
    assert len(points) == 5
    assert points[0]["point3d_id"] == 1
    assert points[0]["x"] == 0.0
    assert points[0]["r"] == 128
    assert points[0]["g"] == 64
    assert points[0]["b"] == 32
    assert points[0]["error"] == 0.5
    assert len(points[0]["track"]) == 1
    assert points[0]["track"][0] == {"image_id": 1, "point2d_idx": 0}


def test_convert_bin_to_txt_roundtrip(tmp_path):
    """Write binary files, convert to text, parse text, compare values."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_tiny_cameras_bin(bin_dir / "cameras.bin")
    _write_tiny_images_bin(bin_dir / "images.bin", num_images=3)
    _write_tiny_points3d_bin(bin_dir / "points3D.bin", num_points=5)

    txt_dir = tmp_path / "txt"
    txt_dir.mkdir()
    convert_colmap_bin_to_txt(bin_dir, txt_dir)

    # Parse text output and compare
    cameras = list(parse_cameras_txt(txt_dir / "cameras.txt"))
    assert len(cameras) == 2
    assert cameras[0]["camera_id"] == 1
    assert cameras[0]["model"] == "SIMPLE_PINHOLE"

    images = list(parse_images_txt(txt_dir / "images.txt"))
    assert len(images) == 3
    assert images[0]["name"] == "img_000.jpg"

    points = list(parse_points3d_txt(txt_dir / "points3D.txt"))
    assert len(points) == 5
    assert points[0]["point3d_id"] == 1


# ── Format detection tests ───────────────────────────────────────


def test_detect_colmap_format_text(tmp_path):
    for f in ("cameras.txt", "images.txt", "points3D.txt"):
        (tmp_path / f).touch()
    assert detect_colmap_format(tmp_path) == "text"


def test_detect_colmap_format_binary(tmp_path):
    for f in ("cameras.bin", "images.bin", "points3D.bin"):
        (tmp_path / f).touch()
    assert detect_colmap_format(tmp_path) == "binary"


def test_detect_colmap_format_unknown(tmp_path):
    assert detect_colmap_format(tmp_path) == "unknown"


def test_detect_alignment_format_colmap_text(tmp_path):
    for f in ("cameras.txt", "images.txt", "points3D.txt"):
        (tmp_path / f).touch()
    assert detect_alignment_format(tmp_path) == "colmap_text"


def test_detect_alignment_format_colmap_binary(tmp_path):
    for f in ("cameras.bin", "images.bin", "points3D.bin"):
        (tmp_path / f).touch()
    assert detect_alignment_format(tmp_path) == "colmap_binary"


def test_detect_alignment_format_bundler(tmp_path):
    (tmp_path / "bundle.out").touch()
    (tmp_path / "cloud.ply").touch()
    assert detect_alignment_format(tmp_path) == "bundler"


def test_detect_alignment_format_realityscan(tmp_path):
    (tmp_path / "registration.csv").touch()
    (tmp_path / "cloud.ply").touch()
    assert detect_alignment_format(tmp_path) == "realityscan"


def test_detect_alignment_format_blocksexchange(tmp_path):
    (tmp_path / "alignment.xml").touch()
    assert detect_alignment_format(tmp_path) == "blocksexchange"


def test_detect_alignment_format_unknown(tmp_path):
    (tmp_path / "random.dat").touch()
    assert detect_alignment_format(tmp_path) == "unknown"


def test_alignment_format_labels_complete():
    """All format strings have labels."""
    for fmt in ("colmap_text", "colmap_binary", "bundler", "realityscan", "blocksexchange", "unknown"):
        assert fmt in ALIGNMENT_FORMAT_LABELS


# ── Source type detection tests ─────────────────────────────────


def test_detect_source_type_psht_file(tmp_path):
    """detect_source_type returns 'postshot' for .psht files."""
    psht = tmp_path / "scene.psht"
    psht.write_bytes(b"fake psht data")
    assert detect_source_type(psht) == "postshot"


def test_detect_source_type_directory(tmp_path):
    """detect_source_type delegates to detect_alignment_format for directories."""
    (tmp_path / "cameras.txt").touch()
    (tmp_path / "images.txt").touch()
    (tmp_path / "points3D.txt").touch()
    assert detect_source_type(tmp_path) == "colmap_text"


def test_detect_source_type_unknown_file(tmp_path):
    """detect_source_type returns 'unknown' for non-.psht files."""
    f = tmp_path / "data.xyz"
    f.write_bytes(b"data")
    assert detect_source_type(f) == "unknown"
