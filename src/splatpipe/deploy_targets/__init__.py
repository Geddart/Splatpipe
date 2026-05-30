"""Pluggable deploy-target backends.

Mirrors ``splatpipe.trainers``: an ABC + a name-string registry so the
scene-deploy step is not infra-bound. Two adapters ship today — ``bunny``
(the default; a faithful delegation to the battle-tested
``steps/deploy.py``) and ``folder`` (copy the staged output to a local
directory). Adding ``sftp`` / ``s3`` / ``rsync`` later is a one-line
registry entry (see ``registry.py``).
"""

from .base import DeployTarget
from .bunny import BunnyDeployTarget
from .folder import FolderDeployTarget
from .registry import DEPLOY_TARGETS, get_deploy_target, list_deploy_targets

__all__ = [
    "DeployTarget",
    "BunnyDeployTarget",
    "FolderDeployTarget",
    "DEPLOY_TARGETS",
    "get_deploy_target",
    "list_deploy_targets",
]
