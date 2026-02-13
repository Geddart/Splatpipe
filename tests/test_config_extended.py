"""Extended tests for config helpers: tool path resolution, save/roundtrip, deep merge."""

import tomllib

import pytest
import tomli_w

from splatpipe.core.config import (
    get_postshot_cli,
    get_postshot_gui,
    save_defaults,
    load_defaults,
    save_project_config,
    check_dependencies,
    _deep_merge,
)


# --- Tool path helpers ---


class TestGetPostshotCli:
    def test_valid_root(self, tmp_path):
        """Returns bin/postshot-cli.exe when root and exe exist."""
        bin_dir = tmp_path / "postshot" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "postshot-cli.exe").write_text("")
        config = {"tools": {"postshot": str(tmp_path / "postshot")}}
        result = get_postshot_cli(config)
        assert result == bin_dir / "postshot-cli.exe"

    def test_missing_config(self):
        """Raises ValueError when postshot not in config."""
        with pytest.raises(ValueError, match="not configured"):
            get_postshot_cli({"tools": {}})

    def test_root_exists_no_cli(self, tmp_path):
        """Raises FileNotFoundError when root exists but CLI binary missing."""
        root = tmp_path / "postshot"
        root.mkdir()
        (root / "bin").mkdir()
        config = {"tools": {"postshot": str(root)}}
        with pytest.raises(FileNotFoundError, match="Postshot CLI not found"):
            get_postshot_cli(config)


class TestGetPostshotGui:
    def test_valid_root(self, tmp_path):
        """Returns bin/postshot.exe when root and exe exist."""
        bin_dir = tmp_path / "postshot" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "postshot.exe").write_text("")
        config = {"tools": {"postshot": str(tmp_path / "postshot")}}
        result = get_postshot_gui(config)
        assert result == bin_dir / "postshot.exe"

    def test_missing_config(self):
        """Raises ValueError when postshot not in config."""
        with pytest.raises(ValueError, match="not configured"):
            get_postshot_gui({"tools": {}})

    def test_root_exists_no_gui(self, tmp_path):
        """Raises FileNotFoundError when root exists but GUI binary missing."""
        root = tmp_path / "postshot"
        root.mkdir()
        (root / "bin").mkdir()
        config = {"tools": {"postshot": str(root)}}
        with pytest.raises(FileNotFoundError, match="Postshot GUI not found"):
            get_postshot_gui(config)



# --- Save / roundtrip ---


class TestSaveDefaults:
    def test_save_and_reload(self, tmp_path, monkeypatch):
        """save_defaults writes valid TOML that load_defaults reads back."""
        toml_path = tmp_path / "defaults.toml"
        # Write initial config
        with open(toml_path, "wb") as f:
            tomli_w.dump({"tools": {}, "colmap_clean": {"kdtree_threshold": 0.001}}, f)

        monkeypatch.setattr("splatpipe.core.config.DEFAULTS_PATH", toml_path)

        config = load_defaults()
        config["colmap_clean"]["kdtree_threshold"] = 0.005
        config["new_section"] = {"key": "value"}
        save_defaults(config)

        reloaded = load_defaults()
        assert reloaded["colmap_clean"]["kdtree_threshold"] == 0.005
        assert reloaded["new_section"]["key"] == "value"


class TestSaveProjectConfig:
    def test_roundtrip(self, tmp_path):
        """save_project_config writes TOML that can be read back."""
        toml_path = tmp_path / "project.toml"
        config = {"postshot": {"profile": "Splat MCMC"}, "custom": {"flag": True}}
        save_project_config(toml_path, config)

        with open(toml_path, "rb") as f:
            reloaded = tomllib.load(f)
        assert reloaded["postshot"]["profile"] == "Splat MCMC"
        assert reloaded["custom"]["flag"] is True


# --- check_dependencies ---


class TestCheckDependencies:
    def test_known_packages(self):
        """Known installed packages return True."""
        result = check_dependencies()
        assert result["numpy"] is True
        assert result["fastapi"] is True

    def test_returns_dict(self):
        """Returns a dict with all expected packages."""
        result = check_dependencies()
        assert isinstance(result, dict)
        assert "numpy" in result
        assert "tomli_w" in result


# --- _deep_merge ---


class TestDeepMerge:
    def test_nested_override(self):
        """Override value in nested dict."""
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"x": 10}}
        _deep_merge(base, override)
        assert base["a"]["x"] == 10
        assert base["a"]["y"] == 2  # preserved
        assert base["b"] == 3

    def test_new_keys_added(self):
        """New keys in override are added to base."""
        base = {"a": 1}
        _deep_merge(base, {"b": 2, "c": {"d": 3}})
        assert base["b"] == 2
        assert base["c"]["d"] == 3

    def test_non_dict_overwrite(self):
        """Non-dict value overwrites dict key."""
        base = {"a": {"x": 1}}
        _deep_merge(base, {"a": "string"})
        assert base["a"] == "string"

    def test_dict_overwrites_non_dict(self):
        """Dict value overwrites non-dict key."""
        base = {"a": "string"}
        _deep_merge(base, {"a": {"x": 1}})
        assert base["a"] == {"x": 1}
