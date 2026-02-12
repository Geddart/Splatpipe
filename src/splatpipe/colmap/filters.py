"""COLMAP cleaning filters: camera outlier removal, KD-tree point filtering, POINTS2D cleanup.

Refactored from fix_colmap_export.py, step1/step2/step3 scripts.
All functions are pure: they take paths in, write paths out, return structured stats.
No hardcoded paths. No try/except. Failures surface immediately.
"""

import statistics
import time
from pathlib import Path

from scipy.spatial import cKDTree

from .ply_io import read_binary_ply, ply_vertices_to_colmap_coords


def analyze_cameras(images_path: Path) -> dict:
    """Stream images.txt, return camera positions and outlier analysis.

    Returns dict with keys:
        cameras: list of (name, tx, ty, tz)
        median: (tx, ty, tz)
        outliers: list of (dist, name, tx, ty, tz)
        threshold: float
        ranges: dict with tx/ty/tz min/max/span
    """
    cameras = []
    with open(images_path, "r") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 10:
                name = parts[9]
                tx, ty, tz = float(parts[5]), float(parts[6]), float(parts[7])
                cameras.append((name, tx, ty, tz))
                next(f, None)

    txs = [c[1] for c in cameras]
    tys = [c[2] for c in cameras]
    tzs = [c[3] for c in cameras]
    med_tx = statistics.median(txs)
    med_ty = statistics.median(tys)
    med_tz = statistics.median(tzs)

    dists = []
    for name, tx, ty, tz in cameras:
        d = ((tx - med_tx) ** 2 + (ty - med_ty) ** 2 + (tz - med_tz) ** 2) ** 0.5
        dists.append((d, name, tx, ty, tz))
    dists.sort(reverse=True)

    sorted_d = sorted(d[0] for d in dists)
    p99 = sorted_d[int(len(sorted_d) * 0.99)]
    threshold = max(100.0, p99 * 2.5)

    outliers = [(d, n, tx, ty, tz) for d, n, tx, ty, tz in dists if d > threshold]

    return {
        "cameras": cameras,
        "median": {"tx": med_tx, "ty": med_ty, "tz": med_tz},
        "outliers": [
            {"name": n, "dist": d, "tx": tx, "ty": ty, "tz": tz}
            for d, n, tx, ty, tz in outliers
        ],
        "threshold": threshold,
        "total": len(cameras),
        "ranges": {
            "tx": {"min": min(txs), "max": max(txs), "span": max(txs) - min(txs)},
            "ty": {"min": min(tys), "max": max(tys), "span": max(tys) - min(tys)},
            "tz": {"min": min(tzs), "max": max(tzs), "span": max(tzs) - min(tzs)},
        },
    }


def remove_outlier_cameras(
    images_in: Path, images_out: Path, outlier_names: set[str]
) -> dict:
    """Stream images.txt, write new file without outlier cameras.

    Returns dict with kept/removed counts.
    """
    t0 = time.time()
    kept = 0
    removed = 0

    with open(images_in, "r") as fin, open(images_out, "w") as fout:
        for line in fin:
            if line.startswith("#"):
                fout.write(line)
                continue
            parts = line.split()
            if len(parts) >= 10:
                name = parts[9]
                pts2d_line = next(fin, "\n")
                if name in outlier_names:
                    removed += 1
                else:
                    fout.write(line)
                    fout.write(pts2d_line)
                    kept += 1

    return {
        "kept": kept,
        "removed": removed,
        "duration_s": time.time() - t0,
    }


def remove_outlier_cameras_auto(
    images_in: Path,
    images_out: Path,
    threshold: float | None = None,
    percentile: float = 0.99,
    multiplier: float = 2.5,
    min_threshold: float = 100.0,
) -> dict:
    """Analyze and remove outlier cameras in one call.

    If threshold is None, auto-computes from percentile * multiplier.
    """
    analysis = analyze_cameras(images_in)

    if threshold is None:
        threshold = analysis["threshold"]

    outlier_names = {o["name"] for o in analysis["outliers"]}
    # Recompute outliers with possibly different threshold
    outlier_names = set()
    med = analysis["median"]
    for name, tx, ty, tz in analysis["cameras"]:
        d = ((tx - med["tx"]) ** 2 + (ty - med["ty"]) ** 2 + (tz - med["tz"]) ** 2) ** 0.5
        if d > threshold:
            outlier_names.add(name)

    result = remove_outlier_cameras(images_in, images_out, outlier_names)
    result["analysis"] = analysis
    result["threshold_used"] = threshold
    return result


def filter_points3d_kdtree(
    points3d_in: Path,
    points3d_out: Path,
    ply_path: Path,
    threshold: float = 0.001,
    transform: tuple[int, ...] = (1, 0, 0, 0, 0, -1, 0, 1, 0),
) -> dict:
    """Filter points3D.txt to keep only points near a cleaned PLY via KD-tree.

    Returns dict with filtering statistics.
    """
    t0 = time.time()

    # Read PLY and transform to COLMAP coordinates
    vertices = read_binary_ply(ply_path)
    colmap_coords = ply_vertices_to_colmap_coords(vertices, transform)
    ply_vertex_count = len(colmap_coords)

    # Build KD-tree
    tree = cKDTree(colmap_coords)
    tree_time = time.time() - t0

    # Coordinate ranges of PLY in COLMAP space
    ply_ranges = {}
    for i, axis in enumerate(("x", "y", "z")):
        ply_ranges[axis] = {
            "min": float(colmap_coords[:, i].min()),
            "max": float(colmap_coords[:, i].max()),
        }

    # Stream points3D, query each
    kept = 0
    total = 0
    kept_ids = set()
    coord_ranges_before = {"x": [float("inf"), float("-inf")],
                           "y": [float("inf"), float("-inf")],
                           "z": [float("inf"), float("-inf")]}
    coord_ranges_after = {"x": [float("inf"), float("-inf")],
                          "y": [float("inf"), float("-inf")],
                          "z": [float("inf"), float("-inf")]}

    with open(points3d_in, "r") as fin, open(points3d_out, "w") as fout:
        for line in fin:
            if line.startswith("#"):
                fout.write(line)
                continue
            parts = line.split(maxsplit=4)
            if len(parts) < 4:
                continue
            total += 1
            pid = int(parts[0])
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])

            # Track before ranges
            for axis, val in zip(("x", "y", "z"), (x, y, z)):
                coord_ranges_before[axis][0] = min(coord_ranges_before[axis][0], val)
                coord_ranges_before[axis][1] = max(coord_ranges_before[axis][1], val)

            dist, _ = tree.query([x, y, z], distance_upper_bound=threshold)
            if dist <= threshold:
                fout.write(line)
                kept += 1
                kept_ids.add(pid)
                for axis, val in zip(("x", "y", "z"), (x, y, z)):
                    coord_ranges_after[axis][0] = min(coord_ranges_after[axis][0], val)
                    coord_ranges_after[axis][1] = max(coord_ranges_after[axis][1], val)

    duration = time.time() - t0

    return {
        "ply_vertices": ply_vertex_count,
        "ply_ranges": ply_ranges,
        "threshold": threshold,
        "points_before": total,
        "points_after": kept,
        "points_removed": total - kept,
        "kept_ids": kept_ids,
        "coordinate_ranges_before": {
            k: {"min": v[0], "max": v[1]} for k, v in coord_ranges_before.items()
        },
        "coordinate_ranges_after": {
            k: {"min": v[0], "max": v[1]} for k, v in coord_ranges_after.items()
        },
        "tree_build_s": tree_time,
        "duration_s": duration,
    }


def clean_points2d_refs(
    images_in: Path, images_out: Path, kept_point_ids: set[int]
) -> dict:
    """Replace dangling POINT3D_ID refs in images.txt with -1.

    Returns dict with reference counts.
    """
    t0 = time.time()
    cam_count = 0
    total_refs = 0
    kept_refs = 0
    cleaned_refs = 0

    with open(images_in, "r") as fin, open(images_out, "w") as fout:
        for line in fin:
            if line.startswith("#"):
                fout.write(line)
                continue
            # Camera pose line
            fout.write(line)
            cam_count += 1
            # POINTS2D line
            pts_line = next(fin, None)
            if pts_line is None:
                fout.write("\n")
                break
            pts_stripped = pts_line.strip()
            if not pts_stripped:
                fout.write("\n")
            else:
                parts = pts_stripped.split()
                if len(parts) % 3 != 0:
                    fout.write(pts_line)
                else:
                    new_parts = list(parts)
                    n_triplets = len(parts) // 3
                    total_refs += n_triplets
                    for i in range(n_triplets):
                        pid = int(parts[i * 3 + 2])
                        if pid == -1:
                            cleaned_refs += 1
                        elif pid not in kept_point_ids:
                            new_parts[i * 3 + 2] = "-1"
                            cleaned_refs += 1
                        else:
                            kept_refs += 1
                    fout.write(" ".join(new_parts) + "\n")

    return {
        "cameras": cam_count,
        "total_refs": total_refs,
        "kept_refs": kept_refs,
        "cleaned_refs": cleaned_refs,
        "duration_s": time.time() - t0,
    }


def load_kept_point_ids(points3d_path: Path) -> set[int]:
    """Stream points3D.txt and collect all POINT3D_IDs."""
    kept = set()
    with open(points3d_path, "r") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.split(maxsplit=2)
            if parts:
                kept.add(int(parts[0]))
    return kept
