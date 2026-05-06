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


# splat-transform v2.0.4 stderr captured from a real run on a 46K-gaussian PLY
# (`npx --yes @playcanvas/splat-transform@2.0.4 --no-tty input.ply -l 0
# --filter-nan output/lod-meta.json`). The progress format was refactored in
# v2.0 (PR #204) — the v1.x `[1/8] Generating morton order` step labels are
# gone, replaced by a structured `▸`-prefixed tree with chunks emitted as
# `▸ [N/M] X_Y` lines inside the Writing section.
_V2_STDERR_SINGLE_LOD_2_CHUNKS = """\
splat-transform v2.0.4 (fa46db3)
▸ [1/2] Input /path/to/input.ply
  ▸ Reading
    ▸ decoding 0.005s
  · 46.2K gaussians · 0 SH bands · 3.0MB
  ▸ Filter NaN
    · no change
▸ [2/2] Output /path/to/lod-meta.json
  · 46.2K gaussians · 0 SH bands · 3.2MB
  ▸ Writing
    · lod-meta.json (211B)
    ▸ [1/2] 0_0
      · means_l.webp (135.4KB)
      · means_u.webp (64.6KB)
      · quats.webp (93.2KB)
      · scales.webp (106.6KB)
      · sh0.webp (109.3KB)
      · meta.json (10.1KB)
    ▸ [2/2] 0_1
      · means_l.webp (130.0KB)
      · means_u.webp (62.0KB)
      · quats.webp (92.0KB)
      · scales.webp (105.0KB)
      · sh0.webp (108.0KB)
      · meta.json (10.1KB)
done in 1.499s  [peak 119.1KB]
"""


class TestProgressRegex:
    """Lock in the splat-transform v2.x stderr parser.

    The regexes live in lod_assembly._CHUNK_RE / _SECTION_RE. Each chunk
    line emitted inside the Writing section corresponds to one SOG chunk
    being produced — counting them gives us chunks_done for progress.
    """

    def test_chunk_re_matches_indented_chunk_lines(self):
        from splatpipe.steps.lod_assembly import _CHUNK_RE

        chunk_lines = [
            line for line in _V2_STDERR_SINGLE_LOD_2_CHUNKS.splitlines()
            if _CHUNK_RE.match(line)
        ]
        assert len(chunk_lines) == 2
        m0 = _CHUNK_RE.match(chunk_lines[0])
        assert m0 is not None
        assert (m0.group(1), m0.group(2), m0.group(3), m0.group(4)) == (
            "1", "2", "0", "0",
        )
        m1 = _CHUNK_RE.match(chunk_lines[1])
        assert m1 is not None
        assert (m1.group(1), m1.group(2), m1.group(3), m1.group(4)) == (
            "2", "2", "0", "1",
        )

    def test_chunk_re_does_not_match_top_level_file_steps(self):
        """`▸ [1/2] Input ...` is a file step, not a chunk — must not match."""
        from splatpipe.steps.lod_assembly import _CHUNK_RE

        assert _CHUNK_RE.match("▸ [1/2] Input /path/to/input.ply") is None
        assert _CHUNK_RE.match("▸ [2/2] Output /path/to/lod-meta.json") is None

    def test_chunk_re_does_not_match_v1_format(self):
        """v1.x `[1/8] Generating morton order` lines must not be miscounted
        as chunks if a v1.x splat-transform somehow gets invoked."""
        from splatpipe.steps.lod_assembly import _CHUNK_RE

        assert _CHUNK_RE.match("[1/8] Generating morton order") is None
        assert _CHUNK_RE.match("  [1/8] Generating morton order") is None

    def test_section_re_matches_writing_reading_and_filter(self):
        from splatpipe.steps.lod_assembly import _SECTION_RE

        sections = [
            (_SECTION_RE.match(line).group(1) if _SECTION_RE.match(line) else None)
            for line in _V2_STDERR_SINGLE_LOD_2_CHUNKS.splitlines()
        ]
        sections = [s for s in sections if s]
        assert "Reading" in sections
        assert "Writing" in sections
        assert "Filter NaN" in sections
