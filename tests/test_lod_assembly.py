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

    def test_assembly_includes_filter_harmonics(self, tmp_path):
        """Assembly passes --filter-harmonics from step_settings."""
        from splatpipe.core.project import Project

        project = Project.create(tmp_path / "proj", "Test")
        config = {"tools": {"splat_transform": "@playcanvas/splat-transform"}}

        review_dir = project.get_folder("04_review")
        review_dir.mkdir(parents=True, exist_ok=True)
        _create_fake_ply(review_dir / "lod0_reviewed.ply")

        # Set SH bands to 2 via step_settings
        project.set_step_settings("assemble", {"sh_bands": 2})

        step = LodAssemblyStep(project, config)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Done"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            output_dir = project.get_folder("05_output")
            output_dir.mkdir(parents=True, exist_ok=True)
            step.run(output_dir)

        call_cmd = mock_run.call_args[0][0]
        # --filter-harmonics 2 should appear in the command
        idx = call_cmd.index("--filter-harmonics")
        assert call_cmd[idx + 1] == "2"

    def test_assembly_filter_harmonics_default(self, tmp_path):
        """Assembly defaults to --filter-harmonics 3 when no step_settings."""
        from splatpipe.core.project import Project

        project = Project.create(tmp_path / "proj", "Test")
        config = {"tools": {"splat_transform": "@playcanvas/splat-transform"}}

        review_dir = project.get_folder("04_review")
        review_dir.mkdir(parents=True, exist_ok=True)
        _create_fake_ply(review_dir / "lod0_reviewed.ply")

        step = LodAssemblyStep(project, config)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Done"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            output_dir = project.get_folder("05_output")
            output_dir.mkdir(parents=True, exist_ok=True)
            step.run(output_dir)

        call_cmd = mock_run.call_args[0][0]
        idx = call_cmd.index("--filter-harmonics")
        assert call_cmd[idx + 1] == "3"

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

    def test_assembly_writes_viewer_config(self, tmp_path):
        """Assembly writes viewer-config.json on success."""
        import json as _json
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

        config_path = output_dir / "viewer-config.json"
        assert config_path.exists()
        cfg = _json.loads(config_path.read_text())
        assert "camera" in cfg
        assert cfg["camera"]["pitch_min"] == -89

    def test_assembly_viewer_config_uses_project_scene_config(self, tmp_path):
        """viewer-config.json contains project's scene_config values."""
        import json as _json
        from splatpipe.core.project import Project

        project = Project.create(tmp_path / "proj", "Test")
        config = {"tools": {"splat_transform": "@playcanvas/splat-transform"}}
        project.set_scene_config_section("camera", {"ground_height": 5.0})

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

        cfg = _json.loads((output_dir / "viewer-config.json").read_text())
        assert cfg["camera"]["ground_height"] == 5.0

    def test_assembly_no_viewer_config_on_failure(self, tmp_path):
        """Assembly does NOT write viewer-config.json when splat-transform fails."""
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

        assert not (output_dir / "viewer-config.json").exists()

    def test_assembly_copies_assets_folder(self, tmp_path):
        """Assembly copies project assets/ to output."""
        from splatpipe.core.project import Project

        project = Project.create(tmp_path / "proj", "Test")
        config = {"tools": {"splat_transform": "@playcanvas/splat-transform"}}

        review_dir = project.get_folder("04_review")
        review_dir.mkdir(parents=True, exist_ok=True)
        _create_fake_ply(review_dir / "lod0_reviewed.ply")

        (project.root / "assets" / "audio").mkdir(parents=True)
        (project.root / "assets" / "audio" / "test.mp3").write_bytes(b"fake")

        step = LodAssemblyStep(project, config)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Done"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            output_dir = project.get_folder("05_output")
            output_dir.mkdir(parents=True, exist_ok=True)
            step.run(output_dir)

        assert (output_dir / "assets" / "audio" / "test.mp3").exists()

    def test_assembly_no_error_without_assets_folder(self, tmp_path):
        """Assembly succeeds when no assets/ folder exists."""
        from splatpipe.core.project import Project

        project = Project.create(tmp_path / "proj", "Test")
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

        assert not (output_dir / "assets").exists()

    def test_assembly_viewer_config_includes_splat_budget(self, tmp_path):
        """viewer-config.json contains splat_budget from project scene_config."""
        import json as _json
        from splatpipe.core.project import Project

        project = Project.create(tmp_path / "proj", "Test")
        config = {"tools": {"splat_transform": "@playcanvas/splat-transform"}}
        project.set_scene_config_section("splat_budget", 3000000)

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

        cfg = _json.loads((output_dir / "viewer-config.json").read_text())
        assert cfg["splat_budget"] == 3000000

    def test_assembly_viewer_html_has_custom_preset(self, tmp_path):
        """Production viewer index.html contains Custom preset button and slider panel."""
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

        html = (output_dir / "index.html").read_text(encoding="utf-8")
        assert 'data-preset="custom"' in html
        assert 'id="lod-sliders"' in html

    def test_assembly_viewer_html_has_config_loading(self, tmp_path):
        """Production viewer index.html fetches viewer-config.json."""
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

        html = (output_dir / "index.html").read_text(encoding="utf-8")
        assert "viewer-config.json" in html
        assert "pitchRange" in html

    def test_assembly_viewer_html_has_annotation_markers(self, tmp_path):
        """Production viewer index.html has annotation marker support."""
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

        html = (output_dir / "index.html").read_text(encoding="utf-8")
        assert "annotation-markers" in html
        assert "ann-marker" in html
        assert "ann-dot" in html

    def test_assembly_viewer_html_has_postprocessing(self, tmp_path):
        """Production viewer index.html has post-processing and background support."""
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

        html = (output_dir / "index.html").read_text(encoding="utf-8")
        assert "TONEMAP" in html
        assert "pp.exposure" in html
        assert "pp.tonemapping" in html
        assert "bg.color" in html
        assert "fromString" in html

    def test_assembly_viewer_html_has_audio_support(self, tmp_path):
        """Production viewer index.html has audio component systems and source loading."""
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

        html = (output_dir / "index.html").read_text(encoding="utf-8")
        assert "SoundComponentSystem" in html
        assert "AudioListenerComponentSystem" in html
        assert "AudioHandler" in html
        assert "audiolistener" in html
        assert "viewerConfig.audio" in html
