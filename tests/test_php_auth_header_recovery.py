"""Source-level lock for the Authorization-header recovery chain (#150).

Root cause of the "valid bearer -> 401" production failure on Strato: the
host's PHP SAPI is ``cgi-fcgi``, which (a) drops ``HTTP_AUTHORIZATION`` and
(b) has NO ``apache_request_headers()`` -- so BOTH legacy recovery paths in
``save-camera.php`` / ``upload-asset.php`` were no-ops. The Authorization
header reaches PHP ONLY via an Apache rewrite/SetEnvIf, and a per-directory
(``.htaccess``) ``RewriteRule ... [E=HTTP_AUTHORIZATION:...]`` is exposed by
Apache to PHP as ``$_SERVER['REDIRECT_HTTP_AUTHORIZATION']`` (the REDIRECT_
prefix is added for env vars set by a per-dir rewrite). The fix reads that
key too.

This module is PHP-INDEPENDENT (no ``php`` binary, no network) so it runs in
every environment, including the local Windows box and CI without PHP. The
behavioural proof (a real 200 round-trip + bad-token 401 against the live
geddart.de endpoint) was done out-of-band during the #150 fix; this static
lock prevents a future edit from silently dropping the ``REDIRECT_`` fallback
that makes Strato-class hosts work.

The PHP-driven oracles (``test_php_save_oracle`` / ``test_upload_asset_oracle``)
exercise the merge + every other gate against ``php -S`` -- but ``php -S``
runs the ``cli-server`` SAPI which DOES populate ``HTTP_AUTHORIZATION``
directly, so it can never reach the ``REDIRECT_`` branch. Hence this
complementary source lock.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PHP_ROOT = Path(__file__).parent.parent / "infra" / "php"
SAVE_PHP = PHP_ROOT / "save-camera.php"
UPLOAD_PHP = PHP_ROOT / "upload-asset.php"
HTACCESS = PHP_ROOT / ".htaccess"


@pytest.mark.parametrize("php_file", [SAVE_PHP, UPLOAD_PHP], ids=["save", "upload"])
def test_auth_block_reads_all_three_sources(php_file: Path):
    """Both endpoints must recover the Authorization header from, in order:
    HTTP_AUTHORIZATION, then REDIRECT_HTTP_AUTHORIZATION, then
    apache_request_headers(). The REDIRECT_ form is the one Strato actually
    delivers; dropping it reintroduces the #150 401 regression."""
    src = php_file.read_text(encoding="utf-8")

    assert "$_SERVER['HTTP_AUTHORIZATION']" in src, (
        f"{php_file.name}: must still read the direct HTTP_AUTHORIZATION key"
    )
    assert "$_SERVER['REDIRECT_HTTP_AUTHORIZATION']" in src, (
        f"{php_file.name}: must read REDIRECT_HTTP_AUTHORIZATION -- the key a "
        "per-dir .htaccess rewrite yields on Strato/cgi-fcgi (#150 root cause)"
    )
    assert "apache_request_headers()" in src, (
        f"{php_file.name}: must keep the apache_request_headers() last-resort "
        "fallback for SAPIs that expose neither $_SERVER form"
    )


@pytest.mark.parametrize("php_file", [SAVE_PHP, UPLOAD_PHP], ids=["save", "upload"])
def test_redirect_fallback_ordered_before_apache_headers(php_file: Path):
    """The cheap ``$_SERVER`` reads (incl. REDIRECT_) must come before the
    ``apache_request_headers()`` scan -- and the REDIRECT_ read must be a
    null-coalescing fallback of the direct read, not a separate later branch
    that an empty-string direct value would shadow."""
    src = php_file.read_text(encoding="utf-8")

    # The exact coalescing shape the fix uses:
    #   $auth = $_SERVER['HTTP_AUTHORIZATION']
    #       ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION']
    #       ?? '';
    coalesce = re.search(
        r"\$auth\s*=\s*\$_SERVER\['HTTP_AUTHORIZATION'\]\s*"
        r"\?\?\s*\$_SERVER\['REDIRECT_HTTP_AUTHORIZATION'\]\s*"
        r"\?\?\s*''\s*;",
        src,
    )
    assert coalesce is not None, (
        f"{php_file.name}: expected the "
        "`HTTP_AUTHORIZATION ?? REDIRECT_HTTP_AUTHORIZATION ?? ''` coalescing "
        "assignment to $auth"
    )

    # The $auth coalescing assignment (the REDIRECT_ read) must come before the
    # apache_request_headers() *call*. Anchor on the coalesce match position,
    # not a bare .index() -- the chain is also described in the comment above
    # the block, so a literal .index() would hit the comment occurrence first.
    # The function-existence guard (`function_exists('apache_request_headers')`)
    # also precedes the call, so match the call form `apache_request_headers()`
    # AFTER the coalesce assignment.
    redirect_pos = coalesce.start()
    apache_call = re.search(
        r"foreach\s*\(\s*apache_request_headers\(\)", src
    )
    assert apache_call is not None, (
        f"{php_file.name}: expected a `foreach (apache_request_headers() ...)` "
        "fallback scan"
    )
    assert redirect_pos < apache_call.start(), (
        f"{php_file.name}: the $auth coalescing read (incl. REDIRECT_) must "
        "precede the apache_request_headers() fallback scan"
    )


def test_htaccess_forwards_authorization_to_php():
    """The reference adapter .htaccess must (a) re-inject the Authorization
    header via the rewrite engine and (b) belt-and-braces it via SetEnvIf so
    the un-prefixed HTTP_AUTHORIZATION form is also available."""
    src = HTACCESS.read_text(encoding="utf-8")
    assert "E=HTTP_AUTHORIZATION:%1" in src, (
        ".htaccess must set HTTP_AUTHORIZATION from the request header via "
        "RewriteRule [E=...] (the per-dir form PHP reads as REDIRECT_*)"
    )
    assert re.search(
        r"SetEnvIf\s+Authorization\s+\"\(\.\*\)\"\s+HTTP_AUTHORIZATION=\$1",
        src,
    ), (
        ".htaccess must ALSO expose the Authorization header via SetEnvIf "
        "(un-prefixed HTTP_AUTHORIZATION) for hosts that read that form"
    )
    # The rewrite must be scoped to exactly the two save endpoints.
    assert re.search(r"\^\(save-camera\|upload-asset\)\\?\.php\$", src), (
        ".htaccess auth-forward RewriteRule must be scoped to "
        "save-camera.php / upload-asset.php only"
    )


def test_htaccess_denies_dotfile_secrets():
    """The adapter .htaccess must deny dotfiles (covers .bunny_env +
    .author-token + scratch files) so a docroot-root secret is never
    web-readable -- the pre-existing leak surfaced during the #150 fix."""
    src = HTACCESS.read_text(encoding="utf-8")
    assert "Require all denied" in src
    assert re.search(r'FilesMatch\s+"\^\\\."', src), (
        ".htaccess must deny all dotfiles (^\\.) so .bunny_env / .author-token "
        "are never served"
    )
