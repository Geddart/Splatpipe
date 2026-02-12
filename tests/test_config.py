"""Tests for config loading and merging."""


import pytest

from splatpipe.core.config import load_defaults, load_project_config, get_tool_path


def test_defaults_load():
    """Verify defaults.toml loads and has expected sections."""
    config = load_defaults()
    assert "tools" in config
    assert "colmap_clean" in config
    assert "postshot" in config
    assert "lichtfeld" in config
    assert config["colmap_clean"]["kdtree_threshold"] == 0.001


def test_project_override(tmp_path):
    """Project.toml overrides defaults."""
    import tomli_w

    project_toml = tmp_path / "project.toml"
    with open(project_toml, "wb") as f:
        tomli_w.dump({
            "colmap_clean": {"kdtree_threshold": 0.005},
            "custom_key": "hello",
        }, f)

    config = load_project_config(project_toml)
    # Overridden value
    assert config["colmap_clean"]["kdtree_threshold"] == 0.005
    # Inherited default
    assert config["colmap_clean"]["outlier_threshold_auto"] is True
    # New key
    assert config["custom_key"] == "hello"


def test_missing_project_toml(tmp_path):
    """Missing project.toml just returns defaults."""
    config = load_project_config(tmp_path / "nonexistent.toml")
    assert config == load_defaults()


def test_missing_tool_path():
    """Missing tool raises clear error."""
    config = {"tools": {}}
    with pytest.raises(ValueError, match="Tool path not configured"):
        get_tool_path(config, "realitycapture")


def test_nonexistent_tool_path():
    """Tool at nonexistent path raises FileNotFoundError."""
    config = {"tools": {"fake_tool": r"C:\nonexistent\tool.exe"}}
    with pytest.raises(FileNotFoundError, match="Tool not found"):
        get_tool_path(config, "fake_tool")
