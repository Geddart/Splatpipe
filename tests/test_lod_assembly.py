"""Tests for LOD assembly step — mock subprocess."""

import struct
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from splatpipe.steps.lod_assembly import LodAssemblyStep


def _create_fake_ply(path: Path) -> None:
    """Create a minimal PLY file for testing."""
    with open(path, "wb") as f:
        header = (
            "ply\n"
            "format binary_little_endian 1.0\n"
            "element vertex 1\n"
            "property float x\n"
            "property float y\n"
            "property float z\n"
            "property uchar red\n"
            "property uchar green\n"
            "property uchar blue\n"
            "end_header\n"
        )
        f.write(header.encode("ascii"))
        f.write(struct.pack("<fffBBB", 0.0, 0.0, 0.0, 128, 128, 128))


class TestLodAssembly:
    def test_no_reviewed_plys_raises(self, tmp_path):
        """Missing reviewed PLYs raises FileNotFoundError."""
        from splatpipe.core.project import Project

        project = Project.create(tmp_path / "proj", "Test")
        config = {"tools": {"splat_transform": "@playcanvas/splat-transform"}}

        step = LodAssemblyStep(project, config)

        with pytest.raises(FileNotFoundError, match="No reviewed PLY"):
            step.run(project.get_folder("05_output"))

    def test_assembly_with_reviewed_plys(self, tmp_path):
        """Assembly runs splat-transform with correct interleaved args."""
        from splatpipe.core.project import Project

        project = Project.create(tmp_path / "proj", "Test")
        config = {"tools": {"splat_transform": "@playcanvas/splat-transform"}}

        # Create reviewed PLYs
        review_dir = project.get_folder("04_review")
        review_dir.mkdir(parents=True, exist_ok=True)
        for i in range(5):
            _create_fake_ply(review_dir / f"lod{i}_reviewed.ply")

        step = LodAssemblyStep(project, config)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Done"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            output_dir = project.get_folder("05_output")
            output_dir.mkdir(parents=True, exist_ok=True)
            result = step.run(output_dir)

        assert result["summary"]["lod_count"] == 5
        # Verify the command has interleaved -l flags
        call_cmd = mock_run.call_args[0][0]
        assert "--filter-nan" in call_cmd
        assert call_cmd[-1].endswith("lod-meta.json")
        # Check -l 0 through -l 4 are present
        for i in range(5):
            assert "-l" in call_cmd
            assert str(i) in call_cmd

    def test_assembly_generates_viewer_html(self, tmp_path):
        """Assembly generates index.html viewer when splat-transform succeeds."""
        from splatpipe.core.project import Project

        project = Project.create(tmp_path / "proj", "MyProject")
        config = {"tools": {"splat_transform": "@playcanvas/splat-transform"}}

        review_dir = project.get_folder("04_review")
        review_dir.mkdir(parents=True, exist_ok=True)
        _create_fake_ply(review_dir / "lod0_reviewed.ply")

        step = LodAssemblyStep(project, config)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Done"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            output_dir = project.get_folder("05_output")
            output_dir.mkdir(parents=True, exist_ok=True)
            step.run(output_dir)

        viewer = output_dir / "index.html"
        assert viewer.exists()
        html = viewer.read_text(encoding="utf-8")
        assert "MyProject" in html
        assert "lod-meta.json" in html
        assert "playcanvas" in html
        assert "unified: true" in html

    def test_assembly_no_viewer_on_failure(self, tmp_path):
        """Assembly does NOT generate viewer when splat-transform fails."""
        from splatpipe.core.project import Project

        project = Project.create(tmp_path / "proj", "Test")
        config = {"tools": {"splat_transform": "@playcanvas/splat-transform"}}

        review_dir = project.get_folder("04_review")
        review_dir.mkdir(parents=True, exist_ok=True)
        _create_fake_ply(review_dir / "lod0_reviewed.ply")

        step = LodAssemblyStep(project, config)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error"

        with patch("subprocess.run", return_value=mock_result):
            output_dir = project.get_folder("05_output")
            output_dir.mkdir(parents=True, exist_ok=True)
            step.run(output_dir)

        assert not (output_dir / "index.html").exists()
