"""TOML config loader: defaults + per-project merge."""

import tomllib
from pathlib import Path

import tomli_w

DEFAULTS_PATH = Path(__file__).parent.parent.parent.parent / "config" / "defaults.toml"


def load_defaults() -> dict:
    """Load the global defaults.toml."""
    with open(DEFAULTS_PATH, "rb") as f:
        return tomllib.load(f)


def load_project_config(project_toml: Path) -> dict:
    """Load a per-project project.toml, merged over defaults."""
    defaults = load_defaults()
    if project_toml.exists():
        with open(project_toml, "rb") as f:
            overrides = tomllib.load(f)
        _deep_merge(defaults, overrides)
    return defaults


def save_project_config(project_toml: Path, config: dict) -> None:
    """Write a project.toml file."""
    with open(project_toml, "wb") as f:
        tomli_w.dump(config, f)


def get_tool_path(config: dict, tool_name: str) -> Path:
    """Get a tool path from config, raising if not found or nonexistent."""
    path_str = config.get("tools", {}).get(tool_name)
    if not path_str:
        raise ValueError(f"Tool path not configured: tools.{tool_name}")
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Tool not found at configured path: {path}")
    return path


def _deep_merge(base: dict, override: dict) -> None:
    """Merge override into base in-place, recursing into dicts."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
