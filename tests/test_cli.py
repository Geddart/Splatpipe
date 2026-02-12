"""Tests for CLI commands via Typer CliRunner."""

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from splatpipe.cli.main import app
from splatpipe.core.project import Project

TEST_DATA = Path(__file__).parent / "test_data"
runner = CliRunner()


class TestInitCommand:
    def test_init_creates_project(self, tmp_path):
        """splatpipe init creates project with correct structure."""
        # Set up a COLMAP directory
        colmap_dir = tmp_path / "colmap_data"
        colmap_dir.mkdir()
        shutil.copy(TEST_DATA / "tiny_cameras.txt", colmap_dir / "cameras.txt")
        shutil.copy(TEST_DATA / "tiny_images.txt", colmap_dir / "images.txt")
        shutil.copy(TEST_DATA / "tiny_points3d.txt", colmap_dir / "points3D.txt")

        output = tmp_path / "MyProject"
        result = runner.invoke(app, [
            "init", str(colmap_dir),
            "--name", "TestProject",
            "--output", str(output),
        ])

        assert result.exit_code == 0
        assert (output / "state.json").exists()

        state = json.loads((output / "state.json").read_text())
        assert state["name"] == "TestProject"
        assert state["trainer"] == "postshot"
        assert len(state["lod_levels"]) == 5

    def test_init_custom_lods(self, tmp_path):
        """Custom LODs are parsed correctly."""
        colmap_dir = tmp_path / "colmap_data"
        colmap_dir.mkdir()
        shutil.copy(TEST_DATA / "tiny_cameras.txt", colmap_dir / "cameras.txt")
        shutil.copy(TEST_DATA / "tiny_images.txt", colmap_dir / "images.txt")
        shutil.copy(TEST_DATA / "tiny_points3d.txt", colmap_dir / "points3D.txt")

        output = tmp_path / "MyProject"
        result = runner.invoke(app, [
            "init", str(colmap_dir),
            "--name", "Test",
            "--lods", "3M,1.5M",
            "--output", str(output),
        ])

        assert result.exit_code == 0
        state = json.loads((output / "state.json").read_text())
        assert len(state["lod_levels"]) == 2
        assert state["lod_levels"][0]["max_splats"] == 3_000_000
        assert state["lod_levels"][1]["max_splats"] == 1_500_000

    def test_init_missing_colmap_files(self, tmp_path):
        """Missing COLMAP files gives clear error."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = runner.invoke(app, [
            "init", str(empty_dir),
            "--name", "Test",
            "--output", str(tmp_path / "proj"),
        ])

        assert result.exit_code == 1
        assert "Missing COLMAP files" in result.output

    def test_init_custom_trainer(self, tmp_path):
        """Custom trainer is stored."""
        colmap_dir = tmp_path / "colmap_data"
        colmap_dir.mkdir()
        shutil.copy(TEST_DATA / "tiny_cameras.txt", colmap_dir / "cameras.txt")
        shutil.copy(TEST_DATA / "tiny_images.txt", colmap_dir / "images.txt")
        shutil.copy(TEST_DATA / "tiny_points3d.txt", colmap_dir / "points3D.txt")

        output = tmp_path / "MyProject"
        result = runner.invoke(app, [
            "init", str(colmap_dir),
            "--name", "Test",
            "--trainer", "lichtfeld",
            "--output", str(output),
        ])

        assert result.exit_code == 0
        state = json.loads((output / "state.json").read_text())
        assert state["trainer"] == "lichtfeld"


class TestStatusCommand:
    def test_status_shows_project_info(self, tmp_path):
        """Status command displays project details."""
        project = Project.create(tmp_path / "proj", "StatusTest")
        project.record_step("clean", "completed", summary={"cameras_kept": 10})

        result = runner.invoke(app, ["status", "--project", str(project.root)])

        assert result.exit_code == 0
        assert "StatusTest" in result.output
        assert "completed" in result.output
