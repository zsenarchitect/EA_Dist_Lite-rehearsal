from PIL import Image, ImageDraw
import os

def create_test_gif(filename, color, size=(64, 64), frames=6):
    """Create a simple animated GIF for testing"""
    images = []
    
    for i in range(frames):
        # Create a transparent image
        image = Image.new('RGBA', size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # Draw a simple bouncing circle
        radius = 20
        y_offset = abs((i % frames) - frames//2) * 5
        draw.ellipse([size[0]//2 - radius, 
                     size[1]//2 - radius + y_offset,
                     size[0]//2 + radius,
                     size[1]//2 + radius + y_offset],
                    fill=color)
        
        images.append(image)
    
    # Save the animation
    images[0].save(
        filename,
        save_all=True,
        append_images=images[1:],
        duration=100,
        loop=0,
        transparency=0,
        disposal=2
    )

def main():
    # Create assets directory if it doesn't exist
    assets_dir = os.path.join(os.path.dirname(__file__), "assets")
    os.makedirs(assets_dir, exist_ok=True)
    
    # Create test animations
    create_test_gif(os.path.join(assets_dir, "idle.gif"), (0, 255, 0, 255))  # Green
    create_test_gif(os.path.join(assets_dir, "walk_left.gif"), (255, 0, 0, 255))  # Red
    create_test_gif(os.path.join(assets_dir, "walk_right.gif"), (0, 0, 255, 255))  # Blue

if __name__ == "__main__":
    main()
    print("Test GIFs created in assets folder") 