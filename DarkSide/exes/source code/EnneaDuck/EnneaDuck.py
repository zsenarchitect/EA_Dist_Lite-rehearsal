"""
EnneaDuck - A fun desktop pet application.

This is the main entry point for the EnneaDuck application.
It creates a desktop pet that follows your mouse, tells jokes,
and provides entertainment through various animations.
"""

import sys
import logging
from gui import EnneaDuck
from config import APP_NAME, APP_VERSION

def main():
    """Main entry point for the application."""
    try:
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        logger = logging.getLogger(__name__)
        
        # Log startup
        logger.info(f"Starting {APP_NAME} v{APP_VERSION}")
        
        # Create and run application
        app = EnneaDuck()
        app.mainloop()
        
    except Exception as e:
        logger.error(f"Application error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

