import pygame, os, sys, subprocess, requests, threading
from pymsgbox import alert
from time import sleep
SCREEN_WIDTH, SCREEN_HEIGHT = 800, 600

versions = {
    "3": "latest",
    "16": "latest",
    "coolin": "latest"
}


def resource_path(relative_path):
    try:
        base_path = os.path.dirname(__file__)
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

GZDOOM_EXEC = resource_path("gzdoom/gzdoom.exe")

pygame.init()
pygame.mixer.init()

# music
play = pygame.mixer.Sound(resource_path("assets\\sounds\\play.wav"))
error = pygame.mixer.Sound(resource_path("assets\\sounds\\error.wav"))
select = pygame.mixer.Sound(resource_path("assets\\sounds\\select.wav"))

music = pygame.mixer.music.load(resource_path("assets\\sounds\\sonic.wav"))
pygame.mixer.music.play(-1)


screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("Coolin Launcher")

# Colors
WHITE = (255, 255, 255)

background_image = pygame.image.load(resource_path("assets/bg.png")).convert()
window_bg = pygame.image.load(resource_path("assets/basic-window.png")).convert()
background_width, background_height = background_image.get_width(), background_image.get_height()

game_titles = [
    "Coolin",
    "Coolin 16",
    "Coolin 3"
]

banner_images = [
    pygame.image.load("assets/banners/og-drop.png").convert_alpha(),
    pygame.image.load("assets/banners/16-drop.png").convert_alpha(),
    pygame.image.load("assets/banners/3-drop.png").convert_alpha()
]

center_image = pygame.image.load(resource_path("assets/select.png")).convert_alpha()
center_image_width, center_image_height = center_image.get_width(), center_image.get_height() - 50

# Banner size (359x478)
banner_width, banner_height = 359, 478
banner_images = [pygame.transform.scale(img, (banner_width, banner_height)) for img in banner_images]

selected_game = 0
num_games = len(banner_images)
transition_speed = 20  # Speed of the transition effect
target_offset = 0
current_offset = 0

TEXT_COLOR = (0,0,0)
font = pygame.font.Font('assets/font/Pixeled.ttf', 12)
credit_text = font.render("Launcher by yagmire, Games by DynamicDingo", True, TEXT_COLOR)

clock = pygame.time.Clock()
running = True

# Define the URL and parameters
server_url = "http://localhost:2665/download"
params = {
    'game': '16',
    'version': 'latest'
}

# Path where the file will be saved
save_path = "16.zip"
# Create a function to download the file and update the progress bar
def download_file():
    global downloaded
    downloaded = False
    # Send GET request to the server with streaming enabled
    response = requests.get(server_url, params=params, stream=True)
    
    # Get the total size of the file from the headers
    downloaded_size = 0

    # Open the file where we will save the content
    with open(save_path, 'wb') as file:
        for data in response.iter_content(chunk_size=1024):
            if data:
                # Write the downloaded chunk to the file
                file.write(data)
                downloaded_size += len(data)
    downloaded = True

threading.Thread(target=download_file).start()

while downloaded == False:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
    screen.blit(background_image, (0,0))
    screen.blit(window_bg, (0,0))
    pygame.display.flip()
    # 60 FPS
    clock.tick(60)

while running:
    screen.fill(WHITE)
    screen.blit(background_image, (0, 0))

    # Handle events
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
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


    if current_offset != target_offset:
        diff = target_offset - current_offset
        current_offset += transition_speed if diff > 0 else -transition_speed
        if abs(diff) < transition_speed:
            current_offset = target_offset

    center_image_x = (SCREEN_WIDTH - center_image_width) // 2
    center_image_y = (SCREEN_HEIGHT // 2 - banner_height // 2) - center_image_height - 10  # 10px padding
    screen.blit(center_image, (center_image_x, center_image_y))

    screen.blit(credit_text, (10, SCREEN_HEIGHT - credit_text.get_height() - 10))  # Padding of 10px
    
    for i, banner in enumerate(banner_images):
        banner_x = (SCREEN_WIDTH // 2 - banner_width // 2) + (i * SCREEN_WIDTH // 2) + current_offset
        banner_y = SCREEN_HEIGHT // 2 - banner_height // 2
        screen.blit(banner, (banner_x, banner_y))
    pygame.display.flip()
    # 60 FPS
    clock.tick(60)

pygame.quit()
sys.exit()
