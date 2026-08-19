import pygame
from pygame.locals import *
from OpenGL.GL import *
from OpenGL.GLU import *
from viewer import MeshViewer
from logger import logger
from setting import WINDOW_WIDTH, WINDOW_HEIGHT
if __name__ == "__main__":
    try:
        logger.info("Initializing 3D Viewer application")
        pygame.init()
        
        logger.info("Setting up display")
        
        display = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), DOUBLEBUF | OPENGL)
        pygame.display.set_caption("3D Viewer")
        
        logger.info("Creating MeshViewer instance")
        viewer = MeshViewer(display)
        
        logger.info("Starting viewer")
        viewer.run()
        
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        raise
    finally:
        logger.info("Shutting down application")
        pygame.quit()
