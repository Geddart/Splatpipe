"""splatpipe serve — Local HTTP server with viewer."""

import http.server
import threading
import webbrowser
from pathlib import Path

import typer
from rich.console import Console

from ..core.constants import FOLDER_OUTPUT
from ..core.project import Project

console = Console()

VIEWER_TEMPLATE = """<!DOCTYPE html>
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
    <iframe id="viewer"
        src="https://superspl.at/editor?load={splat_url}"
        allow="cross-origin-isolated">
    </iframe>
</body>
</html>"""


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
    """Start a local HTTP server to preview the LOD output."""
    proj = _resolve_project(project)
    output_dir = proj.get_folder(FOLDER_OUTPUT)

    lod_meta = output_dir / "lod-meta.json"
    if not lod_meta.exists():
        console.print(f"[red]{lod_meta} not found[/red]")
        console.print("Run 'splatpipe assemble' first.")
        raise typer.Exit(1)

    # Use assemble-generated viewer if present, otherwise generate one
    viewer_path = output_dir / "index.html"
    if not viewer_path.exists():
        html = VIEWER_TEMPLATE.format(
            project_name=proj.name,
            splat_url="lod-meta.json",
        )
        viewer_path.write_text(html, encoding="utf-8")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(output_dir), **kwargs)

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
            super().end_headers()

        def log_message(self, format, *args):
            pass  # Suppress request logs

    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    url = f"http://localhost:{port}"

    console.print(f"[bold]Serving:[/bold] {proj.name}")
    console.print(f"URL: {url}")
    console.print(f"Directory: {output_dir}")
    console.print("Press Ctrl+C to stop\n")

    threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\nStopped.")
        server.server_close()


def _resolve_project(project_path: Path | None) -> Project:
    if project_path:
        return Project(project_path)
    return Project.find()
