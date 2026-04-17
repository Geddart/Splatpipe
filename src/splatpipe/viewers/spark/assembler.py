"""Spark assembler — builds 05_output/ for the Spark 2 renderer.

Steps:
1. Pick the highest-quality reviewed PLY (lod0_reviewed.ply by convention).
2. Run the Rust ``build-lod`` binary via the wrapper to produce ``scene.rad``
   (cached in ``~/.cache/splatpipe/rad/`` by hash + git rev).
3. Optionally also emit ``scene.sog`` as a fallback for hosts without
   HTTP-Range support (e.g. ``file://`` opens) — gated on
   ``project.spark_static_fallback``.
4. Write ``viewer-config.json`` (renderer-neutral; the Spark template just
   reads the same fields the PlayCanvas one does, plus ``spark_render``).
5. Render and write ``index.html`` from the Spark template.

The PlayCanvas assembler keeps producing chunked SOG into the same
``05_output/`` folder when ``project.renderer == 'playcanvas'``; we wipe
the dir at the start of either path so toggling renderers doesn't leave
stale assets.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from ...core.constants import FOLDER_REVIEW
from ...core.events import ProgressEvent
from ..base import clear_output_dir
from .build_lod import BuildLodError, build, verify_toolchain
from .template import html_for as spark_html_for


class SparkAssembler:
    """ViewerRenderer implementation for Spark 2 (sparkjsdev/spark)."""

    name = "spark"

    def assemble(self, step, output_dir: Path) -> dict:
        """Synchronous assemble — returns a result dict."""
        # Drain the streaming generator to reuse the same logic.
        gen = self.assemble_streaming(step, output_dir)
        result = None
        try:
            while True:
                next(gen)
        except StopIteration as stop:
            result = stop.value
        return result or {"summary": {"success": False}}

    def assemble_streaming(self, step, output_dir: Path):
        """Generator: yields ProgressEvent, returns result dict via StopIteration."""
        project = step.project

        review_dir = project.get_folder(FOLDER_REVIEW)
        enabled_lods = [lod for lod in project.lod_levels if lod.get("enabled", True)]
        if not enabled_lods:
            raise FileNotFoundError(
                f"No enabled LODs in project {project.name}. Enable at least one and re-run."
            )

        lod_name = enabled_lods[0]["name"]
        candidates = list(review_dir.glob(f"{lod_name}_reviewed.ply"))
        if not candidates:
            raise FileNotFoundError(
                f"No reviewed PLY for {lod_name} in {review_dir}. "
                f"Train + review the project before assembling."
            )
        input_ply = candidates[0]

        # Verify toolchain early so user gets a fast error if Rust/SPARK_REPO missing.
        try:
            tool_info = verify_toolchain()
        except BuildLodError as e:
            raise RuntimeError(str(e)) from e

        yield ProgressEvent(
            step="assemble",
            progress=0.05,
            message="Spark: toolchain ready",
            detail=f"build-lod {tool_info['version']} ({'cargo' if tool_info['is_cargo'] else 'binary'})",
        )

        clear_output_dir(output_dir)

        # ---- Build the .rad ----
        progress_lines: list[str] = []

        def _on_progress(line: str) -> None:
            progress_lines.append(line)

        t0 = time.time()
        try:
            rad_path = build(input_ply, quality=True, on_progress=_on_progress)
        except BuildLodError as e:
            raise RuntimeError(f"build-lod failed: {e}") from e

        rad_size = rad_path.stat().st_size
        yield ProgressEvent(
            step="assemble",
            progress=0.6,
            message="Spark: built scene.rad",
            detail=f"{rad_size / (1<<20):.1f} MB in {time.time() - t0:.1f}s",
        )

        # ---- Place .rad in 05_output/ ----
        out_rad = output_dir / "scene.rad"
        shutil.copy2(rad_path, out_rad)

        # ---- Optional .sog fallback ----
        emitted_sog = False
        if getattr(project, "renderer", "playcanvas") == "spark" and project.state.get(
            "spark_static_fallback", False
        ):
            try:
                _emit_sog_fallback(project, input_ply, output_dir)
                emitted_sog = True
                yield ProgressEvent(
                    step="assemble",
                    progress=0.8,
                    message="Spark: built scene.sog fallback",
                )
            except RuntimeError as e:
                yield ProgressEvent(
                    step="assemble",
                    progress=0.8,
                    message=f"Spark: .sog fallback skipped ({e})",
                )

        # ---- viewer-config.json ----
        scene_config = project.scene_config
        cfg_path = output_dir / "viewer-config.json"
        cfg_path.write_text(json.dumps(scene_config, indent=2), encoding="utf-8")

        # ---- index.html ----
        primary_asset = "scene.rad"
        paged = True
        # If only the .sog fallback exists (e.g. .rad failed mid-build), prefer it.
        if not out_rad.is_file() and (output_dir / "scene.sog").is_file():
            primary_asset = "scene.sog"
            paged = False
        html = spark_html_for(project.name, primary_asset=primary_asset, paged=paged)
        (output_dir / "index.html").write_text(html, encoding="utf-8")

        # ---- Project assets passthrough ----
        assets_src = project.root / "assets"
        if assets_src.is_dir():
            assets_dst = output_dir / "assets"
            if assets_dst.exists():
                shutil.rmtree(assets_dst)
            shutil.copytree(assets_src, assets_dst)

        yield ProgressEvent(
            step="assemble",
            progress=1.0,
            message="Spark: done",
            detail=f"index.html + scene.rad ({'+ scene.sog' if emitted_sog else ''}) in {output_dir.name}",
        )

        return {
            "input_ply": str(input_ply),
            "lod_streaming": {
                "command": tool_info["command"],
                "returncode": 0,
                "stdout": "\n".join(progress_lines),
                "stderr": "",
                "duration_s": round(time.time() - t0, 2),
            },
            "output": {
                "scene_rad": _file_stats(out_rad),
                "scene_sog": _file_stats(output_dir / "scene.sog") if emitted_sog else None,
                "index_html": _file_stats(output_dir / "index.html"),
                "viewer_config": _file_stats(cfg_path),
            },
            "summary": {
                "renderer": "spark",
                "lod_count": len(enabled_lods),
                "rad_size_bytes": rad_size,
                "spark_static_fallback": emitted_sog,
                "success": True,
            },
        }


def _emit_sog_fallback(project, input_ply: Path, output_dir: Path) -> None:
    """Run @playcanvas/splat-transform to produce a bundled .sog next to scene.rad.

    Uses the same Node CLI invocation pattern as the PlayCanvas assembler in
    `lod_assembly.py:716–728`. Requires `npm install` to have been run in
    the Splatpipe repo (the bundled splat-transform lives in node_modules/).
    """
    splat_transform_mjs = (
        Path("node_modules/@playcanvas/splat-transform/bin/cli.mjs").resolve()
    )
    if not splat_transform_mjs.is_file():
        raise RuntimeError(
            "splat-transform not installed (node_modules missing). "
            "Run `npm install` in the Splatpipe repo to enable .sog fallback."
        )
    assemble_settings = project.step_settings.get("assemble", {})
    sh_bands = int(assemble_settings.get("sh_bands", 3))
    out_sog = output_dir / "scene.sog"
    cmd = [
        "node", "--max-old-space-size=32000",
        str(splat_transform_mjs),
        str(input_ply),
        "--filter-nan",
        "--filter-harmonics", str(sh_bands),
        str(out_sog),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(f"splat-transform exit {proc.returncode}: {proc.stderr[:200]}")


def _file_stats(p: Path) -> dict | None:
    try:
        st = p.stat()
        return {"path": str(p), "size_bytes": st.st_size, "mtime": st.st_mtime}
    except OSError:
        return None
