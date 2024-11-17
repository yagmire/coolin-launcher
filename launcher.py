import pygame, os, sys, subprocess, requests, threading, zipfile, hashlib, urllib3, shutil, re, glob
from pymsgbox import alert
from time import sleep
from sys import exit
SCREEN_WIDTH, SCREEN_HEIGHT = 800, 600
SERVER = "http://localhost:2665/"

# OS RESOURCES 

def get_biggest_number_folder(path):
    folders = [f for f in os.listdir(path) if os.path.isdir(os.path.join(path, f))]
    folders = [f for f in folders if f.isdigit()]  # Filter for folders that are numbers
    if not folders:
        return None
    return max(folders, key=int)

def get_gzdoom():
    if os.path.exists(GZDOOM_EXEC):
        print("GZDOOM is already installed.")
        return
    repo_url = "https://api.github.com/repos/ZDoom/gzdoom/releases/latest"
    headers = {
        "Accept": "application/vnd.github.v3+json",
    }

    try:
        # Fetch the latest release information
        response = requests.get(repo_url, headers=headers)
        response.raise_for_status()
        release_data = response.json()

        # Find the desired asset
        assets = release_data.get("assets", [])
        pattern = re.compile(r"gzdoom-.*-windows\.zip")
        download_url = None

        for asset in assets:
            if pattern.match(asset["name"]):
                download_url = asset["browser_download_url"]
                break

        if not download_url:
            print("No matching GZDoom release found.")
            return

        # Download the file
        file_name = download_url.split("/")[-1]
        print(f"Downloading {file_name} from {download_url}...")

        with requests.get(download_url, stream=True) as download_response:
            download_response.raise_for_status()
            with open(file_name, "wb") as file:
                for chunk in download_response.iter_content(chunk_size=8192):
                    file.write(chunk)

        print(f"Downloaded {file_name} successfully!")
        for file in glob.glob("gzdoom-*-windows.zip"):
            GZDOOM_ZIP = file
        print(GZDOOM_ZIP)
        with zipfile.ZipFile(resource_path(GZDOOM_ZIP), 'r') as zip_ref:
            zip_ref.extractall(resource_path("gzdoom"))
        
        os.remove(GZDOOM_ZIP)

        doom2_wad_url = "https://raw.githubusercontent.com/Akbar30Bill/DOOM_wads/refs/heads/master/doom2.wad"
        
        response = requests.get(doom2_wad_url, stream=True)
        save_path = resource_path("gzdoom\\doom2.wad")
        if response.status_code == 200:
            with open(resource_path("gzdoom\\doom2.wad"), "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
            print(f"File downloaded successfully to {save_path}")
        else:
            print(f"Failed to download file. Status code: {response.status_code}")


    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")


def check_internet_conn():
    http = urllib3.PoolManager(timeout=3.0)
    r = http.request('GET', 'google.com', preload_content=False)
    code = r.status
    r.release_conn()
    if code == 200:
        return True
    else:
        return False

def get_beta_key_validity():
    if os.path.isfile(resource_path("betakey")):
        hasher = hashlib.sha512()
        with open('betakey', 'rb') as file:
            while True:
                chunk = file.read(4096)
                if not chunk:
                    break
                hasher.update(chunk)
        server_url = f"{SERVER}betakey"
        params = {
            'key': hasher.hexdigest()
        }
        response = requests.get(server_url, params=params)
        if response.text == "Valid":
            print("Beta key is valid")
            return True
        else:
            print("Beta key is invalid")
            return False
    else:
        return False

def resource_path(relative_path):
    try:
        base_path = os.path.dirname(__file__)
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def is_folder_empty(path):
    """Checks if a folder is empty."""
    if not os.path.exists(path):
        return False
    return not any(os.listdir(path))

GZDOOM_EXEC = resource_path("gzdoom/gzdoom.exe")
INTERNET_PRESENT = check_internet_conn()

# Initialize Pygame
pygame.init()
pygame.mixer.init()

# Music
play = pygame.mixer.Sound(resource_path("assets\\sounds\\play.wav"))
error = pygame.mixer.Sound(resource_path("assets\\sounds\\error.wav"))
select = pygame.mixer.Sound(resource_path("assets\\sounds\\select.wav"))
success = pygame.mixer.Sound(resource_path("assets\\sounds\\success.wav"))
music = pygame.mixer.music.load(resource_path("assets\\sounds\\sonic.wav"))

select.set_volume(0.4)
pygame.mixer.music.play(-1)

screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Coolin Launcher")

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (200, 200, 200)
BLUE = (100, 100, 255)

# Fonts
font = pygame.font.Font('assets/font/Pixeled.ttf', 12)
large_font = pygame.font.Font(None, 32)

# Backgrounds and images
background_image = pygame.image.load(resource_path("assets/bg.png")).convert()
downloading_assets = pygame.image.load(resource_path("assets/download-assets.png")).convert()
background_width, background_height = background_image.get_width(), background_image.get_height()

# Other UI Elements
game_titles = ["Coolin", "Coolin 16", "Coolin 3"]
banner_images = [
    pygame.image.load("assets/banners/og-drop.png").convert_alpha(),
    pygame.image.load("assets/banners/16-drop.png").convert_alpha(),
    pygame.image.load("assets/banners/3-drop.png").convert_alpha()
]
center_image = pygame.image.load(resource_path("assets/select.png")).convert_alpha()
center_image_width, center_image_height = center_image.get_width(), center_image.get_height() - 50

# Rescale images
banner_width, banner_height = 359, 478
banner_images = [pygame.transform.scale(img, (banner_width, banner_height)) for img in banner_images]
selected_game = 0
num_games = len(banner_images)
transition_speed = 20
target_offset = 0
current_offset = 0

# Additional UI Text
credit_text = font.render("Launcher by yagmire, Games and Graphics by DynamicDingo", True, BLACK)
beta_text = font.render("BETA MODE", True, (255,0,0))
clock = pygame.time.Clock()
running = True

VERSION = "stable"
KEY_ENROLLMENT = False
def get_version():
    global VERSION, loading, KEY_ENROLLMENT
    if get_beta_key_validity():
        VERSION = "beta"
        KEY_ENROLLMENT = True
    else:
        VERSION = "stable"
    loading = False

downloaded = False
def download_assets():
    global downloaded
    print("Downloading assets...")
    for game in params['game']:
        shutil.rmtree(f"{os.getcwd()}\\coolin\\{game}")
        os.mkdir(f"{os.getcwd()}\\coolin\\{game}")
        save_path = f"{os.getcwd()}\\coolin\\{game}\\{game}.zip"
        print(f"Downloading {game} {params['version']} assets...")
        print(VERSION)
        temp_params = {
            'game': game,
            'version': VERSION
        }
        response = requests.get(server_url, params=temp_params, stream=True)
        if response.status_code == 404:
            temp_params['version'] = "stable"
            print(temp_params)
            response = requests.get(server_url, params=temp_params, stream=True)
        elif response.status_code != 200:
            print(f"Failed to download file. Status code: {response.status_code}")
            alert(text=f"Failed to download file. Status code: {response.status_code}", title="Error", button="Ok")
            downloaded = True
            return
        downloaded_size = 0
        with open(save_path, 'wb') as file:
            for data in response.iter_content(chunk_size=1024):
                if data:
                    file.write(data)
                    downloaded_size += len(data)
        zipfile.ZipFile(save_path, 'r').extractall(f"{os.getcwd()}\\coolin\\{game}")
        print(f"Downloaded and unzipped {downloaded_size} bytes for {game}")
        os.remove(save_path)
        open(f'{os.getcwd()}\\coolin\\{game}\\{VERSION}.lock', 'a')
        
        latest_version = requests.get(f"{SERVER}get_latest_ver", params={'game': game, 'branch': f'{VERSION}'}).text
        open(f'{os.getcwd()}\\coolin\\{game}\\{VERSION}.lock', 'w').write(latest_version)
        
    get_gzdoom()
    pygame.mixer.Sound.play(success)
    downloaded = True

loading_text = font.render("Loading...", True, (255,255,255))
loading = True
version_got = False
while loading:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            loading = False
    screen.blit(loading_text, loading_text.get_rect(center=(SCREEN_WIDTH / 2, SCREEN_HEIGHT / 2)))
    screen.blit(credit_text, (10, SCREEN_HEIGHT - credit_text.get_height() - 10))
    pygame.display.flip()
    clock.tick(60)
    if INTERNET_PRESENT == False:
        alert(text="This app requires an active internet connection.", title="Error", button="Ok")
        exit()
    if not version_got:
        get_version()
        version_got = True
    
server_url = f"{SERVER}download"

params = {
    'game': ["16", "coolin"],
    'version': VERSION
}

for game in params['game']:
    if is_folder_empty(f"{os.getcwd()}\\coolin\\{game}"):
        downloaded = False
        threading.Thread(target=download_assets).start()
        break
    elif not is_folder_empty(f"{os.getcwd()}\\coolin\\{game}"):
        if os.path.isfile(f"{os.getcwd()}\\coolin\\{game}\\stable.lock") and VERSION == "stable":
            downloaded = True
            break
        elif os.path.isfile(f"{os.getcwd()}\\coolin\\{game}\\beta.lock") and VERSION == "beta":
            downloaded = True
            break
        elif os.path.isfile(f"{os.getcwd()}\\coolin\\{game}\\stable.lock") and VERSION != "stable":
            downloaded = False
            threading.Thread(target=download_assets).start()
            break
        elif os.path.isfile(f"{os.getcwd()}\\coolin\\{game}\\beta.lock") and VERSION != "beta":
            downloaded = False
            threading.Thread(target=download_assets).start()
            break
    else:
        downloaded = True

while downloaded == False and loading == False:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
    screen.blit(downloading_assets, (0,0))
    screen.blit(credit_text, (10, SCREEN_HEIGHT - credit_text.get_height() - 10))
    pygame.display.flip()
    # 60 FPS
    clock.tick(60)

# New: Settings Button and Menu
settings_button = pygame.Rect(SCREEN_WIDTH - 80, SCREEN_HEIGHT - 40, 70, 30)
settings_menu_open = False
input_box = pygame.Rect(300, 200, 200, 40)
color_inactive = GRAY
color_active = BLUE
color = color_inactive
active = False

if os.path.isfile(resource_path("betakey")):
    beta_key = open('betakey', 'r').read()
else:
    beta_key = ""

def save_beta_key(key):
    with open("betakey", "w") as file:
        file.write(key)

# Main loop
while running:
    screen.fill(WHITE)
    screen.blit(background_image, (0, 0))

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN and settings_menu_open == False:
            if event.key == pygame.K_RIGHT:
                pygame.mixer.Sound.play(select)
                if selected_game < num_games - 1:
                    selected_game += 1
                    target_offset -= SCREEN_WIDTH // 2
            elif event.key == pygame.K_LEFT:
                pygame.mixer.Sound.play(select)
                if selected_game > 0:
                    selected_game -= 1
                    target_offset += SCREEN_WIDTH // 2  
            elif event.key == pygame.K_RETURN:
                print(f"Launching: {game_titles[selected_game]}...")
                if game_titles[selected_game] == "Coolin 16":
                    pygame.mixer.Sound.play(play)
                    sleep(0.3)
                    subprocess.Popen([GZDOOM_EXEC, resource_path("coolin/16")])
                    running = False
                elif game_titles[selected_game] == "Coolin":
                    pygame.mixer.Sound.play(play)
                    sleep(0.3)
                    subprocess.Popen([GZDOOM_EXEC, resource_path("coolin/coolin/Coolin.wad")])
                    running = False
                elif game_titles[selected_game] == "Coolin 3":
                    pygame.mixer.Sound.play(error)
                    alert(text="Coolin 3 is still in development", title="Coolin 3", button="Ok")
                    break
                    subprocess.Popen([GZDOOM_EXEC, resource_path("coolin/3")])
                    running = False
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if settings_button.collidepoint(event.pos):
                settings_menu_open = not settings_menu_open
            if settings_menu_open:
                if input_box.collidepoint(event.pos):
                    active = True
                else:
                    active = False
                color = color_active if active else color_inactive
                # Close menu if "X" button is clicked
                close_button = pygame.Rect(500, 150, 30, 30)
                if close_button.collidepoint(event.pos):
                    settings_menu_open = False
        elif event.type == pygame.KEYDOWN and active:
            if event.key == pygame.K_RETURN:
                save_beta_key(beta_key)
                pygame.mixer.Sound.play(success)
                if os.path.isfile(resource_path("betakey")):
                    beta_key = open('betakey', 'r').read()
                else:
                    beta_key = ""

            elif event.key == pygame.K_BACKSPACE:
                beta_key = beta_key[:-1]
            else:
                beta_key += event.unicode

    if current_offset != target_offset:
        diff = target_offset - current_offset
        current_offset += transition_speed if diff > 0 else -transition_speed
        if abs(diff) < transition_speed:
            current_offset = target_offset

    # Draw UI Elements
    center_image_x = (SCREEN_WIDTH - center_image_width) // 2
    center_image_y = (SCREEN_HEIGHT // 2 - banner_height // 2) - center_image_height - 10
    screen.blit(center_image, (center_image_x, center_image_y))
    screen.blit(credit_text, (10, SCREEN_HEIGHT - credit_text.get_height() - 10))
    
    if VERSION == "beta": screen.blit(beta_text, (10, SCREEN_HEIGHT - credit_text.get_height() - 25))

    # Draw banners
    for i, banner in enumerate(banner_images):
        banner_x = (SCREEN_WIDTH // 2 - banner_width // 2) + (i * SCREEN_WIDTH // 2) + current_offset
        banner_y = SCREEN_HEIGHT // 2 - banner_height // 2
        screen.blit(banner, (banner_x, banner_y))
    
    # Draw Settings Button
    pygame.draw.rect(screen, GRAY, settings_button)
    settings_font = pygame.font.Font('assets/font/Pixeled.ttf', 9)
    screen.blit(settings_font.render("Settings", True, BLACK), (settings_button.x + 2, settings_button.y))

    # Draw Settings Menu
    if settings_menu_open:
        pygame.draw.rect(screen, WHITE, (250, 150, 300, 200))
        pygame.draw.rect(screen, BLACK, (250, 150, 300, 200), 2)
        screen.blit(large_font.render("Enter Beta Key", True, BLACK), (300, 170))

        screen.blit(font.render(f"Branch: {VERSION}", True, BLACK), (300, 300))

        # Draw input box
        txt_surface = large_font.render(beta_key, True, BLACK)
        width = max(200, txt_surface.get_width() + 10)
        input_box.w = width
        screen.blit(txt_surface, (input_box.x + 5, input_box.y + 5))
        pygame.draw.rect(screen, color, input_box, 2)

        # Draw "X" button
        close_button = pygame.Rect(500, 150, 30, 30)
        pygame.draw.rect(screen, BLACK, close_button)
        screen.blit(large_font.render("X", True, WHITE), (507, 155))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()
