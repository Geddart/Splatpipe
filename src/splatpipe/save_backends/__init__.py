"""Pluggable keyframe-editor save backends.

Mirrors ``splatpipe.trainers`` / ``splatpipe.deploy_targets``: an ABC + a
name-string registry so the keyframe-editor save layer is not infra-bound.

  * ``cli``        — the decision-A DEFAULT (no web-facing secret): a
    faithful reuse of the ``set_start_view`` relay (fetch → shared
    ``merge_camera_scope`` → write via the pluggable ``DeployTarget``).
  * ``php`` / ``cloudflare`` — THIN config-only adapters; the save runs
    browser→server (the PHP / Worker artifacts are separate later tasks).
"""

from .base import SaveBackend, SaveResult
from .cli import CliRelayBackend
from .cloudflare import CloudflareWorkerBackend
from .php import PhpEndpointBackend
from .registry import SAVE_BACKENDS, get_save_backend, list_save_backends

__all__ = [
    "SaveBackend",
    "SaveResult",
    "CliRelayBackend",
    "PhpEndpointBackend",
    "CloudflareWorkerBackend",
    "SAVE_BACKENDS",
    "get_save_backend",
    "list_save_backends",
]
