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
)


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

        state = {
            "name": name,
            "trainer": trainer,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "lod_levels": lod_levels,
            "colmap_source": colmap_source,
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

    def get_folder(self, folder_name: str) -> Path:
        """Get the path to a project subfolder."""
        return self.root / folder_name

    def colmap_dir(self) -> Path:
        """Return the COLMAP source directory (resolves symlinks)."""
        source = self.get_folder(FOLDER_COLMAP_SOURCE)
        if source.is_symlink():
            return source.resolve()
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
        self.state["steps"][step_name] = {
            "status": status,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "error": error,
        }
        self._save_state()

    def get_step_status(self, step_name: str) -> str | None:
        """Get the status of a step, or None if not yet run."""
        step = self.state["steps"].get(step_name)
        if step is None:
            return None
        return step["status"]

    def get_step_summary(self, step_name: str) -> dict | None:
        """Get the summary dict of a step, or None."""
        step = self.state["steps"].get(step_name)
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
