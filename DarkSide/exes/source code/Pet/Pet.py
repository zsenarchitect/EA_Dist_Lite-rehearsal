"""
DuckiTect - Professional Architecture System
-----------------------------------------

Main entry point for the DuckiTect desktop pet application.
Coordinates core systems and launches the main window.

Author: EnneadTab Team
Version: 2.2
"""

import sys
import os
import logging
from PyQt5.QtWidgets import QApplication

from settings import WINDOW_FLAGS, WINDOW_SIZE
from state_manager import StateManager
from chat_manager import ChatManager
from gui.main_window import DuckWindow

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/ducktect.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('DuckiTect')

def main():
    """Main entry point for the DuckiTect application."""
    try:
        app = QApplication(sys.argv)
        
        # Initialize core systems
        state_manager = StateManager()
        chat_manager = ChatManager()
        
        # Create and show main window
        window = DuckWindow(
            state_manager=state_manager,
            chat_manager=chat_manager,
            flags=WINDOW_FLAGS,
            size=WINDOW_SIZE
        )
        window.show()
        
        # Start event loop
        sys.exit(app.exec_())
        
    except Exception as e:
        logger.error(f"Application crashed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()
