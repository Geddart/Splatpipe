"""Binary COLMAP parsers and text writers.

Binary format is the default COLMAP export from RealityCapture and other tools.
These parsers are streaming generators matching the same dict format as the
text parsers in parsers.py.  Uses `struct` only (no external deps).

Reference: https://colmap.github.io/format.html#binary-file-format
"""

import struct
from pathlib import Path
from typing import Generator

# Camera model ID → (name, num_params)
CAMERA_MODELS = {
    0: ("SIMPLE_PINHOLE", 3),
    1: ("PINHOLE", 4),
    2: ("SIMPLE_RADIAL", 4),
    3: ("RADIAL", 5),
    4: ("OPENCV", 8),
    5: ("OPENCV_FISHEYE", 8),
    6: ("FULL_OPENCV", 12),
    7: ("FOV", 5),
    8: ("SIMPLE_RADIAL_FISHEYE", 4),
    9: ("RADIAL_FISHEYE", 5),
    10: ("THIN_PRISM_FISHEYE", 12),
}


def parse_cameras_bin(path: str | Path) -> Generator[dict, None, None]:
    """Parse cameras.bin, yield one camera dict per entry.

    Yields same keys as parse_cameras_txt:
        {"camera_id": int, "model": str, "width": int, "height": int, "params": list[float]}
    """
    with open(path, "rb") as f:
        num_cameras = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num_cameras):
            camera_id = struct.unpack("<I", f.read(4))[0]
            model_id = struct.unpack("<i", f.read(4))[0]
            width = struct.unpack("<Q", f.read(8))[0]
            height = struct.unpack("<Q", f.read(8))[0]
            model_name, num_params = CAMERA_MODELS.get(model_id, (f"UNKNOWN_{model_id}", 0))
            params = list(struct.unpack(f"<{num_params}d", f.read(num_params * 8)))
            yield {
                "camera_id": camera_id,
                "model": model_name,
                "width": width,
                "height": height,
                "params": params,
            }


def parse_images_bin(path: str | Path) -> Generator[dict, None, None]:
    """Parse images.bin, yield one image dict per entry.

    Yields same keys as parse_images_txt (minus pose_line/points2d_line which
    are text-format only):
        {"image_id", "qw", "qx", "qy", "qz", "tx", "ty", "tz",
         "camera_id", "name", "points2d": [{"x", "y", "point3d_id"}]}
    """
    with open(path, "rb") as f:
        num_images = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num_images):
            image_id = struct.unpack("<I", f.read(4))[0]
            qw, qx, qy, qz = struct.unpack("<4d", f.read(32))
            tx, ty, tz = struct.unpack("<3d", f.read(24))
            camera_id = struct.unpack("<I", f.read(4))[0]
            # Read null-terminated name
            name_bytes = b""
            while True:
                c = f.read(1)
                if c == b"\x00" or not c:
                    break
                name_bytes += c
            name = name_bytes.decode("utf-8")
            # Read POINTS2D
            num_points2d = struct.unpack("<Q", f.read(8))[0]
            points2d = []
            for _ in range(num_points2d):
                x, y = struct.unpack("<2d", f.read(16))
                point3d_id = struct.unpack("<q", f.read(8))[0]  # signed int64
                points2d.append({"x": x, "y": y, "point3d_id": point3d_id})
            yield {
                "image_id": image_id,
                "qw": qw, "qx": qx, "qy": qy, "qz": qz,
                "tx": tx, "ty": ty, "tz": tz,
                "camera_id": camera_id,
                "name": name,
                "points2d": points2d,
            }


def parse_points3d_bin(path: str | Path) -> Generator[dict, None, None]:
    """Parse points3D.bin, yield one point dict per entry.

    Yields same keys as parse_points3d_txt (minus "line" which is text-format only):
        {"point3d_id", "x", "y", "z", "r", "g", "b", "error",
         "track": [{"image_id", "point2d_idx"}]}
    """
    with open(path, "rb") as f:
        num_points = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num_points):
            point3d_id = struct.unpack("<Q", f.read(8))[0]
            x, y, z = struct.unpack("<3d", f.read(24))
            r, g, b = struct.unpack("<3B", f.read(3))
            error = struct.unpack("<d", f.read(8))[0]
            track_length = struct.unpack("<Q", f.read(8))[0]
            track = []
            for _ in range(track_length):
                image_id = struct.unpack("<I", f.read(4))[0]
                point2d_idx = struct.unpack("<I", f.read(4))[0]
                track.append({"image_id": image_id, "point2d_idx": point2d_idx})
            yield {
                "point3d_id": point3d_id,
                "x": x, "y": y, "z": z,
                "r": r, "g": g, "b": b,
                "error": error,
                "track": track,
            }


# ── Text writers (for binary → text conversion) ─────────────────


def write_cameras_txt(cameras_iter, output_path: str | Path) -> int:
    """Write cameras iterable to COLMAP text format. Returns count written."""
    with open(output_path, "w") as f:
        f.write("# Camera list with one line of data per camera:\n")
        f.write("#   CAMERA_ID, MODEL, WIDTH, HEIGHT, PARAMS[]\n")
        count = 0
        for cam in cameras_iter:
            params_str = " ".join(str(p) for p in cam["params"])
            f.write(f"{cam['camera_id']} {cam['model']} {cam['width']} {cam['height']} {params_str}\n")
            count += 1
    return count


def write_images_txt(images_iter, output_path: str | Path) -> int:
    """Write images iterable to COLMAP text format. Returns count written."""
    with open(output_path, "w") as f:
        f.write("# Image list with two lines of data per image:\n")
        f.write("#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n")
        f.write("#   POINTS2D[] as (X, Y, POINT3D_ID)\n")
        count = 0
        for img in images_iter:
            f.write(f"{img['image_id']} {img['qw']} {img['qx']} {img['qy']} {img['qz']} "
                    f"{img['tx']} {img['ty']} {img['tz']} {img['camera_id']} {img['name']}\n")
            pts = " ".join(f"{p['x']} {p['y']} {p['point3d_id']}" for p in img["points2d"])
            f.write(f"{pts}\n")
            count += 1
    return count


def write_points3d_txt(points_iter, output_path: str | Path) -> int:
    """Write points3D iterable to COLMAP text format. Returns count written."""
    with open(output_path, "w") as f:
        f.write("# 3D point list with one line of data per point:\n")
        f.write("#   POINT3D_ID, X, Y, Z, R, G, B, ERROR, TRACK[] as (IMAGE_ID, POINT2D_IDX)\n")
        count = 0
        for pt in points_iter:
            track_str = " ".join(f"{t['image_id']} {t['point2d_idx']}" for t in pt["track"])
            f.write(f"{pt['point3d_id']} {pt['x']} {pt['y']} {pt['z']} "
                    f"{pt['r']} {pt['g']} {pt['b']} {pt['error']} {track_str}\n")
            count += 1
    return count


# ── Convenience ──────────────────────────────────────────────────


def convert_colmap_bin_to_txt(colmap_dir: str | Path, output_dir: str | Path) -> None:
    """Convert all three binary COLMAP files to text format."""
    colmap_dir = Path(colmap_dir)
    output_dir = Path(output_dir)
    write_cameras_txt(parse_cameras_bin(colmap_dir / "cameras.bin"), output_dir / "cameras.txt")
    write_images_txt(parse_images_bin(colmap_dir / "images.bin"), output_dir / "images.txt")
    write_points3d_txt(parse_points3d_bin(colmap_dir / "points3D.bin"), output_dir / "points3D.txt")
