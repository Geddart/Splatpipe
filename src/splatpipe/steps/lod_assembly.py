"""LOD assembly step: uses splat-transform to build LOD streaming format.

Takes reviewed PLY files from 04_review/ and produces PlayCanvas-ready
LOD streaming output (lod-meta.json + SOG chunk files + index.html viewer)
in 05_output/.

CLI syntax (splat-transform v1.7+):
  splat-transform lod0.ply -l 0 lod1.ply -l 1 ... --filter-nan output/lod-meta.json

Output structure (per chunk):
  {lod}_{chunk}/meta.json, means_l.webp, means_u.webp, quats.webp,
  scales.webp, sh0.webp, shN_centroids.webp, shN_labels.webp

splat-transform stderr progress:
  [1/8] Generating morton order
  [2/8] Writing positions
  ... (8 steps per chunk, 6 if no SH bands)
"""

import math
import re
import shutil
import subprocess
import time
from pathlib import Path

from ..core.constants import FOLDER_REVIEW, FOLDER_OUTPUT
from ..core.events import ProgressEvent
from .base import PipelineStep

# Self-contained viewer HTML that auto-detects its hosting URL.
# Works on any origin: CDN, local HTTP server, etc.
_VIEWER_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{project_name} — Splatpipe Viewer</title>
    <style>
        body {{ margin: 0; overflow: hidden; background: #1a1a2e; }}
        #viewer {{ width: 100vw; height: 100vh; border: none; }}
    </style>
</head>
<body>
    <iframe id="viewer" allow="cross-origin-isolated"></iframe>
    <script>
        // Auto-detect base URL so the viewer works on any hosting
        var base = window.location.href.substring(0, window.location.href.lastIndexOf('/') + 1);
        var metaUrl = base + 'lod-meta.json';
        document.getElementById('viewer').src =
            'https://superspl.at/editor?load=' + encodeURIComponent(metaUrl);
    </script>
</body>
</html>
"""


def _write_viewer_html(output_dir: Path, project_name: str) -> None:
    """Generate index.html viewer alongside lod-meta.json."""
    html = _VIEWER_TEMPLATE.format(project_name=project_name)
    (output_dir / "index.html").write_text(html, encoding="utf-8")

# splat-transform defaults: --lod-chunk-count 512 -> binSize = 512 * 1024
_DEFAULT_BIN_SIZE = 512 * 1024  # 524,288 splats per output chunk
_FILES_PER_CHUNK = 8  # 7 webp + 1 meta.json


def _count_ply_vertices(ply_path: Path) -> int:
    """Read vertex count from PLY header without loading the full file."""
    with open(ply_path, "rb") as f:
        for raw in f:
            line = raw.decode("ascii", errors="replace").strip()
            if line.startswith("element vertex"):
                return int(line.split()[-1])
            if line == "end_header":
                break
    return 0


def _estimate_total_chunks(reviewed_plys: list[dict]) -> int:
    """Estimate total output chunks from PLY vertex counts."""
    total = 0
    for ply_info in reviewed_plys:
        verts = _count_ply_vertices(Path(ply_info["ply_path"]))
        total += math.ceil(verts / _DEFAULT_BIN_SIZE) if verts > 0 else 1
    return total


class LodAssemblyStep(PipelineStep):
    step_name = "assemble"
    output_folder = FOLDER_OUTPUT

    def run(self, output_dir: Path) -> dict:
        review_dir = self.project.get_folder(FOLDER_REVIEW)
        lod_levels = self.project.lod_levels

        # Find reviewed PLY files — use sequential lod_index for splat-transform
        # (passing -l 2 -l 3 -l 5 creates 6 LOD levels with empty gaps at 0,1,4)
        reviewed_plys = []
        for i, lod in enumerate(lod_levels):
            lod_name = lod["name"]
            ply_name = f"lod{i}_reviewed.ply"
            ply_path = review_dir / ply_name
            if ply_path.exists():
                reviewed_plys.append({
                    "lod_index": len(reviewed_plys),
                    "lod_name": lod_name,
                    "ply_path": str(ply_path),
                    "stats": self.file_stats(ply_path),
                })

        if not reviewed_plys:
            raise FileNotFoundError(
                f"No reviewed PLY files found in {review_dir}. "
                f"Expected files like lod0_reviewed.ply, lod1_reviewed.ply, etc."
            )

        result = {"input_plys": reviewed_plys}

        # Run splat-transform to generate LOD streaming format
        lod_meta_result = self._build_lod_streaming(output_dir, reviewed_plys)
        result["lod_streaming"] = lod_meta_result

        # Check output files (chunks are in subdirectories: {lod}_{idx}/*.webp)
        lod_meta_path = output_dir / "lod-meta.json"
        chunk_files = sorted(output_dir.rglob("*.webp"))
        chunk_dirs = [d for d in output_dir.iterdir() if d.is_dir()]
        result["output"] = {
            "lod_meta": self.file_stats(lod_meta_path),
            "chunk_files": [self.file_stats(f) for f in chunk_files],
        }

        result["summary"] = {
            "lod_count": len(reviewed_plys),
            "lod_meta_generated": lod_meta_path.exists(),
            "chunk_count": len(chunk_dirs),
            "file_count": len(chunk_files),
            "success": lod_meta_result.get("returncode") == 0,
        }

        # Generate viewer HTML if assembly succeeded
        if lod_meta_result.get("returncode") == 0:
            _write_viewer_html(output_dir, self.project.name)

        return result

    def run_streaming(self, output_dir: Path):
        """Generator yielding ProgressEvent during assembly, returns result dict.

        Reads splat-transform stderr line-by-line for per-chunk step progress
        ([1/8] Writing positions, etc.) and counts output files recursively.
        Estimates total chunks from PLY vertex counts for percentage progress.
        Result is returned via StopIteration.value (use _next_or_sentinel).
        """
        review_dir = self.project.get_folder(FOLDER_REVIEW)
        lod_levels = self.project.lod_levels

        # Find reviewed PLY files — use sequential lod_index for splat-transform
        reviewed_plys = []
        for i, lod in enumerate(lod_levels):
            lod_name = lod["name"]
            ply_name = f"lod{i}_reviewed.ply"
            ply_path = review_dir / ply_name
            if ply_path.exists():
                reviewed_plys.append({
                    "lod_index": len(reviewed_plys),
                    "lod_name": lod_name,
                    "ply_path": str(ply_path),
                    "stats": self.file_stats(ply_path),
                })

        if not reviewed_plys:
            raise FileNotFoundError(
                f"No reviewed PLY files found in {review_dir}. "
                f"Expected files like lod0_reviewed.ply, lod1_reviewed.ply, etc."
            )

        # Estimate total chunks from PLY vertex counts
        est_chunks = _estimate_total_chunks(reviewed_plys)
        est_total_files = est_chunks * _FILES_PER_CHUNK + 1  # +1 for lod-meta.json

        # Build command
        input_args = []
        for ply_info in reviewed_plys:
            input_args.extend([
                ply_info["ply_path"],
                "-l", str(ply_info["lod_index"]),
            ])

        lod_meta_path = output_dir / "lod-meta.json"
        splat_transform_mjs = (
            Path("node_modules/@playcanvas/splat-transform/bin/cli.mjs").resolve()
        )
        cmd = [
            "node", "--max-old-space-size=32000",
            str(splat_transform_mjs),
        ] + input_args + [
            "--filter-nan",
            str(lod_meta_path),
        ]

        # Clear old output completely (subdirs + root files)
        for item in list(output_dir.iterdir()):
            if item.is_dir():
                shutil.rmtree(item)
            elif item.is_file():
                item.unlink()

        t0 = time.time()
        # Read stderr line-by-line for per-chunk step progress
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        stderr_lines = []
        step_re = re.compile(r"\[(\d+)/(\d+)\]\s*(.*)")
        chunks_done = 0
        last_step_msg = ""

        import threading
        import queue

        stderr_q: queue.Queue[str | None] = queue.Queue()

        def _read_stderr():
            assert proc.stderr is not None
            for raw in proc.stderr:
                line = raw.decode("utf-8", errors="replace").rstrip()
                stderr_q.put(line)
            stderr_q.put(None)  # sentinel

        reader = threading.Thread(target=_read_stderr, daemon=True)
        reader.start()

        while True:
            # Drain all available stderr lines
            while True:
                try:
                    line = stderr_q.get_nowait()
                except queue.Empty:
                    break
                if line is None:
                    break
                stderr_lines.append(line)
                m = step_re.match(line)
                if m:
                    step_num, total_steps, step_name = m.group(1), m.group(2), m.group(3)
                    last_step_msg = f"[{step_num}/{total_steps}] {step_name}"
                    if step_num == total_steps:
                        chunks_done += 1
                elif "done" in line:
                    pass  # final completion marker

            # Count actual files recursively
            file_count = sum(1 for _ in output_dir.rglob("*") if _.is_file())
            elapsed = time.time() - t0

            # Progress: use chunks_done / est_chunks for percentage
            pct = min(chunks_done / est_chunks, 0.99) if est_chunks > 0 else 0

            yield ProgressEvent(
                step="assemble",
                progress=pct,
                sub_progress=file_count,
                message=last_step_msg or "Starting...",
                detail=f"{file_count}/~{est_total_files} files | "
                       f"{chunks_done}/~{est_chunks} chunks | "
                       f"{elapsed:.0f}s",
            )

            if proc.poll() is not None:
                break
            time.sleep(0.5)

        reader.join(timeout=5)
        duration = time.time() - t0
        stdout = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
        stderr_full = "\n".join(stderr_lines)

        chunk_files = sorted(output_dir.rglob("*.webp"))
        chunk_dirs = [d for d in output_dir.iterdir() if d.is_dir()]

        # Generate viewer HTML if assembly succeeded
        if proc.returncode == 0:
            _write_viewer_html(output_dir, self.project.name)

        result = {
            "input_plys": reviewed_plys,
            "lod_streaming": {
                "command": cmd,
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr_full,
                "duration_s": round(duration, 2),
            },
            "output": {
                "lod_meta": self.file_stats(lod_meta_path),
                "chunk_files": [self.file_stats(f) for f in chunk_files],
            },
            "summary": {
                "lod_count": len(reviewed_plys),
                "lod_meta_generated": lod_meta_path.exists(),
                "chunk_count": len(chunk_dirs),
                "file_count": len(chunk_files),
                "success": proc.returncode == 0,
            },
        }
        return result

    def _build_lod_streaming(self, output_dir: Path, reviewed_plys: list[dict]) -> dict:
        """Run splat-transform to generate lod-meta.json + SOG chunks."""
        # Build interleaved input args: file.ply -l N file.ply -l N ...
        input_args = []
        for ply_info in reviewed_plys:
            input_args.extend([
                ply_info["ply_path"],
                "-l", str(ply_info["lod_index"]),
            ])

        lod_meta_path = output_dir / "lod-meta.json"

        # Use node with extra memory for large splat files
        splat_transform_mjs = (
            Path("node_modules/@playcanvas/splat-transform/bin/cli.mjs").resolve()
        )
        cmd = [
            "node", "--max-old-space-size=32000",
            str(splat_transform_mjs),
        ] + input_args + [
            "--filter-nan",
            str(lod_meta_path),
        ]

        t0 = time.time()
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=3600,
        )
        duration = time.time() - t0

        return {
            "command": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_s": round(duration, 2),
        }
