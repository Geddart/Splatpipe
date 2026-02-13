"""Extended tests for Project class: setters, colmap_dir fallback, step_settings, LODs."""



from splatpipe.core.project import Project


class TestSetters:
    """Verify each setter persists to disk."""

    def test_set_name(self, tmp_path):
        proj = Project.create(tmp_path / "p", "Original")
        proj.set_name("Renamed")
        assert proj.name == "Renamed"
        reloaded = Project(proj.root)
        assert reloaded.name == "Renamed"

    def test_set_trainer(self, tmp_path):
        proj = Project.create(tmp_path / "p", "T")
        proj.set_trainer("lichtfeld")
        assert proj.trainer == "lichtfeld"
        reloaded = Project(proj.root)
        assert reloaded.trainer == "lichtfeld"

    def test_set_lod_levels(self, tmp_path):
        proj = Project.create(tmp_path / "p", "T")
        new_lods = [{"name": "lod0_5000k", "max_splats": 5_000_000}]
        proj.set_lod_levels(new_lods)
        assert len(proj.lod_levels) == 1
        assert proj.lod_levels[0]["max_splats"] == 5_000_000
        reloaded = Project(proj.root)
        assert len(reloaded.lod_levels) == 1

    def test_set_alignment_file(self, tmp_path):
        proj = Project.create(tmp_path / "p", "T")
        proj.set_alignment_file(r"H:\align.txt")
        assert proj.alignment_file == r"H:\align.txt"
        reloaded = Project(proj.root)
        assert reloaded.alignment_file == r"H:\align.txt"

    def test_set_colmap_source(self, tmp_path):
        proj = Project.create(tmp_path / "p", "T")
        proj.set_colmap_source(r"H:\colmap_data")
        assert proj.colmap_source == r"H:\colmap_data"
        reloaded = Project(proj.root)
        assert reloaded.colmap_source == r"H:\colmap_data"

    def test_set_has_thumbnail(self, tmp_path):
        proj = Project.create(tmp_path / "p", "T")
        assert proj.has_thumbnail is False
        proj.set_has_thumbnail(True)
        assert proj.has_thumbnail is True
        reloaded = Project(proj.root)
        assert reloaded.has_thumbnail is True


class TestColmapDir:
    """colmap_dir() fallback chain tests."""

    def test_bare_directory(self, tmp_path):
        """When 01_colmap_source is a plain directory, returns it."""
        proj = Project.create(tmp_path / "p", "T")
        source = proj.get_folder("01_colmap_source")
        assert source.is_dir()
        assert proj.colmap_dir() == source

    def test_fallback_to_state_colmap_source(self, tmp_path):
        """When 01_colmap_source doesn't exist, falls back to state.json colmap_source."""
        proj = Project.create(tmp_path / "p", "T")
        # Remove the 01_colmap_source directory
        source = proj.get_folder("01_colmap_source")
        source.rmdir()
        assert not source.exists()

        # Create a real directory to point colmap_source at
        real_dir = tmp_path / "real_colmap"
        real_dir.mkdir()
        proj.set_colmap_source(str(real_dir))

        result = proj.colmap_dir()
        assert result == real_dir

    def test_fallback_returns_default_when_nothing_exists(self, tmp_path):
        """When 01_colmap_source gone and colmap_source path doesn't exist, returns default."""
        proj = Project.create(tmp_path / "p", "T")
        source = proj.get_folder("01_colmap_source")
        source.rmdir()
        # colmap_source points to nonexistent dir
        proj.set_colmap_source(r"C:\nonexistent\path")
        result = proj.colmap_dir()
        # Returns the default path (01_colmap_source) even though it doesn't exist
        assert result == proj.root / "01_colmap_source"

    def test_fallback_empty_colmap_source(self, tmp_path):
        """When colmap_source is empty string, falls back to default."""
        proj = Project.create(tmp_path / "p", "T")
        source = proj.get_folder("01_colmap_source")
        source.rmdir()
        # Default colmap_source is None from create (gets "")
        result = proj.colmap_dir()
        assert result == proj.root / "01_colmap_source"


class TestStepSettings:
    def test_default_empty(self, tmp_path):
        """step_settings defaults to empty dict."""
        proj = Project.create(tmp_path / "p", "T")
        assert proj.step_settings == {}

    def test_set_step_settings(self, tmp_path):
        """set_step_settings persists correctly."""
        proj = Project.create(tmp_path / "p", "T")
        proj.set_step_settings("clean", {"kdtree_threshold": 0.005})
        assert proj.step_settings["clean"]["kdtree_threshold"] == 0.005
        reloaded = Project(proj.root)
        assert reloaded.step_settings["clean"]["kdtree_threshold"] == 0.005

    def test_set_multiple_steps(self, tmp_path):
        """Setting one step preserves others."""
        proj = Project.create(tmp_path / "p", "T")
        proj.set_step_settings("clean", {"threshold": 0.1})
        proj.set_step_settings("train", {"profile": "Splat MCMC"})
        assert proj.step_settings["clean"]["threshold"] == 0.1
        assert proj.step_settings["train"]["profile"] == "Splat MCMC"


class TestEnabledLods:
    def test_all_enabled_by_default(self, tmp_path):
        """All LODs are enabled by default (no 'enabled' key)."""
        proj = Project.create(tmp_path / "p", "T")
        enabled = proj.get_enabled_lods()
        assert len(enabled) == len(proj.lod_levels)

    def test_some_disabled(self, tmp_path):
        """Disabled LODs are filtered out."""
        proj = Project.create(tmp_path / "p", "T")
        proj.set_lod_enabled(0, False)
        proj.set_lod_enabled(2, False)
        enabled = proj.get_enabled_lods()
        total = len(proj.lod_levels)
        assert len(enabled) == total - 2

    def test_set_lod_enabled_persistence(self, tmp_path):
        """set_lod_enabled persists to disk."""
        proj = Project.create(tmp_path / "p", "T")
        proj.set_lod_enabled(1, False)
        reloaded = Project(proj.root)
        assert reloaded.lod_levels[1]["enabled"] is False

    def test_set_lod_enabled_invalid_index(self, tmp_path):
        """Invalid index is a no-op (no crash)."""
        proj = Project.create(tmp_path / "p", "T")
        proj.set_lod_enabled(999, False)  # should not raise
        proj.set_lod_enabled(-1, False)  # should not raise


class TestLodDistances:
    def test_default_distances(self, tmp_path):
        """Default distances match PlayCanvas defaults, length matches LOD count."""
        proj = Project.create(tmp_path / "p", "T")
        distances = proj.lod_distances
        assert len(distances) == len(proj.lod_levels)
        assert distances[0] == 5  # First PlayCanvas default

    def test_set_lod_distances(self, tmp_path):
        """Custom distances persist."""
        proj = Project.create(tmp_path / "p", "T")
        custom = [10, 20, 30, 40, 50, 60]
        proj.set_lod_distances(custom)
        assert proj.lod_distances == custom
        reloaded = Project(proj.root)
        assert reloaded.lod_distances == custom


class TestEnabledSteps:
    def test_default_enabled_steps(self, tmp_path):
        """Clean disabled by default, others enabled."""
        proj = Project.create(tmp_path / "p", "T")
        assert proj.is_step_enabled("clean") is False
        for step in ["train", "assemble", "export"]:
            assert proj.is_step_enabled(step) is True

    def test_set_step_enabled(self, tmp_path):
        """Disable a step and verify."""
        proj = Project.create(tmp_path / "p", "T")
        proj.set_step_enabled("assemble", False)
        assert proj.is_step_enabled("assemble") is False
        assert proj.is_step_enabled("train") is True  # others unchanged

    def test_step_enabled_persistence(self, tmp_path):
        """set_step_enabled persists."""
        proj = Project.create(tmp_path / "p", "T")
        proj.set_step_enabled("train", False)
        reloaded = Project(proj.root)
        assert reloaded.is_step_enabled("train") is False

    def test_unknown_step_defaults_true(self, tmp_path):
        """Unknown step defaults to enabled."""
        proj = Project.create(tmp_path / "p", "T")
        assert proj.is_step_enabled("nonexistent") is True


class TestCdnName:
    def test_cdn_name_defaults_to_project_name(self, tmp_path):
        """cdn_name defaults to project name when not set."""
        proj = Project.create(tmp_path / "p", "MyProject")
        assert proj.cdn_name == "MyProject"

    def test_cdn_name_empty_defaults_to_project_name(self, tmp_path):
        """cdn_name empty string still defaults to project name."""
        proj = Project.create(tmp_path / "p", "MyProject")
        proj.set_cdn_name("")
        assert proj.cdn_name == "MyProject"

    def test_cdn_name_set_and_persist(self, tmp_path):
        """set_cdn_name persists and overrides default."""
        proj = Project.create(tmp_path / "p", "MyProject")
        proj.set_cdn_name("custom_folder")
        assert proj.cdn_name == "custom_folder"
        reloaded = Project(proj.root)
        assert reloaded.cdn_name == "custom_folder"


class TestThumbnailPath:
    def test_thumbnail_path(self, tmp_path):
        """thumbnail_path points to root/thumbnail.jpg."""
        proj = Project.create(tmp_path / "p", "T")
        assert proj.thumbnail_path == proj.root / "thumbnail.jpg"


class TestHistory:
    def test_record_step_appends_history(self, tmp_path):
        """record_step with terminal status appends to history."""
        proj = Project.create(tmp_path / "p", "T")
        proj.record_step("clean", "completed", summary={"cameras_kept": 42})
        history = proj.get_history()
        assert len(history) == 1
        assert history[0]["step"] == "clean"
        assert history[0]["status"] == "completed"
        assert history[0]["summary"]["cameras_kept"] == 42

    def test_running_status_not_in_history(self, tmp_path):
        """Intermediate statuses like 'running' are NOT appended to history."""
        proj = Project.create(tmp_path / "p", "T")
        proj.record_step("clean", "running")
        assert proj.get_history() == []

    def test_waiting_status_not_in_history(self, tmp_path):
        """'waiting' status is NOT appended to history."""
        proj = Project.create(tmp_path / "p", "T")
        proj.record_step("review", "waiting")
        assert proj.get_history() == []

    def test_history_newest_first(self, tmp_path):
        """get_history() returns newest first."""
        proj = Project.create(tmp_path / "p", "T")
        proj.record_step("clean", "completed")
        proj.record_step("train", "completed")
        history = proj.get_history()
        assert history[0]["step"] == "train"
        assert history[1]["step"] == "clean"

    def test_history_backward_compat(self, tmp_path):
        """Old projects without 'history' key return empty list."""
        proj = Project.create(tmp_path / "p", "T")
        # Simulate old state.json without history key
        proj.state.pop("history", None)
        proj._save_state()
        reloaded = Project(proj.root)
        assert reloaded.get_history() == []

    def test_history_limit(self, tmp_path):
        """History is capped at _HISTORY_MAX entries."""
        proj = Project.create(tmp_path / "p", "T")
        for i in range(120):
            proj.record_step("clean", "completed", summary={"run": i})
        assert len(proj.state.get("history", [])) == 100
        # Newest kept
        assert proj.get_history()[0]["summary"]["run"] == 119

    def test_history_with_started_at(self, tmp_path):
        """Passing started_at computes duration."""
        proj = Project.create(tmp_path / "p", "T")
        proj.record_step(
            "export", "completed",
            summary={"uploaded": 5},
            started_at="2026-02-13T14:30:00+00:00",
        )
        entry = proj.get_history()[0]
        assert entry["started_at"] == "2026-02-13T14:30:00+00:00"
        assert entry["duration_s"] is not None
        assert entry["duration_s"] >= 0

    def test_history_trims_failed_files(self, tmp_path):
        """Large failed_files lists are trimmed in history copies."""
        proj = Project.create(tmp_path / "p", "T")
        big_summary = {"failed_files": [f"file_{i}" for i in range(50)]}
        proj.record_step("export", "failed", summary=big_summary, error="test")
        entry = proj.get_history()[0]
        assert len(entry["summary"]["failed_files"]) == 3
        # Original summary in steps dict is untrimmed
        step_summary = proj.get_step_summary("export")
        assert len(step_summary["failed_files"]) == 50

    def test_failed_and_cancelled_in_history(self, tmp_path):
        """Failed and cancelled statuses are logged to history."""
        proj = Project.create(tmp_path / "p", "T")
        proj.record_step("train", "failed", error="CUDA OOM")
        proj.record_step("export", "cancelled")
        history = proj.get_history()
        assert len(history) == 2
        assert history[0]["step"] == "export"
        assert history[0]["status"] == "cancelled"
        assert history[1]["step"] == "train"
        assert history[1]["error"] == "CUDA OOM"
