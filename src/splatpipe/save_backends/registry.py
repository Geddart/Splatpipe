"""Save-backend registry: maps backend names to implementations.

Mirrors ``splatpipe.trainers.registry`` / ``splatpipe.deploy_targets.registry``
exactly (name-string selector, ``KeyError`` with the available list on an
unknown name, ``list_save_backends()``). ``cli`` is the decision-A DEFAULT.
"""

from .base import SaveBackend
from .cli import CliRelayBackend
from .cloudflare import CloudflareWorkerBackend
from .php import PhpEndpointBackend

SAVE_BACKENDS: dict[str, type[SaveBackend]] = {
    "cli": CliRelayBackend,
    "php": PhpEndpointBackend,
    "cloudflare": CloudflareWorkerBackend,
}


def get_save_backend(name: str, config: dict) -> SaveBackend:
    """Get a save-backend instance by name.

    Raises KeyError (with the available list) if the name is unknown —
    same contract as ``trainers.registry.get_trainer``.
    """
    cls = SAVE_BACKENDS.get(name)
    if cls is None:
        available = ", ".join(SAVE_BACKENDS.keys())
        raise KeyError(f"Unknown save backend: {name!r}. Available: {available}")
    return cls(config)


def list_save_backends() -> list[str]:
    """Return available save-backend names."""
    return list(SAVE_BACKENDS.keys())
