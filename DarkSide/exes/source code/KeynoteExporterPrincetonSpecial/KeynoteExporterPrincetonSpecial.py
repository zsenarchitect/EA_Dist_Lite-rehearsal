#!/usr/bin/env python3
"""
KeynoteExporter PrincetonSpecial - GUI Entry Point

Simple entry point that launches the GUI interface.
"""

if __name__ == "__main__":
    # Launch the PrincetonSpecial GUI
    from src.keynote_gui import main as gui_main
    gui_main()