"""Tests for CLI commands via Typer CliRunner."""

import json
import shutil
import struct
from pathlib import Path

from typer.testing import CliRunner

from splatpipe.cli.main import app
from splatpipe.core.project import Project

TEST_DATA = Path(__file__).parent / "test_data"
runner = CliRunner()


def _write_binary_colmap(colmap_dir: Path) -> None:
    """Write minimal binary COLMAP files for testing."""
    with open(colmap_dir / "cameras.bin", "wb") as f:
        f.write(struct.pack("<Q", 1))
        f.write(struct.pack("<I", 1))
        f.write(struct.pack("<i", 0))  # SIMPLE_PINHOLE
        f.write(struct.pack("<Q", 1920))
        f.write(struct.pack("<Q", 1080))
        f.write(struct.pack("<3d", 1500.0, 960.0, 540.0))
    with open(colmap_dir / "images.bin", "wb") as f:
        f.write(struct.pack("<Q", 1))
        f.write(struct.pack("<I", 1))
        f.write(struct.pack("<4d", 0.5, 0.5, 0.5, 0.5))
        f.write(struct.pack("<3d", 0.0, 0.0, 0.0))
        f.write(struct.pack("<I", 1))
        f.write(b"img.jpg\x00")
        f.write(struct.pack("<Q", 0))
    with open(colmap_dir / "points3D.bin", "wb") as f:
        f.write(struct.pack("<Q", 0))


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
        assert len(state["lod_levels"]) == 6

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

    def test_init_unknown_format_warns(self, tmp_path):
        """Unknown alignment format warns but still creates project."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = runner.invoke(app, [
            "init", str(empty_dir),
            "--name", "Test",
            "--output", str(tmp_path / "proj"),
        ])

        assert result.exit_code == 0
        assert "Warning" in result.output or "warning" in result.output.lower()
        assert (tmp_path / "proj" / "state.json").exists()

    def test_init_binary_colmap(self, tmp_path):
        """Binary COLMAP format is detected and reported."""
        colmap_dir = tmp_path / "colmap_data"
        colmap_dir.mkdir()
        _write_binary_colmap(colmap_dir)

        output = tmp_path / "MyProject"
        result = runner.invoke(app, [
            "init", str(colmap_dir),
            "--name", "BinaryTest",
            "--output", str(output),
        ])

        assert result.exit_code == 0
        assert "COLMAP (binary)" in result.output
        assert (output / "state.json").exists()

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

    def test_init_psht_file(self, tmp_path):
        """splatpipe init with .psht file copies file into project."""
        psht_file = tmp_path / "scene.psht"
        psht_file.write_bytes(b"fake psht data")
        output = tmp_path / "proj"

        result = runner.invoke(app, [
            "init", str(psht_file),
            "--name", "PshtProject",
            "--output", str(output),
        ])

        assert result.exit_code == 0, result.output
        assert "Postshot" in result.output
        state = json.loads((output / "state.json").read_text())
        assert state["source_type"] == "postshot"
        # Verify file was copied
        copied = output / "01_colmap_source" / "source.psht"
        assert copied.exists()
        assert copied.read_bytes() == b"fake psht data"


class TestExportCommand:
    def test_export_folder_mode(self, tmp_path):
        """splatpipe export --mode folder copies output files."""
        project = Project.create(tmp_path / "proj", "ExportTest")

        # Create some output files
        output_dir = project.get_folder("05_output")
        (output_dir / "lod-meta.json").write_text('{"lods": []}')
        (output_dir / "chunk0.sog").write_bytes(b"x" * 100)

        dest = tmp_path / "export_dest"
        result = runner.invoke(app, [
            "export",
            "--project", str(project.root),
            "--mode", "folder",
            "--destination", str(dest),
        ])

        assert result.exit_code == 0
        assert (dest / "lod-meta.json").exists()
        assert (dest / "chunk0.sog").exists()

    def test_export_no_output_files(self, tmp_path):
        """Export with empty output dir gives error."""
        project = Project.create(tmp_path / "proj", "EmptyTest")

        result = runner.invoke(app, [
            "export",
            "--project", str(project.root),
            "--mode", "folder",
            "--destination", str(tmp_path / "dest"),
        ])

        assert result.exit_code == 1
        assert "No output files" in result.output


class TestStatusCommand:
    def test_status_shows_project_info(self, tmp_path):
        """Status command displays project details."""
        project = Project.create(tmp_path / "proj", "StatusTest")
        project.record_step("clean", "completed", summary={"cameras_kept": 10})

        result = runner.invoke(app, ["status", "--project", str(project.root)])

        assert result.exit_code == 0
        assert "StatusTest" in result.output
        assert "completed" in result.output
