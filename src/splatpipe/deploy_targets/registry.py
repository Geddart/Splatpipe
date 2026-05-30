"""Deploy-target registry: maps target names to implementations.

Mirrors ``splatpipe.trainers.registry``. Adding a future backend is a
ONE-LINE registry entry plus its adapter module, e.g.::

    from .sftp import SftpDeployTarget
    DEPLOY_TARGETS = {..., "sftp": SftpDeployTarget}

``sftp`` / ``s3`` / ``rsync`` are intentionally NOT implemented yet (YAGNI;
a later task adds ``sftp`` if needed).
"""

from .base import DeployTarget
from .bunny import BunnyDeployTarget
from .folder import FolderDeployTarget

DEPLOY_TARGETS: dict[str, type[DeployTarget]] = {
    "bunny": BunnyDeployTarget,
    "folder": FolderDeployTarget,
}

#: The default target when no name is given (the existing, infra-bound
#: behaviour stays the default so nothing changes for current users).
DEFAULT_DEPLOY_TARGET = "bunny"


def get_deploy_target(name: str | None = None, **kwargs) -> DeployTarget:
    """Get a deploy-target instance by name (defaults to ``"bunny"``).

    ``**kwargs`` are forwarded to the adapter constructor (e.g.
    ``env=...`` for bunny, ``destination=...`` for folder).

    Raises ``KeyError`` (with the available list) if the name is unknown —
    same contract as ``trainers.registry.get_trainer``.
    """
    if name is None:
        name = DEFAULT_DEPLOY_TARGET
    cls = DEPLOY_TARGETS.get(name)
    if cls is None:
        available = ", ".join(DEPLOY_TARGETS.keys())
        raise KeyError(
            f"Unknown deploy target: {name!r}. Available: {available}"
        )
    return cls(**kwargs)


def list_deploy_targets() -> list[str]:
    """Return available deploy-target names."""
    return list(DEPLOY_TARGETS.keys())
