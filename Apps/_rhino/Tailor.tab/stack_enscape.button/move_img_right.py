import move_imgs as mi

__title__ = "MoveImg_1643"
__doc__ = """Image Relocation Tool for 1643 Project

Launches the file organizer GUI for relocating rendering images between study versions.
Features:
- Opens interactive file organizer interface
- Supports study selection (angled_frame, sawtooth, solar_panel, etc.)
- Handles glass/chrome version organization
- Automates file cleanup and relocation
- Maintains project-specific folder structure

Usage:
- Right-click to open file organizer GUI
- Select target study and version
- Automatically relocates PNG files to appropriate folders"""

if __name__ == '__main__':
    mi.main()

