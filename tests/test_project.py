"""Tests for Project class: folder scaffolding, state CRUD."""

import json

import pytest

from splatpipe.core.constants import PROJECT_FOLDERS
from splatpipe.core.project import Project


def test_create_project(tmp_path):
    """Verify all folders are created and state.json is written."""
    project = Project.create(tmp_path / "proj", "TestProject")

    for folder in PROJECT_FOLDERS:
        assert (project.root / folder).is_dir()

    assert project.state_path.exists()
    state = json.loads(project.state_path.read_text())
    assert state["name"] == "TestProject"
    assert state["trainer"] == "postshot"
    assert len(state["lod_levels"]) == 6
    assert state["steps"] == {}


def test_create_project_custom_trainer(tmp_path):
    """Custom trainer is stored in state."""
    project = Project.create(tmp_path / "proj", "Test", trainer="lichtfeld")
    assert project.trainer == "lichtfeld"


def test_create_project_custom_lods(tmp_path):
    """Custom LOD levels are stored in state."""
    lods = [
        {"name": "lod0_3000k", "max_splats": 3_000_000},
        {"name": "lod1_1500k", "max_splats": 1_500_000},
    ]
    project = Project.create(tmp_path / "proj", "Test", lod_levels=lods)
    assert len(project.lod_levels) == 2
    assert project.lod_levels[0]["max_splats"] == 3_000_000


def test_create_project_colmap_source(tmp_path):
    """COLMAP source path is stored in state."""
    project = Project.create(
        tmp_path / "proj", "Test",
        colmap_source=r"H:\some\colmap\dir",
    )
    assert project.state["colmap_source"] == r"H:\some\colmap\dir"


def test_record_step(tmp_path):
    """Recording a step updates state.json."""
    project = Project.create(tmp_path / "proj", "Test")
    project.record_step("clean", "completed", summary={"cameras_kept": 42})

    assert project.get_step_status("clean") == "completed"
    assert project.get_step_summary("clean") == {"cameras_kept": 42}


def test_record_step_failed(tmp_path):
    """Failed step records error."""
    project = Project.create(tmp_path / "proj", "Test")
    project.record_step("train", "failed", error="CUDA out of memory")

    assert project.get_step_status("train") == "failed"
    step = project.state["steps"]["train"]
    assert step["error"] == "CUDA out of memory"


def test_step_not_run(tmp_path):
    """Unrun step returns None."""
    project = Project.create(tmp_path / "proj", "Test")
    assert project.get_step_status("clean") is None
    assert project.get_step_summary("clean") is None


def test_state_json_roundtrip(tmp_path):
    """Write + read state.json preserves all fields."""
    project = Project.create(tmp_path / "proj", "Test")
    project.record_step("clean", "completed", summary={"test": 42})

    # Reload from disk
    project2 = Project(project.root)
    assert project2.name == "Test"
    assert project2.get_step_status("clean") == "completed"
    assert project2.get_step_summary("clean") == {"test": 42}


def test_find_project(tmp_path):
    """Find project by walking up from subdirectory."""
    project = Project.create(tmp_path / "proj", "Test")
    subdir = project.root / "02_colmap_clean" / "nested"
    subdir.mkdir(parents=True)

    found = Project.find(subdir)
    assert found.root == project.root
    assert found.name == "Test"


def test_find_project_not_found(tmp_path):
    """Missing project raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="No splatpipe project"):
        Project.find(tmp_path)


def test_get_folder(tmp_path):
    """get_folder returns correct path."""
    project = Project.create(tmp_path / "proj", "Test")
    clean_dir = project.get_folder("02_colmap_clean")
    assert clean_dir == project.root / "02_colmap_clean"
    assert clean_dir.is_dir()


def test_reset_step(tmp_path):
    """reset_step removes step entry, making status None (pending)."""
    project = Project.create(tmp_path / "proj", "Test")
    project.record_step("clean", "completed", summary={"cameras_kept": 42})
    assert project.get_step_status("clean") == "completed"

    project.reset_step("clean")
    assert project.get_step_status("clean") is None
    # Verify persisted
    project2 = Project(project.root)
    assert project2.get_step_status("clean") is None


def test_reset_step_nonexistent(tmp_path):
    """reset_step on a step that hasn't run is a no-op."""
    project = Project.create(tmp_path / "proj", "Test")
    project.reset_step("clean")  # should not raise
    assert project.get_step_status("clean") is None


def test_reset_all_steps(tmp_path):
    """reset_all_steps clears all step entries."""
    project = Project.create(tmp_path / "proj", "Test")
    project.record_step("clean", "completed")
    project.record_step("train", "failed", error="test")
    project.record_step("assemble", "completed")

    project.reset_all_steps()
    assert project.get_step_status("clean") is None
    assert project.get_step_status("train") is None
    assert project.get_step_status("assemble") is None
    # Verify persisted
    project2 = Project(project.root)
    assert project2.state["steps"] == {}


def test_export_mode_default(tmp_path):
    """Export mode defaults to 'folder'."""
    project = Project.create(tmp_path / "proj", "Test")
    assert project.export_mode == "folder"


def test_set_export_mode(tmp_path):
    """set_export_mode persists to state.json."""
    project = Project.create(tmp_path / "proj", "Test")
    project.set_export_mode("cdn")
    assert project.export_mode == "cdn"
    # Verify persisted
    project2 = Project(project.root)
    assert project2.export_mode == "cdn"


def test_export_folder_default(tmp_path):
    """Export folder defaults to empty string."""
    project = Project.create(tmp_path / "proj", "Test")
    assert project.export_folder == ""


def test_set_export_folder(tmp_path):
    """set_export_folder persists to state.json."""
    project = Project.create(tmp_path / "proj", "Test")
    project.set_export_folder(r"Z:\output\test")
    assert project.export_folder == r"Z:\output\test"
    # Verify persisted
    project2 = Project(project.root)
    assert project2.export_folder == r"Z:\output\test"
