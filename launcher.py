import glob, hashlib, json, os, re, shutil, subprocess, sys, threading, webbrowser, zipfile
from time import sleep

import pygame, requests
from dotenv import load_dotenv
from pymsgbox import alert

SCREEN_WIDTH, SCREEN_HEIGHT = 800, 600
TIMEOUT = 15

# Game types this launcher knows how to start. Anything else in the catalog needs a newer launcher.
SUPPORTED_TYPES = ("doom", "exe", "java", "flash", "url", "extras")

# Everything the launcher downloads lives next to it. It ships with no graphics or sounds:
# all of them come from the server and are checked for updates on every start.
APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
GAMES_DIR = os.path.join(APP_DIR, "coolin")
ASSET_CACHE_DIR = os.path.join(APP_DIR, "asset_cache")
RUNTIME_DIR = os.path.join(APP_DIR, "runtimes")
GZDOOM_DIR = os.path.join(APP_DIR, "gzdoom")
CATALOG_CACHE = os.path.join(APP_DIR, "catalog.json")
BETA_KEY_FILE = os.path.join(APP_DIR, "betakey")
INTRO_LOCK = os.path.join(APP_DIR, "intro.lock")

# Settings: real environment variables, then a .env next to the launcher, then one bundled into the build.
load_dotenv(os.path.join(APP_DIR, ".env"))
load_dotenv(os.path.join(BUNDLE_DIR, ".env"))
SERVER = os.environ.get("COOLIN_SERVER", "http://localhost:2665/").rstrip("/") + "/"
JAVA_EXE = "javaw.exe" if os.name == "nt" else "java"
RUFFLE_EXE = "ruffle.exe" if os.name == "nt" else "ruffle"
ASSET_PATH_RE = re.compile(r"^(?:[A-Za-z0-9_-][A-Za-z0-9_.-]*/)*[A-Za-z0-9_-][A-Za-z0-9_.-]*\.[A-Za-z0-9]+$")

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (200, 200, 200)
BLUE = (100, 100, 255)
RED = (255, 0, 0)

# OS RESOURCES

def asset_path(relative_path):
    """Where a downloaded asset lives. It may not exist yet on the very first start."""
    return os.path.join(ASSET_CACHE_DIR, *relative_path.split("/"))

def file_sha256(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def path_inside(base, relative):
    """Joins a path from the server onto `base`, refusing anything that escapes it."""
    base = os.path.normpath(base)
    path = os.path.normpath(os.path.join(base, relative))
    if os.path.commonpath([base, path]) != base:
        raise RuntimeError(f"Invalid path from server: {relative}")
    return path

# SERVER

def beta_key_hash():
    try:
        with open(BETA_KEY_FILE, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return hashlib.sha512(data).hexdigest() if data else None

def key_params():
    key = beta_key_hash()
    return {"key": key} if key else {}

def fetch_catalog():
    response = requests.get(f"{SERVER}api/catalog", params=key_params(), timeout=TIMEOUT)
    response.raise_for_status()
    catalog = response.json()
    write_json(CATALOG_CACHE, catalog)
    return catalog

def download_file(url, dest, task, label, params=None, expected_sha256=None):
    tmp = dest + ".part"
    hasher = hashlib.sha256()
    with requests.get(url, params=params, stream=True, timeout=TIMEOUT) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0)
        done = 0
        with open(tmp, "wb") as f:
            for chunk in response.iter_content(chunk_size=256 * 1024):
                f.write(chunk)
                hasher.update(chunk)
                done += len(chunk)
                if total:
                    task.update(f"{label} {done / 1e6:.1f}/{total / 1e6:.1f} MB", done / total)
                else:
                    task.update(f"{label} {done / 1e6:.1f} MB", None)
    if expected_sha256 and hasher.hexdigest() != expected_sha256:
        os.remove(tmp)
        raise RuntimeError(f"{label} failed: the file was corrupted. Try again.")
    os.replace(tmp, dest)

def extract_zip(zip_path, dest, task, label):
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.infolist()
        for i, member in enumerate(members):
            zf.extract(member, dest)
            task.update(label, (i + 1) / max(len(members), 1))

def sync_assets(task):
    """Makes the local assets match the server's exactly: downloads every file that's missing
    or different (checked by hash) and deletes anything the server no longer has.
    Returns True if anything changed."""
    task.update("Checking graphics & sounds...", None)
    response = requests.get(f"{SERVER}api/assets/manifest", timeout=TIMEOUT)
    response.raise_for_status()
    files = {p: f for p, f in response.json().get("files", {}).items() if ASSET_PATH_RE.match(p) and ".." not in p}

    changed = False
    to_download = []
    for i, (path, info) in enumerate(files.items()):
        task.update("Checking graphics & sounds...", (i + 1) / max(len(files), 1))
        cached = asset_path(path)
        if not (os.path.isfile(cached) and file_sha256(cached) == info["sha256"]):
            to_download.append(path)

    # Remove files the server doesn't have (and leftover partial downloads).
    if os.path.isdir(ASSET_CACHE_DIR):
        for root, _dirs, names in os.walk(ASSET_CACHE_DIR):
            for name in names:
                rel = os.path.relpath(os.path.join(root, name), ASSET_CACHE_DIR).replace(os.sep, "/")
                if rel not in files:
                    os.remove(os.path.join(root, name))
                    changed = True

    for i, path in enumerate(to_download):
        dest = asset_path(path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        download_file(f"{SERVER}api/assets/{path}", dest, task, f"Downloading graphics & sounds ({i + 1}/{len(to_download)})",
                      expected_sha256=files[path]["sha256"])
        changed = True
    return changed

def assets_missing():
    return not os.path.isdir(ASSET_CACHE_DIR) or not any(files for _root, _dirs, files in os.walk(ASSET_CACHE_DIR))

# GAMES

def install_dir(game):
    return path_inside(GAMES_DIR, game["id"])

def installed_build(game):
    folder = install_dir(game)
    info = read_json(os.path.join(folder, ".install.json"))
    if info:
        return info
    # Installs from older launchers only left a <branch>.lock file with the version in it.
    for branch in ("beta", "stable"):
        lock = os.path.join(folder, f"{branch}.lock")
        if os.path.isfile(lock):
            with open(lock, "r") as f:
                version = f.read().strip()
            return {"branch": branch, "version": int(version) if version.isdigit() else 0}
    return None

def needs_update(game):
    build = game.get("build")
    installed = installed_build(game)
    if not build or not installed:
        return False
    return installed.get("version") != build["version"] or installed.get("branch") != build["branch"]

def install_game(game, task):
    build = game["build"]
    title = game["title"]
    os.makedirs(GAMES_DIR, exist_ok=True)
    zip_path = os.path.join(GAMES_DIR, f"{game['id']}.zip")
    params = {"branch": build["branch"], "version": build["version"], **key_params()}
    download_file(f"{SERVER}api/games/{game['id']}/download", zip_path, task, f"Downloading {title}",
                  params=params, expected_sha256=build.get("sha256"))

    dest = install_dir(game)
    if game["type"] in ("doom", "flash") or not os.path.isdir(dest):
        # Clean install so removed files don't linger. (Doom and Flash saves live outside the game folder.)
        staging = dest + ".new"
        shutil.rmtree(staging, ignore_errors=True)
        extract_zip(zip_path, staging, task, f"Installing {title}...")
        shutil.rmtree(dest, ignore_errors=True)
        os.replace(staging, dest)
    else:
        # Programs may keep saves and settings in their folder, so update in place.
        extract_zip(zip_path, dest, task, f"Updating {title}...")
    os.remove(zip_path)

    for branch in ("stable", "beta"):
        lock = os.path.join(dest, f"{branch}.lock")
        if os.path.isfile(lock):
            os.remove(lock)
    write_json(os.path.join(dest, ".install.json"), {"branch": build["branch"], "version": build["version"]})

def update_installed_games(task):
    errors = []
    for game in [g for g in GAMES if needs_update(g)]:
        try:
            install_game(game, task)
        except Exception as e:
            errors.append(f"{game['title']}: {e}")
    if errors:
        raise RuntimeError("Some games couldn't be updated:\n" + "\n".join(errors))

# RUNTIMES

def find_gzdoom():
    for path in [os.path.join(GZDOOM_DIR, "gzdoom.exe"), *glob.glob(os.path.join(GZDOOM_DIR, "*", "gzdoom.exe"))]:
        if os.path.isfile(path):
            return path
    return None

def install_gzdoom(task):
    task.update("Finding the latest GZDoom...", None)
    response = requests.get("https://api.github.com/repos/ZDoom/gzdoom/releases/latest",
                            headers={"Accept": "application/vnd.github.v3+json"}, timeout=TIMEOUT)
    response.raise_for_status()
    pattern = re.compile(r"gzdoom-.*-windows\.zip")
    download_url = next((a["browser_download_url"] for a in response.json().get("assets", []) if pattern.match(a["name"])), None)
    if not download_url:
        raise RuntimeError("Couldn't find a GZDoom download.")

    os.makedirs(GZDOOM_DIR, exist_ok=True)
    zip_path = os.path.join(GZDOOM_DIR, "gzdoom.zip")
    download_file(download_url, zip_path, task, "Downloading GZDoom")
    extract_zip(zip_path, GZDOOM_DIR, task, "Installing GZDoom...")
    os.remove(zip_path)

    doom2_wad_url = "https://raw.githubusercontent.com/Akbar30Bill/DOOM_wads/refs/heads/master/doom2.wad"
    download_file(doom2_wad_url, os.path.join(os.path.dirname(find_gzdoom()), "doom2.wad"), task, "Downloading doom2.wad")

def find_java(game):
    # A Java runtime shipped inside the game's zip wins.
    for folder in ("jre", "runtime", "java"):
        path = os.path.join(install_dir(game), folder, "bin", JAVA_EXE)
        if os.path.isfile(path):
            return path
    runtime = os.path.join(RUNTIME_DIR, f"java-{game.get('java_version', 21)}")
    found = glob.glob(os.path.join(runtime, "*", "bin", JAVA_EXE)) + glob.glob(os.path.join(runtime, "bin", JAVA_EXE))
    return found[0] if found else None

def install_java(game, task):
    version = int(game.get("java_version", 21))
    if os.name != "nt":
        raise RuntimeError(f"Please install Java {version}.")
    runtime = os.path.join(RUNTIME_DIR, f"java-{version}")
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    zip_path = runtime + ".zip"
    url = f"https://api.adoptium.net/v3/binary/latest/{version}/ga/windows/x64/jre/hotspot/normal/eclipse"
    download_file(url, zip_path, task, f"Downloading Java {version}")
    shutil.rmtree(runtime, ignore_errors=True)
    extract_zip(zip_path, runtime, task, f"Installing Java {version}...")
    os.remove(zip_path)

def find_ruffle():
    path = os.path.join(RUNTIME_DIR, "ruffle", RUFFLE_EXE)
    return path if os.path.isfile(path) else shutil.which("ruffle")

def install_ruffle(task):
    """Installs Ruffle, the open-source Flash Player replacement, from its GitHub releases."""
    if os.name != "nt":
        raise RuntimeError("Please install Ruffle (ruffle.rs) to play Flash games.")
    task.update("Finding the latest Ruffle...", None)
    pattern = re.compile(r"ruffle-.*-windows-x86_64\.zip")
    headers = {"Accept": "application/vnd.github.v3+json"}
    download_url = None
    # Prefer the latest stable release; fall back to the newest nightly if it has no Windows build.
    for url in ("https://api.github.com/repos/ruffle-rs/ruffle/releases/latest",
                "https://api.github.com/repos/ruffle-rs/ruffle/releases?per_page=1"):
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
        release = response.json()
        release = release[0] if isinstance(release, list) and release else release
        download_url = next((a["browser_download_url"] for a in release.get("assets", []) if pattern.match(a["name"])), None)
        if download_url:
            break
    if not download_url:
        raise RuntimeError("Couldn't find a Ruffle download.")

    folder = os.path.join(RUNTIME_DIR, "ruffle")
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    zip_path = folder + ".zip"
    download_file(download_url, zip_path, task, "Downloading Ruffle (Flash Player)")
    shutil.rmtree(folder, ignore_errors=True)
    extract_zip(zip_path, folder, task, "Installing Ruffle...")
    os.remove(zip_path)

def build_command(game):
    """Returns (command, working directory) for a game that's installed."""
    folder = install_dir(game)
    target = game.get("target") or ""
    args = list(game.get("args") or [])
    if game["type"] == "doom":
        gzdoom = find_gzdoom()
        command = [gzdoom]
        if game.get("iwad"):
            command += ["-iwad", game["iwad"]]
        return command + [path_inside(folder, target) if target else folder] + args, os.path.dirname(gzdoom)
    path = path_inside(folder, target)
    if not os.path.exists(path):
        raise RuntimeError(f"{game['title']} is missing {target}. Try again after the next update.")
    if game["type"] == "exe":
        return [path] + args, os.path.dirname(path)
    if game["type"] == "java":
        java = find_java(game) or shutil.which(JAVA_EXE) or shutil.which("java")
        return [java] + list(game.get("jvm_args") or []) + ["-jar", path] + args, os.path.dirname(path)
    if game["type"] == "flash":
        # Ruffle options go before the movie; relative loads resolve from the SWF's folder.
        return [find_ruffle()] + args + [path], os.path.dirname(path)
    raise RuntimeError(f"Don't know how to start {game['title']}.")

# TASKS

class Task:
    """Work running on a background thread while the main thread draws its progress."""
    def __init__(self, title):
        self.title = title
        self.status = title
        self.progress = None
        self.error = None
        self.result = None

    def update(self, status, progress=None):
        self.status = status
        self.progress = progress

def run_task(title, work, background=None):
    task = Task(title)

    def runner():
        try:
            task.result = work(task)
        except Exception as e:
            print(f"{title} failed: {e}")
            task.error = e

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    while thread.is_alive():
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
        draw_progress(task, background)
        pygame.display.flip()
        clock.tick(30)
    return task

def draw_progress(task, background):
    if background:
        screen.blit(background, (0, 0))
    else:
        screen.fill(BLACK)
    panel = pygame.Surface((SCREEN_WIDTH - 160, 90), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 180))
    panel_y = SCREEN_HEIGHT - 170
    screen.blit(panel, (80, panel_y))
    text = font.render(task.status, True, WHITE)
    screen.blit(text, text.get_rect(center=(SCREEN_WIDTH / 2, panel_y + 28)))

    bar = pygame.Rect(110, panel_y + 55, SCREEN_WIDTH - 220, 14)
    pygame.draw.rect(screen, GRAY, bar, 1)
    if task.progress is not None:
        pygame.draw.rect(screen, WHITE, (bar.x + 2, bar.y + 2, int((bar.w - 4) * task.progress), bar.h - 4))
    else:
        # Unknown length: bounce a block back and forth.
        block = bar.w // 5
        span = bar.w - 4 - block
        t = (pygame.time.get_ticks() // 4) % (span * 2)
        x = t if t < span else span * 2 - t
        pygame.draw.rect(screen, WHITE, (bar.x + 2 + x, bar.y + 2, block, bar.h - 4))
    screen.blit(credit_text, (10, SCREEN_HEIGHT - credit_text.get_height() - 10))

# ASSETS

# Missing assets (before the first download, or removed on the server) load as None and are skipped.

def load_image(relative_path, alpha=True):
    try:
        image = pygame.image.load(asset_path(relative_path))
        return image.convert_alpha() if alpha else image.convert()
    except (pygame.error, OSError):
        return None

def load_sound(relative_path):
    try:
        return pygame.mixer.Sound(asset_path(relative_path))
    except (pygame.error, OSError):
        return None

def load_font(relative_path, size):
    try:
        return pygame.font.Font(asset_path(relative_path), size)
    except (pygame.error, OSError):
        # pygame's built-in font renders smaller, so scale it up to roughly match.
        return pygame.font.Font(None, int(size * 2))

def play(sound):
    if sound:
        sound.play()

def load_assets():
    global font, settings_font, credit_text, beta_text, offline_text
    global background_image, downloading_assets, intro, center_image, holder_banner
    global play_sound, error_sound, select_sound, success_sound, gummibar

    font = load_font("font/Pixeled.ttf", 12)
    settings_font = load_font("font/Pixeled.ttf", 9)
    credit_text = font.render("Launcher by yagmire, Games and Graphics by DynamicDingo", True, BLACK)
    beta_text = font.render("BETA MODE", True, RED)
    offline_text = font.render("OFFLINE", True, RED)

    background_image = load_image("bg.png", alpha=False)
    downloading_assets = load_image("download-assets.png", alpha=False)
    intro = load_image("intro.png")
    center_image = load_image("select.png")
    holder_banner = load_image("banners/holder-drop.png")

    play_sound = load_sound("sounds/play.wav")
    error_sound = load_sound("sounds/error.wav")
    select_sound = load_sound("sounds/select.wav")
    success_sound = load_sound("sounds/success.wav")
    gummibar = load_sound("sounds/extras.wav")
    if select_sound:
        select_sound.set_volume(0.4)
    if gummibar:
        gummibar.set_volume(0.5)

    icon = load_image("rock.png")
    if icon:
        pygame.display.set_icon(icon)

def start_music():
    try:
        pygame.mixer.music.load(asset_path("sounds/sonic.wav"))
        pygame.mixer.music.play(-1)
    except (pygame.error, OSError) as e:
        print(f"Couldn't play music: {e}")

def placeholder_banner(title):
    """The holder banner with the game's name on a band across the middle (covering the holder's own text)."""
    image = holder_banner.copy() if holder_banner else pygame.Surface((banner_width, banner_height))
    image = pygame.transform.scale(image, (banner_width, banner_height))
    lines, line = [], ""
    for word in title.split():
        if line and large_font.size(f"{line} {word}")[0] > 200:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    lines.append(line)
    rendered = [large_font.render(text, True, WHITE) for text in lines]
    height = sum(r.get_height() for r in rendered) + 30
    band = pygame.Surface((226, height))
    band.fill((20, 20, 40))
    image.blit(band, band.get_rect(center=(banner_width / 2, banner_height / 2)))
    y = banner_height / 2 - height / 2 + 15
    for r in rendered:
        image.blit(r, r.get_rect(midtop=(banner_width / 2, y)))
        y += r.get_height()
    return image

def build_banners():
    banners = []
    for game in GAMES:
        image = load_image(game["banner"]) if game.get("banner") else None
        if image is None:
            image = placeholder_banner(game["title"])
        banners.append(pygame.transform.scale(image, (banner_width, banner_height)))
    return banners

# CATALOG

def apply_catalog(catalog):
    global GAMES, VERSION
    VERSION = catalog.get("branch", "stable")
    GAMES = [g for g in catalog.get("games", []) if g.get("id") and g.get("title")]
    status_cache.clear()

status_cache = {}

def game_status(game):
    """Short line shown for the selected game. Cached because it reads install info from disk."""
    if game["id"] not in status_cache:
        status_cache[game["id"]] = _game_status(game)
    return status_cache[game["id"]]

def _game_status(game):
    if game["status"] == "coming_soon":
        return "COMING SOON"
    if game["type"] not in SUPPORTED_TYPES:
        return "UPDATE THE LAUNCHER TO PLAY"
    if game["type"] == "url":
        return "OPENS IN YOUR BROWSER"
    if game["type"] == "extras":
        return ""
    installed = installed_build(game)
    if not installed:
        if OFFLINE:
            return "CONNECT TO THE INTERNET TO INSTALL"
        if not game.get("build"):
            return "NOT AVAILABLE YET"
        size = game["build"]["size"] / 1e6
        return f"PRESS ENTER TO INSTALL ({size:.0f} MB)" if size >= 1 else "PRESS ENTER TO INSTALL (<1 MB)"
    if needs_update(game) and not OFFLINE:
        return "UPDATE AVAILABLE"
    return ""

def launch_game(game):
    """Returns "extras" to open the extras screen, "quit" if a game started, or None to stay in the menu."""
    title = game["title"]
    if game["status"] == "coming_soon":
        play(error_sound)
        alert(text=game.get("message") or f"{title} is coming soon!", title=title, button="Ok")
        return None
    if game["type"] not in SUPPORTED_TYPES:
        play(error_sound)
        alert(text=f"This version of the launcher can't play {title}. Download the latest launcher.", title=title, button="Ok")
        return None
    if game["type"] == "extras":
        return "extras"
    if game["type"] == "url":
        play(play_sound)
        webbrowser.open(game["target"])
        return None

    installed = installed_build(game)
    if not OFFLINE and game.get("build") and (not installed or needs_update(game)):
        task = run_task(f"Installing {title}", lambda task: install_game(game, task), downloading_assets)
        if task.error:
            play(error_sound)
            alert(text=f"Couldn't install {title}:\n{task.error}", title="Error", button="Ok")
            return None
        play(success_sound)
    elif not installed:
        play(error_sound)
        message = "Connect to the internet to install it." if OFFLINE else "It isn't available yet."
        alert(text=f"{title} isn't installed. {message}", title=title, button="Ok")
        return None

    runtime = None
    if game["type"] == "doom" and not find_gzdoom():
        runtime = ("GZDoom", install_gzdoom)
    elif game["type"] == "java" and not find_java(game):
        runtime = (f"Java {game.get('java_version', 21)}", lambda task: install_java(game, task))
    elif game["type"] == "flash" and not find_ruffle():
        runtime = ("Ruffle", install_ruffle)
    if runtime:
        name, work = runtime
        task = run_task(f"Installing {name}", work, downloading_assets)
        if task.error and not (game["type"] == "java" and (shutil.which(JAVA_EXE) or shutil.which("java"))):
            play(error_sound)
            alert(text=f"Couldn't install {name}:\n{task.error}", title="Error", button="Ok")
            return None

    try:
        command, cwd = build_command(game)
        print(f"Launching {title}: {command}")
        play(play_sound)
        sleep(0.3)
        subprocess.Popen(command, cwd=cwd)
    except Exception as e:
        play(error_sound)
        alert(text=f"Couldn't start {title}:\n{e}", title="Error", button="Ok")
        return None
    return "quit"

# Initialize Pygame
pygame.init()
pygame.mixer.init()

screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Coolin Launcher")
clock = pygame.time.Clock()
large_font = pygame.font.Font(None, 32)
banner_width, banner_height = 359, 478

load_assets()

GAMES = []
VERSION = "stable"
OFFLINE = False

loading = run_task("Loading...", lambda task: fetch_catalog())
if loading.error:
    cached = read_json(CATALOG_CACHE)
    if not cached:
        alert(text="This app requires an active internet connection.", title="Error", button="Ok")
        sys.exit()
    OFFLINE = True
    apply_catalog(cached)
else:
    apply_catalog(loading.result)
    assets = run_task("Loading...", sync_assets)
    if assets.error:
        print(f"Asset sync failed: {assets.error}")
        if assets_missing():
            alert(text=f"Couldn't download the launcher's graphics and sounds:\n{assets.error}", title="Error", button="Ok")
    elif assets.result:
        load_assets()
    updates = run_task("Updating games", update_installed_games, downloading_assets)
    if updates.error:
        play(error_sound)
        alert(text=str(updates.error), title="Error", button="Ok")

start_music()

INTRO_PLAYED = os.path.isfile(INTRO_LOCK) or intro is None
while not INTRO_PLAYED:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        if event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
            INTRO_PLAYED = True
            open(INTRO_LOCK, 'a').close()
    screen.blit(intro, (0, 0))
    screen.blit(credit_text, (10, SCREEN_HEIGHT - credit_text.get_height() - 10))
    pygame.display.flip()
    clock.tick(60)

# Carousel
banner_images = build_banners()
selected_game = 0
transition_speed = 20
target_offset = 0
current_offset = 0

# Settings Button and Menu
settings_button = pygame.Rect(SCREEN_WIDTH - 80, SCREEN_HEIGHT - 40, 70, 30)
close_button = pygame.Rect(500, 150, 30, 30)
settings_menu_open = False
input_box = pygame.Rect(300, 200, 200, 40)
color_inactive = GRAY
color_active = BLUE
color = color_inactive
active = False

beta_key = ""
if os.path.isfile(BETA_KEY_FILE):
    with open(BETA_KEY_FILE, 'r') as f:
        beta_key = f.read()

def save_beta_key(key):
    with open(BETA_KEY_FILE, "w") as file:
        file.write(key)

def reload_catalog():
    """Re-fetches the catalog (e.g. after a new beta key) and rebuilds the carousel."""
    global banner_images, selected_game, target_offset, current_offset
    task = run_task("Checking beta key...", lambda task: fetch_catalog())
    if task.error:
        return False
    apply_catalog(task.result)
    banner_images = build_banners()
    selected_game = target_offset = current_offset = 0
    return True

# Extras
def cutscene_render(pattern):
    screen.fill(BLACK)
    screen.blit(large_font.render("Cutscenes", True, WHITE), (0, 0))
    y = 20
    for scene in sorted(glob.glob(os.path.join(GAMES_DIR, pattern))):
        screen.blit(large_font.render(os.path.basename(scene), True, WHITE), (20, y))
        y += 20
    hint = large_font.render("Press Esc to go back", True, GRAY)
    screen.blit(hint, (10, SCREEN_HEIGHT - hint.get_height() - 10))

def draw_menu():
    screen.fill(WHITE)
    if background_image:
        screen.blit(background_image, (0, 0))

    banner_y = SCREEN_HEIGHT // 2 - banner_height // 2
    if center_image:
        center_image_x = (SCREEN_WIDTH - center_image.get_width()) // 2
        center_image_y = banner_y - (center_image.get_height() - 50) - 10
        screen.blit(center_image, (center_image_x, center_image_y))
    screen.blit(credit_text, (10, SCREEN_HEIGHT - credit_text.get_height() - 10))
    if OFFLINE:
        screen.blit(offline_text, (10, SCREEN_HEIGHT - credit_text.get_height() - 25))
    elif VERSION == "beta":
        screen.blit(beta_text, (10, SCREEN_HEIGHT - credit_text.get_height() - 25))

    for i, banner in enumerate(banner_images):
        banner_x = (SCREEN_WIDTH // 2 - banner_width // 2) + (i * SCREEN_WIDTH // 2) + current_offset
        screen.blit(banner, (banner_x, banner_y))

    if GAMES:
        status = game_status(GAMES[selected_game])
        if status:
            # Wrapped to stay left of the header graphic at the top of the screen.
            lines, line = [], ""
            for word in status.split():
                if line and settings_font.size(f"{line} {word}")[0] > 170:
                    lines.append(line)
                    line = word
                else:
                    line = f"{line} {word}".strip()
            lines.append(line)
            rendered = [settings_font.render(text, True, WHITE) for text in lines]
            pill = pygame.Surface((max(r.get_width() for r in rendered) + 16, sum(r.get_height() for r in rendered) + 6), pygame.SRCALPHA)
            pill.fill((0, 0, 0, 190))
            screen.blit(pill, (10, 10))
            y = 13
            for r in rendered:
                screen.blit(r, (18, y))
                y += r.get_height()
    else:
        message = font.render("No games available right now.", True, BLACK)
        screen.blit(message, message.get_rect(center=(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)))

    # Settings Button
    pygame.draw.rect(screen, GRAY, settings_button)
    screen.blit(settings_font.render("Settings", True, BLACK), (settings_button.x + 2, settings_button.y))

    # Settings Menu
    if settings_menu_open:
        pygame.draw.rect(screen, WHITE, (250, 150, 300, 200))
        pygame.draw.rect(screen, BLACK, (250, 150, 300, 200), 2)
        screen.blit(large_font.render("Enter Beta Key", True, BLACK), (300, 170))
        screen.blit(settings_font.render("Press Enter to save", True, GRAY), (300, 245))
        screen.blit(font.render(f"Branch: {VERSION}", True, BLACK), (300, 300))

        txt_surface = large_font.render(beta_key, True, BLACK)
        input_box.w = max(200, txt_surface.get_width() + 10)
        screen.blit(txt_surface, (input_box.x + 5, input_box.y + 5))
        pygame.draw.rect(screen, color, input_box, 2)

        pygame.draw.rect(screen, BLACK, close_button)
        screen.blit(large_font.render("X", True, WHITE), (507, 155))

# Main loop
state = "menu"
extras_pattern = ""
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        elif state == "extras":
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                state = "menu"

        elif event.type == pygame.KEYDOWN and not settings_menu_open and GAMES:
            if event.key == pygame.K_RIGHT:
                play(select_sound)
                if selected_game < len(GAMES) - 1:
                    selected_game += 1
                    target_offset -= SCREEN_WIDTH // 2
            elif event.key == pygame.K_LEFT:
                play(select_sound)
                if selected_game > 0:
                    selected_game -= 1
                    target_offset += SCREEN_WIDTH // 2
            elif event.key == pygame.K_RETURN:
                game = GAMES[selected_game]
                print(f"Launching: {game['title']}...")
                if game["type"] == "extras" and pygame.key.get_mods() & pygame.KMOD_SHIFT:
                    play(gummibar)
                result = launch_game(game)
                status_cache.clear()
                if result == "extras":
                    state = "extras"
                    extras_pattern = game.get("target") or ""
                elif result == "quit":
                    running = False

        elif event.type == pygame.MOUSEBUTTONDOWN:
            if settings_button.collidepoint(event.pos):
                settings_menu_open = not settings_menu_open
            if settings_menu_open:
                active = input_box.collidepoint(event.pos)
                color = color_active if active else color_inactive
                if close_button.collidepoint(event.pos):
                    settings_menu_open = False

        elif event.type == pygame.KEYDOWN and settings_menu_open:
            if event.key == pygame.K_ESCAPE:
                settings_menu_open = False
            elif not active:
                pass
            elif event.key == pygame.K_RETURN:
                save_beta_key(beta_key)
                was_beta = VERSION == "beta"
                if OFFLINE or not reload_catalog():
                    play(success_sound)
                    alert(text="Beta key saved. Restart the launcher while online to use it.", title="Success", button="Ok")
                elif VERSION == "beta":
                    play(success_sound)
                    if not was_beta:
                        alert(text="Beta key accepted! You're on the beta branch now.", title="Success", button="Ok")
                else:
                    play(error_sound)
                    alert(text="That beta key isn't valid. You're on the stable branch.", title="Beta", button="Ok")
            elif event.key == pygame.K_BACKSPACE:
                beta_key = beta_key[:-1]
            else:
                beta_key += event.unicode

    if current_offset != target_offset:
        diff = target_offset - current_offset
        current_offset += transition_speed if diff > 0 else -transition_speed
        if abs(diff) < transition_speed:
            current_offset = target_offset

    if state == "extras":
        cutscene_render(extras_pattern)
    else:
        draw_menu()

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()
