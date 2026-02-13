"""Background pipeline runner: browser-independent execution.

Execution runs in a daemon thread. The SSE endpoint polls RunnerSnapshot
for state — browser disconnect has zero effect on execution.

All step execution logic lives here. steps.py becomes a thin HTTP/SSE adapter.
"""

import json
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..core.config import DEFAULTS_PATH
from ..core.constants import (
    FOLDER_COLMAP_CLEAN,
    FOLDER_OUTPUT,
    FOLDER_REVIEW,
    STEP_CLEAN,
    STEP_TRAIN,
    STEP_REVIEW,
    STEP_ASSEMBLE,
    STEP_EXPORT,
)
from ..core.project import Project
from ..steps.colmap_clean import ColmapCleanStep
from ..steps.lod_assembly import LodAssemblyStep
from ..steps.deploy import deploy_to_bunny, export_to_folder, load_bunny_env
from ..trainers.registry import get_trainer


STEP_ORDER = [STEP_CLEAN, STEP_TRAIN, STEP_REVIEW, STEP_ASSEMBLE, STEP_EXPORT]
STEP_LABELS = {
    STEP_CLEAN: "Clean COLMAP",
    STEP_TRAIN: "Train Splats",
    STEP_REVIEW: "Review Splats",
    STEP_ASSEMBLE: "Assemble LODs",
    STEP_EXPORT: "Export",
}


@dataclass(frozen=True)
class RunnerSnapshot:
    """Immutable, thread-safe snapshot of runner state."""
    status: str        # "running" | "completed" | "failed" | "cancelled"
    current_step: str  # e.g. "train"
    step_label: str    # e.g. "Running: Train Splats (2/3)"
    progress: float    # 0.0–1.0
    message: str       # e.g. "LOD lod2_5000k (1/3): Training — Step 234/500 kSteps"
    error: str | None
    updated_at: float  # time.monotonic()


class _CancelledError(Exception):
    """Raised when a run is cancelled."""


class PipelineRunner:
    """Executes pipeline steps in a background daemon thread."""

    def __init__(self, project_path: str, steps: list[str], config: dict):
        self._project_path = project_path
        self._steps = steps
        self._config = config
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._active_trainer = None
        self._snapshot = RunnerSnapshot(
            status="running",
            current_step=steps[0] if steps else "",
            step_label="Starting...",
            progress=0.0,
            message="",
            error=None,
            updated_at=time.monotonic(),
        )
        self._thread: threading.Thread | None = None

    @property
    def snapshot(self) -> RunnerSnapshot:
        with self._lock:
            return self._snapshot

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_event.set()
        # Kill active trainer subprocess if any
        trainer = self._active_trainer
        if trainer and hasattr(trainer, "_proc") and trainer._proc:
            try:
                trainer._proc.terminate()
            except OSError:
                pass

    def _update(self, **kwargs) -> None:
        with self._lock:
            vals = {
                "status": self._snapshot.status,
                "current_step": self._snapshot.current_step,
                "step_label": self._snapshot.step_label,
                "progress": self._snapshot.progress,
                "message": self._snapshot.message,
                "error": self._snapshot.error,
                "updated_at": time.monotonic(),
            }
            vals.update(kwargs)
            self._snapshot = RunnerSnapshot(**vals)

    def _check_cancel(self) -> None:
        if self._cancel_event.is_set():
            raise _CancelledError()

    def _run(self) -> None:
        proj_path = Path(self._project_path)
        if not (proj_path / "state.json").exists():
            self._update(status="failed", error=f"Project not found: {proj_path}")
            return

        proj = Project(proj_path)
        total = len(self._steps)

        try:
            for step_idx, step_name in enumerate(self._steps):
                self._check_cancel()

                label = STEP_LABELS.get(step_name, step_name)
                # Review step manages its own state (may already be "completed")
                if step_name != STEP_REVIEW:
                    proj.record_step(step_name, "running")

                self._update(
                    current_step=step_name,
                    step_label=f"Running: {label} ({step_idx + 1}/{total})",
                    progress=step_idx / total,
                    message="",
                )

                base_pct = step_idx / total
                step_range = 1.0 / total

                if step_name == STEP_CLEAN:
                    self._execute_clean(proj, base_pct, step_range)
                elif step_name == STEP_TRAIN:
                    self._execute_train(proj, base_pct, step_range)
                elif step_name == STEP_REVIEW:
                    self._execute_review(proj, base_pct, step_range)
                elif step_name == STEP_ASSEMBLE:
                    self._execute_assemble(proj, base_pct, step_range)
                elif step_name == STEP_EXPORT:
                    self._execute_export(proj, base_pct, step_range)

                self._check_cancel()

            self._update(status="completed", progress=1.0, message="All steps completed.")

        except _CancelledError:
            # Record the step that was active when cancelled
            current = self._snapshot.current_step
            if current:
                proj.record_step(current, "cancelled")
            self._update(status="cancelled", message="Cancelled.")

        except Exception as e:
            current = self._snapshot.current_step
            if current:
                proj.record_step(current, "failed", error=str(e))
            self._update(status="failed", error=str(e), message=f"Failed: {e}")

    # ── Step executors ────────────────────────────────────────────

    def _execute_clean(self, proj: Project, base_pct: float, step_range: float) -> None:
        step = ColmapCleanStep(proj, self._config)
        result = step.execute()
        # execute() records "completed" internally, but record again to be safe
        summary = result.get("summary", {})
        proj.record_step(STEP_CLEAN, "completed", summary=summary)
        self._update(
            progress=base_pct + step_range,
            message="Clean COLMAP completed",
        )

    def _execute_review(self, proj: Project, base_pct: float, step_range: float) -> None:
        """Wait for manual review approval — no automated processing."""
        # Re-read state from disk (approval may have been set before run-all started)
        proj._state = None
        if proj.get_step_status(STEP_REVIEW) == "completed":
            self._update(
                progress=base_pct + step_range,
                message="Review already approved",
            )
            return

        proj.record_step(STEP_REVIEW, "waiting")
        self._update(message="Waiting for manual review — approve in the project page")
        while True:
            self._check_cancel()
            # Re-read state from disk (approval is written by a separate HTTP request)
            proj._state = None
            if proj.get_step_status(STEP_REVIEW) == "completed":
                break
            time.sleep(2)
        self._update(progress=base_pct + step_range, message="Review approved")

    def _execute_train(self, proj: Project, base_pct: float, step_range: float) -> None:
        trainer_name = proj.trainer
        trainer_instance = get_trainer(trainer_name, self._config)
        self._active_trainer = trainer_instance

        # Determine source directory
        clean_dir = proj.get_folder(FOLDER_COLMAP_CLEAN)
        if proj.is_step_enabled(STEP_CLEAN) and (clean_dir / "cameras.txt").exists():
            source_dir = clean_dir
        else:
            source_dir = proj.colmap_dir()

        # Count images for adaptive training steps
        _IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
        num_images = sum(
            1 for f in source_dir.iterdir()
            if f.is_file() and f.suffix.lower() in _IMG_EXTS
        ) if source_dir.is_dir() else 0

        # Build train options
        postshot_cfg = self._config.get("postshot", {})
        train_opts = {
            "profile": postshot_cfg.get("profile", "Splat3"),
            "downsample": postshot_cfg.get("downsample", True),
            "max_image_size": postshot_cfg.get("max_image_size", 3840),
            "anti_aliasing": postshot_cfg.get("anti_aliasing", False),
            "create_sky_model": postshot_cfg.get("create_sky_model", False),
            "train_steps_limit": postshot_cfg.get("train_steps_limit", 0),
        }
        train_settings = proj.step_settings.get("train", {})
        train_opts.update(train_settings)

        all_lod_levels = proj.lod_levels
        active_lods = [(i, lod) for i, lod in enumerate(all_lod_levels) if lod.get("enabled", True)]

        if not active_lods:
            proj.record_step(STEP_TRAIN, "failed", error="No LOD levels enabled")
            raise Exception("No LOD levels enabled")

        # Prepare review directory
        review_dir = proj.get_folder(FOLDER_REVIEW)
        if review_dir.exists():
            for f in review_dir.iterdir():
                if f.is_file():
                    try:
                        f.unlink()
                    except OSError:
                        pass
        review_dir.mkdir(parents=True, exist_ok=True)

        try:
            trained_count = 0
            for li, (orig_i, lod) in enumerate(active_lods):
                self._check_cancel()

                lod_name = lod["name"]
                max_splats = lod["max_splats"]
                lod_dir = proj.get_folder("03_training") / lod_name

                _clean_lod_dir(lod_dir)

                lod_train_steps = lod.get("train_steps", 0)
                effective_steps = lod_train_steps if lod_train_steps else train_opts.get("train_steps_limit", 0)

                gen = trainer_instance.train_lod(
                    source_dir, lod_dir, lod_name, max_splats,
                    num_images=num_images,
                    profile=train_opts["profile"],
                    downsample=train_opts["downsample"],
                    max_image_size=int(train_opts["max_image_size"]),
                    anti_aliasing=train_opts["anti_aliasing"],
                    create_sky_model=train_opts["create_sky_model"],
                    train_steps_limit=effective_steps,
                )

                # Consume generator synchronously — StopIteration propagates normally
                try:
                    while True:
                        self._check_cancel()
                        event = next(gen)
                        lod_progress = (li + event.sub_progress) / len(active_lods)
                        overall = base_pct + lod_progress * step_range
                        self._update(
                            progress=overall,
                            message=f"LOD {lod_name} ({li+1}/{len(active_lods)}): {event.message}",
                        )
                        time.sleep(0.1)
                except StopIteration as e:
                    ret = e.value
                    _write_train_debug(lod_dir, ret)
                    if ret.output_ply and Path(ret.output_ply).exists():
                        review_ply = review_dir / f"lod{orig_i}_reviewed.ply"
                        shutil.copy2(ret.output_ply, review_ply)
                    trained_count += 1
                    self._update(
                        message=f"LOD {lod_name} complete ({ret.duration_s:.1f}s)",
                    )

            proj.record_step(STEP_TRAIN, "completed", summary={"lod_count": trained_count})
            self._update(
                progress=base_pct + step_range,
                message="Training completed",
            )
        finally:
            self._active_trainer = None

    def _execute_assemble(self, proj: Project, base_pct: float, step_range: float) -> None:
        step = LodAssemblyStep(proj, self._config)
        output_dir = proj.get_folder(FOLDER_OUTPUT)
        output_dir.mkdir(parents=True, exist_ok=True)

        gen = step.run_streaming(output_dir)

        try:
            while True:
                self._check_cancel()
                event = next(gen)
                pct = base_pct + event.progress * step_range
                self._update(
                    progress=pct,
                    message=f"{event.message} {event.detail}",
                )
                time.sleep(0.3)
        except StopIteration as e:
            result = e.value

        # Write debug JSON
        if result:
            result["step"] = "assemble"
            result["environment"] = step._get_environment()
            step._write_debug_json(output_dir / "assemble_debug.json", result)

        summary = result.get("summary", {}) if result else {}
        if not summary.get("success", False):
            stderr = result.get("lod_streaming", {}).get("stderr", "") if result else ""
            proj.record_step(STEP_ASSEMBLE, "failed", error=f"Assembly failed: {stderr[:500]}")
            raise Exception(f"Assembly failed: {stderr[:500]}")

        proj.record_step(STEP_ASSEMBLE, "completed", summary=summary)
        self._update(
            progress=base_pct + step_range,
            message="Assembly completed",
        )

    def _execute_export(self, proj: Project, base_pct: float, step_range: float) -> None:
        output_dir = proj.get_folder(FOLDER_OUTPUT)
        mode = proj.export_mode
        export_settings = proj.step_settings.get("export", {})
        purge = _to_bool(export_settings.get("purge_before_export", False))

        if mode == "folder":
            dest = proj.export_folder
            if not dest:
                proj.record_step(STEP_EXPORT, "failed", error="No export folder configured")
                raise Exception("No export folder configured")
            gen = export_to_folder(output_dir, Path(dest), purge=purge)
        else:
            env = load_bunny_env(proj.root / ".env", DEFAULTS_PATH.parent.parent / ".env")
            gen = deploy_to_bunny(proj.name, output_dir, env, purge=purge)

        try:
            while True:
                self._check_cancel()
                event = next(gen)
                pct = base_pct + event.progress * step_range
                self._update(
                    progress=pct,
                    message=event.message,
                )
                time.sleep(0.05)
        except StopIteration as e:
            result = e.value

        if result:
            if result.success:
                proj.record_step(STEP_EXPORT, "completed", summary=result.summary)
            else:
                proj.record_step(STEP_EXPORT, "failed", error=result.error)
                raise Exception(result.error)

        self._update(
            progress=base_pct + step_range,
            message="Export completed",
        )


# ── Module-level API ──────────────────────────────────────────────

_runners: dict[str, PipelineRunner] = {}
_runners_lock = threading.Lock()


def _normalize_key(project_path: str) -> str:
    """Normalize path to consistent key (resolves Windows backslash/forward-slash mismatch)."""
    return str(Path(project_path))


def start_run(project_path: str, steps: list[str], config: dict) -> PipelineRunner:
    """Start a new pipeline run, cancelling any existing one for the same project."""
    key = _normalize_key(project_path)
    with _runners_lock:
        old = _runners.get(key)
        if old:
            old.cancel()
        runner = PipelineRunner(project_path, steps, config)
        _runners[key] = runner
    runner.start()
    return runner


def get_runner(project_path: str) -> PipelineRunner | None:
    """Get the active runner for a project, or None."""
    key = _normalize_key(project_path)
    with _runners_lock:
        return _runners.get(key)


def cancel_run(project_path: str) -> bool:
    """Cancel the runner for a project. Returns True if a runner was found."""
    key = _normalize_key(project_path)
    with _runners_lock:
        runner = _runners.get(key)
    if runner:
        runner.cancel()
        return True
    return False


# ── Helpers (moved from steps.py) ─────────────────────────────────

def _clean_lod_dir(lod_dir: Path) -> None:
    """Wipe and recreate LOD directory for a clean training slate.

    Previous approach deleted only .psht/.ply with silent error swallowing.
    If a file was locked (Resilio Sync, antivirus), deletion silently failed
    and Postshot would open the existing .psht, adding a SECOND radiance field
    on top of the first — doubling the exported splat count.
    """
    if lod_dir.exists():
        shutil.rmtree(lod_dir)
    lod_dir.mkdir(parents=True, exist_ok=True)


def _write_train_debug(lod_dir: Path, ret) -> None:
    """Write a training debug JSON for a completed LOD."""
    debug = {
        "lod_name": ret.lod_name,
        "max_splats": ret.max_splats,
        "success": ret.success,
        "command": ret.command,
        "returncode": ret.returncode,
        "stdout": ret.stdout,
        "stderr": ret.stderr,
        "duration_s": ret.duration_s,
        "output_dir": ret.output_dir,
        "output_ply": ret.output_ply,
    }
    debug_path = lod_dir / f"{ret.lod_name}_train_debug.json"
    with open(debug_path, "w") as f:
        json.dump(debug, f, indent=2)


def _to_bool(val) -> bool:
    """Convert form string values to bool."""
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("true", "1", "yes")
