"""Tests for PipelineStep base class: file_stats, debug JSON, execute flow."""

import json
from pathlib import Path

import pytest

from splatpipe.core.project import Project
from splatpipe.steps.base import PipelineStep


class ConcreteStep(PipelineStep):
    """Minimal concrete step for testing the base class."""

    @property
    def step_name(self) -> str:
        return "test_step"

    @property
    def output_folder(self) -> str:
        return "02_colmap_clean"

    def run(self, output_dir: Path) -> dict:
        # Write a marker file to prove output_dir is used
        (output_dir / "marker.txt").write_text("done")
        return {
            "summary": {"items": 42, "status": "ok"},
            "extra_debug": "some value",
        }


class FailingStep(PipelineStep):
    """Step that raises an exception."""

    @property
    def step_name(self) -> str:
        return "failing_step"

    @property
    def output_folder(self) -> str:
        return "02_colmap_clean"

    def run(self, output_dir: Path) -> dict:
        raise RuntimeError("Step failed intentionally")


class TestFileStats:
    def test_existing_file(self, tmp_path):
        """file_stats returns path and size for existing file."""
        f = tmp_path / "test.bin"
        f.write_bytes(b"x" * 1024)
        stats = PipelineStep.file_stats(f)
        assert stats["path"] == str(f)
        assert stats["size_bytes"] == 1024
        assert stats["size_mb"] == pytest.approx(0.001, abs=0.001)

    def test_nonexistent_file(self, tmp_path):
        """file_stats returns {exists: False} for missing file."""
        stats = PipelineStep.file_stats(tmp_path / "nope.txt")
        assert stats == {"exists": False}


class TestWriteDebugJson:
    def test_writes_valid_json(self, tmp_path):
        """_write_debug_json writes parseable JSON."""
        proj = Project.create(tmp_path / "p", "T")
        step = ConcreteStep(proj, {})
        path = tmp_path / "debug.json"
        step._write_debug_json(path, {"key": "value", "num": 42})
        data = json.loads(path.read_text())
        assert data["key"] == "value"
        assert data["num"] == 42

    def test_handles_path_objects(self, tmp_path):
        """_write_debug_json serializes Path objects to strings."""
        proj = Project.create(tmp_path / "p", "T")
        step = ConcreteStep(proj, {})
        debug_file = tmp_path / "debug.json"
        test_path = tmp_path / "some" / "file.txt"
        step._write_debug_json(debug_file, {"file": test_path})
        data = json.loads(debug_file.read_text())
        assert data["file"] == str(test_path)

    def test_handles_sets(self, tmp_path):
        """_write_debug_json serializes sets to lists."""
        proj = Project.create(tmp_path / "p", "T")
        step = ConcreteStep(proj, {})
        path = tmp_path / "debug.json"
        step._write_debug_json(path, {"ids": {1, 2, 3}})
        data = json.loads(path.read_text())
        assert sorted(data["ids"]) == [1, 2, 3]


class TestGetEnvironment:
    def test_has_required_keys(self, tmp_path):
        """_get_environment returns python_version, platform, disk_free_gb."""
        proj = Project.create(tmp_path / "p", "T")
        step = ConcreteStep(proj, {})
        env = step._get_environment()
        assert "python_version" in env
        assert "platform" in env
        assert "disk_free_gb" in env
        assert isinstance(env["disk_free_gb"], float)


class TestExecuteFlow:
    def test_creates_output_dir(self, tmp_path):
        """execute() creates the output directory."""
        proj = Project.create(tmp_path / "p", "T")
        step = ConcreteStep(proj, {})
        step.execute()
        assert (proj.root / "02_colmap_clean").is_dir()

    def test_calls_run(self, tmp_path):
        """execute() calls run() which writes marker file."""
        proj = Project.create(tmp_path / "p", "T")
        step = ConcreteStep(proj, {})
        step.execute()
        assert (proj.root / "02_colmap_clean" / "marker.txt").exists()

    def test_writes_debug_json(self, tmp_path):
        """execute() writes debug JSON in output folder."""
        proj = Project.create(tmp_path / "p", "T")
        step = ConcreteStep(proj, {})
        step.execute()
        debug_path = proj.root / "02_colmap_clean" / "test_step_debug.json"
        assert debug_path.exists()
        data = json.loads(debug_path.read_text())
        assert data["step"] == "test_step"
        assert "started_at" in data
        assert "duration_s" in data
        assert "environment" in data
        assert data["summary"]["items"] == 42

    def test_records_step_completed(self, tmp_path):
        """execute() records step as completed in state.json."""
        proj = Project.create(tmp_path / "p", "T")
        step = ConcreteStep(proj, {})
        step.execute()
        assert proj.get_step_status("test_step") == "completed"
        assert proj.get_step_summary("test_step") == {"items": 42, "status": "ok"}

    def test_failing_step_raises(self, tmp_path):
        """execute() lets exceptions from run() propagate."""
        proj = Project.create(tmp_path / "p", "T")
        step = FailingStep(proj, {})
        with pytest.raises(RuntimeError, match="Step failed intentionally"):
            step.execute()
