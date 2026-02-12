"""splatpipe web — Start the web dashboard."""

import typer
from rich.console import Console

console = Console()


def web(
    port: int = typer.Option(
        8000,
        "--port",
        help="HTTP port for the dashboard",
    ),
    host: str = typer.Option(
        "0.0.0.0",
        "--host",
        help="Host to bind to",
    ),
) -> None:
    """Start the Splatpipe web dashboard (FastAPI + HTMX)."""
    import uvicorn

    console.print("[bold]Starting Splatpipe dashboard[/bold]")
    console.print(f"URL: http://localhost:{port}")
    console.print()

    uvicorn.run(
        "splatpipe.web.app:app",
        host=host,
        port=port,
        reload=False,
    )
