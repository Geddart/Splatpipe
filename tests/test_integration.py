"""Integration tests: end-to-end on tiny test data."""

import json
import shutil
from pathlib import Path


from splatpipe.core.constants import FOLDER_COLMAP_SOURCE, FOLDER_COLMAP_CLEAN
from splatpipe.core.config import load_defaults
from splatpipe.core.project import Project
from splatpipe.steps.colmap_clean import ColmapCleanStep

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
