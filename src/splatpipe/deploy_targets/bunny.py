"""Bunny CDN deploy target — a FAITHFUL DELEGATION, not a reimplementation.

Every method here calls the existing, battle-tested ``steps/deploy.py``
functions verbatim. This is deliberate: it makes "the Bunny path is
byte-identical" *structurally* true — it is literally the same code,
behind the interface. The hard-won, load-bearing invariants live in
``steps/deploy.py`` / ``steps/publish.py`` and are NOT duplicated here:

  * ``deploy_to_bunny(..., purge=False)`` — the async-delete race fix.
  * the no-edge-cache Edge Rule (``ensure_edge_rules``) — the
    cache-freshness mechanism, asserted every run.
  * selective ``purge_bunny_cache`` of ONLY the two stable text files.

Credentials are read via the existing ``load_bunny_env`` by the caller and
passed in as ``env`` (the same dict ``publish_scene`` already builds).

Optional function injection: the three delegated callables can be passed
in explicitly (``deploy_fn`` / ``ensure_fresh_fn`` / ``invalidate_fn``).
This is purely a *seam*, not a reimplementation — the adapter still only
calls the real ``steps/deploy.py`` functions; injection lets the consumer
hand in its own already-imported (and therefore independently mockable)
references so existing call-site tests keep their patch points. When not
injected, the defaults ARE the real ``steps.deploy`` functions, so
``patch("splatpipe.steps.deploy.deploy_to_bunny")`` intercepts them.
"""

from pathlib import Path
from typing import Callable, Generator

from ..core.events import ProgressEvent, StepResult
from ..steps import deploy as _deploy
from ..steps.deploy import load_bunny_env
from .base import DeployTarget


class BunnyDeployTarget(DeployTarget):
    """The existing Bunny CDN flow, behind the DeployTarget interface."""

    def __init__(
        self,
        *,
        env: dict | None = None,
        deploy_fn: Callable | None = None,
        ensure_fresh_fn: Callable | None = None,
        invalidate_fn: Callable | None = None,
    ):
        # Same precedence as the rest of the codebase: caller-supplied env
        # (publish_scene already resolves this) else load_bunny_env().
        self.env = env if env is not None else load_bunny_env(None)
        # Default to the real, battle-tested steps/deploy.py functions.
        # Resolved at call time off the module so a
        # patch("splatpipe.steps.deploy.deploy_to_bunny") still intercepts
        # the default path.
        self._deploy_fn = deploy_fn
        self._ensure_fresh_fn = ensure_fresh_fn
        self._invalidate_fn = invalidate_fn

    @property
    def name(self) -> str:
        return "bunny"

    def validate_environment(self) -> tuple[bool, str]:
        if not self.env.get("BUNNY_STORAGE_ZONE") or not self.env.get(
            "BUNNY_STORAGE_PASSWORD"
        ):
            return (
                False,
                "BUNNY_STORAGE_ZONE and BUNNY_STORAGE_PASSWORD must be set "
                "(.env / environment / defaults.toml [bunny])",
            )
        return True, "bunny credentials present"

    def deploy_staged(
        self,
        slug: str,
        staged_dir: Path,
        *,
        workers: int = 8,
    ) -> Generator[ProgressEvent, None, StepResult]:
        # Delegate verbatim. purge is hard-pinned False here exactly as the
        # old direct call passed it explicitly (the async-delete race fix);
        # this adapter never overrides it.
        fn = self._deploy_fn or _deploy.deploy_to_bunny
        return fn(slug, staged_dir, self.env, workers=workers, purge=False)

    def ensure_fresh(self, *, quiet: bool = False) -> bool:
        # The cache-freshness REQUIREMENT for bunny IS the Edge-Rule
        # mechanism — delegate to it unchanged (do not weaken).
        fn = self._ensure_fresh_fn or _deploy.ensure_edge_rules
        return fn(self.env.get("BUNNY_ACCOUNT_API_KEY", ""), quiet=quiet)

    def invalidate(self, urls: list[str]) -> None:
        # Mirrors the `if api:` guard in publish_scene step 7 — no account
        # API key → nothing to purge (and purge_bunny_cache is best-effort).
        api = self.env.get("BUNNY_ACCOUNT_API_KEY", "")
        if api and urls:
            fn = self._invalidate_fn or _deploy.purge_bunny_cache
            fn(api, urls)
