"""Tests for binary PLY reader."""

import struct


from splatpipe.colmap.ply_io import read_binary_ply, ply_vertices_to_colmap_coords


def test_read_binary_ply(tiny_ply_path):
    """Read tiny PLY, verify vertex count and coordinate types."""
    vertices = read_binary_ply(tiny_ply_path)
    assert len(vertices) == 20
    assert "x" in vertices.dtype.names
    assert "y" in vertices.dtype.names
    assert "z" in vertices.dtype.names
    assert "red" in vertices.dtype.names
    assert "green" in vertices.dtype.names
    assert "blue" in vertices.dtype.names


def test_ply_coordinates(tiny_ply_path):
    """Verify PLY coordinates match expected values."""
    vertices = read_binary_ply(tiny_ply_path)
    # First vertex should be PLY transform of COLMAP(-1.234, 0.567, 1.890)
    # PLY(X,Y,Z) = (COLMAP_X, COLMAP_Z, -COLMAP_Y)
    # PLY = (-1.234, 1.890, -0.567)
    assert abs(vertices["x"][0] - (-1.234)) < 0.001
    assert abs(vertices["y"][0] - 1.890) < 0.001
    assert abs(vertices["z"][0] - (-0.567)) < 0.001


def test_ply_to_colmap_transform(tiny_ply_path):
    """Verify PLY->COLMAP coordinate transform roundtrips."""
    vertices = read_binary_ply(tiny_ply_path)
    colmap_coords = ply_vertices_to_colmap_coords(vertices)

    # First vertex in COLMAP space should be (-1.234, 0.567, 1.890)
    assert abs(colmap_coords[0, 0] - (-1.234)) < 0.001
    assert abs(colmap_coords[0, 1] - 0.567) < 0.001
    assert abs(colmap_coords[0, 2] - 1.890) < 0.001


def test_ply_header_parsing(tmp_path):
    """Various PLY headers: with normals, extra properties."""
    # PLY with normals
    ply_path = tmp_path / "normals.ply"
    with open(ply_path, "wb") as f:
        header = (
            "ply\n"
            "format binary_little_endian 1.0\n"
            "element vertex 2\n"
            "property float x\n"
            "property float y\n"
            "property float z\n"
            "property float nx\n"
            "property float ny\n"
            "property float nz\n"
            "property uchar red\n"
            "property uchar green\n"
            "property uchar blue\n"
            "end_header\n"
        )
        f.write(header.encode("ascii"))
        for i in range(2):
            f.write(struct.pack("<ffffffBBB",
                                float(i), float(i + 1), float(i + 2),
                                0.0, 0.0, 1.0,
                                128, 128, 128))

    vertices = read_binary_ply(ply_path)
    assert len(vertices) == 2
    assert "nx" in vertices.dtype.names
    assert abs(vertices["x"][0] - 0.0) < 0.001
    assert abs(vertices["x"][1] - 1.0) < 0.001
