"""Streaming parsers for COLMAP text files.

These parsers are generators that yield one record at a time,
keeping memory usage constant regardless of file size.
"""

from pathlib import Path
from typing import Generator


def parse_cameras_txt(path: str | Path) -> Generator[dict, None, None]:
    """Parse cameras.txt, yield one camera dict per line.

    Yields:
        {"camera_id": int, "model": str, "width": int, "height": int, "params": list[float]}
    """
    with open(path, "r") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            yield {
                "camera_id": int(parts[0]),
                "model": parts[1],
                "width": int(parts[2]),
                "height": int(parts[3]),
                "params": [float(p) for p in parts[4:]],
            }


def parse_images_txt(path: str | Path) -> Generator[dict, None, None]:
    """Parse images.txt, yield one image dict per paired lines.

    Yields:
        {
            "image_id": int, "qw": float, "qx": float, "qy": float, "qz": float,
            "tx": float, "ty": float, "tz": float, "camera_id": int, "name": str,
            "pose_line": str, "points2d_line": str,
            "points2d": list[{"x": float, "y": float, "point3d_id": int}]
        }
    """
    with open(path, "r") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) < 10:
                continue
            # Read POINTS2D line
            pts_line = next(f, "\n")
            pts_line_stripped = pts_line.strip()

            # Parse POINTS2D triplets
            points2d = []
            if pts_line_stripped:
                pts_parts = pts_line_stripped.split()
                if len(pts_parts) >= 3 and len(pts_parts) % 3 == 0:
                    for i in range(0, len(pts_parts), 3):
                        points2d.append({
                            "x": float(pts_parts[i]),
                            "y": float(pts_parts[i + 1]),
                            "point3d_id": int(pts_parts[i + 2]),
                        })

            yield {
                "image_id": int(parts[0]),
                "qw": float(parts[1]),
                "qx": float(parts[2]),
                "qy": float(parts[3]),
                "qz": float(parts[4]),
                "tx": float(parts[5]),
                "ty": float(parts[6]),
                "tz": float(parts[7]),
                "camera_id": int(parts[8]),
                "name": parts[9],
                "pose_line": line,
                "points2d_line": pts_line,
                "points2d": points2d,
            }


def parse_points3d_txt(path: str | Path) -> Generator[dict, None, None]:
    """Parse points3D.txt, yield one point dict per line.

    Yields:
        {
            "point3d_id": int, "x": float, "y": float, "z": float,
            "r": int, "g": int, "b": int, "error": float,
            "track": list[{"image_id": int, "point2d_idx": int}],
            "line": str
        }
    """
    with open(path, "r") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) < 8:
                continue

            track = []
            for i in range(8, len(parts), 2):
                if i + 1 < len(parts):
                    track.append({
                        "image_id": int(parts[i]),
                        "point2d_idx": int(parts[i + 1]),
                    })

            yield {
                "point3d_id": int(parts[0]),
                "x": float(parts[1]),
                "y": float(parts[2]),
                "z": float(parts[3]),
                "r": int(parts[4]),
                "g": int(parts[5]),
                "b": int(parts[6]),
                "error": float(parts[7]),
                "track": track,
                "line": line,
            }


def count_cameras(path: str | Path) -> int:
    """Count cameras in cameras.txt without loading all data."""
    count = 0
    with open(path, "r") as f:
        for line in f:
            if not line.startswith("#") and line.strip():
                count += 1
    return count


def count_images(path: str | Path) -> int:
    """Count images in images.txt without loading all data."""
    count = 0
    with open(path, "r") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 10:
                count += 1
                next(f, None)  # skip POINTS2D line
    return count


def count_points3d(path: str | Path) -> int:
    """Count points in points3D.txt without loading all data."""
    count = 0
    with open(path, "r") as f:
        for line in f:
            if not line.startswith("#") and line.strip():
                count += 1
    return count


def stream_comment_lines(path: str | Path) -> list[str]:
    """Extract comment lines from a COLMAP text file."""
    comments = []
    with open(path, "r") as f:
        for line in f:
            if line.startswith("#"):
                comments.append(line)
            else:
                break
    return comments


# ── Format detection ─────────────────────────────────────────────


def detect_colmap_format(colmap_dir: Path) -> str:
    """Detect COLMAP data format in a directory.

    Returns: "text" | "binary" | "unknown"
    """
    txt_files = {"cameras.txt", "images.txt", "points3D.txt"}
    bin_files = {"cameras.bin", "images.bin", "points3D.bin"}

    if all((colmap_dir / f).exists() for f in txt_files):
        return "text"
    if all((colmap_dir / f).exists() for f in bin_files):
        return "binary"
    return "unknown"


def detect_alignment_format(data_dir: Path) -> str:
    """Detect alignment/pose format in a directory.

    Checks all formats Postshot supports:
    - "colmap_text": cameras.txt + images.txt + points3D.txt
    - "colmap_binary": cameras.bin + images.bin + points3D.bin
    - "bundler": *.out + *.ply
    - "realityscan": *.csv + *.ply
    - "blocksexchange": *.xml (BlocksExchange format)
    - "unknown": none of the above
    """
    colmap_fmt = detect_colmap_format(data_dir)
    if colmap_fmt == "text":
        return "colmap_text"
    if colmap_fmt == "binary":
        return "colmap_binary"

    exts = {f.suffix.lower() for f in data_dir.iterdir() if f.is_file()}

    if ".out" in exts and ".ply" in exts:
        return "bundler"

    if ".csv" in exts and ".ply" in exts:
        return "realityscan"

    if ".xml" in exts:
        return "blocksexchange"

    return "unknown"


def detect_source_type(path: Path) -> str:
    """Detect source type from a path (file or directory).

    Returns one of: "postshot", "colmap_text", "colmap_binary",
    "bundler", "realityscan", "blocksexchange", "unknown"
    """
    if path.is_file():
        if path.suffix.lower() == ".psht":
            return "postshot"
        return "unknown"
    if path.is_dir():
        return detect_alignment_format(path)
    return "unknown"


ALIGNMENT_FORMAT_LABELS = {
    "postshot": "Postshot (.psht)",
    "colmap_text": "COLMAP (text)",
    "colmap_binary": "COLMAP (binary)",
    "bundler": "Bundler",
    "realityscan": "RealityScan",
    "blocksexchange": "BlocksExchange XML",
    "unknown": "Unknown",
}
