"""COLMAP clean step: outlier camera removal, KD-tree point filtering, POINTS2D cleanup.

Orchestrates the three cleaning functions from colmap/filters.py.
Reads from 01_colmap_source/, writes to 02_colmap_clean/.
"""

import shutil
from pathlib import Path

from ..core.constants import FOLDER_COLMAP_SOURCE, FOLDER_COLMAP_CLEAN
from ..colmap.filters import (
    analyze_cameras,
    remove_outlier_cameras,
    filter_points3d_kdtree,
    clean_points2d_refs,
    load_kept_point_ids,
)
from ..colmap.parsers import detect_colmap_format
from ..colmap.parsers_bin import convert_colmap_bin_to_txt
from .base import PipelineStep


class ColmapCleanStep(PipelineStep):
    step_name = "clean"
    output_folder = FOLDER_COLMAP_CLEAN

    def run(self, output_dir: Path) -> dict:
        colmap_dir = self.project.colmap_dir()
        clean_config = self.config.get("colmap_clean", {})

        fmt = detect_colmap_format(colmap_dir)
        converted_dir = None

        if fmt == "binary":
            # Convert binary → text into a temp subdir so *_in != *_out
            converted_dir = output_dir / "_converted"
            converted_dir.mkdir(exist_ok=True)
            convert_colmap_bin_to_txt(colmap_dir, converted_dir)
            cameras_in = converted_dir / "cameras.txt"
            images_in = converted_dir / "images.txt"
            points3d_in = converted_dir / "points3D.txt"
        elif fmt == "text":
            cameras_in = colmap_dir / "cameras.txt"
            images_in = colmap_dir / "images.txt"
            points3d_in = colmap_dir / "points3D.txt"
        else:
            raise FileNotFoundError(
                f"No COLMAP data (cameras/images/points3D as .txt or .bin) in {colmap_dir}"
            )

        cameras_out = output_dir / "cameras.txt"
        images_out = output_dir / "images.txt"
        points3d_out = output_dir / "points3D.txt"

        result = {
            "input": {
                "cameras_txt": self.file_stats(cameras_in),
                "images_txt": self.file_stats(images_in),
                "points3d_txt": self.file_stats(points3d_in),
            }
        }

        # Step 1: Copy cameras.txt (unchanged)
        shutil.copy2(cameras_in, cameras_out)

        # Step 2: Analyze and remove outlier cameras
        analysis = analyze_cameras(images_in)

        # Determine threshold: use fixed if configured, otherwise auto-detected
        use_auto = clean_config.get("outlier_threshold_auto", True)
        if use_auto:
            threshold = analysis["threshold"]
        else:
            threshold = clean_config.get("outlier_threshold_fixed", 100.0)

        # Recompute outliers with the chosen threshold
        med = analysis["median"]
        outlier_list = []
        for name, tx, ty, tz in analysis["cameras"]:
            d = ((tx - med["tx"])**2 + (ty - med["ty"])**2 + (tz - med["tz"])**2)**0.5
            if d > threshold:
                outlier_list.append({"name": name, "dist": d, "tx": tx, "ty": ty, "tz": tz})

        result["camera_analysis"] = {
            "total": analysis["total"],
            "median_position": analysis["median"],
            "ranges": analysis["ranges"],
            "threshold_used": threshold,
            "threshold_mode": "auto" if use_auto else "fixed",
            "outliers_found": len(outlier_list),
            "outliers": outlier_list,
        }

        outlier_names = {o["name"] for o in outlier_list}
        if outlier_names:
            cam_result = remove_outlier_cameras(images_in, images_out, outlier_names)
        else:
            shutil.copy2(images_in, images_out)
            cam_result = {"kept": analysis["total"], "removed": 0, "duration_s": 0}

        result["camera_removal"] = cam_result

        # Step 3: KD-tree filter points3D (if PLY provided)
        ply_path = self._find_ply(colmap_dir)
        if ply_path:
            kdtree_threshold = clean_config.get("kdtree_threshold", 0.001)
            transform = tuple(clean_config.get("coordinate_transform", [1, 0, 0, 0, 0, -1, 0, 1, 0]))

            kdtree_result = filter_points3d_kdtree(
                points3d_in, points3d_out, ply_path,
                threshold=kdtree_threshold,
                transform=transform,
            )
            kept_ids = kdtree_result.pop("kept_ids")
            result["kdtree_filter"] = kdtree_result
        else:
            # No PLY — copy points3D as-is
            shutil.copy2(points3d_in, points3d_out)
            kept_ids = load_kept_point_ids(points3d_out)
            result["kdtree_filter"] = {"skipped": True, "reason": "no PLY found"}

        # Step 4: Clean POINTS2D references
        images_temp = output_dir / "images_precleaned.txt"
        images_out.rename(images_temp)
        pts2d_result = clean_points2d_refs(images_temp, images_out, kept_ids)
        images_temp.unlink()
        result["points2d_clean"] = pts2d_result

        # Symlink images folder if it exists
        images_folder = colmap_dir / "images"
        clean_images_folder = output_dir / "images"
        if images_folder.exists() and not clean_images_folder.exists():
            clean_images_folder.symlink_to(images_folder, target_is_directory=True)

        # Output stats
        result["output"] = {
            "cameras_txt": self.file_stats(cameras_out),
            "images_txt": self.file_stats(images_out),
            "points3d_txt": self.file_stats(points3d_out),
        }

        result["summary"] = {
            "cameras_total": analysis["total"],
            "cameras_removed": len(outlier_names),
            "cameras_kept": cam_result["kept"],
            "points_before": result.get("kdtree_filter", {}).get("points_before"),
            "points_after": result.get("kdtree_filter", {}).get("points_after"),
            "points2d_total": pts2d_result["total_refs"],
            "points2d_kept": pts2d_result["kept_refs"],
            "points2d_cleaned": pts2d_result["cleaned_refs"],
        }

        # Clean up temp conversion directory
        if converted_dir and converted_dir.exists():
            shutil.rmtree(converted_dir)

        return result

    def _find_ply(self, colmap_dir: Path) -> Path | None:
        """Find the cleaned PLY file for KD-tree filtering."""
        # Check project config first
        ply_path_str = self.config.get("colmap_clean", {}).get("ply_path")
        if ply_path_str:
            ply_path = Path(ply_path_str)
            if ply_path.exists():
                return ply_path

        # Look in colmap_dir for any .ply file
        plys = list(colmap_dir.glob("*.ply"))
        if plys:
            return plys[0]

        # Look in COLMAP source folder (in case of symlink)
        source_dir = self.project.get_folder(FOLDER_COLMAP_SOURCE)
        if source_dir != colmap_dir:
            plys = list(source_dir.glob("*.ply"))
            if plys:
                return plys[0]

        return None
