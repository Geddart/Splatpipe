"""Security tests for the ``splatpipe web`` CLI command.

Bug-audit-2026-05-19 finding #5: the dashboard previously bound to
``0.0.0.0`` (every interface) by default, exposing filesystem browsing,
OS-level open actions (open folder / open file / open tool) and settings
edit to any host on the LAN -- with no authentication, no CSRF. These
tests lock the hardened defaults:

* The default bind is ``127.0.0.1`` (loopback only). Running
  ``splatpipe web`` with no flags must NOT expose the dashboard to LAN.
* ``--unsafe-network`` is an explicit, named opt-in that resolves to
  ``0.0.0.0``. The name itself signals the risk.
* An explicit ``--host`` always wins (it is the most precise expression
  of intent). When combined with ``--unsafe-network`` a warning is
  emitted noting the precedence.
* Binding to any non-loopback host emits a clear startup warning naming
  the host:port and the filesystem-browsing / OS-open exposure surface,
  so a user who deliberately opens the LAN port cannot be surprised by
  it later.
* Binding to a loopback host (``127.0.0.1``, ``localhost``, ``::1``)
  emits NO warning -- that is the safe default and must stay quiet.

Mocking note: ``uvicorn.run`` is patched in every test so no server is
ever actually started. The patched call's ``host=`` kwarg is the
load-bearing observable -- that is what governs which interfaces the
dashboard listens on.
"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from splatpipe.cli.main import app


# Typer >= 0.16 / Click >= 8.2 dropped the ``mix_stderr`` kwarg; stdout
# and stderr are captured into a single combined ``result.output`` /
# ``result.stdout`` stream. That is what the warning assertions below
# inspect.
runner = CliRunner()


# Warning sentinel -- a fragment of the exact warning text required by
# task #109 / bug-audit-2026-05-19 #5. Asserting on a fragment (not the
# whole string) lets us evolve the wording without breaking these tests,
# while still locking the load-bearing content: the host:port the
# dashboard is bound to AND the filesystem-exposure framing.
_WARN_HOSTPORT_FRAGMENT = "Dashboard bound to"
_WARN_FS_EXPOSURE_FRAGMENT = "filesystem browsing"


def _invoke_web(*args: str):
    """Invoke ``splatpipe web ARGS`` with uvicorn.run patched.

    Returns a tuple ``(result, mock_run)`` -- ``result`` is the typer
    CliRunner result (exit code, stdout, stderr); ``mock_run`` is the
    captured Mock so callers can assert on the host/port it received.
    """
    with patch("uvicorn.run") as mock_run:
        result = runner.invoke(app, ["web", *args])
    return result, mock_run


def test_web_command_default_host_is_localhost():
    """``splatpipe web`` with no flags MUST bind to 127.0.0.1.

    This is THE central regression test for bug-audit #5. Any change
    that flips the default back to 0.0.0.0 (or any non-loopback) MUST
    fail this test.
    """
    result, mock_run = _invoke_web()

    assert result.exit_code == 0, result.output
    assert mock_run.called, "uvicorn.run must be invoked"
    kwargs = mock_run.call_args.kwargs
    assert kwargs["host"] == "127.0.0.1", (
        f"Expected default host=127.0.0.1, got {kwargs['host']!r}. "
        "This is a SECURITY regression -- see bug-audit-2026-05-19 #5."
    )


def test_web_command_explicit_host_overrides_default():
    """``--host 192.168.1.10`` MUST bind to exactly that host."""
    result, mock_run = _invoke_web("--host", "192.168.1.10")

    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs["host"] == "192.168.1.10"


def test_web_command_unsafe_network_flag_binds_to_all_interfaces():
    """``--unsafe-network`` MUST resolve to host=0.0.0.0.

    This is the explicit, named opt-in for LAN exposure.
    """
    result, mock_run = _invoke_web("--unsafe-network")

    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs["host"] == "0.0.0.0"


def test_web_command_explicit_host_takes_precedence_over_unsafe_network():
    """``--host X --unsafe-network`` MUST keep host=X (explicit wins).

    Also: a precedence warning MUST be emitted so the user is not
    silently surprised by their flag combination being collapsed.
    """
    result, mock_run = _invoke_web(
        "--host", "10.0.0.5",
        "--unsafe-network",
    )

    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs["host"] == "10.0.0.5"
    # Precedence note must surface somewhere visible. CliRunner combines
    # stdout + stderr into ``result.output`` in current Click/Typer.
    combined = result.output or ""
    assert "host" in combined.lower() and (
        "unsafe-network" in combined.lower() or "unsafe_network" in combined.lower()
    ), (
        "Expected a precedence warning when both --host and "
        f"--unsafe-network are passed. Got: {combined!r}"
    )


def test_web_command_emits_warning_when_bound_non_loopback():
    """An explicit non-loopback host MUST trigger the LAN-exposure warning."""
    result, mock_run = _invoke_web("--host", "0.0.0.0")

    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs["host"] == "0.0.0.0"

    combined = result.output or ""
    assert _WARN_HOSTPORT_FRAGMENT in combined, (
        f"Expected LAN-exposure warning containing "
        f"{_WARN_HOSTPORT_FRAGMENT!r}. Got: {combined!r}"
    )
    assert _WARN_FS_EXPOSURE_FRAGMENT in combined, (
        f"Expected warning to mention {_WARN_FS_EXPOSURE_FRAGMENT!r} "
        f"so the user understands the actual exposure surface. "
        f"Got: {combined!r}"
    )


def test_web_command_emits_warning_when_unsafe_network_used():
    """``--unsafe-network`` (the named LAN opt-in) MUST also emit the warning.

    The flag is documented as ``unsafe`` precisely because it opens this
    surface; suppressing the warning when the unsafe flag is used would
    defeat the purpose.
    """
    result, _ = _invoke_web("--unsafe-network")

    combined = result.output or ""
    assert _WARN_HOSTPORT_FRAGMENT in combined, combined
    assert _WARN_FS_EXPOSURE_FRAGMENT in combined, combined


def test_web_command_no_warning_when_bound_loopback_default():
    """Default invocation (no flags) MUST NOT print the LAN warning.

    127.0.0.1 is the safe default. Emitting the warning here would
    train users to ignore it.
    """
    result, _ = _invoke_web()

    combined = result.output or ""
    assert _WARN_HOSTPORT_FRAGMENT not in combined, (
        f"Default loopback bind must be quiet (no LAN warning). "
        f"Got: {combined!r}"
    )
    assert _WARN_FS_EXPOSURE_FRAGMENT not in combined, combined


def test_web_command_no_warning_when_explicit_loopback_127():
    """Explicit ``--host 127.0.0.1`` MUST be treated as safe (no warning)."""
    result, _ = _invoke_web("--host", "127.0.0.1")

    combined = result.output or ""
    assert _WARN_HOSTPORT_FRAGMENT not in combined, combined


def test_web_command_no_warning_when_explicit_loopback_localhost():
    """``--host localhost`` is loopback by DNS convention; treat as safe."""
    result, mock_run = _invoke_web("--host", "localhost")

    assert mock_run.call_args.kwargs["host"] == "localhost"
    combined = result.output or ""
    assert _WARN_HOSTPORT_FRAGMENT not in combined, combined


def test_web_command_no_warning_when_explicit_loopback_ipv6():
    """``--host ::1`` is the IPv6 loopback literal; treat as safe."""
    result, mock_run = _invoke_web("--host", "::1")

    assert mock_run.call_args.kwargs["host"] == "::1"
    combined = result.output or ""
    assert _WARN_HOSTPORT_FRAGMENT not in combined, combined


def test_web_command_warning_contains_resolved_host_and_port():
    """The warning MUST name the actual bound host:port so the user can
    distinguish a 0.0.0.0 bind from a specific-interface bind in their
    own console history.
    """
    result, _ = _invoke_web("--host", "192.168.1.42", "--port", "8765")

    combined = result.output or ""
    assert "192.168.1.42" in combined, (
        f"Warning must name the actual host. Got: {combined!r}"
    )
    assert "8765" in combined, (
        f"Warning must name the actual port. Got: {combined!r}"
    )
