"""Abstract save-backend interface for the keyframe-editor save layer.

The deployed Spark viewers are static files on a CDN with no backend (the
storage key must never live in client JS). A viewer's keyframe editor
therefore only *emits* an untrusted patch; the trusted side fetches the
project's current ``viewer-config.json``, merges the patch onto it via the
shared :func:`splatpipe.core.config_merge.merge_camera_scope` core, and
writes it back.

A ``SaveBackend`` is the pluggable strategy for *how* that trusted save
happens for a given scene:

  * ``cli``        — the decision-A DEFAULT (no web-facing secret): the
    author relays the editor's token to a local CLI, which does
    fetch → merge → write via the pluggable ``DeployTarget``.
  * ``php`` / ``cloudflare`` — the scene's viewer POSTs the patch directly
    to an external HTTP endpoint; the actual save runs browser→server
    (the PHP / Worker artifact, separate later tasks). The splatpipe-side
    role is config only — these backends are THIN.

This mirrors :mod:`splatpipe.trainers.base` and
:mod:`splatpipe.deploy_targets.base` so the three abstractions feel
identical to callers (ABC + ``@property name`` + ``validate_environment``
+ a ``@dataclass`` result type).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


def _looks_like_url(url: str) -> bool:
    """Return True if *url* looks like an HTTP/HTTPS URL.

    Used by the thin HTTP backends (php, cloudflare) to validate their
    configured ``endpoint``.
    """
    return isinstance(url, str) and url.startswith(("http://", "https://"))


@dataclass
class SaveResult:
    """Result of a keyframe-editor save (mirrors ``TrainResult``'s spirit).

    ``ignored_keys`` is the Task-4 review carry-forward: the shared
    :func:`merge_camera_scope` core silently drops any patch key not in its
    locked allow-list (and never moves ``primary_asset``) with no caller
    signal. The ``cli`` backend recomputes those dropped keys here so the
    CLI/UI can tell the author "these keys were not saved" — purely
    informational, NOT an error (a non-empty ``ignored_keys`` with
    ``success=True`` is a normal, valid outcome). ``primary_asset`` is
    deliberately never listed here (it is a locked-invariant force-keep,
    not an author-typo diagnostic).
    """

    backend: str
    success: bool
    slug: str = ""
    message: str = ""
    error: str = ""
    ignored_keys: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


class SaveBackend(ABC):
    """Abstract base for keyframe-editor save backends (cli, php, …)."""

    def __init__(self, config: dict):
        self.config = config

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this save backend (e.g. ``"cli"``)."""

    @abstractmethod
    def save_keyframes(self, slug: str, payload: dict, token: str) -> SaveResult:
        """Persist a viewer-emitted camera-scope *payload* for scene *slug*.

        Args:
            slug: the scene's permanent (kebab-case) slug — the CDN folder.
            payload: the untrusted camera-scope patch (already decoded from
                the editor's ``SPCP1`` token by the caller).
            token: the original per-scene/relay token. For the ``cli``
                backend there is no web-facing secret (it is accepted for
                interface parity / future use); the HTTP backends do not
                perform the save in Python at all.

        Returns:
            A :class:`SaveResult` with full diagnostics.
        """

    @abstractmethod
    def validate_environment(self) -> tuple[bool, str]:
        """Check that this backend's dependencies / config are available.

        Returns ``(ok, message)`` — ``ok=True`` if ready, ``message``
        explains why not. Mirrors the trainer / deploy-target ABCs.
        """
