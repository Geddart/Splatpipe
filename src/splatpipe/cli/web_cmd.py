"""splatpipe web — Start the web dashboard.

Bind defaults are security-critical: the dashboard exposes filesystem
browsing, OS-level open actions (open folder / open file / open tool)
and settings editing without authentication or CSRF. Binding to
``0.0.0.0`` makes that surface reachable from any host on the LAN.

This module locks two defaults (bug-audit-2026-05-19 finding #5):

1. Default ``--host`` is ``127.0.0.1`` (loopback only). ``splatpipe web``
   with no flags is safe to run on an untrusted network.
2. LAN exposure requires an explicit opt-in -- either ``--host 0.0.0.0``
   (or any specific non-loopback address) or the named convenience
   flag ``--unsafe-network``. Both paths emit a clear startup warning
   naming the actual host:port and the exposure surface.

If both ``--host`` and ``--unsafe-network`` are passed the explicit
``--host`` value wins (it is the most precise expression of intent);
a small precedence note is printed so the user is not surprised.
"""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


# Loopback host literals that MUST NOT trigger the LAN-exposure warning.
# IPv4 loopback, the DNS-convention name (resolves to a loopback address
# in any reasonable configuration), and the IPv6 loopback literal.
# Kept narrow on purpose -- 127.0.0.0/8 is reachable but uncommon enough
# that callers using e.g. 127.0.0.2 will see the warning and can decide
# whether that surprises them.
_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_loopback(host: str) -> bool:
    """Return True iff ``host`` is one of the recognised loopback literals."""
    return host.strip().lower() in _LOOPBACK_HOSTS


def _emit_lan_warning(console: Console, host: str, port: int) -> None:
    """Print the LAN-exposure warning to the user.

    Worded so a user grep'ing their console history later sees both
    the actual host:port AND a description of WHAT is being exposed.
    """
    console.print(
        f"[yellow]⚠[/yellow]  [bold yellow]Dashboard bound to "
        f"{host}:{port}[/bold yellow] -- this exposes filesystem "
        f"browsing and OS-level open actions to any host that can "
        f"reach this port. Only do this on a trusted network. To "
        f"restrict to localhost only, run [cyan]splatpipe web[/cyan] "
        f"without [cyan]--host[/cyan] / [cyan]--unsafe-network[/cyan]."
    )


def web(
    port: int = typer.Option(
        8000,
        "--port",
        help="HTTP port for the dashboard.",
    ),
    host: str | None = typer.Option(
        None,
        "--host",
        help=(
            "Host/interface to bind to. Default: 127.0.0.1 "
            "(loopback only -- safe). To expose to the LAN, pass an "
            "explicit address (e.g. --host 0.0.0.0) or use "
            "--unsafe-network. A warning is printed for any non-loopback "
            "bind."
        ),
    ),
    unsafe_network: bool = typer.Option(
        False,
        "--unsafe-network",
        help=(
            "Bind to 0.0.0.0 (all interfaces) -- equivalent to "
            "--host 0.0.0.0. Required to expose the dashboard to the "
            "LAN; the name is explicit because the dashboard has no "
            "authentication and exposes filesystem browsing + OS-level "
            "open actions. If --host is also passed, --host wins."
        ),
    ),
) -> None:
    """Start the Splatpipe web dashboard (FastAPI + HTMX).

    Default bind is 127.0.0.1 (loopback only). LAN exposure requires an
    explicit opt-in (``--host 0.0.0.0`` or ``--unsafe-network``).
    """
    import uvicorn

    # Resolve the bind host. Precedence:
    #   1. explicit --host (most precise; wins, even over --unsafe-network)
    #   2. --unsafe-network (named LAN opt-in; resolves to 0.0.0.0)
    #   3. default 127.0.0.1 (safe; loopback only)
    if host is not None:
        resolved_host = host
        if unsafe_network:
            # Both passed -- the explicit value wins, but make that
            # precedence visible so the user is not surprised.
            console.print(
                f"[yellow]Note:[/yellow] both [cyan]--host {host}[/cyan] "
                f"and [cyan]--unsafe-network[/cyan] were passed; the "
                f"explicit [cyan]--host[/cyan] value takes precedence."
            )
    elif unsafe_network:
        resolved_host = "0.0.0.0"
    else:
        resolved_host = "127.0.0.1"

    console.print("[bold]Starting Splatpipe dashboard[/bold]")
    console.print(f"URL: http://localhost:{port}")

    if not _is_loopback(resolved_host):
        _emit_lan_warning(console, resolved_host, port)

    console.print()

    uvicorn.run(
        "splatpipe.web.app:app",
        host=resolved_host,
        port=port,
        reload=False,
    )
