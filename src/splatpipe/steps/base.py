"""Abstract base class for pipeline steps.

Each step:
- Takes a Project and config
- Runs its work
- Writes a _debug.json with full diagnostics
- Returns structured results (no try/except — failures surface)
"""

import json
import platform
import sys
import shutil
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from ..core.project import Project


class PipelineStep(ABC):
    """Base class for all pipeline steps."""

    def __init__(self, project: Project, config: dict):
        self.project = project
        self.config = config

    @property
    @abstractmethod
    def step_name(self) -> str:
        """Identifier for this step (used in debug JSON filenames and state)."""

    @property
    @abstractmethod
    def output_folder(self) -> str:
        """Project subfolder name for outputs."""

    def execute(self) -> dict:
        """Run the step, write debug JSON, return results."""
        output_dir = self.project.get_folder(self.output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)

        started_at = datetime.now(timezone.utc).isoformat()
        t0 = time.time()

        # Run the actual work
        result = self.run(output_dir)

        duration = time.time() - t0
        result["step"] = self.step_name
        result["started_at"] = started_at
        result["duration_s"] = round(duration, 2)
        result["environment"] = self._get_environment()

        # Write debug JSON
        debug_path = output_dir / f"{self.step_name}_debug.json"
        self._write_debug_json(debug_path, result)

        # Record in project state
        summary = result.get("summary", {})
        self.project.record_step(self.step_name, "completed", summary=summary)

        return result

    @abstractmethod
    def run(self, output_dir: Path) -> dict:
        """Execute the step's work. Return a dict of results/debug data.

        Must not catch exceptions — let them propagate for clear failure.
        """

    def _get_environment(self) -> dict:
        return {
            "python_version": sys.version,
            "platform": platform.platform(),
            "disk_free_gb": self._disk_free_gb(),
        }

    def _disk_free_gb(self) -> float | None:
        root = self.project.root
        usage = shutil.disk_usage(root)
        return round(usage.free / (1024 ** 3), 2)

    def _write_debug_json(self, path: Path, data: dict) -> None:
        """Write debug JSON, converting non-serializable types."""

        def default(obj):
            if isinstance(obj, set):
                return list(obj)
            if isinstance(obj, Path):
                return str(obj)
            raise TypeError(f"Not JSON serializable: {type(obj)}")

        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=default)

    @staticmethod
    def file_stats(path: Path) -> dict:
        """Get basic file stats for debug output."""
        if not path.exists():
            return {"exists": False}
        size = path.stat().st_size
        return {
            "path": str(path),
            "size_bytes": size,
            "size_mb": round(size / (1024 ** 2), 2),
        }
