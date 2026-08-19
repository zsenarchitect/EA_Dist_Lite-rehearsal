import pygame
from pygame.locals import *
from OpenGL.GL import *
from OpenGL.GLU import *
from logger import logger
from mesh import Mesh, load_mesh
from camera import Camera
from ui_renderer import UIRenderer
from setting import WINDOW_WIDTH, WINDOW_HEIGHT

class MeshViewer:
    def __init__(self, display):
        logger.info("Initializing MeshViewer")
        self.display = display
        self.window_width = WINDOW_WIDTH
        self.window_height = WINDOW_HEIGHT
        self.panel_width = 100

        logger.info("Loading mesh data")
        mesh_data = load_mesh()
        self.meshes = [Mesh(mesh_data) for mesh_data in mesh_data["meshes"]]
        
        self.camera = Camera()
        self.ui_renderer = UIRenderer(self.window_width, self.window_height, self.panel_width)
        self.selected_mesh = None
        
        self._setup_opengl()
        
        logger.info(f"Loaded {len(self.meshes)} meshes")

    def _setup_opengl(self):
        logger.info("Configuring OpenGL settings")
        try:
            glViewport(0, 0, self.window_width - self.panel_width, self.window_height)
            glEnable(GL_DEPTH_TEST)
            glEnable(GL_LIGHTING)
            glShadeModel(GL_SMOOTH)
            
            # Modified color material settings
            glEnable(GL_COLOR_MATERIAL)
            glColorMaterial(GL_FRONT, GL_AMBIENT_AND_DIFFUSE)
            
            # Set global ambient light
            glLightModelfv(GL_LIGHT_MODEL_AMBIENT, (0.3, 0.3, 0.3, 1.0))
            
            # Configure main light (key light)
            glEnable(GL_LIGHT0)
            glLight(GL_LIGHT0, GL_POSITION, (5.0, 5.0, 5.0, 0.0))
            glLight(GL_LIGHT0, GL_DIFFUSE, (1.0, 1.0, 1.0, 1.0))
            glLight(GL_LIGHT0, GL_SPECULAR, (1.0, 1.0, 1.0, 1.0))
            
            # Add fill light
            glEnable(GL_LIGHT1)
            glLight(GL_LIGHT1, GL_POSITION, (-3.0, 0.0, -3.0, 0.0))
            glLight(GL_LIGHT1, GL_DIFFUSE, (0.4, 0.4, 0.4, 1.0))
            glLight(GL_LIGHT1, GL_SPECULAR, (0.4, 0.4, 0.4, 1.0))
            
            glClearColor(0.15, 0.15, 0.15, 1.0)
            
            logger.info("OpenGL configuration completed successfully")
        except Exception as e:
            logger.error(f"Failed to configure OpenGL: {str(e)}")

    def run(self):
        logger.info("Starting main render loop")
        running = True
        clock = pygame.time.Clock()
        
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button in [1, 2, 3]:  # Left, Middle, Right click
                        self._handle_mouse_click(event)
                elif event.type == pygame.MOUSEMOTION:
                    if event.buttons[0]:  # Left button drag
                        self.camera.handle_rotation(event.rel)
                    elif event.buttons[1]:  # Middle button drag
                        self.camera.handle_pan(event.rel)

            # Clear the screen
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            
            # Set up camera view
            self.camera.setup(self.window_width - self.panel_width, self.window_height)
            
            # Render all meshes
            for mesh in self.meshes:
                mesh.render()
            
            # Render UI elements
            self.ui_renderer.setup_2d_view()
            self.ui_renderer.render_side_panel(self.selected_mesh)
            self.ui_renderer.restore_3d_state()
            
            pygame.display.flip()
            clock.tick(60)

    def _handle_mouse_click(self, event):
        # Basic mesh selection - can be enhanced with proper picking later
        if event.pos[0] < self.window_width - self.panel_width:
            # Clicked in the 3D view area
            if self.selected_mesh:
                self.selected_mesh = None
            else:
                # Select the first mesh for now
                # This should be replaced with proper picking logic
                if self.meshes:
                    self.selected_mesh = self.meshes[0]
