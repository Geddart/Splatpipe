"""Binary PLY reader for cleaned point clouds."""

from pathlib import Path

import numpy as np


def read_ply_header(f) -> tuple[int, list[str]]:
    """Read PLY header, return (vertex_count, header_lines)."""
    header_lines = []
    num_vertices = 0
    while True:
        raw = f.readline()
        if not raw:
            break  # EOF before end_header
        line = raw.decode("ascii").strip()
        header_lines.append(line)
        if line.startswith("element vertex"):
            num_vertices = int(line.split()[-1])
        if line == "end_header":
            break
    return num_vertices, header_lines


def read_binary_ply(ply_path: str | Path) -> np.ndarray:
    """Read a binary little-endian PLY with float x,y,z and uchar r,g,b.

    Returns structured numpy array with fields: x, y, z, r, g, b
    """
    ply_path = Path(ply_path)
    with open(ply_path, "rb") as f:
        num_vertices, header_lines = read_ply_header(f)

        # Determine vertex format from header properties
        props = []
        in_vertex = False
        for line in header_lines:
            if line.startswith("element vertex"):
                in_vertex = True
                continue
            if line.startswith("element ") and in_vertex:
                in_vertex = False
                continue
            if in_vertex and line.startswith("property"):
                props.append(line)

        # Build numpy dtype from properties
        dtype_map = {
            "float": "<f4", "float32": "<f4",
            "double": "<f8", "float64": "<f8",
            "uchar": "u1", "uint8": "u1",
            "char": "i1", "int8": "i1",
            "ushort": "<u2", "uint16": "<u2",
            "short": "<i2", "int16": "<i2",
            "uint": "<u4", "uint32": "<u4",
            "int": "<i4", "int32": "<i4",
        }

        dt_fields = []
        for prop in props:
            parts = prop.split()
            # "property <type> <name>"
            ptype = parts[1]
            pname = parts[2]
            if ptype not in dtype_map:
                raise ValueError(f"Unknown PLY property type: {ptype}")
            dt_fields.append((pname, dtype_map[ptype]))

        dt = np.dtype(dt_fields)
        data = f.read(num_vertices * dt.itemsize)

    vertices = np.frombuffer(data, dtype=dt, count=num_vertices)
    return vertices


def ply_vertices_to_colmap_coords(vertices: np.ndarray,
                                   transform: tuple[int, ...] = (1, 0, 0, 0, 0, -1, 0, 1, 0)
                                   ) -> np.ndarray:
    """Transform PLY vertices (Z-up) to COLMAP coordinates (Y-down, Z-forward).

    Default transform matrix (row-major 3x3):
        [1,  0, 0]     X_colmap =  X_ply
        [0,  0,-1]  => Y_colmap = -Z_ply
        [0,  1, 0]     Z_colmap =  Y_ply

    Returns Nx3 float64 array in COLMAP coordinate space.
    """
    px = vertices["x"].astype(np.float64)
    py = vertices["y"].astype(np.float64)
    pz = vertices["z"].astype(np.float64)

    mat = np.array(transform, dtype=np.float64).reshape(3, 3)
    ply_coords = np.column_stack([px, py, pz])
    colmap_coords = ply_coords @ mat.T

    return colmap_coords
