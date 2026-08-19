# Desktop Pet

A simple desktop pet application that displays an animated character on your Windows desktop.

## Features
- Transparent window that stays on top
- Drag and drop movement
- Multiple animation states (idle, walking left/right)
- Low resource usage
- Right-click menu for basic controls

## Required GIF Assets
Place your GIF animations in the `assets` folder with the following names:
- `idle.gif` - Basic idle animation
- `walk_left.gif` - Walking animation facing left
- `walk_right.gif` - Walking animation facing right

### Getting GIF Assets
You can get suitable GIF assets from:
1. itch.io's game assets section (search for "desktop pet" or "virtual pet")
2. spriters-resource.com
3. Create your own using tools like:
   - GraphicsGale
   - Piskel (online tool)
   - Aseprite

### Asset Requirements
- Recommended size: 32x32 to 128x128 pixels
- Transparent background
- Frame rate: 8-12 fps recommended for smooth animation
- File format: GIF with transparency

## Dependencies
- Python 3.6+
- Tkinter (usually comes with Python)
- Pillow (PIL) library: `pip install Pillow` 