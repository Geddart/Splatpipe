<?php
/**
 * save-camera.php — the server side of save_backend="php".
 *
 * GENERIC, self-hostable reference adapter. Drop this file plus the sibling
 * .htaccess next to a `scenes/<slug>/` tree on ANY plain-PHP host (shared
 * LAMP, VPS, Strato, ...). No framework, no Composer, no DB, no shelling
 * out. geddart.de / Strato is just ONE such host — nothing here is bound
 * to it; all paths come from the small CONFIG block below.
 *
 * What it does: a viewer's keyframe editor emits an UNTRUSTED camera-scope
 * patch and POSTs it here with a per-scene bearer token. This endpoint
 * authenticates, then fetch -> merge -> atomic-write the scene's
 * viewer-config.json.
 *
 * THE MERGE IS A CROSS-LANGUAGE TWIN of the Python source of truth
 * `src/splatpipe/core/config_merge.py::merge_camera_scope`. It MUST stay
 * semantically identical (locked by tests/test_php_save_oracle.py — same
 * (existing, patch) in => deep-equal viewer-config.json out). Byte-identical
 * serialization is NOT required (the viewer parses JSON order-independently);
 * DATA equality is the contract. If you change the 9-key allow-list or the
 * merge semantics, change config_merge.py FIRST (it is the source of truth)
 * and this file second, and re-run the oracle.
 *
 * Locked, security-critical invariant ("Speicher-blank" failure class): the
 * patch can NEVER move the `primary_asset` Bunny pointer. existing's
 * primary_asset is force-kept, applied LAST, independent of the patch.
 */

declare(strict_types=1);

/* ===== CONFIG (generic — edit these, nothing else host-specific) ========= *
 * SCENES_ROOT: absolute path to the directory that holds scenes/<slug>/.
 *   Default = `scenes/` next to this script (the documented relative
 *   layout). Override for any other host/layout.
 * TOKEN_BASENAME: per-scene token store filename inside scenes/<slug>/.
 *   May hold the raw token OR its lowercase hex sha256 (both accepted;
 *   denied to the web by the sibling .htaccess). Never logged/echoed.
 * MAX_BODY_BYTES: hard request-body cap. Over it -> 413 pointing the author
 *   at `splatpipe set-camera-path` (the always-available over-cap escape).
 *
 * BUNNY_ENV_FILE: optional .env-style file with Bunny CDN credentials. When
 *   present, save-camera.php ALSO pushes the merged viewer-config.json to
 *   Bunny Storage (additive — the local atomic write stays as the source of
 *   truth for the oracle's data-parity contract). This lets a deployed
 *   Spark viewer on Bunny CDN see the new state on the very next reload.
 *   When ABSENT, the local Strato write is the only side-effect (the
 *   original "scenes/ tree co-located with the viewer" model).
 *
 *   The file holds .env-style KEY=VALUE lines:
 *     BUNNY_STORAGE_ZONE=<zone>     (e.g. splatpipe-cdn-zone)
 *     BUNNY_STORAGE_PASSWORD=<key>  (Bunny Storage access key; READ+PUT)
 *     BUNNY_CDN_URL=<url>           (e.g. https://splatpipe-cdn.b-cdn.net)
 *     BUNNY_ACCOUNT_API_KEY=<key>   (optional, for edge purge)
 *
 *   Place it OUTSIDE the docroot OR behind the sibling .htaccess (the
 *   `^\.` deny rule already covers `.bunny_env`). The file MUST NOT be
 *   web-readable.
 */
const SCENES_ROOT     = __DIR__ . '/scenes';
const TOKEN_BASENAME  = '.author-token';
const MAX_BODY_BYTES  = 256 * 1024;            // 256 KB
const BUNNY_ENV_FILE  = __DIR__ . '/.bunny_env';

/**
 * The §H2 locked camera-scope allow-list — the ONLY keys an untrusted patch
 * may set. MIRRORS splatpipe.core.config_merge.ALLOWED_PATCH_KEYS verbatim
 * (that module is the single source of truth — keep these in lockstep;
 * the oracle fails if they drift). `primary_asset` is deliberately ABSENT:
 * it is force-kept from the existing config and can never be moved by a
 * patch.
 */
const ALLOWED_PATCH_KEYS = [
    'start_view',
    'camera_paths',
    'clips',
    'cameras',
    'default_path_id',
    'intro',
    'titles3d',
    'spark_render',
    'annotations',
    'panorama_backdrop',
    'postprocessing',
    'audio',
];

/* ===== tiny helpers ===================================================== */

function send_json(int $status, array $body): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    // Same-origin is the default deployment; harmless for an authed POST.
    header('Access-Control-Allow-Origin: *');
    header('Cache-Control: no-store');
    echo json_encode(
        $body,
        JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
    );
    exit;
}

function fail(int $status, string $error): never
{
    // The token is NEVER part of $error (we never put it there).
    send_json($status, ['ok' => false, 'error' => $error]);
}

/**
 * Read a .env-style file into an assoc array (KEY=VALUE per line).
 *
 * Returns `[]` if the file is absent / unreadable -- caller treats that as
 * "no Bunny sync configured" and falls back to local-only writes. Quotes
 * around values are stripped; blank lines + `#` comments skipped. Never
 * logged / never echoed (the only consumer is the Bunny helpers below).
 */
function load_env_file(string $path): array
{
    if (!is_file($path) || !is_readable($path)) {
        return [];
    }
    $env = [];
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) ?: [] as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#') {
            continue;
        }
        if (preg_match('/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/', $line, $m)) {
            $val = $m[2];
            if (strlen($val) >= 2 &&
                (($val[0] === '"' && $val[strlen($val) - 1] === '"') ||
                 ($val[0] === "'" && $val[strlen($val) - 1] === "'"))) {
                $val = substr($val, 1, -1);
            }
            $env[$m[1]] = $val;
        }
    }
    return $env;
}

/**
 * GET the live viewer-config.json from Bunny Storage. Returns null on any
 * error (network, 404, parse failure, missing creds) -- caller falls back
 * to the local file (or `{}`). Never throws.
 */
function bunny_fetch_config(array $env, string $slug): ?array
{
    $zone = $env['BUNNY_STORAGE_ZONE'] ?? '';
    $key  = $env['BUNNY_STORAGE_PASSWORD'] ?? '';
    if ($zone === '' || $key === '') {
        return null;
    }
    $url = 'https://storage.bunnycdn.com/' . rawurlencode($zone)
         . '/' . rawurlencode($slug) . '/viewer-config.json';
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER     => ['AccessKey: ' . $key, 'Accept: application/json'],
        CURLOPT_TIMEOUT        => 30,
        CURLOPT_FAILONERROR    => false,
    ]);
    $body = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if (!is_string($body) || $code < 200 || $code >= 300) {
        return null;
    }
    $decoded = json_decode($body, true);
    return is_array($decoded) ? $decoded : null;
}

/**
 * PUT the merged viewer-config.json to Bunny Storage. Returns true on
 * success, false on any error. A failure here does NOT abort the response:
 * the local atomic write already succeeded; a Bunny-push failure surfaces
 * via the success body's `bunny_push_ok: false` flag so the operator can
 * investigate without losing the edit.
 */
function bunny_put_config(array $env, string $slug, string $body): bool
{
    $zone = $env['BUNNY_STORAGE_ZONE'] ?? '';
    $key  = $env['BUNNY_STORAGE_PASSWORD'] ?? '';
    if ($zone === '' || $key === '') {
        return false;
    }
    $url = 'https://storage.bunnycdn.com/' . rawurlencode($zone)
         . '/' . rawurlencode($slug) . '/viewer-config.json';
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_CUSTOMREQUEST  => 'PUT',
        CURLOPT_POSTFIELDS     => $body,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER     => [
            'AccessKey: ' . $key,
            'Content-Type: application/json',
        ],
        CURLOPT_TIMEOUT        => 60,
        CURLOPT_FAILONERROR    => false,
    ]);
    curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    return $code >= 200 && $code < 300;
}

/**
 * Purge the Bunny edge cache for the slug's viewer-config.json so the
 * very next read sees the new state. Best-effort -- a purge failure does
 * NOT abort the response (the no-cache headers also keep the edge fresh
 * after a short TTL).
 */
function bunny_purge_config(array $env, string $slug): bool
{
    $api = $env['BUNNY_ACCOUNT_API_KEY'] ?? '';
    $cdn = rtrim($env['BUNNY_CDN_URL'] ?? '', '/');
    if ($api === '' || $cdn === '') {
        return false;
    }
    $purge_url = 'https://api.bunny.net/purge?url='
               . urlencode($cdn . '/' . $slug . '/viewer-config.json');
    $ch = curl_init($purge_url);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER     => ['AccessKey: ' . $api],
        CURLOPT_TIMEOUT        => 10,
        CURLOPT_FAILONERROR    => false,
    ]);
    curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    return $code >= 200 && $code < 300;
}

/* ===== 1. CORS preflight =============================================== */

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
if ($method === 'OPTIONS') {
    http_response_code(204);
    header('Access-Control-Allow-Origin: *');
    header('Access-Control-Allow-Methods: POST, OPTIONS');
    header('Access-Control-Allow-Headers: Authorization, Content-Type');
    header('Access-Control-Max-Age: 600');
    exit;
}

/* ===== 2. method + content-type + body-size cap ======================== */

if ($method !== 'POST') {
    fail(405, 'method not allowed; POST application/json only');
}

$ctype = $_SERVER['CONTENT_TYPE'] ?? '';
if (stripos($ctype, 'application/json') === false) {
    fail(415, 'Content-Type must be application/json');
}

// Cheap pre-check via the declared length, then a hard cap on what we read
// (a lying/absent Content-Length cannot smuggle a larger body past us).
$declared = (int) ($_SERVER['CONTENT_LENGTH'] ?? 0);
if ($declared > MAX_BODY_BYTES) {
    fail(413,
        'request body exceeds 256 KB; for very large imported camera paths '
        . 'run `splatpipe set-camera-path <token>` (the admin CLI handles '
        . 'over-cap saves) instead of the in-browser Save.');
}

$raw = file_get_contents('php://input', false, null, 0, MAX_BODY_BYTES + 1);
if ($raw === false) {
    fail(400, 'could not read request body');
}
if (strlen($raw) > MAX_BODY_BYTES) {
    fail(413,
        'request body exceeds 256 KB; for very large imported camera paths '
        . 'run `splatpipe set-camera-path <token>` (the admin CLI handles '
        . 'over-cap saves) instead of the in-browser Save.');
}

/* ===== 3. parse JSON + resolve slug =================================== */

$patch = json_decode($raw, true);
if (!is_array($patch) || array_is_list($patch)) {
    fail(400, 'request body must be a JSON object');
}

$slug = $patch['slug'] ?? '';
if (!is_string($slug)) {
    fail(400, 'slug must be a string');
}

/* ===== 4. slug charset — match the Python side EXACTLY ================ *
 * Python has no standalone slug-validation regex; the only slug-charset
 * code that actually exists Python-side is the viewer slug sanitizer in
 * `viewers/spark/template.py` (`replace(/[^A-Za-z0-9_-]+/g,'_')`), which —
 * after the codebase-wide `slug.strip("/").lower()` — admits exactly
 * `[a-z0-9_-]`. That is also §H2-DECISION's authoritative
 * `^[a-z0-9_-]{1,64}$` (the historical §H1 `^[a-z0-9-]{1,64}$` was
 * explicitly superseded). Validating against this set ALSO blocks path
 * traversal: no `.`, `/`, `\`, NUL, or `..`. All paths below are built
 * from the validated slug only.
 */
if (preg_match('/^[a-z0-9_-]{1,64}$/D', $slug) !== 1) {
    fail(400, 'invalid slug (must match ^[a-z0-9_-]{1,64}$)');
}

$scene_dir = SCENES_ROOT . '/' . $slug;
$cfg_path  = $scene_dir . '/viewer-config.json';
$tok_path  = $scene_dir . '/' . TOKEN_BASENAME;

/* ===== 5. auth: constant-time per-scene bearer ======================= */

// Authorization-header recovery, in priority order:
//  1. HTTP_AUTHORIZATION       — set directly when the SAPI keeps it.
//  2. REDIRECT_HTTP_AUTHORIZATION — what the sibling .htaccess actually
//     produces: its `RewriteRule ... [E=HTTP_AUTHORIZATION:%1]` runs in a
//     per-directory (.htaccess) context, and Apache prefixes env vars set
//     by a per-dir rewrite with `REDIRECT_`. On Strato (and most shared
//     LAMP hosts that strip the raw header) THIS is the key that carries
//     the Bearer token — the un-prefixed HTTP_AUTHORIZATION is never set.
//  3. apache_request_headers() — last-resort raw-header scan for SAPIs
//     that expose neither $_SERVER form.
$auth = $_SERVER['HTTP_AUTHORIZATION']
    ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION']
    ?? '';
if ($auth === '' && function_exists('apache_request_headers')) {
    // Some SAPIs drop both $_SERVER forms; recover from the raw headers.
    foreach (apache_request_headers() as $k => $v) {
        if (strcasecmp($k, 'Authorization') === 0) {
            $auth = $v;
            break;
        }
    }
}
$given = '';
if (preg_match('/^Bearer\s+(.+)$/i', trim($auth), $m) === 1) {
    $given = trim($m[1]);
}

$stored = is_file($tok_path) ? trim((string) file_get_contents($tok_path)) : '';
// Accept either a raw token or its lowercase hex sha256 in the store.
$expected_raw    = $stored;
$expected_sha256 = (strlen($stored) === 64 && ctype_xdigit($stored)) ? $stored : '';

$ok_auth = false;
if ($given !== '' && $stored !== '') {
    if ($expected_sha256 !== '') {
        $ok_auth = hash_equals($expected_sha256, hash('sha256', $given));
    } else {
        $ok_auth = hash_equals($expected_raw, $given);
    }
}
if (!$ok_auth) {
    // Never reveal whether the slug/token store exists, nor echo any token.
    fail(401, 'unauthorized');
}

/* ===== 6. load existing config (Bunny first, then local fallback) ===== *
 * Two-source read so the merge always operates on the actual deployed
 * state: if BUNNY_ENV_FILE is configured + the CDN returns a config, that
 * is the source of truth (the deployed viewer reads from Bunny). Otherwise
 * fall back to the local Strato file (the documented "scenes/<slug>/ tree
 * co-located with the viewer" model). Both branches still feed the same
 * merge -> local-write -> Bunny-push pipeline; only the "existing" base
 * changes.
 */
$bunny_env = load_env_file(BUNNY_ENV_FILE);
$existing  = null;
if ($bunny_env) {
    $existing = bunny_fetch_config($bunny_env, $slug);
}
if ($existing === null) {
    $existing = [];
    if (is_file($cfg_path)) {
        $existing_raw = (string) file_get_contents($cfg_path);
        if (trim($existing_raw) !== '') {
            $decoded = json_decode($existing_raw, true);
            if (!is_array($decoded)) {
                fail(500, 'existing viewer-config.json is not a JSON object');
            }
            $existing = $decoded;
        }
    }
}

/* ===== 7. MERGE — cross-language twin of merge_camera_scope ========== *
 * Python (config_merge.py), parity-critical lines:
 *   result = copy.deepcopy(existing)
 *   for key, value in patch.items():
 *       if key in ALLOWED_PATCH_KEYS:
 *           result[key] = copy.deepcopy(value)        # WHOLE-key replace
 *   if "primary_asset" in existing:
 *       result["primary_asset"] = copy.deepcopy(existing["primary_asset"])
 *
 * PHP equivalents:
 *  - `$result = $existing;` — json_decode produced a fresh, unshared tree;
 *    PHP arrays are value types (copy-on-write), so this is the deep-copy
 *    base, preserving every non-allow-listed key + nested data unchanged.
 *  - whole-key REPLACE (`$result[$k] = $patch[$k]`), NOT a recursive
 *    merge — a nested dict in an allowed key replaces wholesale, exactly
 *    like the Python `result[key] = value` (oracle: nested_dict_whole_replace).
 *  - force-keep existing's primary_asset, applied LAST and independent of
 *    the patch loop, so a patch primary_asset can NEVER win; if existing
 *    has none, none is synthesized.
 *  - non-allow-listed patch keys are silently dropped (NOT a 400 — mirrors
 *    the core's silent-drop contract) and collected for `ignored`.
 */
$result  = $existing;                 // deep-copy base (value semantics)
$ignored = [];
foreach ($patch as $key => $value) {
    if ($key === 'slug') {
        continue;                     // transport field, not config
    }
    if (in_array($key, ALLOWED_PATCH_KEYS, true)) {
        $result[$key] = $value;       // whole-key replace
    } elseif ($key !== 'primary_asset') {
        // primary_asset is a locked-invariant force-keep, NOT an author
        // diagnostic — never list it (mirrors SaveResult.ignored_keys).
        $ignored[] = $key;
    }
}
// Force-keep the existing pointer (locked invariant). Last + independent of
// the loop so a patched primary_asset can never take effect. No synthesis.
if (array_key_exists('primary_asset', $existing)) {
    $result['primary_asset'] = $existing['primary_asset'];
}
sort($ignored);
$ignored = array_values(array_unique($ignored));

/* ===== 8. atomic write (flock -> tmp -> .bak -> rename) ============== */

if (!is_dir($scene_dir)) {
    // Slug is valid but unknown here: nothing to write into. Do not leak
    // existence beyond the auth gate already passed.
    fail(404, 'scene not found');
}

$encoded = json_encode(
    $result,
    JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
);
if ($encoded === false) {
    fail(500, 'failed to encode merged config');
}

$lock_path = $scene_dir . '/.save.lock';
$tmp_path  = $cfg_path . '.tmp';
$bak_path  = $cfg_path . '.bak';

$lock = fopen($lock_path, 'c');
if ($lock === false || !flock($lock, LOCK_EX)) {
    fail(500, 'could not acquire write lock');
}
try {
    // Write the full new content to a sibling tmp first (never truncate the
    // live file) — a crash mid-write leaves the live config intact.
    // The outer flock() above already serialises all writers for this scene;
    // the .tmp file is a fresh exclusive write, so no per-write lock is needed.
    if (file_put_contents($tmp_path, $encoded) === false) {
        fail(500, 'failed to write temp config');
    }
    // Snapshot the prior live file before swapping (single author =>
    // last-write-wins is acceptable; .bak is the one-step undo).
    if (is_file($cfg_path)) {
        @copy($cfg_path, $bak_path);
    }
    // POSIX-atomic publish: same-filesystem rename over the live path.
    if (!rename($tmp_path, $cfg_path)) {
        @unlink($tmp_path);
        fail(500, 'failed to publish merged config');
    }
} finally {
    flock($lock, LOCK_UN);
    fclose($lock);
}

/* ===== 8b. Bunny push (additive; non-blocking) ======================== *
 * If BUNNY_ENV_FILE is configured, also push the merged config to Bunny
 * Storage so the deployed viewer on the CDN sees the new state. Failure
 * here is NON-FATAL — the local atomic write already succeeded; surface
 * the status as `bunny_push_ok` in the success body so the operator can
 * investigate without re-doing the edit. (The oracle test_php_save_oracle
 * does not configure BUNNY_ENV_FILE, so its data-parity contract on the
 * local file is unchanged.)
 */
$bunny_push_ok    = false;
$bunny_purge_ok   = false;
$bunny_configured = !empty($bunny_env);
if ($bunny_configured) {
    $bunny_push_ok = bunny_put_config($bunny_env, $slug, $encoded);
    if ($bunny_push_ok) {
        $bunny_purge_ok = bunny_purge_config($bunny_env, $slug);
    }
}

/* ===== 9. success ===================================================== *
 * `ignored` = the dropped non-allow-listed key names — INFORMATIONAL, not
 * an error (Task-4 carry-forward; mirrors SaveResult.ignored_keys). The
 * token is never part of any response or log. `bunny_push_ok` is OMITTED
 * entirely when Bunny is not configured (the legacy local-only path).
 */
$out = ['ok' => true, 'ignored' => $ignored];
if ($bunny_configured) {
    $out['bunny_push_ok']  = $bunny_push_ok;
    $out['bunny_purge_ok'] = $bunny_purge_ok;
}
send_json(200, $out);
