"""LOD assembly step: uses splat-transform to build LOD streaming format.

Takes reviewed PLY files from 04_review/ and produces PlayCanvas-ready
LOD streaming output (lod-meta.json + SOG chunk files) in 05_output/.

CLI syntax (splat-transform v1.7+):
  splat-transform lod0.ply -l 0 lod1.ply -l 1 ... --filter-nan output/lod-meta.json
"""

import subprocess
import time
from pathlib import Path

from ..core.constants import FOLDER_REVIEW, FOLDER_OUTPUT
from .base import PipelineStep


class LodAssemblyStep(PipelineStep):
    step_name = "assemble"
    output_folder = FOLDER_OUTPUT

    def run(self, output_dir: Path) -> dict:
        review_dir = self.project.get_folder(FOLDER_REVIEW)
        lod_levels = self.project.lod_levels

        # Find reviewed PLY files
        reviewed_plys = []
        for i, lod in enumerate(lod_levels):
            lod_name = lod["name"]
            ply_name = f"lod{i}_reviewed.ply"
            ply_path = review_dir / ply_name
            if ply_path.exists():
                reviewed_plys.append({
                    "lod_index": i,
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

        # Check output files
        lod_meta_path = output_dir / "lod-meta.json"
        result["output"] = {
            "lod_meta": self.file_stats(lod_meta_path),
            "chunk_files": [
                self.file_stats(f)
                for f in sorted(output_dir.glob("*.webp"))
            ],
        }

        result["summary"] = {
            "lod_count": len(reviewed_plys),
            "lod_meta_generated": lod_meta_path.exists(),
            "chunk_count": len(list(output_dir.glob("*.webp"))),
            "success": lod_meta_result.get("returncode") == 0,
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
