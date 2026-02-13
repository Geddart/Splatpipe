"""TOML config loader: defaults + per-project merge."""

import shutil
import subprocess
import tomllib
from pathlib import Path

import tomli_w

DEFAULTS_PATH = Path(__file__).parent.parent.parent.parent / "config" / "defaults.toml"

# Standard install locations for auto-detection (root folders)
TOOL_SEARCH_PATHS: dict[str, list[str]] = {
    "postshot": [
        r"C:\Program Files\Jawset Postshot",
        r"C:\Program Files (x86)\Jawset Postshot",
    ],
    "lichtfeld_studio": [
        r"C:\Program Files\LichtFeld-Studio",
        r"C:\Program Files\LichtFeld Studio",
    ],
}


def load_defaults() -> dict:
    """Load the global defaults.toml."""
    with open(DEFAULTS_PATH, "rb") as f:
        return tomllib.load(f)


def save_defaults(config: dict) -> None:
    """Write the global defaults.toml."""
    with open(DEFAULTS_PATH, "wb") as f:
        tomli_w.dump(config, f)


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


def get_postshot_cli(config: dict) -> Path:
    """Get the Postshot CLI executable from the configured root folder."""
    root = get_tool_path(config, "postshot")
    cli = root / "bin" / "postshot-cli.exe"
    if not cli.exists():
        raise FileNotFoundError(f"Postshot CLI not found: {cli}")
    return cli


def get_postshot_gui(config: dict) -> Path:
    """Get the Postshot GUI executable from the configured root folder."""
    root = get_tool_path(config, "postshot")
    gui = root / "bin" / "postshot.exe"
    if not gui.exists():
        raise FileNotFoundError(f"Postshot GUI not found: {gui}")
    return gui


def get_lichtfeld_exe(config: dict) -> Path:
    """Get the LichtFeld Studio executable from the configured root folder."""
    root = get_tool_path(config, "lichtfeld_studio")
    exe = root / "bin" / "LichtFeld-Studio.exe"
    if not exe.exists():
        raise FileNotFoundError(f"LichtFeld Studio not found: {exe}")
    return exe



def auto_detect_tools() -> dict[str, str | None]:
    """Scan standard install locations for pipeline tools.

    Returns dict of {tool_name: found_path_or_None}.
    """
    found: dict[str, str | None] = {}

    for tool_name, search_paths in TOOL_SEARCH_PATHS.items():
        found[tool_name] = None
        # Check known paths first
        for path_str in search_paths:
            if Path(path_str).exists():
                found[tool_name] = path_str
                break
        # Fall back to PATH lookup
        if found[tool_name] is None:
            exe_name = Path(search_paths[0]).name if search_paths else tool_name
            which_result = shutil.which(exe_name)
            if which_result:
                found[tool_name] = which_result

    # splat-transform: check via npx
    found["splat_transform"] = None
    which_npx = shutil.which("npx")
    if which_npx:
        try:
            proc = subprocess.run(
                ["npx", "@playcanvas/splat-transform", "--version"],
                capture_output=True, text=True, timeout=15,
            )
            if proc.returncode == 0:
                found["splat_transform"] = "splat-transform"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    # Also check if splat-transform is on PATH directly
    if found["splat_transform"] is None:
        which_st = shutil.which("splat-transform")
        if which_st:
            found["splat_transform"] = which_st

    return found


def check_dependencies() -> dict[str, bool]:
    """Check which Python packages are available."""
    packages = ["numpy", "scipy", "fastapi", "uvicorn", "jinja2",
                "sse_starlette", "typer", "rich", "tomli_w"]
    result = {}
    for pkg in packages:
        try:
            __import__(pkg)
            result[pkg] = True
        except ImportError:
            result[pkg] = False
    return result


def _deep_merge(base: dict, override: dict) -> None:
    """Merge override into base in-place, recursing into dicts."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
