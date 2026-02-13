"""Tests for pure helper functions in projects route module."""

from pathlib import Path


from splatpipe.web.routes.projects import (
    _format_size,
    _parse_lods,
    _parse_single_lod,
    _renumber_lods,
    _folder_stats,
    _clear_folder,
)


class TestFormatSize:
    def test_kilobytes(self):
        assert _format_size(512 * 1024) == "512 KB"

    def test_megabytes(self):
        result = _format_size(5 * 1024 * 1024)
        assert "5.0 MB" in result

    def test_gigabytes(self):
        result = _format_size(2 * 1024 * 1024 * 1024)
        assert "2.00 GB" in result

    def test_small_bytes(self):
        result = _format_size(100)
        assert "KB" in result  # <1KB still shows as KB


class TestParseLods:
    def test_standard_format(self):
        """Parse '20M,10M,5M' into LOD dicts."""
        lods = _parse_lods("20M,10M,5M")
        assert len(lods) == 3
        assert lods[0]["name"] == "lod0"
        assert lods[0]["max_splats"] == 20_000_000
        assert lods[1]["name"] == "lod1"
        assert lods[2]["max_splats"] == 5_000_000

    def test_k_suffix(self):
        """Parse '500K' into 500,000 splats."""
        lods = _parse_lods("500K")
        assert lods[0]["max_splats"] == 500_000
        assert lods[0]["name"] == "lod0"

    def test_raw_integer(self):
        """Parse raw integer string."""
        lods = _parse_lods("3000000")
        assert lods[0]["max_splats"] == 3_000_000

    def test_mixed_formats(self):
        """Parse mixed M, K, and raw formats."""
        lods = _parse_lods("5M, 1.5M, 500K")
        assert len(lods) == 3
        assert lods[0]["max_splats"] == 5_000_000
        assert lods[1]["max_splats"] == 1_500_000
        assert lods[2]["max_splats"] == 500_000


class TestParseSingleLod:
    def test_millions(self):
        lod = _parse_single_lod("5M", 2)
        assert lod["name"] == "lod2"
        assert lod["max_splats"] == 5_000_000

    def test_thousands(self):
        lod = _parse_single_lod("500K", 0)
        assert lod["name"] == "lod0"
        assert lod["max_splats"] == 500_000


class TestRenumberLods:
    def test_renumbers_after_removal(self):
        """After removing middle LOD, names are renumbered."""
        lods = [
            {"name": "lod0", "max_splats": 20_000_000},
            {"name": "lod2", "max_splats": 5_000_000},  # was index 2
        ]
        result = _renumber_lods(lods)
        assert result[0]["name"] == "lod0"
        assert result[1]["name"] == "lod1"  # renumbered to 1

    def test_preserves_splat_counts(self):
        """Renumbering doesn't change max_splats."""
        lods = [{"name": "old", "max_splats": 3_000_000}]
        result = _renumber_lods(lods)
        assert result[0]["max_splats"] == 3_000_000

    def test_preserves_extra_fields(self):
        """Renumbering preserves enabled, train_steps, and other fields."""
        lods = [
            {"name": "lod0", "max_splats": 20_000_000, "enabled": False, "train_steps": 50},
            {"name": "lod1", "max_splats": 5_000_000, "enabled": True},
        ]
        result = _renumber_lods(lods)
        assert result[0]["enabled"] is False
        assert result[0]["train_steps"] == 50
        assert result[1]["enabled"] is True
        assert result[1]["name"] == "lod1"


class TestFolderStats:
    def test_nonexistent_folder(self, tmp_path):
        stats = _folder_stats(tmp_path / "nope")
        assert stats["exists"] is False
        assert stats["file_count"] == 0
        assert stats["display"] == ""
        assert stats["file_list"] == []

    def test_empty_folder(self, tmp_path):
        folder = tmp_path / "empty"
        folder.mkdir()
        stats = _folder_stats(folder)
        assert stats["exists"] is True
        assert stats["file_count"] == 0
        assert stats["display"] == ""

    def test_folder_with_files(self, tmp_path):
        folder = tmp_path / "data"
        folder.mkdir()
        (folder / "a.txt").write_text("hello")
        (folder / "b.bin").write_bytes(b"x" * 1000)
        stats = _folder_stats(folder)
        assert stats["exists"] is True
        assert stats["file_count"] == 2
        assert stats["total_bytes"] == 5 + 1000
        assert "2 files" in stats["display"]
        assert len(stats["file_list"]) == 2

    def test_folder_with_subdir(self, tmp_path):
        """Subdirectories show aggregate size."""
        folder = tmp_path / "data"
        sub = folder / "subdir"
        sub.mkdir(parents=True)
        (sub / "file.txt").write_text("x" * 100)
        stats = _folder_stats(folder)
        assert stats["file_count"] == 1
        assert any("subdir/" in item for item in stats["file_list"])


class TestClearFolder:
    def test_clears_files(self, tmp_path):
        folder = tmp_path / "data"
        folder.mkdir()
        (folder / "a.txt").write_text("x")
        (folder / "b.txt").write_text("y")
        count, failed = _clear_folder(folder)
        assert count == 2
        assert failed == []
        assert folder.exists()  # folder itself preserved
        assert list(folder.iterdir()) == []

    def test_clears_subdirs(self, tmp_path):
        folder = tmp_path / "data"
        (folder / "sub").mkdir(parents=True)
        (folder / "sub" / "file.txt").write_text("x")
        count, failed = _clear_folder(folder)
        assert count == 1  # sub dir counted as one item
        assert failed == []
        assert folder.exists()
        assert list(folder.iterdir()) == []

    def test_nonexistent_folder(self, tmp_path):
        count, failed = _clear_folder(tmp_path / "nope")
        assert count == 0
        assert failed == []

    def test_locked_file_continues(self, tmp_path, monkeypatch):
        """Locked files are skipped; remaining items still deleted."""
        folder = tmp_path / "data"
        folder.mkdir()
        (folder / "locked.txt").write_text("x")
        (folder / "ok.txt").write_text("y")

        orig_unlink = Path.unlink
        def _fake_unlink(self, *a, **kw):
            if self.name == "locked.txt":
                raise OSError("locked")
            return orig_unlink(self, *a, **kw)

        monkeypatch.setattr(Path, "unlink", _fake_unlink)
        count, failed = _clear_folder(folder)
        assert count == 1
        assert failed == ["locked.txt"]
        assert (folder / "locked.txt").exists()
        assert not (folder / "ok.txt").exists()
