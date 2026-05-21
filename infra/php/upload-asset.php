<?php
/**
 * upload-asset.php -- the server side of the keyframe-editor's in-browser
 * panorama / audio FILE UPLOAD (save_backend="http").
 *
 * SIBLING of save-camera.php. GENERIC, self-hostable reference adapter:
 * drop this file plus the shared .htaccess next to save-camera.php and the
 * `scenes/<slug>/` tree on ANY plain-PHP host. No framework, no Composer,
 * no DB, no shelling out. geddart.de / Strato is just ONE such host.
 *
 * WHY THIS EXISTS: a deployed Spark viewer is a STATIC bundle on a CDN. The
 * editor's panorama/audio file pickers used to POST to `../upload-image` /
 * `../upload-audio`, which only exist on the splatpipe web DASHBOARD (the
 * FastAPI dev server). On a live CDN scene those POSTs 404 silently -- the
 * upload feature was DEAD. This endpoint is the http-mode replacement: the
 * browser POSTs the picked file here with the same per-scene bearer token
 * the Save button uses; this endpoint authenticates, validates, then PUTs
 * the file to Bunny Storage at `<slug>/<sanitized-filename>` so the
 * deployed viewer can load it as a RELATIVE url next to its index.html.
 *
 * It REUSES save-camera.php's primitives verbatim (same auth flow, same
 * Bunny PUT helper shape, same CORS, same slug charset) -- this is a thin
 * sibling, NOT a reimplementation. The ONLY new surface is multipart file
 * handling + an extension allow-list + a size cap. The filename
 * sanitisation MIRRORS the Python dashboard route hardening (#107 /
 * bug-audit #7 in src/splatpipe/web/routes/projects.py): reject any path
 * separator / drive-colon / dotfile / rewrite; allow-list the extension.
 *
 * SECURITY MODEL (identical trust boundary to save-camera.php):
 *  - The ONLY client-held secret is the per-scene bearer (URL fragment).
 *    It can do exactly two things now: POST a camera-scope patch
 *    (save-camera.php) OR upload an allow-listed asset for ONE slug (here).
 *  - No storage/CDN/object key ever touches the client. The Bunny Storage
 *    key lives only in `.bunny_env` server-side (htaccess-denied).
 *  - The destination filename is built from a sanitised basename only; the
 *    slug is charset-validated (no traversal). The asset can ONLY land
 *    inside `<slug>/` on the storage zone.
 */

declare(strict_types=1);

/* ===== CONFIG (generic -- mirrors save-camera.php's CONFIG block) ======= *
 * SCENES_ROOT / TOKEN_BASENAME: same per-scene token store as
 *   save-camera.php (the auth source of truth is identical -- a scene
 *   authorable via Save is authorable for upload, same bearer).
 * BUNNY_ENV_FILE: the SAME .env-style Bunny credentials file
 *   save-camera.php reads. Required here -- without it there is nowhere
 *   to PUT the asset for a deployed CDN viewer (a 503 is returned).
 * MAX_IMAGE_BYTES / MAX_AUDIO_BYTES: per-kind size caps, mirroring the
 *   Python dashboard route caps (5 MiB image / 50 MiB audio).
 */
const SCENES_ROOT     = __DIR__ . '/scenes';
const TOKEN_BASENAME  = '.author-token';
const BUNNY_ENV_FILE  = __DIR__ . '/.bunny_env';

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;        // 5 MiB  (mirrors _IMAGE_UPLOAD_MAX_BYTES)
const MAX_AUDIO_BYTES = 50 * 1024 * 1024;       // 50 MiB (mirrors _AUDIO_UPLOAD_MAX_BYTES)

/**
 * Extension allow-lists -- lower-cased, dot-prefixed. MIRRORS the Python
 * dashboard routes verbatim:
 *   images -> _IMAGE_UPLOAD_ALLOWED_EXTS = {.jpg, .jpeg, .png}
 *   audio  -> _AUDIO_UPLOAD_ALLOWED_EXTS = {.mp3, .wav, .ogg, .opus, .m4a,
 *                                           .aac, .flac, .webm}
 * Deny-by-default: anything not on a list is a 415. The two lists are
 * unioned for the actual accept gate; the matched list also picks the
 * size cap.
 */
const ALLOWED_IMAGE_EXTS = ['.jpg', '.jpeg', '.png'];
const ALLOWED_AUDIO_EXTS = [
    '.mp3', '.wav', '.ogg', '.opus', '.m4a', '.aac', '.flac', '.webm',
];

/* ===== tiny helpers (verbatim shape from save-camera.php) =============== */

function send_json(int $status, array $body): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
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
 * VERBATIM port of save-camera.php::load_env_file -- same quote-stripping,
 * same comment/blank skipping. Returns [] if absent/unreadable. Never
 * logged / never echoed.
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
 * PUT a local file to Bunny Storage at `<slug>/<filename>`. Returns true on
 * success, false on any error. Same auth header + endpoint shape as
 * save-camera.php::bunny_put_config, but streams a FILE body (the asset can
 * be tens of MB -- never materialise it twice) and sends a generic
 * Content-Type (Bunny stores bytes verbatim; the CDN sets the response
 * Content-Type from the extension on read).
 */
function bunny_put_asset(array $env, string $slug, string $filename, string $local_path): bool
{
    $zone = $env['BUNNY_STORAGE_ZONE'] ?? '';
    $key  = $env['BUNNY_STORAGE_PASSWORD'] ?? '';
    if ($zone === '' || $key === '') {
        return false;
    }
    $url = 'https://storage.bunnycdn.com/' . rawurlencode($zone)
         . '/' . rawurlencode($slug) . '/' . rawurlencode($filename);
    $fh = fopen($local_path, 'rb');
    if ($fh === false) {
        return false;
    }
    $size = filesize($local_path);
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_PUT            => true,
        CURLOPT_INFILE        => $fh,
        CURLOPT_INFILESIZE    => $size === false ? 0 : $size,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER     => [
            'AccessKey: ' . $key,
            'Content-Type: application/octet-stream',
        ],
        CURLOPT_TIMEOUT        => 120,
        CURLOPT_FAILONERROR    => false,
    ]);
    curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    fclose($fh);
    return $code >= 200 && $code < 300;
}

/**
 * Purge the Bunny edge cache for the freshly-uploaded asset so the very
 * next read sees it (best-effort; a purge failure does NOT abort -- a new
 * filename is rarely already edge-cached anyway). VERBATIM shape from
 * save-camera.php::bunny_purge_config.
 */
function bunny_purge_asset(array $env, string $slug, string $filename): bool
{
    $api = $env['BUNNY_ACCOUNT_API_KEY'] ?? '';
    $cdn = rtrim($env['BUNNY_CDN_URL'] ?? '', '/');
    if ($api === '' || $cdn === '') {
        return false;
    }
    $purge_url = 'https://api.bunny.net/purge?url='
               . urlencode($cdn . '/' . $slug . '/' . $filename);
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

/* ===== 1. CORS preflight (identical to save-camera.php) ================ */

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
if ($method === 'OPTIONS') {
    http_response_code(204);
    header('Access-Control-Allow-Origin: *');
    header('Access-Control-Allow-Methods: POST, OPTIONS');
    header('Access-Control-Allow-Headers: Authorization, Content-Type');
    header('Access-Control-Max-Age: 600');
    exit;
}

/* ===== 2. method gate ================================================== */

if ($method !== 'POST') {
    fail(405, 'method not allowed; POST multipart/form-data only');
}

/* ===== 3. resolve + validate slug (from the multipart `slug` field) ==== *
 * Same charset as save-camera.php (`^[a-z0-9_-]{1,64}$`) which also blocks
 * path traversal. The slug arrives as a normal multipart form field.
 */
$slug = $_POST['slug'] ?? '';
if (!is_string($slug)) {
    fail(400, 'slug must be a string');
}
if (preg_match('/^[a-z0-9_-]{1,64}$/D', $slug) !== 1) {
    fail(400, 'invalid slug (must match ^[a-z0-9_-]{1,64}$)');
}

$scene_dir = SCENES_ROOT . '/' . $slug;
$tok_path  = $scene_dir . '/' . TOKEN_BASENAME;

/* ===== 4. auth: constant-time per-scene bearer (verbatim) ============== */

$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
if ($auth === '' && function_exists('apache_request_headers')) {
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

/* ===== 5. the uploaded file =========================================== */

if (!isset($_FILES['file']) || !is_array($_FILES['file'])) {
    fail(400, 'no file uploaded (multipart field "file" required)');
}
$f = $_FILES['file'];

// PHP's own upload error codes -- map the size-related ones to 413, the
// rest to 400. UPLOAD_ERR_INI_SIZE / UPLOAD_ERR_FORM_SIZE happen when the
// body exceeds the host's upload_max_filesize / post_max_size BEFORE our
// own cap can run, so surface them as 413 too.
$err = (int) ($f['error'] ?? UPLOAD_ERR_NO_FILE);
if ($err === UPLOAD_ERR_INI_SIZE || $err === UPLOAD_ERR_FORM_SIZE) {
    fail(413, 'uploaded file exceeds the server upload size limit');
}
if ($err !== UPLOAD_ERR_OK) {
    fail(400, 'file upload failed (php upload error ' . $err . ')');
}

$tmp_upload = (string) ($f['tmp_name'] ?? '');
if ($tmp_upload === '' || !is_uploaded_file($tmp_upload)) {
    // is_uploaded_file guards against a forged tmp_name pointing at an
    // arbitrary server file (the canonical PHP upload-safety check).
    fail(400, 'invalid upload (not a POSTed file)');
}

/* ===== 6. filename sanitisation -- MIRRORS the #107 Python hardening === *
 * src/splatpipe/web/routes/projects.py upload_audio / upload_image:
 *   - reject any '/' or '\\' (path separator)
 *   - reject ':' (Windows drive-colon)
 *   - basename(raw) must EQUAL raw (else the sanitiser rewrote it -> reject)
 *   - reject empty / '.' / '..' / leading-dot (dotfile)
 *   - allow-list the extension (case-insensitive)
 * PHP's basename() resolves '/' on all platforms and '\\' on Windows; we
 * additionally hard-reject both separators + ':' up front so the rejection
 * is OS-uniform (matching the Python route's explicit pre-checks).
 */
$raw_name = (string) ($f['name'] ?? '');
if ($raw_name === '') {
    fail(400, 'uploaded file has no name');
}
if (strpos($raw_name, '/') !== false || strpos($raw_name, '\\') !== false) {
    fail(400, 'filename must not contain path separators');
}
if (strpos($raw_name, ':') !== false) {
    fail(400, 'filename must not contain path separators');
}
$safe_name = basename($raw_name);
if ($safe_name !== $raw_name) {
    fail(400, 'filename was rewritten by sanitiser');
}
if ($safe_name === '' || $safe_name === '.' || $safe_name === '..'
    || $safe_name[0] === '.') {
    fail(400, 'filename must not be empty or a dotfile');
}
// NUL byte / control chars are never valid in a filename here.
if (preg_match('/[\x00-\x1f]/', $safe_name) === 1) {
    fail(400, 'filename contains control characters');
}

/* ===== 7. extension allow-list + per-kind size cap ===================== */

$dot = strrpos($safe_name, '.');
$ext = ($dot === false) ? '' : strtolower(substr($safe_name, $dot));

$max_bytes = 0;
if (in_array($ext, ALLOWED_IMAGE_EXTS, true)) {
    $max_bytes = MAX_IMAGE_BYTES;
} elseif (in_array($ext, ALLOWED_AUDIO_EXTS, true)) {
    $max_bytes = MAX_AUDIO_BYTES;
} else {
    // Deny-by-default: not an allow-listed image or audio extension.
    fail(415, 'unsupported file extension (allowed: '
        . implode(' ', ALLOWED_IMAGE_EXTS) . ' '
        . implode(' ', ALLOWED_AUDIO_EXTS) . ')');
}

$size = (int) ($f['size'] ?? 0);
// Prefer the real on-disk size of the received temp file over the reported
// multipart size (the latter is client-supplied and could lie).
$actual = filesize($tmp_upload);
if ($actual !== false) {
    $size = (int) $actual;
}
if ($size <= 0) {
    fail(400, 'uploaded file is empty');
}
if ($size > $max_bytes) {
    fail(413, 'uploaded file exceeds the size cap for its type ('
        . (int) ($max_bytes / (1024 * 1024)) . ' MiB)');
}

/* ===== 8. push to Bunny Storage at <slug>/<filename> =================== *
 * The deployed viewer is a static CDN bundle: the asset MUST land on the
 * storage zone next to the scene's index.html so the viewer can load it as
 * a relative url. Without Bunny creds there is nowhere to put it for a CDN
 * scene -> 503 (the dashboard-local upload path is a separate route).
 */
$bunny_env = load_env_file(BUNNY_ENV_FILE);
if (empty($bunny_env)
    || ($bunny_env['BUNNY_STORAGE_ZONE'] ?? '') === ''
    || ($bunny_env['BUNNY_STORAGE_PASSWORD'] ?? '') === '') {
    fail(503, 'asset storage is not configured on this host '
        . '(no Bunny credentials); cannot store the upload');
}

$put_ok = bunny_put_asset($bunny_env, $slug, $safe_name, $tmp_upload);
if (!$put_ok) {
    fail(502, 'failed to store the uploaded asset on the CDN');
}
// Best-effort edge purge (a brand-new filename is rarely already cached).
$purge_ok = bunny_purge_asset($bunny_env, $slug, $safe_name);

/* ===== 9. success ===================================================== *
 * Return the RELATIVE filename so the JS client writes it straight into
 * cfg.panorama_backdrop.image_url / cfg.audio[].file (both are resolved
 * relative to the viewer's index.html on the CDN). `url` is the contract
 * field the client reads; `purge_ok` is informational.
 */
send_json(200, [
    'ok'       => true,
    'url'      => $safe_name,
    'slug'     => $slug,
    'bytes'    => $size,
    'purge_ok' => $purge_ok,
]);
