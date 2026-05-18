"""Local-folder deploy target — copy the staged output to a directory.

Pure local filesystem; no network. The staged tree (root ``index.html`` +
``viewer-config.json`` + immutable ``b<key>/`` chunk subfolder) is copied
under ``<destination>/<slug>/``, overwrite-safe and idempotent.

Cache-freshness note (per the §H2-DECISION REQUIREMENT): a local folder is
inherently fresh — there is no edge cache to invalidate. This target
therefore makes ``ensure_fresh`` / ``invalidate`` no-ops and RELIES ON the
consuming web server to send ``Cache-Control: no-cache`` (or a short TTL)
for the two mutable text files (``index.html`` + ``viewer-config.json``)
while long-caching the immutable ``.rad`` / ``.radc`` chunks.
"""

import shutil
import time
from pathlib import Path
from typing import Generator

from ..core.constants import STEP_PUBLISH
from ..core.events import ProgressEvent, StepResult
from .base import DeployTarget


class FolderDeployTarget(DeployTarget):
    """Copy the staged output directory into a local destination folder."""

    def __init__(self, *, destination: Path | str):
        self.destination = Path(destination)

    @property
    def name(self) -> str:
        return "folder"

    def validate_environment(self) -> tuple[bool, str]:
        # The parent of the destination must be creatable; we don't require
        # it to pre-exist (deploy_staged makes it). Only fail if a non-dir
        # file already occupies the destination path.
        if self.destination.exists() and not self.destination.is_dir():
            return False, f"destination exists and is not a directory: {self.destination}"
        return True, f"folder target → {self.destination}"

    def deploy_staged(
        self,
        slug: str,
        staged_dir: Path,
        *,
        workers: int = 8,  # accepted for interface parity; unused locally
    ) -> Generator[ProgressEvent, None, StepResult]:
        staged_dir = Path(staged_dir)
        out_root = self.destination / slug

        files = sorted(f for f in staged_dir.rglob("*") if f.is_file())
        if not files:
            return StepResult(
                step=STEP_PUBLISH, success=False,
                error=f"No files found in {staged_dir}",
            )

        total_size = sum(f.stat().st_size for f in files)
        total_count = len(files)
        yield ProgressEvent(
            step=STEP_PUBLISH, progress=0.0,
            message=f"Copying {total_count} files ({total_size / 1e6:.1f} MB) "
                    f"→ {out_root}",
        )

        # Overwrite-safe: clear the slug dir so a re-deploy mirrors the new
        # staged content exactly (stale chunks from a prior build don't
        # linger). Local-only; cheap.
        if out_root.exists():
            shutil.rmtree(out_root)
        out_root.mkdir(parents=True, exist_ok=True)

        copied = 0
        copied_bytes = 0
        t0 = time.time()
        for f in files:
            rel = f.relative_to(staged_dir)
            dest_file = out_root / rel
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest_file)
            copied += 1
            copied_bytes += f.stat().st_size
            yield ProgressEvent(
                step=STEP_PUBLISH,
                progress=copied / total_count,
                message=f"Copied {copied}/{total_count}",
                detail=f"{copied_bytes / 1e6:.1f} MB",
            )

        duration = time.time() - t0
        return StepResult(
            step=STEP_PUBLISH,
            success=True,
            summary={
                "uploaded": copied,
                "failed": 0,
                "failed_files": [],
                "total_files": total_count,
                "total_mb": round(total_size / 1e6, 1),
                "duration_s": round(duration, 1),
                "destination": str(out_root),
            },
        )

    def ensure_fresh(self, *, quiet: bool = False) -> bool:
        # A local folder is inherently fresh — see module docstring.
        return True

    def invalidate(self, urls: list[str]) -> None:
        # No edge cache for a local folder — no-op.
        return None
