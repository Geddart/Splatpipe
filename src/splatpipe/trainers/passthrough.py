"""Passthrough trainer: skip training, extract/copy a finished splat.

For .psht input: runs ``postshot-cli export -f source.psht --export-splat out.ply``
to extract the embedded splat without retraining.

For .ply input: copies the file straight to the LOD output.

Used to publish a finished splat to Bunny CDN without spending hours retraining
something that's already done.
"""

import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Generator

from ..core.config import get_postshot_cli
from ..core.events import ProgressEvent
from .base import Trainer, TrainResult


def _fmt_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"


class PassthroughTrainer(Trainer):
    name = "passthrough"

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
        # source_dir is a FILE path here (not a directory) — same convention
        # PostshotTrainer uses for .psht (see postshot.py: --import str(source_dir)).
        output_dir.mkdir(parents=True, exist_ok=True)
        out_ply = output_dir / f"{lod_name}.ply"
        ext = source_dir.suffix.lower()
        t0 = time.time()
        cmd: list[str] = []
        stdout = ""
        returncode = 0
        ok = False

        if ext == ".psht":
            postshot_cli = get_postshot_cli(self.config)
            cmd = [
                str(postshot_cli), "export",
                "-f", str(source_dir),
                "--export-splat", str(out_ply),
            ]
            yield ProgressEvent(
                step="train", progress=0.05,
                message=f"Extracting splat from {source_dir.name}",
                sub_step=lod_name, sub_progress=0.05,
            )
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            # Drain stdout in a background thread so the generator can keep
            # yielding heartbeats. Without this, communicate() blocks the
            # generator and the runner's cancel check never fires until
            # Postshot finishes (can be 30s+ on multi-GB .psht files).
            line_q: queue.Queue[str | None] = queue.Queue()

            def _reader():
                assert self._proc is not None and self._proc.stdout is not None
                for line in iter(self._proc.stdout.readline, ""):
                    line_q.put(line)
                line_q.put(None)

            reader_thread = threading.Thread(target=_reader, daemon=True)
            reader_thread.start()

            stdout_lines: list[str] = []
            done = False
            while not done:
                # Drain any available lines without blocking.
                while True:
                    try:
                        line = line_q.get_nowait()
                    except queue.Empty:
                        break
                    if line is None:
                        done = True
                        break
                    stdout_lines.append(line)

                elapsed = time.time() - t0
                yield ProgressEvent(
                    step="train", progress=0.5,
                    message=f"Extracting {source_dir.name} — {_fmt_elapsed(elapsed)} elapsed",
                    sub_step=lod_name, sub_progress=0.5,
                )

                if not done and self._proc.poll() is not None:
                    # Process exited; drain any remaining lines then finish.
                    reader_thread.join(timeout=2)
                    while True:
                        try:
                            line = line_q.get_nowait()
                        except queue.Empty:
                            break
                        if line is None:
                            break
                        stdout_lines.append(line)
                    done = True

                if not done:
                    time.sleep(2)

            self._proc.wait()
            reader_thread.join(timeout=5)
            returncode = self._proc.returncode
            stdout = "".join(stdout_lines)
            self._proc = None
            ok = returncode == 0 and out_ply.exists()
        elif ext == ".ply":
            # No subprocess — shutil.copy2 does the work. Keep cmd empty so the
            # debug JSON doesn't look like an OS command was invoked.
            yield ProgressEvent(
                step="train", progress=0.05,
                message=f"Copying {source_dir.name}",
                sub_step=lod_name, sub_progress=0.05,
            )
            shutil.copy2(source_dir, out_ply)
            ok = out_ply.exists()
        else:
            return TrainResult(
                lod_name=lod_name,
                max_splats=max_splats,
                success=False,
                command=[],
                returncode=-1,
                stdout="",
                stderr=f"Passthrough requires .psht or .ply input, got {ext or '(no ext)'}",
                duration_s=round(time.time() - t0, 2),
                output_dir=str(output_dir),
                output_ply="",
            )

        yield ProgressEvent(
            step="train", progress=1.0,
            message=f"Passthrough {lod_name} done",
            sub_step=lod_name, sub_progress=1.0,
        )

        return TrainResult(
            lod_name=lod_name,
            max_splats=max_splats,
            success=ok,
            command=cmd,  # [] for .ply (just a file copy), populated for .psht (Postshot CLI export)
            returncode=returncode,
            stdout=stdout,
            stderr="" if ok else "Passthrough produced no output PLY",
            duration_s=round(time.time() - t0, 2),
            output_dir=str(output_dir),
            output_ply=str(out_ply) if out_ply.exists() else "",
        )

    def validate_environment(self) -> tuple[bool, str]:
        # Postshot CLI is only needed for .psht extraction. Defer the check
        # to runtime so .ply users aren't blocked by a missing Postshot install.
        return (True, "")

    def parse_progress(self, line: str) -> float | None:
        return None
