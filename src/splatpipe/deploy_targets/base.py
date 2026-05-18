"""Abstract deploy-target interface for scene-output backends.

A ``DeployTarget`` publishes an already-*staged* output directory (the
exact tree publish_scene builds: ``index.html`` + ``viewer-config.json`` +
an immutable ``b<key>/`` chunk subfolder) under a slug, and keeps the two
small mutable text files fresh after a re-deploy.

The method surface is derived strictly from what ``steps/publish.py`` needs
(no speculative methods — YAGNI):

  * ``deploy_staged``  — publish_scene step 6 uploads the staged dir and
    needs the progress generator + the ``StepResult``.
  * ``ensure_fresh``   — publish_scene step 1 asserts the cache-freshness
    mechanism before deploying (the §H2-DECISION REQUIREMENT that the
    mutable config URL is served no-cache / short-TTL).
  * ``invalidate``     — publish_scene step 7 invalidates ONLY the two
    stable text files (``index.html`` + ``viewer-config.json``) — never the
    immutable chunks.

``name`` + ``validate_environment()`` mirror the trainer ABC so the two
abstractions feel identical to callers.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generator

from ..core.events import ProgressEvent, StepResult


class DeployTarget(ABC):
    """Abstract base for scene-deploy backends (Bunny CDN, local folder, …)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this deploy target (e.g. ``"bunny"``)."""

    @abstractmethod
    def validate_environment(self) -> tuple[bool, str]:
        """Check that the target's dependencies / credentials are available.

        Returns ``(ok, message)`` — ``ok=True`` if ready, ``message``
        explains why not.
        """

    @abstractmethod
    def deploy_staged(
        self,
        slug: str,
        staged_dir: Path,
        *,
        workers: int = 8,
    ) -> Generator[ProgressEvent, None, StepResult]:
        """Publish an already-staged output directory under ``slug``.

        ``staged_dir`` is the exact tree publish_scene assembled (root
        ``index.html`` + ``viewer-config.json`` + immutable ``b<key>/``
        chunk subfolder). Yields ``ProgressEvent`` for the CLI/SSE progress
        bar and returns a ``StepResult``.
        """

    @abstractmethod
    def ensure_fresh(self, *, quiet: bool = False) -> bool:
        """Ensure the mutable text files (``index.html`` /
        ``viewer-config.json``) will be served fresh on re-deploy.

        For network CDN targets this asserts the cache-freshness rule
        (Bunny: the no-edge-cache Edge Rule). For a local folder it is a
        no-op (a local file is inherently fresh — the consuming web server
        is expected to send ``Cache-Control: no-cache`` on those two files).
        Best-effort: prefer returning ``False`` and handling failures
        internally rather than raising; callers additionally swallow any
        exception defensively, so a raised exception is tolerated but
        considered an adapter-contract smell.
        """

    @abstractmethod
    def invalidate(self, urls: list[str]) -> None:
        """Invalidate cached copies of the given URLs (the two stable text
        files only — never the immutable chunks).

        For a CDN this purges the edge cache; for a local folder it is a
        no-op. Best-effort: prefer handling failures internally rather than
        raising; callers additionally swallow any exception defensively, so
        a raised exception is tolerated but considered an adapter-contract
        smell.
        """
