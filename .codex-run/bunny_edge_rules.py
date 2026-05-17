"""Ensure the Bunny pull-zone Edge Rule that makes the small viewer text
files always-fresh at the edge.

ROOT CAUSE (hit 3x — see memory project_bunny_viewer_config_cache /
project_bunny_rad_edgecache_corruption): pull zone `splatpipe-cdn`
(id 5316940) has CacheControlMaxAgeOverride=2592000 — Bunny force-caches
EVERY object for 30 days, overriding origin Cache-Control, and
IgnoreQueryStrings=True so `?cb=` busters are ignored. A redeployed
permanent-slug `index.html` / `viewer-config.json` therefore keeps
serving the 30-day-stale copy on most edges (purge is unreliable; the
client `cache:'no-store'` is overridden by the pull zone). The whole
permanent-slug design needs the *small text* files to be fresh while the
big immutable b<key>/*.rad|*.radc stay 30-day cached.

FIX (surgical, durable, reversible): one Edge Rule —
  ActionType 3 (OverrideCacheTime)        ActionParameter1 "0"  -> no edge cache
plus a sibling rule
  ActionType 15 (OverrideBrowserCacheTime) ActionParameter1 "0" -> browser revalidates
triggered by request URL matching `*/index.html` OR `*/viewer-config.json`.
Only those two filenames are affected; .rad/.radc are untouched (still
fast 30-day cached, and they live in immutable per-build subfolders so
caching them is correct).

Idempotent: matched by Description; updates in place via
/pullzone/{id}/edgerules/addOrUpdate (Guid round-trips).

Usage:  python .codex-run/bunny_edge_rules.py [--verify-only]
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "src")
from splatpipe.steps.deploy import load_bunny_env  # noqa: E402

PULLZONE_HOST = "splatpipe-cdn"          # the CDN host the slugs are served from
DESC = "splatpipe: no-edge-cache for permanent-slug index/config (redeploy-safe)"
# request-URL globs — the host is fixed; only these two basenames bypass cache
URL_PATTERNS = [
    "https://splatpipe-cdn.b-cdn.net/*/index.html",
    "https://splatpipe-cdn.b-cdn.net/*/viewer-config.json",
    "https://splatpipe-cdn.b-cdn.net/index.html",
    "https://splatpipe-cdn.b-cdn.net/viewer-config.json",
]


def _api(api_key: str, method: str, url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("AccessKey", api_key)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw.strip() else {}


def _find_zone(api_key: str) -> dict:
    zs = _api(api_key, "GET", "https://api.bunny.net/pullzone?page=1&perPage=100")
    items = zs.get("Items", zs if isinstance(zs, list) else [])
    for z in items:
        if z.get("Name") == PULLZONE_HOST:
            return z
    raise SystemExit(f"pull zone {PULLZONE_HOST!r} not found")


def _trigger():
    # Type 0 = Url, PatternMatchingType 0 = MatchAny
    return {"Type": 0, "PatternMatchingType": 0,
            "PatternMatches": URL_PATTERNS, "Parameter1": ""}


def _desired_rules(existing: list[dict]) -> list[dict]:
    """Two rules (edge cache 0, browser cache 0). Reuse Guids if present so
    addOrUpdate edits in place instead of duplicating."""
    by_desc = {r.get("Description"): r for r in existing}
    out = []
    for action, tag in ((3, "edge"), (15, "browser")):
        d = f"{DESC} [{tag}]"
        prev = by_desc.get(d)
        out.append({
            "Guid": prev.get("Guid") if prev else None,
            "ActionType": action,
            "ActionParameter1": "0",
            "ActionParameter2": "",
            "Enabled": True,
            "Description": d,
            "TriggerMatchingType": 0,        # 0 = MatchAny across triggers
            "Triggers": [_trigger()],
        })
    return out


def apply(api_key: str, verify_only: bool = False, quiet: bool = False) -> bool:
    """Ensure (or, with verify_only, just check) the no-edge-cache Edge
    Rules. Reusable from deploy_scene_cs.py so every deploy re-asserts
    them idempotently. Returns True on success / present-and-enabled."""
    def _log(*a):
        if not quiet:
            print(*a, flush=True)

    z = _find_zone(api_key)
    zid = z["Id"]
    existing = z.get("EdgeRules", []) or []
    ours = [r for r in existing if str(r.get("Description", "")).startswith(DESC)]
    _log(f"pull zone {PULLZONE_HOST} id={zid} | "
         f"CacheControlMaxAgeOverride={z.get('CacheControlMaxAgeOverride')} | "
         f"existing edge rules={len(existing)} (ours={len(ours)})")

    if verify_only:
        ok = len(ours) >= 2 and all(r.get("Enabled") for r in ours)
        _log("VERIFY:", "PRESENT+ENABLED" if ok else "MISSING/DISABLED")
        return ok

    for rule in _desired_rules(existing):
        _api(api_key, "POST",
             f"https://api.bunny.net/pullzone/{zid}/edgerules/addOrUpdate", rule)
        _log(f"  applied: [{rule['Description']}] "
             f"ActionType={rule['ActionType']} -> cache 0")
    z2 = _find_zone(api_key)
    now = [r for r in (z2.get("EdgeRules") or [])
           if str(r.get("Description", "")).startswith(DESC)]
    _log(f"post-apply: {len(now)} rule(s) present")
    if len(now) < 2:
        raise SystemExit(f"expected >=2 edge rules, got {len(now)}")
    _log("OK - */index.html and */viewer-config.json bypass edge+browser "
         "cache; .rad/.radc still 30-day cached.")
    return True


def main() -> int:
    verify_only = "--verify-only" in sys.argv
    env = load_bunny_env(Path(".env"))
    api_key = env.get("BUNNY_ACCOUNT_API_KEY", "")
    assert api_key, "BUNNY_ACCOUNT_API_KEY missing"
    ok = apply(api_key, verify_only=verify_only)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
