"""LichtFeld Studio trainer: open-source Gaussian splatting.

CLI: LichtFeld-Studio -d <data> -o <output> --strategy mcmc --max-cap <N> -i <iters>

Key differences from Postshot:
- --max-cap takes actual splat count (not kSplats)
- Native SOG output (could skip splat-transform in future)
- CUDA 12.8+ / driver 570+ required
- Headless mode uncertain (may need display)
"""

import re
import subprocess
import time
from pathlib import Path
from typing import Generator

from ..core.config import get_lichtfeld_exe, get_tool_path
from ..core.events import ProgressEvent
from .base import Trainer, TrainResult


class LichtfeldTrainer(Trainer):
    name = "lichtfeld"

    # Matches iteration progress like "Iteration 1234/30000"
    _ITER_RE = re.compile(r"[Ii]teration\s+(\d+)\s*/\s*(\d+)")

    def train_lod(
        self,
        source_dir: Path,
        output_dir: Path,
        lod_name: str,
        max_splats: int,
        *,
        num_images: int = 0,
        **kwargs,
    ) -> Generator[ProgressEvent, None, TrainResult]:
        lf_exe = get_lichtfeld_exe(self.config)
        lf_cfg = self.config.get("lichtfeld", {})

        output_dir.mkdir(parents=True, exist_ok=True)

        strategy = lf_cfg.get("strategy", "mcmc")
        iterations = lf_cfg.get("iterations", 30000)

        cmd = [
            str(lf_exe),
            "-d", str(source_dir),
            "-o", str(output_dir / lod_name),
            "--strategy", strategy,
            "--max-cap", str(max_splats),  # actual count, not kSplats
            "-i", str(iterations),
        ]

        t0 = time.time()
        stdout_lines = []
        stderr_lines = []

        yield ProgressEvent(
            step="train", progress=0.0,
            message=f"Starting {lod_name}", sub_step=lod_name,
        )

        self._proc = None
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self._proc = proc

        for line in proc.stdout:
            stdout_lines.append(line)
            progress = self.parse_progress(line)
            if progress is not None:
                yield ProgressEvent(
                    step="train", progress=progress,
                    message=f"Training {lod_name}",
                    sub_step=lod_name, sub_progress=progress,
                )

        proc.wait()
        self._proc = None
        stderr_lines = proc.stderr.read().splitlines() if proc.stderr else []
        duration = time.time() - t0

        # LichtFeld outputs PLY in the output directory
        ply_path = output_dir / lod_name / "point_cloud.ply"
        if not ply_path.exists():
            # Try alternate naming
            ply_candidates = list((output_dir / lod_name).glob("*.ply"))
            ply_path = ply_candidates[0] if ply_candidates else ply_path

        return TrainResult(
            lod_name=lod_name,
            max_splats=max_splats,
            success=proc.returncode == 0,
            command=[str(c) for c in cmd],
            returncode=proc.returncode,
            stdout="".join(stdout_lines),
            stderr="\n".join(stderr_lines),
            duration_s=round(duration, 2),
            output_dir=str(output_dir / lod_name),
            output_ply=str(ply_path) if ply_path.exists() else "",
        )

    def validate_environment(self) -> tuple[bool, str]:
        try:
            exe = get_lichtfeld_exe(self.config)
            return True, f"Found at {exe}"
        except (ValueError, FileNotFoundError) as e:
            return False, str(e)

    def parse_progress(self, line: str) -> float | None:
        match = self._ITER_RE.search(line)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            if total > 0:
                return min(current / total, 1.0)
        return None

    def compute_training_steps(self, num_images: int) -> int:
        """LichtFeld uses fixed iterations from config."""
        return self.config.get("lichtfeld", {}).get("iterations", 30000)
