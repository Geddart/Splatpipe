"""splatpipe serve — Local HTTP server with viewer.

Uses FastAPI's FileResponse so HTTP Range requests work — required for
Spark 2's `.rad` paged streaming. Python's stdlib `http.server` does NOT
support Range, which is why earlier versions of this command made Spark
output look broken (Spark fell back to whole-file load and rendered only
the coarsest root-level splats).
"""

import json
import threading
import webbrowser
from pathlib import Path

import typer
from rich.console import Console

from ..core.constants import FOLDER_OUTPUT
from ..core.project import Project
from ..steps.lod_assembly import _VIEWER_TEMPLATE

console = Console()


def serve(
    project: Path = typer.Option(
        None,
        "--project", "-p",
        help="Project directory (auto-detected if not specified)",
    ),
    port: int = typer.Option(
        8080,
        "--port",
        help="HTTP port",
    ),
) -> None:
    """Start a local HTTP server to preview the LOD output (Range-supported)."""
    proj = _resolve_project(project)
    output_dir = proj.get_folder(FOLDER_OUTPUT)

    # Both renderers are valid: PlayCanvas writes lod-meta.json, Spark writes scene.rad.
    lod_meta = output_dir / "lod-meta.json"
    scene_rad = output_dir / "scene.rad"
    scene_sog = output_dir / "scene.sog"
    if not (lod_meta.exists() or scene_rad.exists() or scene_sog.exists()):
        console.print(f"[red]No assembled output in {output_dir}[/red]")
        console.print("Run 'splatpipe assemble' first.")
        raise typer.Exit(1)

    # Generate fallbacks for legacy PlayCanvas projects without index.html
    viewer_path = output_dir / "index.html"
    if not viewer_path.exists() and lod_meta.exists():
        distances = proj.lod_distances[:len(proj.get_enabled_lods())]
        html = _VIEWER_TEMPLATE.format(
            project_name=proj.name,
            lod_distances_json=json.dumps(distances),
        )
        viewer_path.write_text(html, encoding="utf-8")

    config_path = output_dir / "viewer-config.json"
    if not config_path.exists():
        config_path.write_text(
            json.dumps(proj.scene_config, indent=2), encoding="utf-8"
        )

    # Spin up a tiny FastAPI app that serves the output dir via FileResponse,
    # which Starlette implements with proper HTTP Range support.
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    @app.get("/", response_class=HTMLResponse)
    def index_root():
        return FileResponse(viewer_path)

    @app.get("/{file_path:path}")
    def serve_file(file_path: str):
        target = (output_dir / file_path).resolve()
        out_resolved = output_dir.resolve()
        if not str(target).startswith(str(out_resolved)):
            return HTMLResponse("Forbidden", status_code=403)
        if not target.is_file():
            return HTMLResponse("Not found", status_code=404)
        return FileResponse(target, headers={
            "Cross-Origin-Opener-Policy": "same-origin",
            "Cross-Origin-Embedder-Policy": "require-corp",
        })

    url = f"http://localhost:{port}"
    console.print(f"[bold]Serving:[/bold] {proj.name}")
    console.print(f"URL: {url}")
    console.print(f"Directory: {output_dir}")
    console.print(
        "Range-capable (Spark .rad streaming + PC chunked SOG both work). "
        "Press Ctrl+C to stop.\n"
    )
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


def _resolve_project(project_path: Path | None) -> Project:
    if project_path:
        return Project(project_path)
    return Project.find()
