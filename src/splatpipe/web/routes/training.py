"""Training routes with SSE progress streaming."""

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from ...core.config import load_project_config
from ...core.constants import FOLDER_COLMAP_CLEAN
from ...core.project import Project
from ...trainers.registry import get_trainer

router = APIRouter(prefix="/training", tags=["training"])


@router.post("/{project_path:path}/start")
async def start_training(project_path: str, trainer: str = "postshot"):
    """Start training (returns SSE endpoint URL)."""
    return {
        "sse_url": f"/training/{project_path}/progress?trainer={trainer}",
        "status": "started",
    }


@router.get("/{project_path:path}/progress")
async def training_progress(request: Request, project_path: str, trainer: str = "postshot"):
    """SSE endpoint for live training progress."""

    async def event_generator():
        proj = Project(Path(project_path))
        config = load_project_config(proj.config_path)
        trainer_instance = get_trainer(trainer, config)

        clean_dir = proj.get_folder(FOLDER_COLMAP_CLEAN)
        if not (clean_dir / "cameras.txt").exists():
            clean_dir = proj.colmap_dir()

        lod_levels = proj.lod_levels

        for i, lod in enumerate(lod_levels):
            lod_name = lod["name"]
            max_splats = lod["max_splats"]
            lod_dir = proj.get_folder("03_training") / lod_name

            gen = trainer_instance.train_lod(
                clean_dir, lod_dir, lod_name, max_splats,
            )

            try:
                while True:
                    event = next(gen)
                    yield {
                        "event": "progress",
                        "data": json.dumps({
                            "lod": lod_name,
                            "lod_index": i,
                            "lod_total": len(lod_levels),
                            "progress": event.sub_progress,
                            "overall": (i + event.sub_progress) / len(lod_levels),
                            "message": event.message,
                        }),
                    }
                    await asyncio.sleep(0.1)
            except StopIteration as e:
                result = e.value
                yield {
                    "event": "lod_complete",
                    "data": json.dumps({
                        "lod": lod_name,
                        "success": result.success,
                        "duration_s": result.duration_s,
                    }),
                }

        yield {
            "event": "complete",
            "data": json.dumps({"status": "done"}),
        }

    return EventSourceResponse(event_generator())
