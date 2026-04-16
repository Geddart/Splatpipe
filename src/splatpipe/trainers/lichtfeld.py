"""LichtFeld Studio trainer: open-source Gaussian splatting (v0.5.1+).

CLI: LichtFeld-Studio -d <data> -o <output> --strategy mcmc --max-cap <N> -i <iters>
     --headless --train [--ppisp] [--ppisp-controller]

Key differences from Postshot:
- --max-cap takes actual splat count (not kSplats)
- Native SOG output (could skip splat-transform in future)
- CUDA 12.8+ / driver 570+ required
- PPISP support for per-camera appearance modeling (exposure, vignetting, WB, CRF)
- Headless mode via --headless --train flags
"""

import re
import subprocess
import time
from pathlib import Path
from typing import Generator

from ..core.config import get_lichtfeld_exe
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
            "--output-name", lod_name,  # predictable PLY naming
            "--strategy", strategy,
            "--max-cap", str(max_splats),  # actual count, not kSplats
            "-i", str(iterations),
            "--headless",
            "--train",
        ]

        # PPISP: per-camera appearance modeling (exposure, vignetting, WB, CRF)
        if kwargs.get("ppisp", lf_cfg.get("ppisp", False)):
            cmd.append("--ppisp")
        if kwargs.get("ppisp_controller", lf_cfg.get("ppisp_controller", False)):
            cmd.append("--ppisp-controller")

        # PPISP sidecar: freeze learning and load pre-trained weights
        ppisp_sidecar = kwargs.get("ppisp_sidecar", lf_cfg.get("ppisp_sidecar", ""))
        if ppisp_sidecar:
            cmd.extend(["--ppisp-freeze", "--ppisp-sidecar", str(ppisp_sidecar)])

        # SH degree (0-3)
        sh_degree = int(kwargs.get("sh_degree", lf_cfg.get("sh_degree", 3)))
        if sh_degree != 3:  # only pass if non-default
            cmd.extend(["--sh-degree", str(sh_degree)])

        # Anti-aliasing (mip filter)
        if kwargs.get("enable_mip", lf_cfg.get("enable_mip", False)):
            cmd.append("--enable-mip")

        # Bilateral grid filtering
        if kwargs.get("bilateral_grid", lf_cfg.get("bilateral_grid", False)):
            cmd.append("--bilateral-grid")

        # Image downscaling
        max_width = int(kwargs.get("max_width", lf_cfg.get("max_width", 3840)))
        if max_width != 3840:  # only pass if non-default
            cmd.extend(["--max-width", str(max_width)])

        # Tile mode for VRAM management (1, 2, or 4)
        tile_mode = int(kwargs.get("tile_mode", lf_cfg.get("tile_mode", 1)))
        if tile_mode != 1:  # only pass if non-default
            cmd.extend(["--tile-mode", str(tile_mode)])

        # Sparsity optimization
        if kwargs.get("enable_sparsity", lf_cfg.get("enable_sparsity", False)):
            cmd.append("--enable-sparsity")

        # Undistort images on-the-fly
        if kwargs.get("undistort", lf_cfg.get("undistort", False)):
            cmd.append("--undistort")

        t0 = time.time()
        stdout_lines = []

        yield ProgressEvent(
            step="train", progress=0.0,
            message=f"Starting {lod_name}", sub_step=lod_name,
        )

        self._proc = None
        # Merge stderr into stdout so the reader below drains both pipes as one.
        # Leaving stderr on its own PIPE would let LichtFeld block on a full
        # stderr buffer (~64KB) while we're only consuming stdout, hanging the
        # whole process.
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
        full_output = "".join(stdout_lines)
        # On failure, surface the tail of the merged output as the stderr field
        # so the debug JSON still points at something useful.
        stderr_payload = (
            "" if proc.returncode == 0
            else "\n".join(full_output.splitlines()[-40:])
        )
        duration = time.time() - t0

        # With --output-name, LichtFeld outputs <name>.ply in the output dir
        ply_path = output_dir / lod_name / f"{lod_name}.ply"
        if not ply_path.exists():
            # Fallback: try point_cloud.ply or any PLY
            fallback = output_dir / lod_name / "point_cloud.ply"
            if fallback.exists():
                ply_path = fallback
            else:
                ply_candidates = list((output_dir / lod_name).glob("*.ply"))
                ply_path = ply_candidates[0] if ply_candidates else ply_path

        return TrainResult(
            lod_name=lod_name,
            max_splats=max_splats,
            success=proc.returncode == 0,
            command=[str(c) for c in cmd],
            returncode=proc.returncode,
            stdout=full_output,
            stderr=stderr_payload,
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
