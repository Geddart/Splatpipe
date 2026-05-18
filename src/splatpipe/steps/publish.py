"""Publish step: build a source PLY (or stage a prebuilt chunked set) and
deploy it to a **permanent Bunny slug URL that never changes across rebuilds.**

This is the productised form of what was the `.codex-run/deploy_scene_cs.py`
scratch script. The hard-won, load-bearing invariants (don't break these -
six live production scenes depend on them; see the project memories
`project_bunny_viewer_config_cache` and `project_bunny_purge_reupload_race`):

  * **Build-agnostic `index.html`** - `html_for(primary_asset="scene.rad")`,
    NEVER the per-build `b<key>/scene.rad`. The viewer's `_PRIMARY` JS reads
    the real pointer from the no-store `viewer-config.json`.
  * **`viewer-config.json` carries `primary_asset = "<bkey>/scene.rad"`** -
    the always-fresh small file is the single source of truth for which
    immutable build subfolder to load.
  * **`deploy_to_bunny(..., purge=False)`** - purge=True issues a Bunny
    recursive directory DELETE that runs async server-side and races the
    re-upload of the same paths (observed clobbering a live scene).
  * **Edge Rule asserted every run** - the pull zone force-caches 30 days
    and overrides client `cache:'no-store'`; the rule keeps the two small
    text files edge+browser fresh while chunks stay long-cached.
  * **Selective purge** - only `index.html` + `viewer-config.json`, never
    the immutable `b<key>/` chunks.

Layout per slug (e.g. ``speicher``):

    <slug>/index.html          stable, build-agnostic, edge-fresh
    <slug>/viewer-config.json  stable, no-store, holds primary_asset pointer
    <slug>/preview.jpg         stable (published separately as a share card)
    <slug>/b<key>/scene.rad    immutable per-build manifest
    <slug>/b<key>/*.radc       immutable per-build chunks

The public URL is forever ``https://<cdn>/<slug>/index.html`` (+ ``?embed=1``).
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Generator
from urllib.request import Request, urlopen

from ..core.constants import STEP_PUBLISH
from ..core.events import ProgressEvent, StepResult
from ..deploy_targets import get_deploy_target
from ..viewers.spark.build_lod import BuildLodError, build
from ..viewers.spark.template import html_for
from .deploy import (
    _purge_bunny_folder,
    deploy_to_bunny,
    ensure_edge_rules,
    list_bunny_subfolders,
    purge_bunny_cache,
)

# NOTE: ``deploy_to_bunny`` / ``ensure_edge_rules`` / ``purge_bunny_cache``
# are still imported here on purpose. The scene deploy now goes through the
# pluggable ``DeployTarget`` abstraction (so splatpipe is not infra-bound),
# but for the DEFAULT ``bunny`` target we hand these *same* module-level
# references into the adapter (``BunnyDeployTarget(..., deploy_fn=...)``).
# The adapter is a faithful delegation — it just calls whatever deploy
# functions it's given (default = the real ``steps.deploy`` ones). Keeping
# the names here preserves the existing call-site patch points so the
# behaviour-preservation oracle (tests/test_publish.py) stays byte-identical
# AND unchanged. ``list_bunny_subfolders`` / ``_purge_bunny_folder`` are
# Bunny-Storage-specific stale-subfolder bookkeeping, NOT part of the
# cohesive DeployTarget contract, so they stay a direct call (only ever
# reached on the bunny path).

#: Neutral, never-fabricated share-card description (see the project memory
#: `feedback_no_fabricated_scene_descriptions`). Pass real user copy to
#: override; never invent scene specifics.
NEUTRAL_DESC = "Interactive 3D photogrammetry scene - explore it in your browser."

#: Words that, if present in a generated card, indicate a fabricated
#: description slipped in. The self-check rejects them unless an explicit
#: `description` was supplied by the caller.
_FABRICATED_MARKERS = ("derelict", "brewery", "Sterni", "printworks", "art-festival")


def _ev(progress: float, message: str, detail: str = "") -> ProgressEvent:
    return ProgressEvent(step=STEP_PUBLISH, progress=progress,
                         message=message, detail=detail)


def _fetch_live_config(cdn: str, live_slug: str) -> dict:
    """Inherit a deployed slug's viewer-config.json (start_view, per-scene
    overrides). Best-effort: {} if it can't be fetched."""
    url = f"{cdn}/{live_slug}/viewer-config.json"
    try:
        req = Request(url, headers={"Cache-Control": "no-cache"})
        data = json.loads(urlopen(req, timeout=30).read())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def publish_scene(
    *,
    scene_name: str,
    slug: str,
    env: dict,
    ply: Path | None = None,
    rad_dir: Path | None = None,
    base_config: dict | None = None,
    live_slug: str | None = None,
    clip_xy: float | None = None,
    move_speed_mult: float | None = None,
    splat_budget: int | None = None,
    crop_within: str | None = None,
    desc: str | None = None,
    prune_stale: bool = False,
    spark_repo: Path | None = None,
    on_build_line: Callable[[str], None] | None = None,
    deploy_target: str = "bunny",
    deploy_dest: Path | None = None,
) -> Generator[ProgressEvent, None, StepResult]:
    """Build/stage a scene and deploy it to its permanent slug.

    Exactly one of ``ply`` / ``rad_dir`` must be given. ``base_config`` (e.g.
    a project's ``scene_config``) is inherited if provided; otherwise
    ``live_slug`` is fetched from the CDN to inherit a previously deployed
    config; otherwise an empty config is used. Yields ``ProgressEvent`` and
    returns a ``StepResult``.

    ``deploy_target`` selects the pluggable ``DeployTarget`` backend
    (default ``"bunny"`` — the existing, infra-bound behaviour, byte-
    identical). ``"folder"`` copies the staged output to ``deploy_dest``.
    The bunny path is unchanged: the same ``deploy_to_bunny(..., purge=
    False)``, the same edge-rule assertion, the same selective purge.
    """
    if bool(ply) == bool(rad_dir):
        return StepResult(step=STEP_PUBLISH, success=False,
                          error="give exactly one of ply= or rad_dir=")
    if crop_within and rad_dir:
        return StepResult(step=STEP_PUBLISH, success=False,
                          error="crop_within only applies to a --ply build")

    slug = slug.strip("/").lower()
    cdn = env.get("BUNNY_CDN_URL", "").rstrip("/")
    zone = env.get("BUNNY_STORAGE_ZONE", "")
    pw = env.get("BUNNY_STORAGE_PASSWORD", "")
    api = env.get("BUNNY_ACCOUNT_API_KEY", "")
    is_bunny = deploy_target == "bunny"
    if is_bunny and (not zone or not pw):
        return StepResult(step=STEP_PUBLISH, success=False,
                          error="BUNNY_STORAGE_ZONE / BUNNY_STORAGE_PASSWORD missing")
    if deploy_target == "folder" and deploy_dest is None:
        return StepResult(step=STEP_PUBLISH, success=False,
                          error="deploy_target='folder' requires deploy_dest=")

    # Build the deploy target. For the DEFAULT bunny path we inject this
    # module's own (patchable) deploy-fn references so the adapter delegates
    # to *exactly* the functions the old direct call used — preserving the
    # behaviour-preservation oracle byte-for-byte. Adding sftp/s3/rsync
    # later is a one-line registry entry (see deploy_targets/registry.py).
    try:
        if is_bunny:
            target = get_deploy_target(
                "bunny", env=env,
                deploy_fn=deploy_to_bunny,
                ensure_fresh_fn=ensure_edge_rules,
                invalidate_fn=purge_bunny_cache,
            )
        else:
            target = get_deploy_target(deploy_target, destination=deploy_dest)
    except KeyError as e:
        return StepResult(step=STEP_PUBLISH, success=False, error=str(e))

    # 1. Re-assert the edge rule (best-effort; never blocks the deploy).
    #    For bunny this is the no-edge-cache Edge Rule; for folder a no-op.
    yield _ev(0.02, "Ensuring deploy-target cache freshness")
    try:
        target.ensure_fresh(quiet=True)
    except Exception as e:  # noqa: BLE001 - never fatal
        yield _ev(0.03, f"cache-freshness ensure skipped ({e!r})")

    # 2. Obtain the chunked set: build from --ply, or stage a prebuilt --rad-dir.
    if rad_dir is not None:
        rd = Path(rad_dir)
        mans = sorted(rd.glob("*-lod.rad"))
        if len(mans) != 1:
            return StepResult(step=STEP_PUBLISH, success=False,
                              error=f"expected one *-lod.rad in {rd}, found {len(mans)}")
        manifest = mans[0]
        radc = sorted(rd.glob("*.radc"))
        if not radc:
            return StepResult(step=STEP_PUBLISH, success=False,
                              error=f"no .radc in {rd}")
        h = hashlib.sha256()
        with open(manifest, "rb") as fh:
            for c in iter(lambda: fh.read(1 << 20), b""):
                h.update(c)
        bkey = "b" + h.hexdigest()[:16]
        yield _ev(0.40, f"Prebuilt set: {manifest.name} + {len(radc)} .radc")
    else:
        ply = Path(ply)
        if not ply.is_file():
            return StepResult(step=STEP_PUBLISH, success=False,
                              error=f"source PLY not found: {ply}")
        xf = [f"--within-dist={crop_within}"] if crop_within else None
        yield _ev(0.05, f"build-lod --quality --rad-chunked --cluster-sh"
                        f"{' ' + xf[0] if xf else ''}")
        _last: list[str] = []

        def _build_cb(line: str) -> None:
            _last.append(line)
            if on_build_line is not None:   # live-forward to the caller's sink
                on_build_line(line)

        try:
            manifest = build(
                ply, quality=True, chunked=True, cluster_sh=True,
                extra_flags=xf, on_progress=_build_cb,
                spark_repo=spark_repo,
            )
        except BuildLodError as e:
            return StepResult(step=STEP_PUBLISH, success=False,
                              error=f"build-lod failed: {e}")
        rd = manifest.parent
        radc = sorted(rd.glob("*.radc"))
        if not radc:
            return StepResult(step=STEP_PUBLISH, success=False,
                              error=f"no .radc next to {manifest}")
        # bkey must be unique per (PLY + build flags), not just PLY content,
        # so adding e.g. --within-dist maps to a fresh subfolder instead of
        # overwriting in place. The cache dir name already encodes
        # <sha256[:16]>-<rev>-<flags>, so hash the whole name.
        bkey = "b" + hashlib.sha256(rd.name.encode()).hexdigest()[:16]
        yield _ev(0.42, f"Built {len(radc)} .radc"
                        + (f" - {_last[-1]}" if _last else ""))

    total_mb = (manifest.stat().st_size
                + sum(p.stat().st_size for p in radc)) / 1e6

    # 3. Stage: stable root files + immutable b<key>/ subfolder.
    stage = Path(tempfile.mkdtemp(prefix=f"splatpipe-publish-{slug}-"))
    try:
        (stage / bkey).mkdir(parents=True)
        shutil.copy2(manifest, stage / bkey / "scene.rad")
        for rc in radc:                       # original basenames (manifest refs them)
            shutil.copy2(rc, stage / bkey / rc.name)

        # 4. viewer-config.json - inherit (project scene_config or live slug),
        #    apply per-scene overrides, then the primary_asset pointer.
        if base_config is not None:
            cfg = copy.deepcopy(base_config)
        elif live_slug:
            cfg = _fetch_live_config(cdn, live_slug)
            yield _ev(0.46, f"Inherited config from {live_slug} "
                            f"(start_view={bool(cfg.get('start_view'))})")
        else:
            cfg = {}
        if clip_xy is not None:
            cfg.setdefault("spark_render", {})["clip_xy"] = clip_xy
        if move_speed_mult is not None:
            cfg.setdefault("spark_render", {})["move_speed_mult"] = move_speed_mult
        if splat_budget is not None:
            cfg["splat_budget"] = splat_budget
        cfg["primary_asset"] = f"{bkey}/scene.rad"
        (stage / "viewer-config.json").write_text(
            json.dumps(cfg, indent=2), encoding="utf-8")

        # 5. index.html - BUILD-AGNOSTIC (no b<key> baked in).
        share_url = f"{cdn}/{slug}/index.html"
        share_image = f"{cdn}/{slug}/preview.jpg"
        eff_desc = desc or NEUTRAL_DESC
        html = html_for(scene_name, primary_asset="scene.rad", paged=True,
                        share_url=share_url, share_image=share_image,
                        description=eff_desc)
        (stage / "index.html").write_text(html, encoding="utf-8")

        checks = {
            "fork_rcf2": "_sparkfork-rcf2" in html,
            "cfg_has_pointer": cfg.get("primary_asset") == f"{bkey}/scene.rad",
            "html_reads_cfg_pointer": "typeof cfg.primary_asset === 'string'" in html,
            "html_build_agnostic": bkey not in html,
            "share_card_abs": (f'content="{share_image}"' in html
                               and f'content="{share_url}"' in html),
            "no_brace_mangle": chr(8) not in html,
            "desc_not_fabricated": (not any(w in html for w in _FABRICATED_MARKERS)
                                    or desc is not None),
        }
        if not all(checks.values()):
            bad = [k for k, v in checks.items() if not v]
            return StepResult(step=STEP_PUBLISH, success=False,
                              error=f"publish self-checks failed: {bad}",
                              summary={"checks": checks})
        yield _ev(0.50, f"Staged {bkey}/ ({len(radc)} chunks, {total_mb:.0f} MB), "
                        f"checks OK", detail=json.dumps(checks))

        # 6. Deploy via the target. For bunny this is the SAME
        #    deploy_to_bunny(slug, stage, env, workers=12, purge=False) call
        #    (the async-delete race fix) — the adapter is a verbatim
        #    delegation to the injected reference; nothing changes.
        yield _ev(0.52, f"Uploading {slug}/ via {target.name} (purge=False)")
        gen = target.deploy_staged(slug, stage, workers=12)
        dresult: StepResult | None = None
        try:
            while True:
                ev = next(gen)
                # map the upload generator's 0..1 into our 0.52..0.95 band
                yield _ev(0.52 + 0.43 * ev.progress, ev.message, ev.detail or "")
        except StopIteration as stop:
            dresult = stop.value
        summ = dict(dresult.summary) if dresult and dresult.summary else {}
        if not dresult or not dresult.success or summ.get("failed_files"):
            return StepResult(step=STEP_PUBLISH, success=False,
                              error=(dresult.error if dresult else "deploy: no result")
                                    or f"deploy failed: {summ.get('failed_files')}",
                              summary=summ)

        # 7. Invalidate ONLY the two stable text files (chunks are
        #    immutable). For bunny this delegates to purge_bunny_cache,
        #    gated on the account API key EXACTLY as before (the adapter
        #    also guards internally; folder = no-op).
        invalidate_urls = [share_url, f"{cdn}/{slug}/viewer-config.json"]
        if not is_bunny or api:
            yield _ev(0.96, "Invalidating index.html + viewer-config.json")
        target.invalidate(invalidate_urls)

        # 8. Optional stale-subfolder prune (Bunny Storage only).
        kept_note = ""
        subs: list[str] = []
        if is_bunny:
            subs = [d for d in list_bunny_subfolders(zone, pw, slug)
                    if d.startswith("b") and d != bkey]
            if prune_stale:
                for d in subs:
                    n = _purge_bunny_folder(zone, pw, f"{slug}/{d}")
                    yield _ev(0.98, f"Pruned stale subfolder {d}/ ({n} files)")
            elif subs:
                kept_note = (f"kept {len(subs)} prior subfolder(s) {subs} "
                             f"(no prune_stale - protects 30-day-cached old index)")
                yield _ev(0.98, kept_note)

        summary = {
            "slug": slug,
            "viewer_url": share_url,
            "embed_url": f"{share_url}?embed=1",
            "bkey": bkey,
            "uploaded": summ.get("uploaded"),
            "total_mb": round(total_mb, 1),
            "chunks": len(radc),
            "kept_subfolders": subs if not prune_stale else [],
            "checks": checks,
        }
        yield _ev(1.0, f"Published {slug} -> {share_url}")
        return StepResult(step=STEP_PUBLISH, success=True, summary=summary)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
