"""Postshot trainer: Gaussian splatting via postshot-cli.exe.

Uses Popen for real-time stdout parsing and progress reporting.
CLI expects kSplats (3000 = 3M splats).

Stdout is read in a background thread via a queue so the generator
never blocks — it yields a heartbeat with elapsed time every ~2s
even when Postshot hasn't flushed its output buffer yet.
"""

import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Generator

from ..core.config import get_postshot_cli
from ..core.events import ProgressEvent
from .base import Trainer, TrainResult


class PostshotTrainer(Trainer):
    name = "postshot"

    # Matches Postshot v1.0.185+ output in two formats:
    #   <1000: "..., 999 Steps of 2.00 kSteps, 1.38 MSplats"
    #   >=1000: "..., 1.924 kSteps of 2.00 kSteps, 2.23 MSplats"
    _PROGRESS_RE = re.compile(
        r"Training Radiance Field:\s*(\d+)%.*?"
        r"([\d,.]+)\s+(?:k)?Steps\s+of\s+([\d.]+)\s+kSteps.*?"
        r"([\d.]+)\s+MSplats"
    )
    # Legacy format: "Step 1234/5000"
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
        postshot_cli = get_postshot_cli(self.config)
        postshot_cfg = self.config.get("postshot", {})

        output_dir.mkdir(parents=True, exist_ok=True)
        ksplats = max_splats // 1000

        # Profile: kwargs override > config > default
        profile = kwargs.get("profile", postshot_cfg.get("profile", "Splat3"))

        cmd = [
            str(postshot_cli),
            "train",
            "--import", str(source_dir),
            "-p", profile,
            "--max-num-splats", str(ksplats),
            "--store-training-context",
            "--show-train-error",
            "-o", str(output_dir / f"{lod_name}.psht"),
            "--export-splat", str(output_dir / f"{lod_name}.ply"),
        ]

        # Downsample images (--max-image-size, default 3840, 0 = disabled)
        downsample = kwargs.get("downsample", postshot_cfg.get("downsample", True))
        max_image_size = int(kwargs.get("max_image_size", postshot_cfg.get("max_image_size", 3840)))
        if downsample and max_image_size > 0:
            cmd.extend(["--max-image-size", str(max_image_size)])
        elif not downsample:
            cmd.extend(["--max-image-size", "0"])

        # Anti-aliasing (boolean flag)
        if kwargs.get("anti_aliasing", postshot_cfg.get("anti_aliasing", False)):
            cmd.extend(["--anti-aliasing", "true"])

        # Sky model (presence flag)
        if kwargs.get("create_sky_model", postshot_cfg.get("create_sky_model", False)):
            cmd.append("--create-sky-model")

        # Train steps limit (kSteps, 0 = auto based on image count)
        train_steps = int(kwargs.get("train_steps_limit", postshot_cfg.get("train_steps_limit", 0)))
        if train_steps == 0 and num_images > 0:
            train_steps = self.compute_training_steps(num_images)
        if train_steps > 0:
            cmd.extend(["-s", str(train_steps)])

        # Append auth args if configured
        login = postshot_cfg.get("login", "")
        password = postshot_cfg.get("password", "")
        if login:
            cmd.extend(["--login", login])
        if password:
            cmd.extend(["--password", password])

        t0 = time.time()
        stdout_lines: list[str] = []

        yield ProgressEvent(
            step="train", progress=0.0,
            message=f"Starting {lod_name}", sub_step=lod_name,
        )

        self._proc = None
        # Merge stderr into stdout so we catch progress from either stream
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        self._proc = proc

        # Read stdout in a background thread so we never block the generator
        line_q: queue.Queue[str | None] = queue.Queue()

        def _reader():
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, ''):
                line_q.put(line)
            line_q.put(None)  # sentinel: process done

        reader_thread = threading.Thread(target=_reader, daemon=True)
        reader_thread.start()

        last_progress = 0.0
        last_parsed: dict | None = None
        done = False

        while not done:
            # Drain all available lines without blocking
            while True:
                try:
                    line = line_q.get_nowait()
                except queue.Empty:
                    break
                if line is None:
                    done = True
                    break
                stdout_lines.append(line)
                parsed = self._parse_step_line(line)
                if parsed is not None:
                    last_parsed = parsed
                    last_progress = parsed["progress"]

            elapsed = time.time() - t0

            # Build message: show step progress if available, otherwise elapsed time
            if last_parsed:
                p = last_parsed
                msg = (
                    f"Training {lod_name} — "
                    f"Step {p['steps']}/{p['total_ksteps']:.0f}k"
                )
                if "msplats" in p:
                    msg += f" | {p['msplats']:.1f}M splats"
            else:
                msg = f"Training {lod_name} — {_fmt_elapsed(elapsed)} elapsed"

            yield ProgressEvent(
                step="train", progress=last_progress,
                message=msg,
                sub_step=lod_name, sub_progress=last_progress,
            )

            if not done and proc.poll() is not None:
                # Process exited but reader might still have lines
                reader_thread.join(timeout=2)
                while True:
                    try:
                        line = line_q.get_nowait()
                    except queue.Empty:
                        break
                    if line is None:
                        break
                    stdout_lines.append(line)
                    parsed = self._parse_step_line(line)
                    if parsed is not None:
                        last_parsed = parsed
                        last_progress = parsed["progress"]
                done = True

            if not done:
                time.sleep(2)

        proc.wait()
        reader_thread.join(timeout=5)
        self._proc = None
        duration = time.time() - t0

        ply_path = output_dir / f"{lod_name}.ply"

        return TrainResult(
            lod_name=lod_name,
            max_splats=max_splats,
            success=proc.returncode == 0,
            command=[str(c) for c in cmd],
            returncode=proc.returncode,
            stdout="".join(stdout_lines),
            stderr="",  # merged into stdout
            duration_s=round(duration, 2),
            output_dir=str(output_dir),
            output_ply=str(ply_path) if ply_path.exists() else "",
        )

    def validate_environment(self) -> tuple[bool, str]:
        try:
            path = get_postshot_cli(self.config)
            return True, f"Found at {path}"
        except (ValueError, FileNotFoundError) as e:
            return False, str(e)

    def _parse_step_line(self, line: str) -> dict | None:
        """Parse a Postshot progress line.

        Returns dict with keys: pct, steps, total_ksteps, msplats, progress
        or None if no match.
        """
        # New format: "Training Radiance Field: 2%, ... 46 Steps of 2.00 kSteps, 1.38 MSplats"
        m = self._PROGRESS_RE.search(line)
        if m:
            pct = int(m.group(1))
            raw_steps = m.group(2).replace(",", "")
            total_ksteps = float(m.group(3))
            msplats = float(m.group(4))
            total_steps = int(total_ksteps * 1000)
            # Postshot uses "999 Steps" below 1000, "1.924 kSteps" at/above 1000
            if "." in raw_steps:
                steps = int(float(raw_steps) * 1000)
            else:
                steps = int(raw_steps)
            progress = min(steps / total_steps, 1.0) if total_steps > 0 else pct / 100
            return {
                "pct": pct,
                "steps": steps,
                "total_ksteps": total_ksteps,
                "total_steps": total_steps,
                "msplats": msplats,
                "progress": progress,
            }
        # Legacy format: "Step X/Y"
        m = self._STEP_RE.search(line)
        if m:
            current = int(m.group(1))
            total = int(m.group(2))
            if total > 0:
                return {
                    "steps": current,
                    "total_steps": total,
                    "total_ksteps": total / 1000,
                    "progress": min(current / total, 1.0),
                }
        return None

    def parse_progress(self, line: str) -> float | None:
        parsed = self._parse_step_line(line)
        return parsed["progress"] if parsed else None

    def compute_training_steps(self, num_images: int) -> int:
        """Auto-step: max(50, round(image_count * 52 / 1000)) kSteps."""
        return max(50, round(num_images * 52 / 1000))


def _fmt_elapsed(seconds: float) -> str:
    """Format elapsed seconds as 'Xm Ys' or 'Xs'."""
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"
