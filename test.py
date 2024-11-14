import pygame
import sys

# Initialize Pygame
pygame.init()

# Screen settings
WIDTH, HEIGHT = 640, 480
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Settings Menu")

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (200, 200, 200)
BLUE = (100, 100, 255)

# Fonts
font = pygame.font.Font(None, 32)

# Input Box Settings
input_box = pygame.Rect(200, 200, 240, 40)
color_inactive = GRAY
color_active = BLUE
color = color_inactive
active = False
beta_key = ""

# Function to save beta key to a file
def save_beta_key(key):
    with open("betakey", "w") as file:
        file.write(key)

# Main loop
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.MOUSEBUTTONDOWN:
            # Check if the input box was clicked
            if input_box.collidepoint(event.pos):
                active = not active
            else:
                active = False
            color = color_active if active else color_inactive
        elif event.type == pygame.KEYDOWN:
            if active:
                if event.key == pygame.K_RETURN:
                    # Save beta key when Enter is pressed
                    save_beta_key(beta_key)
                    print("Beta Key saved:", beta_key)
                    beta_key = ""  # Clear input after saving
                elif event.key == pygame.K_BACKSPACE:
                    beta_key = beta_key[:-1]  # Remove last character
                else:
                    beta_key += event.unicode  # Add typed character

    # Fill screen with white
    screen.fill(WHITE)

    # Render text and input box
    txt_surface = font.render(beta_key, True, BLACK)
    width = max(200, txt_surface.get_width() + 10)
    input_box.w = width
    screen.blit(txt_surface, (input_box.x + 5, input_box.y + 5))
    pygame.draw.rect(screen, color, input_box, 2)

    # Display instruction text
    instruction_text = font.render("Enter Beta Key and press Enter", True, BLACK)
    screen.blit(instruction_text, (200, 150))

    # Update display
    pygame.display.flip()

# Quit Pygame
pygame.quit()
sys.exit()
