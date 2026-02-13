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
    def test_default_all_enabled(self, tmp_path):
        """All steps enabled by default."""
        proj = Project.create(tmp_path / "p", "T")
        for step in ["clean", "train", "assemble", "export"]:
            assert proj.is_step_enabled(step) is True

    def test_set_step_enabled(self, tmp_path):
        """Disable a step and verify."""
        proj = Project.create(tmp_path / "p", "T")
        proj.set_step_enabled("assemble", False)
        assert proj.is_step_enabled("assemble") is False
        assert proj.is_step_enabled("clean") is True  # others unchanged

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


class TestThumbnailPath:
    def test_thumbnail_path(self, tmp_path):
        """thumbnail_path points to root/thumbnail.jpg."""
        proj = Project.create(tmp_path / "p", "T")
        assert proj.thumbnail_path == proj.root / "thumbnail.jpg"
