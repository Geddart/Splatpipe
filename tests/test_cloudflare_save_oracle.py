"""Cross-language SEMANTIC-parity oracle for ``infra/cloudflare/worker.js``.

The deployed Spark viewers are static files with no backend. A viewer's
keyframe editor only *emits* an untrusted patch; the trusted side fetches
the scene's current ``viewer-config.json``, merges the patch onto it via
the shared :func:`splatpipe.core.config_merge.merge_camera_scope` core, and
writes it back. ``worker.js`` is the ``save_backend="cloudflare"`` server
side — the OPT-IN serverless exemplar (``cli`` is the default) that
performs that merge+write in a Cloudflare Worker instead of via the ``cli``
relay or the ``php`` adapter.

This module is the cross-language twin's lock — the *exact* mirror of
``tests/test_php_save_oracle.py``, retargeted at the JS merge: the
Worker's ``mergeCameraScope`` MUST be semantically identical to the Python
``merge_camera_scope``. For the SAME representative ``(existing, patch)``
fixture set the PHP oracle uses, we drive the *real* JS merge through
``node`` (subprocess — the project hard rule: run the tool, capture real
output, then assert) and assert:

  * ``json.loads(<node merge output>) == merge_camera_scope(existing, patch)``
    by deep structural equality (byte-identical serialization is NOT the
    contract — ``JSON.stringify`` != Python ``json.dumps``; the viewer
    parses JSON order-independently — DATA equality is the contract), AND
  * the JS ``ignored`` list ==
    ``sorted(set(patch) - ALLOWED_PATCH_KEYS - {"primary_asset"} - {"slug"})``
    (the Task-4 carry-forward: non-allow-listed keys are silently dropped
    by the merge core and surfaced informationally, never as an error;
    ``primary_asset`` is a locked-invariant force-keep and the ``slug`` is
    the transport field — neither is an author diagnostic).

The locked, security-critical invariant exercised by the malicious fixture:
a ``patch`` carrying ``primary_asset`` (the Bunny pointer) can NEVER move
it — that is the "Speicher-blank" production-failure class.

Gated with ``skipif(shutil.which("node") is None)`` for portability, but
``node`` IS present on the dev box (and required) so this really runs the
JS merge and asserts data parity against ``merge_camera_scope``.  This
oracle deliberately exercises only the pure MERGE (the cross-language
contract that must be executably locked, exactly like the PHP twin); the
Worker's auth / CORS / Bunny GET-PUT-purge relay is statically verified
against the §H spec + ``save-camera.php`` and documented in
``infra/cloudflare/README.md`` (§H2-DECISION downscoped ``cloudflare`` to
"one exemplar, doc'd" — no Miniflare runtime).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from splatpipe.core.config_merge import ALLOWED_PATCH_KEYS, merge_camera_scope

NODE = shutil.which("node")
WORKER_JS = Path(__file__).parent.parent / "infra" / "cloudflare" / "worker.js"

pytestmark = pytest.mark.skipif(
    NODE is None,
    reason=(
        "node not on PATH — oracle needs `node` present to drive the real JS "
        "merge (the dev box has Node v24; CI/dev without Node skips this). "
        "Verify on a Node host: "
        "`node --check infra/cloudflare/worker.js && "
        "pytest tests/test_cloudflare_save_oracle.py`."
    ),
)


# ---------------------------------------------------------------------------
# representative (existing, patch) fixtures — the SAME set as the PHP oracle
# (tests/test_php_save_oracle.py). Keeping them identical is deliberate: the
# php and cloudflare adapters are cross-language twins of the SAME Python
# merge core, so the contract they must satisfy is identical.
# ---------------------------------------------------------------------------
FIXTURES: dict[str, tuple[dict, dict]] = {
    # 1. a normal camera-paths patch onto a populated config
    "normal_camera_paths": (
        {
            "primary_asset": "bKEEP/scene.rad",
            "start_view": {"pos": [1, 2, 3], "fov": 60},
            "spark_render": {"clip_xy": 1.4},
            "unrelated_legacy_key": {"nested": [1, 2, 3]},
        },
        {
            "camera_paths": [
                {"id": "p1", "loop": True, "keyframes": [{"t": 0.0}, {"t": 1.0}]}
            ],
            "default_path_id": "p1",
        },
    ),
    # 2. MALICIOUS: patch carries primary_asset + an unknown key. The
    #    pointer must NOT move (Speicher-blank invariant); the unknown key
    #    must be dropped and reported in `ignored`.
    "malicious_primary_asset_and_unknown": (
        {
            "primary_asset": "bKEEP/scene.rad",
            "start_view": {"pos": [0, 0, 0]},
            "keep_me": "untouched",
        },
        {
            "primary_asset": "bEVIL/attacker.rad",
            "camera_paths": [{"id": "p1"}],
            "splat_budget": 999_999_999,
            "index.html": "<script>evil</script>",
            "totally_unknown": True,
        },
    ),
    # 3. existing WITHOUT primary_asset — none must be synthesized, and a
    #    patched one still cannot be introduced.
    "existing_without_primary_asset": (
        {"start_view": {"pos": [9]}},
        {"camera_paths": [{"id": "p"}], "primary_asset": "bEVIL/x.rad"},
    ),
    # 4. empty patch — result is the equivalent of existing
    "empty_patch": (
        {
            "primary_asset": "bK/s.rad",
            "start_view": {"pos": [1]},
            "annotations": [{"id": "a1"}],
        },
        {},
    ),
    # 5. all nine allow-listed keys at once (whole-key replace each)
    "all_nine_keys": (
        {"primary_asset": "bK/s.rad", "preexisting": "x"},
        {
            "start_view": {"pos": [0]},
            "camera_paths": [{"id": "p"}],
            "clips": [{"id": "c"}],
            "cameras": [{"id": "cam"}],
            "default_path_id": "p",
            "intro": {"type": "fade", "ms": 900},
            "titles3d": [{"text": "T", "pos": [0, 0, 0]}],
            "spark_render": {"clip_xy": 3.0},
            "annotations": [{"id": "an"}],
        },
    ),
    # 6. nested dict in an allowed key — confirm WHOLE-key replace, NOT a
    #    deep-merge (the parity-critical config_merge semantic).
    "nested_dict_whole_replace": (
        {
            "primary_asset": "bK/s.rad",
            "spark_render": {"clip_xy": 1.4, "stale_subkey": "OLD"},
        },
        {"spark_render": {"clip_xy": 3.0}},  # no stale_subkey -> must vanish
    ),
}


# A tiny Node harness that imports the Worker's EXPORTED pure merge and
# runs it on (existing, patch) read from argv, printing
# {"result": <merged>, "ignored": [...]} as JSON to stdout. It deliberately
# never touches the Workers `fetch` runtime — `worker.js` is structured so
# `mergeCameraScope` / `computeIgnored` / `ALLOWED_PATCH_KEYS` are
# standalone named ESM exports (clean separation; also better code).
_HARNESS = textwrap.dedent(
    """
    import { mergeCameraScope, computeIgnored, ALLOWED_PATCH_KEYS }
      from {worker_url};

    const existing = JSON.parse(process.argv[2]);
    const patch    = JSON.parse(process.argv[3]);

    const result  = mergeCameraScope(existing, patch);
    const ignored = computeIgnored(patch);

    // Defensive: the harness must observe the SAME 9-key allow-list the
    // Python source of truth pins (drift here would silently pass the
    // oracle); surface it so the test can assert it too.
    process.stdout.write(JSON.stringify({
      result,
      ignored,
      allowed: Array.from(ALLOWED_PATCH_KEYS).sort(),
    }));
    """
).strip()


def _run_node_merge(existing: dict, patch: dict) -> dict:
    """Drive the REAL JS merge via ``node`` and return the parsed result.

    Uses ``--input-type=module`` so the harness can ``import`` the Worker's
    ESM exports without writing a temp file; the worker URL is passed as a
    proper ``file://`` URL so the import resolves regardless of cwd.
    """
    worker_url = WORKER_JS.resolve().as_uri()
    src = _HARNESS.replace("{worker_url}", json.dumps(worker_url))
    proc = subprocess.run(
        [NODE, "--input-type=module", "-", json.dumps(existing), json.dumps(patch)],
        input=src,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"node merge harness failed (rc={proc.returncode})\n"
        f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# THE ORACLE: JS merge == Python merge_camera_scope, for every fixture
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_id", list(FIXTURES))
def test_js_merge_matches_python_oracle(fixture_id):
    existing, patch = FIXTURES[fixture_id]

    out = _run_node_merge(existing, patch)

    # 0. the JS harness must see the SAME 9-key allow-list the Python source
    #    of truth pins (a silent drift would otherwise pass the oracle).
    assert out["allowed"] == sorted(ALLOWED_PATCH_KEYS), (
        f"{fixture_id}: JS ALLOWED_PATCH_KEYS drifted from the Python "
        f"source of truth\n  python={sorted(ALLOWED_PATCH_KEYS)}\n"
        f"  js    ={out['allowed']}"
    )

    # 1. DATA equality (NOT byte equality) vs the Python source of truth
    expected = merge_camera_scope(existing, patch)
    written = out["result"]
    assert written == expected, (
        f"{fixture_id}: JS merge != merge_camera_scope\n"
        f"  expected={expected}\n  written ={written}"
    )

    # 2. the `ignored` list contract (Task-4 carry-forward) — non-allow-
    #    listed patch keys, minus the force-kept primary_asset and minus the
    #    transport-only slug.
    expected_ignored = sorted(
        set(patch) - set(ALLOWED_PATCH_KEYS) - {"primary_asset"} - {"slug"}
    )
    assert sorted(out["ignored"]) == expected_ignored, (
        f"{fixture_id}: ignored mismatch\n"
        f"  expected={expected_ignored}\n  got     ={sorted(out['ignored'])}"
    )

    # 3. the locked invariant, asserted directly (esp. the malicious case)
    if "primary_asset" in existing:
        assert written["primary_asset"] == existing["primary_asset"]
    else:
        assert "primary_asset" not in written


def test_malicious_primary_asset_never_moves():
    """Focused assertion of the Speicher-blank invariant against the real
    JS merge: a patched primary_asset is dropped *and* the pointer stays."""
    existing = {"primary_asset": "bGOOD/scene.rad", "keep": 1}
    patch = {
        "slug": "oracle-scene",
        "primary_asset": "bEVIL/x.rad",
        "camera_paths": [{"id": "p"}],
    }
    out = _run_node_merge(existing, patch)
    written = out["result"]
    assert written["primary_asset"] == "bGOOD/scene.rad"  # NEVER the patch's
    assert written["camera_paths"] == [{"id": "p"}]
    assert written["keep"] == 1
    # slug is transport-only and primary_asset is the locked force-keep —
    # neither is surfaced as an author diagnostic.
    assert sorted(out["ignored"]) == []


def test_worker_js_syntax_is_valid():
    """`node --check` the Worker — a parse error here would make the oracle
    above fail confusingly; assert the artifact is at least syntactically
    valid ES-module source (the project hard rule: run the tool)."""
    proc = subprocess.run(
        [NODE, "--check", str(WORKER_JS)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"`node --check {WORKER_JS}` failed:\n"
        f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
