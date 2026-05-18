"""Cross-language SEMANTIC-parity oracle for ``infra/php/save-camera.php``.

The deployed Spark viewers are static files with no backend. A viewer's
keyframe editor only *emits* an untrusted patch; the trusted side fetches
the scene's current ``viewer-config.json``, merges the patch onto it via
the shared :func:`splatpipe.core.config_merge.merge_camera_scope` core, and
writes it back. ``save-camera.php`` is the ``save_backend="php"`` server
side — a self-hostable PHP endpoint that performs that merge+write in the
browser→server path instead of via the ``cli`` relay.

This module is the cross-language twin's lock: ``save-camera.php``'s merge
MUST be semantically identical to the Python ``merge_camera_scope``. For a
set of representative ``(existing, patch)`` fixtures we drive the *real*
PHP endpoint (authenticated POST through ``php -S``) and assert:

  * ``json.loads(<written viewer-config.json>) == merge_camera_scope(existing, patch)``
    by deep structural equality (byte-identical serialization is NOT the
    contract — PHP ``json_encode`` != Python ``json.dumps``; the viewer
    parses JSON order-independently — DATA equality is the contract), AND
  * the PHP ``ignored`` list ==
    ``sorted(set(patch) - ALLOWED_PATCH_KEYS - {"primary_asset"})``
    (the Task-4 carry-forward: non-allow-listed keys are silently dropped
    by the merge core and surfaced informationally, never as an error).

The locked, security-critical invariant exercised by the malicious fixture:
a ``patch`` carrying ``primary_asset`` (the Bunny pointer) can NEVER move
it — that is the "Speicher-blank" production-failure class.

Gated with ``skipif(shutil.which("php") is None)`` so the suite stays green
where PHP is absent (the project's local box has no PHP; Strato PHP 8.4 is
the deployment target). When ``php`` IS present the endpoint is really run
(project hard rule: run the tool, capture real output, then assert).
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from splatpipe.core.config_merge import ALLOWED_PATCH_KEYS, merge_camera_scope

PHP = shutil.which("php")
PHP_ROOT = Path(__file__).parent.parent / "infra" / "php"
SAVE_PHP = PHP_ROOT / "save-camera.php"

pytestmark = pytest.mark.skipif(
    PHP is None,
    reason=(
        "php CLI not on PATH — oracle needs `php` present to drive the real "
        "endpoint (Strato PHP 8.4 is the deploy target; CI/dev without PHP skips "
        "this). Verify on a PHP host: "
        "`php -l infra/php/save-camera.php && pytest tests/test_php_save_oracle.py`."
    ),
)

# The bearer the test scene's .author-token holds. Constant-time-compared
# server side; never echoed.
TOKEN = "oracle-test-token-0123456789abcdef"
SLUG = "oracle-scene"


# ---------------------------------------------------------------------------
# representative (existing, patch) fixtures — id -> (existing, patch)
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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def php_server(tmp_path_factory):
    """A ``php -S`` instance serving a tmp docroot that has both the real
    ``save-camera.php`` and a ``scenes/<slug>/`` tree with a known token.

    Yields ``(base_url, scene_dir)``. The scene_dir's viewer-config.json is
    reset per-test by the fixtures below.
    """
    assert SAVE_PHP.exists(), f"missing artifact: {SAVE_PHP}"
    docroot = tmp_path_factory.mktemp("php_docroot")
    # the endpoint, copied into the docroot exactly as deployed
    shutil.copy(SAVE_PHP, docroot / "save-camera.php")
    scene_dir = docroot / "scenes" / SLUG
    scene_dir.mkdir(parents=True)
    (scene_dir / ".author-token").write_text(TOKEN, encoding="utf-8")

    port = _free_port()
    proc = subprocess.Popen(
        [PHP, "-d", "display_errors=0", "-S", f"127.0.0.1:{port}", "-t", str(docroot)],
        cwd=str(docroot),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    # wait for the dev server to accept connections
    deadline = time.time() + 15
    while time.time() < deadline:
        if proc.poll() is not None:
            out, err = proc.communicate()
            raise RuntimeError(
                f"php -S exited early: {err.decode(errors='replace')}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("php -S did not start within 15s")

    yield base, scene_dir

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _post(base: str, body: bytes, *, token: str | None = TOKEN,
          content_type: str = "application/json", method: str = "POST"):
    """Real authenticated request to the live endpoint. Returns
    ``(status, json_or_text)``."""
    req = urllib.request.Request(f"{base}/save-camera.php", data=body, method=method)
    req.add_header("Content-Type", content_type)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        raw, status = resp.read(), resp.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    text = raw.decode("utf-8", errors="replace")
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        return status, text


# ---------------------------------------------------------------------------
# THE ORACLE: PHP merge == Python merge_camera_scope, for every fixture
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_id", list(FIXTURES))
def test_php_merge_matches_python_oracle(php_server, fixture_id):
    base, scene_dir = php_server
    existing, patch = FIXTURES[fixture_id]

    # seed the scene's live config exactly as `existing`
    cfg_path = scene_dir / "viewer-config.json"
    cfg_path.write_text(json.dumps(existing), encoding="utf-8")
    for stale in ("viewer-config.json.tmp", "viewer-config.json.bak"):
        (scene_dir / stale).unlink(missing_ok=True)

    body = json.dumps({"slug": SLUG, **patch}).encode("utf-8")
    status, payload = _post(base, body)

    assert status == 200, f"{fixture_id}: HTTP {status} — {payload}"
    assert isinstance(payload, dict) and payload.get("ok") is True, payload

    # 1. DATA equality (NOT byte equality) vs the Python source of truth
    expected = merge_camera_scope(existing, patch)
    written = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert written == expected, (
        f"{fixture_id}: PHP merge != merge_camera_scope\n"
        f"  expected={expected}\n  written ={written}"
    )

    # 2. the `ignored` list contract (Task-4 carry-forward)
    expected_ignored = sorted(
        set(patch) - set(ALLOWED_PATCH_KEYS) - {"primary_asset"}
    )
    assert sorted(payload.get("ignored", [])) == expected_ignored, (
        f"{fixture_id}: ignored mismatch"
    )

    # 3. the locked invariant, asserted directly on the malicious case
    if "primary_asset" in existing:
        assert written["primary_asset"] == existing["primary_asset"]
    else:
        assert "primary_asset" not in written

    # 4. atomic-write hygiene: no torn .tmp left behind; .bak is the prior
    assert not (scene_dir / "viewer-config.json.tmp").exists()


def test_malicious_primary_asset_never_moves(php_server):
    """Focused assertion of the Speicher-blank invariant against the real
    endpoint: a patched primary_asset is dropped *and* the pointer stays."""
    base, scene_dir = php_server
    (scene_dir / "viewer-config.json").write_text(
        json.dumps({"primary_asset": "bGOOD/scene.rad", "keep": 1}),
        encoding="utf-8",
    )
    body = json.dumps(
        {"slug": SLUG, "primary_asset": "bEVIL/x.rad", "camera_paths": [{"id": "p"}]}
    ).encode("utf-8")
    status, payload = _post(base, body)
    assert status == 200 and payload["ok"] is True
    written = json.loads((scene_dir / "viewer-config.json").read_text("utf-8"))
    assert written["primary_asset"] == "bGOOD/scene.rad"  # NEVER the patch's
    assert written["camera_paths"] == [{"id": "p"}]
    assert written["keep"] == 1


# ---------------------------------------------------------------------------
# auth / method / size / slug guards (this is auth + FS-write code)
# ---------------------------------------------------------------------------
def test_options_preflight_is_204(php_server):
    base, _ = php_server
    status, _ = _post(base, b"", token=None, method="OPTIONS")
    assert status == 204


def test_bad_bearer_is_401_and_does_not_write(php_server):
    base, scene_dir = php_server
    (scene_dir / "viewer-config.json").write_text(
        json.dumps({"primary_asset": "bK/s.rad"}), encoding="utf-8"
    )
    body = json.dumps({"slug": SLUG, "camera_paths": [{"id": "p"}]}).encode()
    status, payload = _post(base, body, token="wrong-token")
    assert status == 401
    assert isinstance(payload, dict) and payload.get("ok") is False
    # untouched — the bad request never reached the merge/write
    assert json.loads((scene_dir / "viewer-config.json").read_text("utf-8")) == {
        "primary_asset": "bK/s.rad"
    }


def test_missing_bearer_is_401(php_server):
    base, _ = php_server
    body = json.dumps({"slug": SLUG, "camera_paths": []}).encode()
    status, payload = _post(base, body, token=None)
    assert status == 401
    assert isinstance(payload, dict) and payload.get("ok") is False


def test_get_is_405(php_server):
    base, _ = php_server
    status, _ = _post(base, b"", token=None, method="GET")
    assert status == 405


def test_non_json_content_type_is_415_or_405(php_server):
    base, _ = php_server
    status, _ = _post(
        base, b"slug=x", content_type="application/x-www-form-urlencoded"
    )
    assert status in (405, 415)


def test_over_256kb_body_is_413_and_directs_to_cli(php_server):
    base, _ = php_server
    big = "x" * (256 * 1024 + 64)
    body = json.dumps({"slug": SLUG, "intro": big}).encode()
    status, payload = _post(base, body)
    assert status == 413
    assert isinstance(payload, dict) and payload.get("ok") is False
    # 413 body must point the author at the over-cap CLI escape
    assert "set-camera-path" in json.dumps(payload)


@pytest.mark.parametrize(
    "bad_slug",
    ["../escape", "a/b", "a\\b", "UPPER", "with space", "dot.dot", "", "x" * 65],
)
def test_path_traversal_and_bad_slug_rejected_400(php_server, bad_slug):
    base, _ = php_server
    body = json.dumps({"slug": bad_slug, "camera_paths": []}).encode()
    status, payload = _post(base, body)
    assert status == 400, f"slug {bad_slug!r} should be rejected, got {status}"
    assert isinstance(payload, dict) and payload.get("ok") is False


@pytest.mark.parametrize("ok_slug", ["scene", "my-scene", "my_scene", "s1", "a" * 64])
def test_valid_slug_charset_accepted(php_server, tmp_path_factory, ok_slug):
    """The slug charset save-camera.php enforces must match the only
    Python-side slug-charset code that exists (the viewer slug sanitizer
    ``[^A-Za-z0-9_-]`` lower-cased -> ``[a-z0-9_-]``; §H2-DECISION's
    ``^[a-z0-9_-]{1,64}$``). A 401 (token store missing) — NOT a 400 —
    proves the slug itself passed validation."""
    base, _ = php_server
    body = json.dumps({"slug": ok_slug, "camera_paths": []}).encode()
    status, payload = _post(base, body, token="whatever")
    # valid slug, but no scenes/<ok_slug>/.author-token exists -> 401, not 400
    assert status == 401, f"slug {ok_slug!r} should pass charset, got {status}"
    assert isinstance(payload, dict) and payload.get("ok") is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
