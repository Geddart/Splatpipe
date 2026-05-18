"""``cli`` save backend — the decision-A DEFAULT (no web-facing secret).

This is the productised, reusable form of exactly what
``cli/set_start_view_cmd.py`` already does for the start-view relay,
generalised from the single ``start_view`` write to the full camera-scope
allow-list. It is a FAITHFUL REUSE, not a reimplementation — it ties
together three already-built, separately-tested pieces:

  * **fetch** the project's current live ``viewer-config.json`` — via the
    *same* ``_fetch_remote_config`` helper ``set_start_view`` uses
    (imported directly; it is already a clean, console-free module-level
    function — no extraction needed, zero behaviour change).
  * **merge** the untrusted patch onto it with
    :func:`splatpipe.core.config_merge.merge_camera_scope` (Task 4 — the
    one shared merge core; ``primary_asset`` force-kept, non-allow-listed
    keys silently dropped). The merge is NOT reimplemented here.
  * **write/deploy** the merged config via the pluggable
    :class:`splatpipe.deploy_targets.DeployTarget` (Task 5, default
    ``bunny`` — a faithful delegation to the battle-tested
    ``steps/deploy.py``). The deploy is NOT reimplemented here.

There is **no web-facing secret** in ``cli`` mode (mirrors
``set_start_view``, which performs no token-based auth — it simply decodes
the relayed token and writes). ``token`` is accepted for interface parity
/ future use; the caller (Task 7's ``splatpipe set-camera-path`` CLI) has
already decoded the ``SPCP1`` token into ``slug`` + ``payload`` via
:mod:`splatpipe.core.spcp_token` before reaching this backend.

The Task-4 review carry-forward: ``merge_camera_scope`` silently drops any
patch key outside its locked allow-list with no caller signal. We recompute
those dropped keys (``set(payload) - ALLOWED_PATCH_KEYS``, never
``primary_asset``) and surface them in :attr:`SaveResult.ignored_keys` so
the CLI/UI can tell the author "these keys were not saved" — informational,
not an error. ``config_merge.py``'s silent-drop contract is unchanged.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..cli.set_start_view_cmd import _fetch_remote_config
from ..core.config_merge import ALLOWED_PATCH_KEYS, merge_camera_scope
from ..deploy_targets import get_deploy_target
from ..steps.deploy import load_bunny_env
from .base import SaveBackend, SaveResult


class CliRelayBackend(SaveBackend):
    """fetch → merge_camera_scope → write via the pluggable DeployTarget.

    The DEFAULT save backend. Kept a clean reusable unit so Task 7's
    ``splatpipe set-camera-path`` CLI can thin-wrap it.
    """

    @property
    def name(self) -> str:
        return "cli"

    # ---- config helpers -----------------------------------------------------

    def _save_backend_cfg(self) -> dict:
        return self.config.get("save_backend", {}) or {}

    def _deploy_target_name(self) -> str | None:
        """Which DeployTarget to write through (default = bunny via the
        registry's own default when None — same precedence as publish)."""
        return self._save_backend_cfg().get("deploy_target") or None

    def _bunny_env(self) -> dict:
        """Resolve Bunny creds the same way the rest of the codebase does
        (.env / environment / defaults.toml ``[bunny]`` — via
        ``load_bunny_env``)."""
        try:
            return load_bunny_env(None)
        except Exception:  # noqa: BLE001 - env discovery is best-effort
            return {}

    def _resolve_target(self):
        """Resolve the configured DeployTarget. For ``bunny`` (the default)
        inject the same module-level (patchable) ``steps.deploy`` refs
        ``publish_scene`` injects, so the bunny path stays byte-identical
        and existing call-site patch points keep working."""
        name = self._deploy_target_name()
        if name is None or name == "bunny":
            from ..steps.deploy import (
                deploy_to_bunny,
                ensure_edge_rules,
                purge_bunny_cache,
            )

            return get_deploy_target(
                "bunny",
                env=self._bunny_env(),
                deploy_fn=deploy_to_bunny,
                ensure_fresh_fn=ensure_edge_rules,
                invalidate_fn=purge_bunny_cache,
            )
        if name == "folder":
            dest = self._save_backend_cfg().get("deploy_dest")
            return get_deploy_target("folder", destination=dest)
        # Any other registered target — let the registry construct it (and
        # raise KeyError with the available list if unknown).
        return get_deploy_target(name)

    def _fetch_live_config(self, slug: str) -> dict:
        """GET the scene's current viewer-config.json from Bunny Storage
        origin — the SAME ``_fetch_remote_config`` helper ``set_start_view``
        uses (returns ``{}`` if it does not exist yet). Kept as a thin
        method so tests can stub the I/O without touching the merge/deploy."""
        env = self._bunny_env()
        return _fetch_remote_config(
            env.get("BUNNY_STORAGE_ZONE", ""),
            env.get("BUNNY_STORAGE_PASSWORD", ""),
            slug,
        )

    # ---- SaveBackend API ----------------------------------------------------

    def save_keyframes(self, slug: str, payload: dict, token: str) -> SaveResult:
        slug = slug.strip("/").lower()

        # Task-4 carry-forward: which patch keys merge_camera_scope will
        # silently drop. primary_asset is a locked-invariant force-keep, not
        # an author diagnostic — never list it.
        ignored = sorted(
            k for k in payload
            if k not in ALLOWED_PATCH_KEYS and k != "primary_asset"
        )

        try:
            target = self._resolve_target()
        except KeyError as e:
            return SaveResult(backend=self.name, success=False, slug=slug,
                              error=str(e), ignored_keys=ignored)

        ok, why = target.validate_environment()
        if not ok:
            return SaveResult(backend=self.name, success=False, slug=slug,
                              error=f"deploy target not ready: {why}",
                              ignored_keys=ignored)

        # 1. Re-assert the target's cache-freshness mechanism (best-effort;
        #    never fatal — same posture as publish_scene step 1).
        try:
            target.ensure_fresh(quiet=True)
        except Exception:  # noqa: BLE001 - never fatal
            pass

        # 2. fetch → merge (force-keep primary_asset) via the SHARED core, so
        #    this CLI relay and every future HTTP save adapter agree
        #    byte-for-byte. The merge is NOT reimplemented here.
        try:
            existing = self._fetch_live_config(slug)
        except Exception as exc:  # noqa: BLE001 - network/HTTP error -> SaveResult, not a raise
            return SaveResult(backend=self.name, success=False, slug=slug,
                              error=f"fetch viewer-config failed: {exc}",
                              ignored_keys=ignored)
        merged = merge_camera_scope(existing, payload)

        # 3. Stage the merged config and deploy it via the resolved target.
        #    A keyframe save only rewrites the small mutable viewer-config —
        #    NOT index.html and NOT the immutable chunks (those are owned by
        #    publish_scene). primary_asset stays whatever the live config
        #    had, so the existing build keeps loading.
        stage = Path(tempfile.mkdtemp(prefix=f"splatpipe-save-{slug}-"))
        try:
            (stage / "viewer-config.json").write_text(
                json.dumps(merged, indent=2), encoding="utf-8")

            gen = target.deploy_staged(slug, stage, workers=8)
            dresult = None
            try:
                while True:
                    next(gen)
            except StopIteration as stop:
                dresult = stop.value

            summ = dict(dresult.summary) if dresult and dresult.summary else {}
            if not dresult or not dresult.success or summ.get("failed_files"):
                return SaveResult(
                    backend=self.name, success=False, slug=slug,
                    error=(dresult.error if dresult else "deploy: no result")
                          or f"deploy failed: {summ.get('failed_files')}",
                    ignored_keys=ignored, summary=summ)

            # 4. Invalidate ONLY the mutable viewer-config.json (the keyframe
            #    save never touches index.html or the immutable chunks). The
            #    target guards internally on missing creds / no edge cache.
            cdn = self._bunny_env().get("BUNNY_CDN_URL", "").rstrip("/")
            if cdn:
                target.invalidate([f"{cdn}/{slug}/viewer-config.json"])

            msg = f"saved camera-scope for {slug} via {target.name}"
            if ignored:
                msg += f" (ignored non-allow-listed keys: {ignored})"
            return SaveResult(backend=self.name, success=True, slug=slug,
                              message=msg, ignored_keys=ignored, summary=summ)
        finally:
            import shutil
            shutil.rmtree(stage, ignore_errors=True)

    def validate_environment(self) -> tuple[bool, str]:
        """Ready iff a DeployTarget is resolvable AND its env is valid."""
        try:
            target = self._resolve_target()
        except KeyError as e:
            return False, str(e)
        ok, why = target.validate_environment()
        if not ok:
            return False, f"deploy target '{target.name}' not ready: {why}"
        return True, f"cli relay → deploy target '{target.name}' ready"
