"""Project class: folder scaffolding, state.json CRUD.

No fixed stage ordering — each CLI command checks its own prerequisites
and updates state.json independently.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

from .constants import (
    DEFAULT_LOD_LEVELS,
    PROJECT_FOLDERS,
    FOLDER_COLMAP_SOURCE,
    STEP_CLEAN,
    STEP_TRAIN,
    STEP_REVIEW,
    STEP_ASSEMBLE,
    STEP_EXPORT,
)

ALL_STEPS = [STEP_CLEAN, STEP_TRAIN, STEP_REVIEW, STEP_ASSEMBLE, STEP_EXPORT]


class Project:
    """Manages a single splatpipe project."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.state_path = self.root / "state.json"
        self.config_path = self.root / "project.toml"
        self._state: dict | None = None

    @classmethod
    def create(
        cls,
        root: Path,
        name: str,
        *,
        trainer: str = "postshot",
        lod_levels: list[dict] | None = None,
        colmap_source: str | None = None,
        enabled_steps: dict[str, bool] | None = None,
    ) -> "Project":
        """Create a new project with folder scaffolding and initial state."""
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)

        for folder in PROJECT_FOLDERS:
            (root / folder).mkdir(exist_ok=True)

        if lod_levels is None:
            lod_levels = [
                {"name": n, "max_splats": s} for n, s in DEFAULT_LOD_LEVELS
            ]

        if enabled_steps is None:
            enabled_steps = {s: True for s in ALL_STEPS}

        state = {
            "name": name,
            "trainer": trainer,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "lod_levels": lod_levels,
            "colmap_source": colmap_source,
            "alignment_file": "",
            "has_thumbnail": False,
            "enabled_steps": enabled_steps,
            "steps": {},
        }

        project = cls(root)
        project._state = state
        project._save_state()
        return project

    @property
    def state(self) -> dict:
        if self._state is None:
            self._state = self._load_state()
        return self._state

    @property
    def name(self) -> str:
        return self.state["name"]

    @property
    def trainer(self) -> str:
        return self.state.get("trainer", "postshot")

    @property
    def lod_levels(self) -> list[dict]:
        return self.state["lod_levels"]

    @property
    def alignment_file(self) -> str:
        return self.state.get("alignment_file", "")

    @property
    def has_thumbnail(self) -> bool:
        return self.state.get("has_thumbnail", False)

    @property
    def thumbnail_path(self) -> Path:
        return self.root / "thumbnail.jpg"

    @property
    def enabled_steps(self) -> dict[str, bool]:
        return self.state.get("enabled_steps", {s: True for s in ALL_STEPS})

    def is_step_enabled(self, step_name: str) -> bool:
        """Check if a step is enabled (defaults to True for unknown steps)."""
        return self.enabled_steps.get(step_name, True)

    def set_step_enabled(self, step_name: str, enabled: bool) -> None:
        """Enable or disable a step and save state."""
        if "enabled_steps" not in self.state:
            self.state["enabled_steps"] = {s: True for s in ALL_STEPS}
        self.state["enabled_steps"][step_name] = enabled
        self._save_state()

    def set_name(self, name: str) -> None:
        self.state["name"] = name
        self._save_state()

    def set_trainer(self, trainer: str) -> None:
        self.state["trainer"] = trainer
        self._save_state()

    def set_lod_levels(self, levels: list[dict]) -> None:
        self.state["lod_levels"] = levels
        self._save_state()

    def set_alignment_file(self, path: str) -> None:
        self.state["alignment_file"] = path
        self._save_state()

    @property
    def colmap_source(self) -> str:
        return self.state.get("colmap_source", "")

    def set_colmap_source(self, path: str) -> None:
        self.state["colmap_source"] = path
        self._save_state()

    @property
    def export_mode(self) -> str:
        return self.state.get("export_mode", "folder")

    def set_export_mode(self, mode: str) -> None:
        self.state["export_mode"] = mode
        self._save_state()

    @property
    def export_folder(self) -> str:
        return self.state.get("export_folder", "")

    def set_export_folder(self, path: str) -> None:
        self.state["export_folder"] = path
        self._save_state()

    # PlayCanvas engine default: [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60]
    PLAYCANVAS_DEFAULT_DISTANCES = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60]

    @property
    def lod_distances(self) -> list[float]:
        """Viewer switch distances per LOD (meters). Defaults to PlayCanvas engine defaults."""
        saved = self.state.get("lod_distances")
        if saved:
            return saved
        # Generate defaults matching PlayCanvas engine: 5m increments
        n = len(self.lod_levels)
        return self.PLAYCANVAS_DEFAULT_DISTANCES[:n]

    def set_lod_distances(self, distances: list[float]) -> None:
        self.state["lod_distances"] = distances
        self._save_state()

    def set_has_thumbnail(self, val: bool) -> None:
        self.state["has_thumbnail"] = val
        self._save_state()

    @property
    def step_settings(self) -> dict:
        return self.state.get("step_settings", {})

    def set_step_settings(self, step_name: str, settings: dict) -> None:
        if "step_settings" not in self.state:
            self.state["step_settings"] = {}
        self.state["step_settings"][step_name] = settings
        self._save_state()

    def get_enabled_lods(self) -> list[dict]:
        """Return only LODs where enabled is True (or missing, defaults to True)."""
        return [lod for lod in self.lod_levels if lod.get("enabled", True)]

    def set_lod_enabled(self, index: int, enabled: bool) -> None:
        """Enable or disable a specific LOD level."""
        if 0 <= index < len(self.lod_levels):
            self.lod_levels[index]["enabled"] = enabled
            self._save_state()

    def get_folder(self, folder_name: str) -> Path:
        """Get the path to a project subfolder."""
        return self.root / folder_name

    def colmap_dir(self) -> Path:
        """Return the COLMAP source directory (resolves symlinks/junctions).

        Falls back to state.json ``colmap_source`` when the expected
        ``01_colmap_source`` folder doesn't exist on disk.
        """
        source = self.get_folder(FOLDER_COLMAP_SOURCE)
        if source.is_symlink() or (hasattr(source, 'is_junction') and source.is_junction()):
            return source.resolve()
        if source.is_dir():
            return source
        # Fallback: use colmap_source path from state.json
        raw = self.state.get("colmap_source", "")
        if raw:
            p = Path(raw)
            if p.is_dir():
                return p
        return source

    def record_step(
        self,
        step_name: str,
        status: str,
        *,
        summary: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Record the result of a step in state.json."""
        if "steps" not in self.state:
            self.state["steps"] = {}
        self.state["steps"][step_name] = {
            "status": status,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "error": error,
        }
        self._save_state()

    def get_step_status(self, step_name: str) -> str | None:
        """Get the status of a step, or None if not yet run."""
        step = self.state.get("steps", {}).get(step_name)
        if step is None:
            return None
        return step["status"]

    def reset_step(self, step_name: str) -> None:
        """Remove a step's entry from state.json, resetting it to 'pending'."""
        steps = self.state.get("steps", {})
        if step_name in steps:
            del steps[step_name]
            self._save_state()

    def reset_all_steps(self) -> None:
        """Remove all step entries from state.json."""
        self.state["steps"] = {}
        self._save_state()

    def get_step_summary(self, step_name: str) -> dict | None:
        """Get the summary dict of a step, or None."""
        step = self.state.get("steps", {}).get(step_name)
        if step is None:
            return None
        return step.get("summary")

    def _load_state(self) -> dict:
        with open(self.state_path, "r") as f:
            return json.load(f)

    def _save_state(self) -> None:
        with open(self.state_path, "w") as f:
            json.dump(self._state, f, indent=2)

    @classmethod
    def find(cls, start: Path | None = None) -> "Project":
        """Search parent directories for state.json.

        Raises FileNotFoundError if no project is found.
        """
        start = Path(start) if start else Path.cwd()
        current = start.resolve()
        while True:
            if (current / "state.json").exists():
                return cls(current)
            parent = current.parent
            if parent == current:
                break
            current = parent
        raise FileNotFoundError(
            f"No splatpipe project found (searched from {start})"
        )

    def __repr__(self) -> str:
        return f"Project({self.root}, name={self.name!r})"
