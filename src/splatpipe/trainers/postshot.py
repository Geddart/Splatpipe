"""Postshot trainer: Gaussian splatting via postshot-cli.exe.

Uses Popen for real-time stdout parsing and progress reporting.
CLI expects kSplats (3000 = 3M splats).
"""

import re
import subprocess
import time
from pathlib import Path
from typing import Generator

from ..core.config import get_tool_path
from ..core.events import ProgressEvent
from .base import Trainer, TrainResult


class PostshotTrainer(Trainer):
    name = "postshot"

    # Matches Postshot progress output like "Step 1234/5000"
    _STEP_RE = re.compile(r"[Ss]tep\s+(\d+)\s*/\s*(\d+)")

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
        postshot_cli = get_tool_path(self.config, "postshot_cli")
        postshot_cfg = self.config.get("postshot", {})

        output_dir.mkdir(parents=True, exist_ok=True)
        ksplats = max_splats // 1000

        cmd = [
            str(postshot_cli),
            "train",
            "--import", str(source_dir),
            "-p", postshot_cfg.get("profile", "Splat3"),
            "--max-num-splats", str(ksplats),
            "--store-training-context",
            "-o", str(output_dir / f"{lod_name}.psht"),
            "--export-splat", str(output_dir / f"{lod_name}.ply"),
        ]

        # Append auth args if configured
        login = postshot_cfg.get("login", "")
        password = postshot_cfg.get("password", "")
        if login:
            cmd.extend(["--login", login])
        if password:
            cmd.extend(["--password", password])

        t0 = time.time()
        stdout_lines = []
        stderr_lines = []

        yield ProgressEvent(
            step="train", progress=0.0,
            message=f"Starting {lod_name}", sub_step=lod_name,
        )

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )

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
        stderr_lines = proc.stderr.read().splitlines() if proc.stderr else []
        duration = time.time() - t0

        ply_path = output_dir / f"{lod_name}.ply"

        return TrainResult(
            lod_name=lod_name,
            max_splats=max_splats,
            success=proc.returncode == 0,
            command=[str(c) for c in cmd],
            returncode=proc.returncode,
            stdout="".join(stdout_lines),
            stderr="\n".join(stderr_lines),
            duration_s=round(duration, 2),
            output_dir=str(output_dir),
            output_ply=str(ply_path) if ply_path.exists() else "",
        )

    def validate_environment(self) -> tuple[bool, str]:
        try:
            path = get_tool_path(self.config, "postshot_cli")
            return True, f"Found at {path}"
        except (ValueError, FileNotFoundError) as e:
            return False, str(e)

    def parse_progress(self, line: str) -> float | None:
        match = self._STEP_RE.search(line)
        if match:
            current = int(match.group(1))
            total = int(match.group(2))
            if total > 0:
                return min(current / total, 1.0)
        return None

    def compute_training_steps(self, num_images: int) -> int:
        """Auto-step: max(50, round(image_count * 52 / 1000)) kSteps."""
        return max(50, round(num_images * 52 / 1000))
