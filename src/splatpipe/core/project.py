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


def _trim_summary(summary: dict | None) -> dict | None:
    """Create a compact copy of summary for history storage."""
    if not summary:
        return None
    trimmed = dict(summary)
    if "failed_files" in trimmed:
        trimmed["failed_files"] = trimmed["failed_files"][:3]
    return trimmed


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
        trainer: str | None = None,
        lod_levels: list[dict] | None = None,
        colmap_source: str | None = None,
        source_type: str = "",
        enabled_steps: dict[str, bool] | None = None,
    ) -> "Project":
        """Create a new project with folder scaffolding and initial state.

        When trainer is None, defaults to ``passthrough`` for finished-splat
        sources (.psht / .ply) and ``postshot`` otherwise.
        """
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)

        for folder in PROJECT_FOLDERS:
            (root / folder).mkdir(exist_ok=True)

        if trainer is None:
            trainer = "passthrough" if source_type in ("postshot", "ply") else "postshot"

        if lod_levels is None:
            if trainer == "passthrough":
                # Passthrough has nothing to retrain — single LOD only.
                lod_levels = [{"name": "lod0", "max_splats": 0}]
            else:
                lod_levels = [
                    {"name": n, "max_splats": s} for n, s in DEFAULT_LOD_LEVELS
                ]

        if enabled_steps is None:
            enabled_steps = {s: s != STEP_CLEAN for s in ALL_STEPS}
            if trainer == "passthrough":
                # Passthrough doesn't operate on COLMAP data.
                enabled_steps[STEP_CLEAN] = False

        state = {
            "name": name,
            "trainer": trainer,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "lod_levels": lod_levels,
            "colmap_source": colmap_source,
            "source_type": source_type,
            "alignment_file": "",
            "has_thumbnail": False,
            "enabled_steps": enabled_steps,
            "steps": {},
        }

        # Uncapped splat budget by default for passthrough — show full quality.
        if trainer == "passthrough":
            state["scene_config"] = {"splat_budget": 0}

        project = cls(root)
        project._state = state
        project._save_state()
        return project

    @property
    def state(self) -> dict:
        if self._state is None:
            self._state = self._load_state()
            if self._migrate_state(self._state):
                self._save_state()
        return self._state

    @staticmethod
    def _migrate_state(state: dict) -> bool:
        """Run idempotent in-place migrations on a freshly loaded state dict.

        Returns True if any field was added/modified (caller should persist).
        """
        changed = False

        scene_config = state.get("scene_config") or {}
        annotations = scene_config.get("annotations")
        if isinstance(annotations, list):
            used_ids = {a["id"] for a in annotations if isinstance(a, dict) and a.get("id")}
            next_n = 1
            for ann in annotations:
                if not isinstance(ann, dict) or ann.get("id"):
                    continue
                while f"a{next_n}" in used_ids:
                    next_n += 1
                ann["id"] = f"a{next_n}"
                used_ids.add(ann["id"])
                next_n += 1
                changed = True
            if changed:
                state.setdefault("scene_config", {})["annotations"] = annotations

        return changed

    @property
    def name(self) -> str:
        return self.state["name"]

    @property
    def trainer(self) -> str:
        return self.state.get("trainer", "postshot")

    @property
    def renderer(self) -> str:
        """Output viewer renderer: 'playcanvas' (default) or 'spark'."""
        return self.state.get("renderer", "playcanvas")

    def set_renderer(self, renderer: str) -> None:
        if renderer not in ("playcanvas", "spark"):
            raise ValueError(f"renderer must be 'playcanvas' or 'spark', got {renderer!r}")
        self.state["renderer"] = renderer
        self._save_state()

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
        return self.state.get("enabled_steps", {s: s != STEP_CLEAN for s in ALL_STEPS})

    def is_step_enabled(self, step_name: str) -> bool:
        """Check if a step is enabled (defaults to True for unknown steps)."""
        return self.enabled_steps.get(step_name, True)

    def set_step_enabled(self, step_name: str, enabled: bool) -> None:
        """Enable or disable a step and save state."""
        if "enabled_steps" not in self.state:
            self.state["enabled_steps"] = {s: s != STEP_CLEAN for s in ALL_STEPS}
        self.state["enabled_steps"][step_name] = enabled
        self._save_state()

    def set_name(self, name: str) -> None:
        self.state["name"] = name
        self._save_state()

    def set_trainer(self, trainer: str) -> None:
        """Set the trainer; passthrough also trims LODs and disables clean step."""
        self.state["trainer"] = trainer
        if trainer == "passthrough":
            # Single LOD only — passthrough doesn't generate alternate resolutions.
            levels = self.state.get("lod_levels", [])
            if len(levels) > 1:
                self.state["lod_levels"] = [levels[0]]
            # Clean step doesn't apply to finished-splat sources.
            es = self.state.setdefault("enabled_steps", {})
            es[STEP_CLEAN] = False
            # Uncapped splat budget so the user sees full pretrained quality.
            sc = self.state.setdefault("scene_config", {})
            sc["splat_budget"] = 0
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
    def source_type(self) -> str:
        """Source type: 'postshot' for .psht, 'ply' for raw PLY, or alignment format for directories."""
        st = self.state.get("source_type", "")
        if st:
            return st
        # Fallback: detect from colmap_source path
        raw = self.colmap_source
        if raw:
            ext = Path(raw).suffix.lower()
            if ext == ".psht":
                return "postshot"
            if ext == ".ply":
                return "ply"
        return ""

    def set_source_type(self, source_type: str) -> None:
        self.state["source_type"] = source_type
        self._save_state()

    def source_file(self) -> Path | None:
        """Return path to the local copy of a single-file source (.psht or .ply)."""
        st = self.source_type
        if st == "postshot":
            local = self.get_folder(FOLDER_COLMAP_SOURCE) / "source.psht"
        elif st == "ply":
            local = self.get_folder(FOLDER_COLMAP_SOURCE) / "source.ply"
        else:
            return None
        return local if local.exists() else None

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

    @property
    def cdn_name(self) -> str:
        """CDN remote folder name. Defaults to project name."""
        return self.state.get("cdn_name", "") or self.name

    def set_cdn_name(self, name: str) -> None:
        self.state["cdn_name"] = name
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

    DEFAULT_SCENE_CONFIG = {
        "camera": {
            "enabled": False,
            "pitch_min": -89, "pitch_max": 89,
            "zoom_min": 1, "zoom_max": 200,
            "ground_height": 0.3, "bounds_radius": 150,
        },
        "splat_budget": 0,  # 0 = platform default (4M desktop / 1M mobile)
        "annotations": [],
        "background": {"type": "color", "color": "#1a1a1a", "skybox": ""},
        "postprocessing": {
            "tonemapping": "neutral", "exposure": 1.5,
            "bloom": False, "bloom_intensity": 0.01,
            "vignette": False, "vignette_intensity": 0.5,
        },
        "audio": [],
        "camera_paths": [],
        "default_path_id": None,
        "spark_render": {
            "lod_splat_scale": 1.0,
            "lod_render_scale": 1.0,
            "foveation": {
                "enabled": False,
                "cone_fov0": 30.0,
                "cone_fov": 90.0,
                "cone_foveate": 2.0,
                "behind_foveate": 4.0,
            },
            "ondemand_lod_fallback": True,
        },
    }

    @property
    def scene_config(self) -> dict:
        """Scene config with defaults <- saved overrides (deep merge for dicts, replace for lists)."""
        import copy
        result = copy.deepcopy(self.DEFAULT_SCENE_CONFIG)
        saved = self.state.get("scene_config", {})
        for key in result:
            if key in saved:
                if isinstance(result[key], dict):
                    result[key].update(saved[key])
                else:
                    result[key] = saved[key]
        return result

    def set_scene_config_section(self, section: str, data) -> None:
        """Update one section of scene_config.

        For dict sections, merges keys (so a partial form submit only changes
        the fields it sent). For scalar sections, replaces the value.
        """
        if "scene_config" not in self.state:
            self.state["scene_config"] = {}
        existing = self.state["scene_config"].get(section)
        if isinstance(data, dict) and isinstance(existing, dict):
            existing.update(data)
        else:
            self.state["scene_config"][section] = data
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
        if source.is_symlink() or source.is_junction():
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

    _HISTORY_MAX = 100

    def record_step(
        self,
        step_name: str,
        status: str,
        *,
        summary: dict | None = None,
        error: str | None = None,
        started_at: str | None = None,
    ) -> None:
        """Record the result of a step in state.json.

        Updates the per-step latest status AND appends terminal statuses
        (completed, failed, cancelled) to the history log.
        """
        if "steps" not in self.state:
            self.state["steps"] = {}

        completed_at = datetime.now(timezone.utc).isoformat()
        self.state["steps"][step_name] = {
            "status": status,
            "completed_at": completed_at,
            "summary": summary,
            "error": error,
        }

        if status in ("completed", "failed", "cancelled"):
            self._append_history({
                "step": step_name,
                "status": status,
                "started_at": started_at or completed_at,
                "completed_at": completed_at,
                "duration_s": None,
                "summary": _trim_summary(summary),
                "error": error,
            })

        self._save_state()

    def _append_history(self, entry: dict) -> None:
        """Append an entry to the history log, trimming if over limit."""
        if "history" not in self.state:
            self.state["history"] = []

        # Compute duration if both timestamps present
        if entry.get("started_at") and entry.get("completed_at"):
            try:
                start = datetime.fromisoformat(entry["started_at"])
                end = datetime.fromisoformat(entry["completed_at"])
                entry["duration_s"] = round((end - start).total_seconds(), 1)
            except (ValueError, TypeError):
                pass

        self.state["history"].append(entry)

        if len(self.state["history"]) > self._HISTORY_MAX:
            self.state["history"] = self.state["history"][-self._HISTORY_MAX:]

    def get_history(self) -> list[dict]:
        """Return the history log (newest first)."""
        return list(reversed(self.state.get("history", [])))

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
        try:
            with open(self.state_path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            # Surface a readable message instead of a bare JSONDecodeError so
            # the runner's failure path logs something users can act on. Root
            # causes include partial writes from a prior crash and Resilio/AV
            # mid-sync interruptions.
            raise RuntimeError(
                f"state.json is corrupted at {self.state_path}: {e}"
            ) from e

    def _save_state(self) -> None:
        # Write atomically: full dump to a sibling .tmp, then os.replace swaps
        # it into place. Crashing mid-dump leaves the old state.json intact
        # instead of truncating it and breaking the next load.
        import os
        tmp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        with open(tmp_path, "w") as f:
            json.dump(self._state, f, indent=2)
        os.replace(tmp_path, self.state_path)

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
