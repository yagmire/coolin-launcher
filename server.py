"""Coolin Launcher server.

Serves game builds and launcher assets to the launcher, and hosts a password
protected admin panel for managing both.

Settings come from environment variables, usually through a .env file next to
this script (see .env.example).

Data layout (under COOLIN_DATA_DIR, default /dingo):
    catalog.json                            games shown in the launcher
    betakey                                 beta key (plain text)
    <game>/<branch>/<version>/<game>.zip    build zips (+ meta.json)
    _launcher/assets/...                    launcher asset overrides/additions
    _launcher/secret                        signing secret for the admin panel
"""
import hashlib, hmac, json, os, re, secrets, shlex, shutil, sys, threading, time, zipfile
from contextlib import contextmanager
from datetime import datetime, timezone

from flask import Flask, request, send_file, send_from_directory, abort, jsonify, render_template, redirect, url_for, flash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_httpauth import HTTPBasicAuth
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
# Real environment variables win over the .env file.
load_dotenv(os.path.join(SERVER_DIR, ".env"))

# A relative data dir is relative to this script, not wherever the server was started from.
BASE_DIRECTORY = os.path.join(SERVER_DIR, os.environ.get("COOLIN_DATA_DIR", "/dingo"))
ADMIN_USER = os.environ.get("COOLIN_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("COOLIN_ADMIN_PASSWORD", "")
HOST = os.environ.get("COOLIN_HOST", "0.0.0.0")
PORT = int(os.environ.get("COOLIN_PORT", "2665"))
LAUNCHER_DIR = os.path.join(BASE_DIRECTORY, "_launcher")
ASSET_DIR = os.path.join(LAUNCHER_DIR, "assets")
CATALOG_FILE = os.path.join(BASE_DIRECTORY, "catalog.json")
BETA_KEY_FILE = os.path.join(BASE_DIRECTORY, "betakey")
SECRET_FILE = os.path.join(LAUNCHER_DIR, "secret")
# Build zips being uploaded in pieces. Same disk as the builds, so finished uploads are moved, not copied.
UPLOAD_DIR = os.path.join(LAUNCHER_DIR, "uploads")
# Pieces stay well under Cloudflare's 100 MB request limit, and small enough to finish within its 100 s timeout.
UPLOAD_CHUNK_SIZE = 16 * 1024 * 1024
UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{32}$")
STALE_UPLOAD_SECONDS = 24 * 60 * 60
# Default launcher assets. The launcher ships without assets and downloads all of them from here,
# with anything uploaded in the admin panel (ASSET_DIR) replacing the default of the same name.
BUNDLED_ASSET_DIR = os.path.join(SERVER_DIR, "assets")

BRANCHES = ("stable", "beta")
GAME_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
ASSET_PATH_RE = re.compile(r"^(?:[A-Za-z0-9_-][A-Za-z0-9_.-]*/)*[A-Za-z0-9_-][A-Za-z0-9_.-]*\.([A-Za-z0-9]+)$")
ASSET_KINDS = {
    "image": {"png", "jpg", "jpeg", "gif", "bmp"},
    "audio": {"wav", "ogg", "mp3"},
    "font": {"ttf", "otf"},
    "other": {"ico", "json", "txt"},
}
ASSET_EXTENSIONS = set().union(*ASSET_KINDS.values())

GAME_TYPES = {
    "doom": {
        "label": "Doom mod",
        "hint": "Runs in GZDoom, which the launcher installs automatically along with doom2.wad.",
        "build": True,
        "target": "WAD/PK3 or folder inside the zip. Leave blank to load the whole game folder.",
    },
    "exe": {
        "label": "Windows program",
        "hint": "Runs an .exe from the zip. Updates extract over the old files, so save files are kept.",
        "build": True,
        "target": "Path to the .exe inside the zip, e.g. MyGame/MyGame.exe",
    },
    "java": {
        "label": "Java game",
        "hint": "Runs a .jar. Uses a jre/ folder from the zip if there is one, otherwise the launcher downloads Java.",
        "build": True,
        "target": "Path to the .jar inside the zip, e.g. game.jar",
    },
    "flash": {
        "label": "Flash game",
        "hint": "Plays a .swf in Ruffle, the modern Flash Player replacement, which the launcher installs automatically.",
        "build": True,
        "target": "Path to the .swf inside the zip, e.g. game.swf",
    },
    "url": {
        "label": "Web link",
        "hint": "Opens a page in the player's browser (itch.io page, web game, video...). No build needed.",
        "build": False,
        "target": "URL to open, starting with https://",
    },
    "extras": {
        "label": "Extras",
        "hint": "The built-in extras screen that lists cutscenes. No build needed.",
        "build": False,
        "target": "Cutscene files to list, relative to the launcher's games folder (wildcards allowed)",
    },
}
VISIBILITY = {"public": "Everyone", "beta": "Beta testers only", "hidden": "Hidden"}
STATUSES = {"available": "Playable", "coming_soon": "Coming soon"}

# Assets the launcher uses. Anything not uploaded in the admin panel uses the server's default copy.
LAUNCHER_SLOTS = [
    ("bg.png", "Main menu background (800x600)"),
    ("intro.png", "First-run intro screen (800x600)"),
    ("download-assets.png", "Downloading / installing screen (800x600)"),
    ("select.png", "Selector graphic above the banners"),
    ("rock.png", "Window icon"),
    ("banners/holder-drop.png", "Banner for games that don't have one (359x478)"),
    ("font/Pixeled.ttf", "Launcher font"),
    ("sounds/sonic.wav", "Menu music (loops)"),
    ("sounds/select.wav", "Moving between games"),
    ("sounds/play.wav", "Launching a game"),
    ("sounds/error.wav", "Error / game unavailable"),
    ("sounds/success.wav", "Download finished / beta key saved"),
    ("sounds/extras.wav", "Extras easter egg (Shift+Enter)"),
]

DEFAULT_GAMES = [
    {"id": "coolin", "title": "Coolin", "type": "doom", "target": "Coolin.wad", "banner": "banners/og-drop.png"},
    {"id": "16", "title": "Coolin 16", "type": "doom", "target": "", "banner": "banners/16-drop.png"},
    {"id": "3", "title": "Coolin 3", "type": "doom", "target": "", "banner": "banners/3-drop.png",
     "status": "coming_soon", "message": "Coolin 3 is still in development"},
    {"id": "extras", "title": "Extras", "type": "extras", "target": "16/intro.pk3/vids/*.ivf",
     "banner": "banners/extras-drop.png"},
]


app = Flask(__name__)
if os.environ.get("COOLIN_TRUST_PROXY", "").lower() in ("1", "true", "yes"):
    # Behind a reverse proxy, rate limits need the real client address.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
auth = HTTPBasicAuth()

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["55 per day", "15 per hour"],
    storage_uri="memory://",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iso_from_timestamp(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def file_sha256(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, path)


def load_secret():
    if os.path.isfile(SECRET_FILE):
        with open(SECRET_FILE, "rb") as f:
            return f.read()
    os.makedirs(LAUNCHER_DIR, exist_ok=True)
    secret = secrets.token_bytes(32)
    with open(SECRET_FILE, "wb") as f:
        f.write(secret)
    return secret


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

_catalog_lock = threading.RLock()


def make_game(**fields):
    game = {
        "id": "", "title": "", "type": "doom", "target": "", "args": "", "jvm_args": "",
        "java_version": 21, "iwad": "", "banner": "", "visibility": "public",
        "status": "available", "message": "", "order": 0,
    }
    game.update(fields)
    pinned = game.get("pinned") or {}
    game["pinned"] = {branch: pinned.get(branch) for branch in BRANCHES}
    return game


def _initial_catalog():
    """Builds the first catalog from the games the old launcher had hardcoded plus any build folders on disk."""
    games = [make_game(order=i, **g) for i, g in enumerate(DEFAULT_GAMES)]
    known = {g["id"] for g in games}
    if os.path.isdir(BASE_DIRECTORY):
        for name in sorted(os.listdir(BASE_DIRECTORY)):
            if name in known or not GAME_ID_RE.match(name):
                continue
            if any(os.path.isdir(os.path.join(BASE_DIRECTORY, name, b)) for b in BRANCHES):
                games.append(make_game(id=name, title=name, order=len(games)))
    return {"games": games}


def load_catalog():
    with _catalog_lock:
        if not os.path.isfile(CATALOG_FILE):
            catalog = _initial_catalog()
            save_catalog(catalog)
            return catalog
        catalog = read_json(CATALOG_FILE, None)
        if not isinstance(catalog, dict):
            raise RuntimeError(f"{CATALOG_FILE} is not valid JSON")
        catalog["games"] = [make_game(**g) for g in catalog.get("games", [])]
        return catalog


def save_catalog(catalog):
    with _catalog_lock:
        catalog["games"].sort(key=lambda g: (g["order"], g["title"].lower()))
        for i, game in enumerate(catalog["games"]):
            game["order"] = i
        write_json(CATALOG_FILE, catalog)


@contextmanager
def edit_catalog():
    """Load, modify and save the catalog atomically. Nothing is saved if the block raises."""
    with _catalog_lock:
        catalog = load_catalog()
        yield catalog
        save_catalog(catalog)


def sorted_games(catalog):
    return sorted(catalog["games"], key=lambda g: (g["order"], g["title"].lower()))


def find_game(catalog, gid):
    return next((g for g in catalog["games"] if g["id"] == gid), None)


def get_game_or_404(gid):
    game = find_game(load_catalog(), gid)
    if game is None:
        abort(404, "Game not found")
    return game


def needs_build(game):
    return GAME_TYPES.get(game["type"], {}).get("build", False)


def visible_on_branch(game, branch):
    return game["visibility"] == "public" or (game["visibility"] == "beta" and branch == "beta")


def split_args(text):
    try:
        return shlex.split(text or "")
    except ValueError:
        return (text or "").split()


# ---------------------------------------------------------------------------
# Builds
# ---------------------------------------------------------------------------

def game_dir(gid):
    if not GAME_ID_RE.match(gid):
        abort(400, "Invalid game id")
    return os.path.join(BASE_DIRECTORY, gid)


def list_versions(gid, branch):
    path = os.path.join(game_dir(gid), branch)
    if not os.path.isdir(path):
        return []
    return sorted((int(f) for f in os.listdir(path) if f.isdigit() and os.path.isdir(os.path.join(path, f))),
                  reverse=True)


def version_dir(gid, branch, version):
    return os.path.join(game_dir(gid), branch, str(version))


def build_zip(gid, branch, version):
    folder = version_dir(gid, branch, version)
    if not os.path.isdir(folder):
        return None
    zips = sorted(f for f in os.listdir(folder) if f.lower().endswith(".zip"))
    for name in zips:
        if name.lower() == f"{gid}.zip":
            return os.path.join(folder, name)
    return os.path.join(folder, zips[0]) if zips else None


def build_info(gid, branch, version):
    path = build_zip(gid, branch, version)
    if not path:
        return None
    meta_path = os.path.join(version_dir(gid, branch, version), "meta.json")
    meta = read_json(meta_path, {})
    stat = os.stat(path)
    if meta.get("size") != stat.st_size or not meta.get("sha256"):
        # Builds uploaded before meta.json existed, or replaced by hand.
        meta["size"] = stat.st_size
        meta["sha256"] = file_sha256(path)
        meta.setdefault("uploaded_at", iso_from_timestamp(stat.st_mtime))
        write_json(meta_path, meta)
    return {
        "version": version,
        "branch": branch,
        "size": meta["size"],
        "sha256": meta["sha256"],
        "uploaded_at": meta.get("uploaded_at", ""),
        "notes": meta.get("notes", ""),
        "filename": meta.get("original_filename") or os.path.basename(path),
    }


def active_version(game, branch):
    """The version players get: the pinned one if set, otherwise the newest."""
    versions = [v for v in list_versions(game["id"], branch) if build_zip(game["id"], branch, v)]
    pinned = game["pinned"].get(branch)
    if pinned in versions:
        return pinned
    return versions[0] if versions else None


def resolve_build(game, branch):
    """Beta players get the beta build when there is one, otherwise stable."""
    if branch == "beta":
        version = active_version(game, "beta")
        if version is not None:
            return build_info(game["id"], "beta", version)
    version = active_version(game, "stable")
    return build_info(game["id"], "stable", version) if version is not None else None


def check_target_in_zip(game, zip_path):
    """Returns a warning if the game's launch target isn't in the zip."""
    target = (game["target"] or "").replace("\\", "/").strip("/")
    if game["type"] not in ("doom", "exe", "java", "flash") or not target:
        return None
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = [n.rstrip("/").lower() for n in zf.namelist()]
    except zipfile.BadZipFile:
        return "The zip file is corrupt."
    lowered = target.lower()
    if lowered in names or any(n.startswith(lowered + "/") for n in names):
        return None
    top = sorted({n.split("/")[0] for n in names if n})[:6]
    return f"Launch target '{target}' isn't in this zip, so players won't be able to start it. " \
           f"Top-level files: {', '.join(top) or 'none'}."


def storage_used():
    total = 0
    for root, _dirs, files in os.walk(BASE_DIRECTORY):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


# ---------------------------------------------------------------------------
# Beta key
# ---------------------------------------------------------------------------

def beta_key_text():
    try:
        with open(BETA_KEY_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def beta_key_hash():
    # The launcher hashes its key file byte for byte, so this must too.
    try:
        with open(BETA_KEY_FILE, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return hashlib.sha512(data).hexdigest() if data else None


def key_is_valid(key):
    expected = beta_key_hash()
    return bool(expected and key and hmac.compare_digest(expected, key))


def request_branch():
    return "beta" if key_is_valid(request.args.get("key")) else "stable"


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

_asset_hash_cache = {}


def clean_asset_path(path):
    path = (path or "").replace("\\", "/").strip("/")
    match = ASSET_PATH_RE.match(path)
    if not match or match.group(1).lower() not in ASSET_EXTENSIONS:
        return None
    return path


def asset_kind(path):
    ext = path.rsplit(".", 1)[-1].lower()
    return next((kind for kind, exts in ASSET_KINDS.items() if ext in exts), "other")


def scan_assets(base):
    assets = {}
    if not os.path.isdir(base):
        return assets
    for root, _dirs, files in os.walk(base):
        for name in files:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, base).replace(os.sep, "/")
            if not clean_asset_path(rel):
                continue
            stat = os.stat(full)
            key = (full, stat.st_mtime, stat.st_size)
            if key not in _asset_hash_cache:
                _asset_hash_cache[key] = file_sha256(full)
            assets[rel] = {"size": stat.st_size, "sha256": _asset_hash_cache[key], "modified": iso_from_timestamp(stat.st_mtime)}
    return dict(sorted(assets.items()))


def list_assets():
    """Assets uploaded in the admin panel."""
    return scan_assets(ASSET_DIR)


def launcher_assets():
    """Every asset the launcher downloads: the defaults, with uploads replacing them."""
    return dict(sorted({**scan_assets(BUNDLED_ASSET_DIR), **scan_assets(ASSET_DIR)}.items()))


def asset_manifest():
    files = {path: {"size": a["size"], "sha256": a["sha256"]} for path, a in launcher_assets().items()}
    revision = hashlib.sha256("\n".join(f"{p}:{f['sha256']}" for p, f in files.items()).encode()).hexdigest()[:16]
    return {"revision": revision, "files": files}


def bundled_asset_exists(path):
    return bool(clean_asset_path(path)) and os.path.isfile(os.path.join(BUNDLED_ASSET_DIR, path))


def asset_preview_url(path):
    """URL for previewing an asset in the admin panel, or None if the launcher won't find it anywhere."""
    if not clean_asset_path(path):
        return None
    if os.path.isfile(os.path.join(ASSET_DIR, path)):
        return url_for("api_asset", path=path, v=int(os.path.getmtime(os.path.join(ASSET_DIR, path))))
    if bundled_asset_exists(path):
        return url_for("admin_builtin_asset", path=path)
    return None


def asset_exists_anywhere(path):
    return bool(clean_asset_path(path)) and (os.path.isfile(os.path.join(ASSET_DIR, path)) or bundled_asset_exists(path))


def banner_choices():
    choices = set()
    for base in (ASSET_DIR, BUNDLED_ASSET_DIR):
        folder = os.path.join(base, "banners")
        if os.path.isdir(folder):
            choices.update(f"banners/{f}" for f in os.listdir(folder) if asset_kind(f) == "image")
    return sorted(choices)


# ---------------------------------------------------------------------------
# Auth & CSRF
# ---------------------------------------------------------------------------

SECRET = load_secret()
app.secret_key = SECRET
_failed_logins = {}
MAX_FAILED_LOGINS = 10
FAILED_LOGIN_WINDOW = 15 * 60


def check_credentials(username, password):
    if not ADMIN_PASSWORD:
        return False
    return hmac.compare_digest(username, ADMIN_USER) and hmac.compare_digest(password, ADMIN_PASSWORD)


@auth.verify_password
def verify_password(username, password):
    ip = get_remote_address()
    now = time.time()
    recent = [t for t in _failed_logins.get(ip, []) if now - t < FAILED_LOGIN_WINDOW]
    _failed_logins[ip] = recent
    if len(recent) >= MAX_FAILED_LOGINS or not username:
        return None
    if check_credentials(username, password or ""):
        return username
    recent.append(now)
    return None


@auth.error_handler
def auth_error(status):
    if not ADMIN_PASSWORD:
        return "The admin panel is disabled. Set COOLIN_ADMIN_PASSWORD in the server's .env file and restart.", status
    return "Unauthorized Access", status


def csrf_token():
    return hmac.new(SECRET, b"coolin-admin-csrf", hashlib.sha256).hexdigest()


@app.before_request
def check_csrf():
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.path.startswith("/admin"):
        # Upload pieces send the token as a header, since their body is raw file data.
        token = request.headers.get("X-CSRF-Token") or request.form.get("csrf", "")
        if not hmac.compare_digest(token, csrf_token()):
            abort(400, "The form expired. Reload the page and try again.")


# Globals rather than a context processor so imported macros can use them too.
app.jinja_env.globals.update(
    csrf_token=csrf_token,
    asset_preview_url=asset_preview_url,
    GAME_TYPES=GAME_TYPES,
    TARGET_HINTS={key: info["target"] for key, info in GAME_TYPES.items()},
    VISIBILITY=VISIBILITY,
    STATUSES=STATUSES,
    BRANCHES=BRANCHES,
)



@app.template_filter("filesize")
def filesize_filter(size):
    size = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


@app.template_filter("when")
def when_filter(iso):
    try:
        return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC")
    except (TypeError, ValueError):
        return iso or "unknown"


# ---------------------------------------------------------------------------
# Launcher API
# ---------------------------------------------------------------------------

def public_game(game, branch):
    info = {
        "id": game["id"],
        "title": game["title"],
        "type": game["type"],
        "target": game["target"],
        "args": split_args(game["args"]),
        "banner": game["banner"],
        "status": game["status"],
        "message": game["message"],
        "build": None,
    }
    if game["type"] == "java":
        info["jvm_args"] = split_args(game["jvm_args"])
        info["java_version"] = game["java_version"]
    if game["type"] == "doom" and game["iwad"]:
        info["iwad"] = game["iwad"]
    if needs_build(game):
        build = resolve_build(game, branch)
        if build:
            info["build"] = {k: build[k] for k in ("version", "branch", "size", "sha256")}
    return info


@app.route("/api/catalog")
@limiter.limit("120 per hour")
def api_catalog():
    branch = request_branch()
    catalog = load_catalog()
    games = [public_game(g, branch) for g in sorted_games(catalog) if visible_on_branch(g, branch)]
    return jsonify(branch=branch, games=games, assets_revision=asset_manifest()["revision"])


@app.route("/api/games/<gid>/download")
@limiter.limit("60 per hour")
def api_download(gid):
    game = get_game_or_404(gid)
    branch = request.args.get("branch", "stable")
    if branch not in BRANCHES:
        abort(400, "Unknown branch")
    player_branch = request_branch()
    if (branch == "beta" and player_branch != "beta") or not visible_on_branch(game, player_branch):
        abort(403, "Not available on your branch")
    version = request.args.get("version", type=int)
    if version is None:
        version = active_version(game, branch)
    path = build_zip(gid, branch, version) if version is not None else None
    if not path:
        abort(404, "Build not found")
    return send_file(path, as_attachment=True, download_name=f"{gid}.zip")


@app.route("/healthz")
@limiter.exempt
def healthz():
    """For container health checks; not rate limited."""
    return jsonify(ok=True, data_dir_exists=os.path.isdir(BASE_DIRECTORY))


@app.route("/api/assets/manifest")
@limiter.limit("300 per hour")
def api_asset_manifest():
    return jsonify(asset_manifest())


@app.route("/api/assets/<path:path>")
@limiter.limit("3000 per hour")
def api_asset(path):
    path = clean_asset_path(path)
    if not path:
        abort(404)
    if os.path.isfile(os.path.join(ASSET_DIR, path)):
        return send_from_directory(ASSET_DIR, path)
    return send_from_directory(BUNDLED_ASSET_DIR, path)


# Endpoints used by launchers released before the catalog existed.

@app.route('/get_latest_ver')
def get_latest_ver():
    game = find_game(load_catalog(), request.args.get('game', ''))
    if game is None:
        return abort(404, "Game not found")
    build = resolve_build(game, request.args.get('branch', 'stable'))
    if build is None:
        return abort(404, "Branch not found")
    return str(build["version"])


@app.route('/download')
def download_file():
    game = find_game(load_catalog(), request.args.get('game', ''))
    if game is None:
        return abort(404, "Game not found")
    build = resolve_build(game, request.args.get('version', 'stable'))
    if build is None:
        return abort(404, "File not found")
    return send_file(build_zip(game["id"], build["branch"], build["version"]), as_attachment=True)


@app.route("/betakey")
def check_beta_key_validity():
    return "Valid" if key_is_valid(request.args.get("key")) else "Invalid"


@app.errorhandler(429)
def slowdown(_error):
    return "You've hit the request limit.", 429


@app.route('/slow')
@limiter.limit("1 per hour")
def slow():
    return ":("


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------

def admin_route(rule, **options):
    """Registers an admin page: login required, exempt from the public rate limits."""
    def decorator(fn):
        return app.route(rule, **options)(limiter.exempt(auth.login_required(fn)))
    return decorator


def back(default="admin_dashboard", **values):
    target = request.form.get("next", "")
    if not target.startswith("/admin") or target.startswith("//"):
        target = url_for(default, **values)
    return redirect(target)


@admin_route("/admin")
def admin_dashboard():
    catalog = load_catalog()
    games = sorted_games(catalog)
    warnings, rows, recent = [], [], []
    for game in games:
        builds = {b: active_version(game, b) for b in BRANCHES}
        rows.append({"game": game, "builds": builds})
        if needs_build(game) and game["status"] == "available":
            if builds["stable"] is None and game["visibility"] == "public":
                warnings.append((game, "has no stable build, so regular players can't install it."))
            elif builds["stable"] is None and builds["beta"] is None and game["visibility"] == "beta":
                warnings.append((game, "has no builds yet, so beta testers can't install it."))
        if game["banner"] and not asset_exists_anywhere(game["banner"]):
            warnings.append((game, f"uses banner '{game['banner']}', which doesn't exist."))
        for branch in BRANCHES:
            for version in list_versions(game["id"], branch):
                info = build_info(game["id"], branch, version)
                if info:
                    recent.append((game, info))
    recent.sort(key=lambda item: item[1]["uploaded_at"], reverse=True)
    stats = {
        "games": len(games),
        "public": sum(1 for g in games if g["visibility"] == "public"),
        "builds": len(recent),
        "assets": len(list_assets()),
        "storage": storage_used(),
        "beta_key": beta_key_hash() is not None,
    }
    return render_template("dashboard.html", page="dashboard", rows=rows, warnings=warnings,
                           recent=recent[:8], stats=stats)


# Games ---------------------------------------------------------------------

@admin_route("/admin/games")
def admin_games():
    rows = [{"game": g, "builds": {b: active_version(g, b) for b in BRANCHES}} for g in sorted_games(load_catalog())]
    return render_template("games.html", page="games", rows=rows)


def read_game_form(form, game):
    """Copies the settings form onto `game`. Returns a list of problems."""
    errors = []
    game["title"] = form.get("title", "").strip()[:60]
    if not game["title"]:
        errors.append("Give the game a title.")
    game["type"] = form.get("type", game["type"])
    if game["type"] not in GAME_TYPES:
        errors.append("Pick a game type.")
    game["target"] = form.get("target", "").strip()
    if game["type"] == "url" and not re.match(r"^https?://", game["target"]):
        errors.append("Web links need a URL starting with http:// or https://.")
    if game["type"] in ("exe", "java", "flash") and not game["target"]:
        errors.append(f"{GAME_TYPES[game['type']]['label']}s need the path of the file to run.")
    game["args"] = form.get("args", "").strip()
    game["jvm_args"] = form.get("jvm_args", "").strip()
    game["iwad"] = form.get("iwad", "").strip()
    try:
        game["java_version"] = max(8, min(99, int(form.get("java_version") or 21)))
    except ValueError:
        errors.append("Java version must be a number, like 21.")
    banner = form.get("banner", "").strip()
    if banner and not clean_asset_path(banner):
        errors.append("That banner path isn't valid.")
    game["banner"] = banner
    game["visibility"] = form.get("visibility") if form.get("visibility") in VISIBILITY else "public"
    game["status"] = form.get("status") if form.get("status") in STATUSES else "available"
    game["message"] = form.get("message", "").strip()[:200]
    return errors


@admin_route("/admin/games/new", methods=["GET", "POST"])
def admin_game_new():
    game = make_game()
    if request.method == "POST":
        game["id"] = request.form.get("id", "").strip().lower()
        errors = read_game_form(request.form, game)
        catalog = load_catalog()
        if not GAME_ID_RE.match(game["id"]):
            errors.insert(0, "The ID can only use lowercase letters, numbers, - and _ (max 32 characters).")
        elif find_game(catalog, game["id"]):
            errors.insert(0, f"There's already a game with the ID '{game['id']}'.")
        if not errors:
            with edit_catalog() as catalog:
                game["order"] = len(catalog["games"])
                catalog["games"].append(game)
            flash(f"Created {game['title']}." + (" Upload a build to make it playable." if needs_build(game) else ""), "success")
            return redirect(url_for("admin_game", gid=game["id"]))
        for error in errors:
            flash(error, "error")
    return render_template("game_new.html", page="games", game=game, banners=banner_choices())


@admin_route("/admin/games/<gid>")
def admin_game(gid):
    game = get_game_or_404(gid)
    branches = {}
    for branch in BRANCHES:
        active = active_version(game, branch)
        builds = [b for b in (build_info(gid, branch, v) for v in list_versions(gid, branch)) if b]
        warning = None
        if active is not None:
            warning = check_target_in_zip(game, build_zip(gid, branch, active))
        branches[branch] = {"active": active, "pinned": game["pinned"][branch], "builds": builds, "warning": warning}
    return render_template("game.html", page="games", game=game, branches=branches, banners=banner_choices())


@admin_route("/admin/games/<gid>/settings", methods=["POST"])
def admin_game_settings(gid):
    get_game_or_404(gid)
    with edit_catalog() as catalog:
        game = find_game(catalog, gid)
        updated = dict(game)
        errors = read_game_form(request.form, updated)
        if not errors:
            game.update(updated)
    for error in errors:
        flash(error, "error")
    if not errors:
        flash("Settings saved.", "success")
    return redirect(url_for("admin_game", gid=gid))


@admin_route("/admin/games/<gid>/move", methods=["POST"])
def admin_game_move(gid):
    step = -1 if request.form.get("direction") == "up" else 1
    with edit_catalog() as catalog:
        games = sorted_games(catalog)
        index = next((i for i, g in enumerate(games) if g["id"] == gid), None)
        if index is None:
            abort(404)
        other = index + step
        if 0 <= other < len(games):
            # Orders are renumbered 0..n on every save, so swapping is enough.
            games[index]["order"], games[other]["order"] = games[other]["order"], games[index]["order"]
    return back("admin_games")


@admin_route("/admin/games/<gid>/delete", methods=["POST"])
def admin_game_delete(gid):
    game = get_game_or_404(gid)
    if request.form.get("confirm", "").strip() != gid:
        flash(f"Type the game ID ({gid}) to confirm deleting it.", "error")
        return redirect(url_for("admin_game", gid=gid))
    with edit_catalog() as catalog:
        catalog["games"] = [g for g in catalog["games"] if g["id"] != gid]
    if request.form.get("delete_files") and os.path.isdir(game_dir(gid)):
        shutil.rmtree(game_dir(gid))
        flash(f"Deleted {game['title']} and all of its builds.", "success")
    else:
        flash(f"Removed {game['title']} from the launcher. Its builds are still on the server.", "success")
    return redirect(url_for("admin_games"))


@admin_route("/admin/games/<gid>/banner", methods=["POST"])
def admin_game_banner(gid):
    game = get_game_or_404(gid)
    file = request.files.get("file")
    ext = file.filename.rsplit(".", 1)[-1].lower() if file and "." in file.filename else ""
    if ext not in ASSET_KINDS["image"]:
        flash("Upload a PNG, JPG, GIF or BMP image.", "error")
        return redirect(url_for("admin_game", gid=gid))
    path = f"banners/{gid}.{ext}"
    os.makedirs(os.path.join(ASSET_DIR, "banners"), exist_ok=True)
    file.save(os.path.join(ASSET_DIR, path))
    with edit_catalog() as catalog:
        find_game(catalog, gid)["banner"] = path
    flash(f"New banner uploaded for {game['title']}. Launchers pick it up next time they start.", "success")
    return redirect(url_for("admin_game", gid=gid))


# Chunked uploads -------------------------------------------------------------
# The browser sends big zips in pieces (so they fit through Cloudflare), then submits
# the normal build form with the upload's ID instead of the file.

def upload_paths(upload_id):
    if not UPLOAD_ID_RE.match(upload_id or ""):
        abort(404, "Unknown upload")
    return os.path.join(UPLOAD_DIR, f"{upload_id}.part"), os.path.join(UPLOAD_DIR, f"{upload_id}.json")


def clean_stale_uploads():
    if not os.path.isdir(UPLOAD_DIR):
        return
    cutoff = time.time() - STALE_UPLOAD_SECONDS
    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)
        if os.path.getmtime(path) < cutoff:
            os.remove(path)


def upload_error(message, status):
    return jsonify(error=message), status


@admin_route("/admin/uploads", methods=["POST"])
def admin_upload_start():
    info = request.get_json(silent=True) or {}
    filename = str(info.get("filename", ""))
    size = info.get("size")
    if not filename.lower().endswith(".zip"):
        return upload_error("Builds must be .zip files.", 400)
    if not isinstance(size, int) or size <= 0:
        return upload_error("That file is empty.", 400)
    clean_stale_uploads()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    upload_id = secrets.token_hex(16)
    part, meta = upload_paths(upload_id)
    open(part, "wb").close()
    write_json(meta, {"filename": filename, "size": size, "started_at": now_iso()})
    return jsonify(id=upload_id, chunk_size=UPLOAD_CHUNK_SIZE, received=0)


@admin_route("/admin/uploads/<upload_id>", methods=["GET", "POST", "DELETE"])
def admin_upload_chunk(upload_id):
    part, meta_path = upload_paths(upload_id)
    meta = read_json(meta_path, None)
    if meta is None or not os.path.isfile(part):
        return upload_error("This upload expired. Start it again.", 404)
    received = os.path.getsize(part)

    if request.method == "DELETE":
        os.remove(part)
        os.remove(meta_path)
        return jsonify(ok=True)
    if request.method == "GET":
        return jsonify(received=received, size=meta["size"])

    # Pieces must arrive in order. After a dropped connection the browser asks how much
    # arrived and continues from there, so a mismatch just reports the right offset.
    offset = request.args.get("offset", type=int)
    if offset != received:
        return jsonify(received=received, size=meta["size"]), 409
    length = request.content_length or 0
    if length > UPLOAD_CHUNK_SIZE * 2 or received + length > meta["size"]:
        return upload_error("Upload piece is too big.", 413)
    with open(part, "ab") as f:
        shutil.copyfileobj(request.stream, f, 1024 * 1024)
    return jsonify(received=os.path.getsize(part), size=meta["size"])


@admin_route("/admin/games/<gid>/builds", methods=["POST"])
def admin_upload_build(gid):
    game = get_game_or_404(gid)
    branch = request.form.get("branch")
    file = request.files.get("file")
    upload_id = request.form.get("upload_id")
    upload = None
    if upload_id:
        part, meta_path = upload_paths(upload_id)
        upload = read_json(meta_path, None)
        if upload is None or not os.path.isfile(part):
            flash("The upload expired before it finished. Please upload the file again.", "error")
            return redirect(url_for("admin_game", gid=gid))
        if os.path.getsize(part) != upload["size"]:
            flash("The upload didn't finish. Please upload the file again.", "error")
            return redirect(url_for("admin_game", gid=gid))
    filename = upload["filename"] if upload else (file.filename if file else "")
    if branch not in BRANCHES:
        flash("Pick a branch to upload to.", "error")
    elif not filename:
        flash("Choose a .zip file to upload.", "error")
    elif not filename.lower().endswith(".zip"):
        flash("Builds must be .zip files.", "error")
    else:
        previous = active_version(game, branch)
        versions = list_versions(gid, branch)
        version = versions[0] + 1 if versions else 1
        folder = version_dir(gid, branch, version)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{gid}.zip")
        if upload:
            os.replace(part, path)
            os.remove(meta_path)
        else:
            file.save(path)
        if not zipfile.is_zipfile(path):
            shutil.rmtree(folder)
            flash("That file isn't a valid zip.", "error")
            return redirect(url_for("admin_game", gid=gid))
        write_json(os.path.join(folder, "meta.json"), {
            "uploaded_at": now_iso(),
            "notes": request.form.get("notes", "").strip()[:500],
            "original_filename": secure_filename(filename),
            "size": os.path.getsize(path),
            "sha256": file_sha256(path),
        })
        go_live = request.form.get("go_live") == "on" or previous is None
        with edit_catalog() as catalog:
            find_game(catalog, gid)["pinned"][branch] = None if go_live else previous
        if go_live:
            flash(f"Uploaded {branch} v{version}. It's live now.", "success")
        else:
            flash(f"Uploaded {branch} v{version}. Players stay on v{previous} until you make it live.", "success")
        warning = check_target_in_zip(game, path)
        if warning:
            flash(warning, "warning")
    return redirect(url_for("admin_game", gid=gid))


def get_build_or_404(gid, branch, version):
    game = get_game_or_404(gid)
    if branch not in BRANCHES or not build_zip(gid, branch, version):
        abort(404, "Build not found")
    return game


@admin_route("/admin/games/<gid>/pin", methods=["POST"])
def admin_pin_build(gid):
    get_game_or_404(gid)
    branch = request.form.get("branch")
    if branch not in BRANCHES:
        abort(400)
    version = request.form.get("version", type=int)
    latest = list_versions(gid, branch)[:1]
    with edit_catalog() as catalog:
        # Choosing the newest build means "follow latest", so later uploads go live as usual.
        find_game(catalog, gid)["pinned"][branch] = None if version is None or [version] == latest else version
    flash(f"Players on {branch} now get v{version}." if version else f"{branch.title()} now follows the newest build.", "success")
    return redirect(url_for("admin_game", gid=gid))


@admin_route("/admin/games/<gid>/builds/<branch>/<int:version>/download")
def admin_download_build(gid, branch, version):
    get_build_or_404(gid, branch, version)
    return send_file(build_zip(gid, branch, version), as_attachment=True, download_name=f"{gid}-{branch}-v{version}.zip")


@admin_route("/admin/games/<gid>/builds/<branch>/<int:version>/promote", methods=["POST"])
def admin_promote_build(gid, branch, version):
    get_build_or_404(gid, branch, version)
    if branch != "beta":
        abort(400, "Only beta builds can be promoted")
    source = build_info(gid, branch, version)
    stable = list_versions(gid, "stable")
    new_version = stable[0] + 1 if stable else 1
    folder = version_dir(gid, "stable", new_version)
    os.makedirs(folder, exist_ok=True)
    shutil.copy2(build_zip(gid, branch, version), os.path.join(folder, f"{gid}.zip"))
    write_json(os.path.join(folder, "meta.json"), {
        "uploaded_at": now_iso(),
        "notes": f"Promoted from beta v{version}." + (f" {source['notes']}" if source["notes"] else ""),
        "original_filename": source["filename"],
        "size": source["size"],
        "sha256": source["sha256"],
    })
    with edit_catalog() as catalog:
        find_game(catalog, gid)["pinned"]["stable"] = None
    flash(f"Beta v{version} is now live on stable as v{new_version}.", "success")
    return redirect(url_for("admin_game", gid=gid))


@admin_route("/admin/games/<gid>/builds/<branch>/<int:version>/delete", methods=["POST"])
def admin_delete_build(gid, branch, version):
    get_build_or_404(gid, branch, version)
    shutil.rmtree(version_dir(gid, branch, version))
    with edit_catalog() as catalog:
        game = find_game(catalog, gid)
        if game["pinned"][branch] == version:
            game["pinned"][branch] = None
    flash(f"Deleted {branch} v{version}.", "success")
    return redirect(url_for("admin_game", gid=gid))


# Assets --------------------------------------------------------------------

@admin_route("/admin/assets")
def admin_assets():
    assets = list_assets()
    catalog = load_catalog()
    used_by = {path: [label] for path, label in LAUNCHER_SLOTS}
    for game in catalog["games"]:
        if game["banner"]:
            used_by.setdefault(game["banner"], []).append(f"Banner for {game['title']}")
    slots = [{"path": path, "label": label, "override": assets.get(path), "builtin": bundled_asset_exists(path)}
             for path, label in LAUNCHER_SLOTS]
    folders = {}
    for path, info in assets.items():
        folder = path.rsplit("/", 1)[0] if "/" in path else ""
        folders.setdefault(folder, []).append({"path": path, "name": path.rsplit("/", 1)[-1], "kind": asset_kind(path),
                                               "used_by": used_by.get(path, []), "builtin": bundled_asset_exists(path), **info})
    folder_names = sorted(set(folders) | {"", "banners", "sounds", "font"})
    return render_template("assets.html", page="assets", slots=slots, folders=dict(sorted(folders.items())),
                           folder_names=folder_names, total=len(assets))


@admin_route("/admin/assets/builtin/<path:path>")
def admin_builtin_asset(path):
    path = clean_asset_path(path)
    if not path:
        abort(404)
    return send_from_directory(BUNDLED_ASSET_DIR, path)


@admin_route("/admin/assets/upload", methods=["POST"])
def admin_asset_upload():
    replace = request.form.get("replace", "").strip()
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if not files:
        flash("Choose at least one file.", "error")
        return back("admin_assets")
    saved = []
    if replace:
        path = clean_asset_path(replace)
        new_ext = files[0].filename.rsplit(".", 1)[-1].lower() if "." in files[0].filename else ""
        if not path:
            flash("That asset path isn't valid.", "error")
            return back("admin_assets")
        if len(files) != 1 or new_ext not in ASSET_KINDS[asset_kind(path)]:
            flash(f"Replace {path} with a single {asset_kind(path)} file.", "error")
            return back("admin_assets")
        targets = [(files[0], path)]
    else:
        folder = request.form.get("new_folder", "").strip() or request.form.get("folder", "").strip()
        folder = "/".join(secure_filename(part) for part in folder.replace("\\", "/").split("/") if secure_filename(part))
        targets = [(f, f"{folder}/{secure_filename(f.filename)}".strip("/")) for f in files]
    for file, path in targets:
        path = clean_asset_path(path)
        if not path:
            flash(f"Skipped {file.filename}: unsupported file type.", "warning")
            continue
        full = os.path.join(ASSET_DIR, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        file.save(full)
        saved.append(path)
    if saved:
        flash(f"Uploaded {', '.join(saved)}. Launchers download changes next time they start.", "success")
    return back("admin_assets")


@admin_route("/admin/assets/delete", methods=["POST"])
def admin_asset_delete():
    path = clean_asset_path(request.form.get("path", ""))
    full = os.path.join(ASSET_DIR, path) if path else None
    if not full or not os.path.isfile(full):
        flash("That asset doesn't exist.", "error")
        return back("admin_assets")
    os.remove(full)
    folder = os.path.dirname(full)
    while folder != ASSET_DIR and os.path.isdir(folder) and not os.listdir(folder):
        os.rmdir(folder)
        folder = os.path.dirname(folder)
    if bundled_asset_exists(path):
        flash(f"Deleted {path}. Launchers go back to the default version.", "success")
    else:
        flash(f"Deleted {path}.", "success")
    return back("admin_assets")


# Help -----------------------------------------------------------------------

@admin_route("/admin/help")
def admin_help():
    return render_template("help.html", page="help")


# Access --------------------------------------------------------------------

@admin_route("/admin/access")
def admin_access():
    return render_template("access.html", page="access", beta_key=beta_key_text(), username=ADMIN_USER)


@admin_route("/admin/access/betakey", methods=["POST"])
def admin_beta_key():
    if request.form.get("action") == "disable":
        if os.path.isfile(BETA_KEY_FILE):
            os.remove(BETA_KEY_FILE)
        flash("Beta disabled. Everyone is on stable now.", "success")
        return redirect(url_for("admin_access"))
    key = request.form.get("betakey", "").strip()
    if len(key) < 4:
        flash("Beta keys need at least 4 characters.", "error")
        return redirect(url_for("admin_access"))
    with open(BETA_KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key)
    flash("Beta key updated. Testers need to enter the new key in the launcher settings.", "success")
    return redirect(url_for("admin_access"))


if __name__ == '__main__':
    print(f"Serving data from {BASE_DIRECTORY}", file=sys.stdout)
    if not ADMIN_PASSWORD:
        print("COOLIN_ADMIN_PASSWORD isn't set, so the admin panel is disabled. See .env.example.", file=sys.stderr)
    app.run(host=HOST, port=PORT)
