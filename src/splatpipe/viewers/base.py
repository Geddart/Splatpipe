"""ViewerRenderer protocol shared by PlayCanvas and Spark assemblers."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..core.events import ProgressGenerator


@runtime_checkable
class ViewerRenderer(Protocol):
    """Output-viewer plugin: turns reviewed PLYs into ``05_output/``.

    Implementations live alongside the runtime template they emit, e.g.
    ``viewers/playcanvas/assembler.py`` ships PlayCanvas's chunked SOG flow,
    ``viewers/spark/assembler.py`` ships Spark's ``.rad`` flow.
    """

    name: str  # "playcanvas" | "spark"

    def assemble(self, project, output_dir: Path) -> dict:
        """Synchronous assemble — returns a result dict with summary + stats."""

    def assemble_streaming(self, project, output_dir: Path) -> ProgressGenerator:
        """Generator variant. Yields ``ProgressEvent`` and returns a result dict
        via ``StopIteration.value``. Used by the FastAPI dashboard for live SSE
        progress."""


def clear_output_dir(output_dir: Path) -> None:
    """Wipe ``output_dir`` before assembling.

    Both PlayCanvas (chunk subdirs) and Spark (`scene.rad`) want a clean slate
    so toggling renderers doesn't leave stale assets next to fresh output.
    Mirrors the existing PlayCanvas pattern (`lod_assembly.py:730–735`).
    """
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
        return
    for item in list(output_dir.iterdir()):
        if item.is_dir():
            shutil.rmtree(item)
        elif item.is_file():
            item.unlink()
