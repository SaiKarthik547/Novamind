import os
from PIL import Image, ImageDraw
import random

def create_texture(name, size=(64, 64), color_base=(100, 100, 100), noise_range=20, grid=False):
    img = Image.new('RGB', size, color_base)
    pixels = img.load()
    for x in range(size[0]):
        for y in range(size[1]):
            # Add noise
            r_noise = random.randint(-noise_range, noise_range)
            g_noise = random.randint(-noise_range, noise_range)
            b_noise = random.randint(-noise_range, noise_range)
            r = max(0, min(255, color_base[0] + r_noise))
            g = max(0, min(255, color_base[1] + g_noise))
            b = max(0, min(255, color_base[2] + b_noise))
            pixels[x, y] = (r, g, b)
            
            # Add grid for bricks/concrete
            if grid:
                if x % 16 == 0 or y % 16 == 0:
                    pixels[x, y] = (max(0, r-30), max(0, g-30), max(0, b-30))
                    
    img.save(name)

def generate_all():
    os.makedirs('assets/textures', exist_ok=True)
    # Asphalt
    create_texture('assets/textures/asphalt.png', color_base=(40, 40, 45), noise_range=15)
    # Concrete (Sidewalks/Buildings)
    create_texture('assets/textures/concrete.png', color_base=(90, 90, 95), noise_range=10, grid=True)
    # Glass (Windows)
    create_texture('assets/textures/glass.png', color_base=(40, 80, 120), noise_range=5)
    # Dark Metal (Buildings/Cars)
    create_texture('assets/textures/metal.png', color_base=(30, 35, 40), noise_range=8)
    # Highlight/Neon Base
    create_texture('assets/textures/neon_base.png', color_base=(255, 255, 255), noise_range=0)
    print("Textures generated successfully.")

if __name__ == '__main__':
    generate_all()
