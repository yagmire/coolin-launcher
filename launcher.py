import pygame
 
pygame.init()
X = 1024
Y = 768

scrn = pygame.display.set_mode((X, Y))
 
pygame.display.set_caption('image')

bg = pygame.image.load("assets\\bg.png").convert()
scrn.blit(bg, (0, 0))

holder16 = pygame.image.load("assets\\banners\\16.png").convert_alpha()
holder3 = pygame.image.load("assets\\holder.png").convert()
holder_coolin = pygame.image.load("assets\\holder.png").convert()


scrn.blit(holder16, ((X/2)/1.3, (Y/2)/2))
#scrn.blit(holder3, ((X/2)/1.3, (Y/2)/2))
#scrn.blit(holder_coolin, ((X/2)/1.3, (Y/2)/2))


pygame.display.flip()
status = True
while (status):
    for i in pygame.event.get():
        if i.type == pygame.QUIT:
            status = False
 
pygame.quit()