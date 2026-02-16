"""Integration tests: end-to-end on tiny test data."""

import json
import shutil
import struct
from pathlib import Path


from splatpipe.core.constants import FOLDER_COLMAP_SOURCE, FOLDER_COLMAP_CLEAN
from splatpipe.core.config import load_defaults
from splatpipe.core.project import Project
from splatpipe.steps.colmap_clean import ColmapCleanStep
from splatpipe.colmap.parsers import parse_cameras_txt, parse_images_txt, count_cameras, count_images

TEST_DATA = Path(__file__).parent / "test_data"


class TestColmapCleanIntegration:
    """End-to-end test of the COLMAP clean step with real tiny data."""

    def _setup_project(self, tmp_path) -> Project:
        """Create a project with test COLMAP data."""
        project = Project.create(tmp_path / "proj", "IntegTest")

        colmap_dir = project.get_folder(FOLDER_COLMAP_SOURCE)
        colmap_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(TEST_DATA / "tiny_cameras.txt", colmap_dir / "cameras.txt")
        shutil.copy(TEST_DATA / "tiny_images.txt", colmap_dir / "images.txt")
        shutil.copy(TEST_DATA / "tiny_points3d.txt", colmap_dir / "points3D.txt")
        shutil.copy(TEST_DATA / "tiny_cloud.ply", colmap_dir / "cloud.ply")

        return project

    def test_colmap_clean_produces_output(self, tmp_path):
        """COLMAP clean step produces all output files."""
        project = self._setup_project(tmp_path)
        config = load_defaults()

        step = ColmapCleanStep(project, config)
        step.execute()

        clean_dir = project.get_folder(FOLDER_COLMAP_CLEAN)
        assert (clean_dir / "cameras.txt").exists()
        assert (clean_dir / "images.txt").exists()
        assert (clean_dir / "points3D.txt").exists()

    def test_colmap_clean_debug_json(self, tmp_path):
        """COLMAP clean step produces valid debug JSON."""
        project = self._setup_project(tmp_path)
        config = load_defaults()

        step = ColmapCleanStep(project, config)
        step.execute()

        debug_path = project.get_folder(FOLDER_COLMAP_CLEAN) / "clean_debug.json"
        assert debug_path.exists()

        debug = json.loads(debug_path.read_text())
        assert debug["step"] == "clean"
        assert "started_at" in debug
        assert "duration_s" in debug
        assert "camera_analysis" in debug
        assert "kdtree_filter" in debug
        assert "points2d_clean" in debug
        assert "environment" in debug
        assert "summary" in debug

    def test_colmap_clean_filters_correctly(self, tmp_path):
        """COLMAP clean removes outliers and filters points."""
        project = self._setup_project(tmp_path)
        config = load_defaults()
        # Use fixed threshold for tiny test data (auto doesn't work with 5 cameras)
        config["colmap_clean"]["outlier_threshold_auto"] = False
        config["colmap_clean"]["outlier_threshold_fixed"] = 100.0

        step = ColmapCleanStep(project, config)
        result = step.execute()

        summary = result["summary"]
        # 2 outlier cameras removed (image004.jpg, image005.jpg)
        assert summary["cameras_removed"] == 2
        assert summary["cameras_kept"] == 3
        # 20 points kept (matched PLY), 30 removed
        assert summary["points_after"] == 20

    def test_colmap_clean_updates_state(self, tmp_path):
        """State is updated to completed after successful clean."""
        project = self._setup_project(tmp_path)
        config = load_defaults()
        config["colmap_clean"]["outlier_threshold_auto"] = False
        config["colmap_clean"]["outlier_threshold_fixed"] = 100.0

        step = ColmapCleanStep(project, config)
        step.execute()

        assert project.get_step_status("clean") == "completed"
        summary = project.get_step_summary("clean")
        assert summary is not None
        assert summary["cameras_kept"] == 3


class TestColmapCleanBinaryInput:
    """Test clean step with binary COLMAP input."""

    def _write_binary_from_text(self, text_dir: Path, bin_dir: Path) -> None:
        """Convert tiny text test data to binary format for testing."""
        from splatpipe.colmap.parsers import parse_points3d_txt
        # Read text data (test files use "tiny_" prefix)
        cameras = list(parse_cameras_txt(text_dir / "tiny_cameras.txt"))
        images = list(parse_images_txt(text_dir / "tiny_images.txt"))
        points = list(parse_points3d_txt(text_dir / "tiny_points3d.txt"))

        # Write binary files
        self._write_cameras_bin(bin_dir / "cameras.bin", cameras)
        self._write_images_bin(bin_dir / "images.bin", images)
        self._write_points3d_bin(bin_dir / "points3D.bin", points)

    def _write_cameras_bin(self, path, cameras):
        MODELS_INV = {
            "SIMPLE_PINHOLE": 0, "PINHOLE": 1, "SIMPLE_RADIAL": 2,
            "RADIAL": 3, "OPENCV": 4, "OPENCV_FISHEYE": 5,
            "FULL_OPENCV": 6, "FOV": 7, "SIMPLE_RADIAL_FISHEYE": 8,
            "RADIAL_FISHEYE": 9, "THIN_PRISM_FISHEYE": 10,
        }
        with open(path, "wb") as f:
            f.write(struct.pack("<Q", len(cameras)))
            for cam in cameras:
                f.write(struct.pack("<I", cam["camera_id"]))
                f.write(struct.pack("<i", MODELS_INV[cam["model"]]))
                f.write(struct.pack("<Q", cam["width"]))
                f.write(struct.pack("<Q", cam["height"]))
                for p in cam["params"]:
                    f.write(struct.pack("<d", p))

    def _write_images_bin(self, path, images):
        with open(path, "wb") as f:
            f.write(struct.pack("<Q", len(images)))
            for img in images:
                f.write(struct.pack("<I", img["image_id"]))
                f.write(struct.pack("<4d", img["qw"], img["qx"], img["qy"], img["qz"]))
                f.write(struct.pack("<3d", img["tx"], img["ty"], img["tz"]))
                f.write(struct.pack("<I", img["camera_id"]))
                f.write(img["name"].encode() + b"\x00")
                f.write(struct.pack("<Q", len(img["points2d"])))
                for p in img["points2d"]:
                    f.write(struct.pack("<2d", p["x"], p["y"]))
                    f.write(struct.pack("<q", p["point3d_id"]))

    def _write_points3d_bin(self, path, points):
        with open(path, "wb") as f:
            f.write(struct.pack("<Q", len(points)))
            for pt in points:
                f.write(struct.pack("<Q", pt["point3d_id"]))
                f.write(struct.pack("<3d", pt["x"], pt["y"], pt["z"]))
                f.write(struct.pack("<3B", pt["r"], pt["g"], pt["b"]))
                f.write(struct.pack("<d", pt["error"]))
                f.write(struct.pack("<Q", len(pt["track"])))
                for t in pt["track"]:
                    f.write(struct.pack("<I", t["image_id"]))
                    f.write(struct.pack("<I", t["point2d_idx"]))

    def test_clean_step_binary_input(self, tmp_path):
        """Clean step converts binary input to text and produces correct output."""
        project = Project.create(tmp_path / "proj", "BinaryTest")

        # Write binary COLMAP files from our tiny text test data
        colmap_dir = project.get_folder(FOLDER_COLMAP_SOURCE)
        colmap_dir.mkdir(parents=True, exist_ok=True)
        self._write_binary_from_text(TEST_DATA, colmap_dir)
        shutil.copy(TEST_DATA / "tiny_cloud.ply", colmap_dir / "cloud.ply")

        config = load_defaults()
        config["colmap_clean"]["outlier_threshold_auto"] = False
        config["colmap_clean"]["outlier_threshold_fixed"] = 100.0

        step = ColmapCleanStep(project, config)
        result = step.execute()

        # Verify output is text format
        clean_dir = project.get_folder(FOLDER_COLMAP_CLEAN)
        assert (clean_dir / "cameras.txt").exists()
        assert (clean_dir / "images.txt").exists()
        assert (clean_dir / "points3D.txt").exists()

        # Verify temp conversion dir was cleaned up
        assert not (clean_dir / "_converted").exists()

        # Verify filtering worked (same as text input: 2 outliers removed)
        summary = result["summary"]
        assert summary["cameras_removed"] == 2
        assert summary["cameras_kept"] == 3
