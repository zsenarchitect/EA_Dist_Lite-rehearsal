import pygame
from OpenGL.GL import *

class UIRenderer:
    def __init__(self, window_width, window_height, panel_width):
        self.window_width = window_width
        self.window_height = window_height
        self.panel_width = panel_width
        self.font = pygame.font.Font(None, 32)

    def setup_2d_view(self):
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0, self.window_width, self.window_height, 0, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_LIGHTING)

    def restore_3d_state(self):
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LIGHTING)
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glPopMatrix()

    def render_text(self, text, x, y, color=(1, 1, 1)):
        text_surface = self.font.render(text, True, (int(color[0]*255), 
                                       int(color[1]*255), 
                                       int(color[2]*255)))
        text_data = pygame.image.tostring(text_surface, "RGBA", True)
        
        texture = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, texture)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, text_surface.get_width(), 
                     text_surface.get_height(), 0, GL_RGBA, GL_UNSIGNED_BYTE, text_data)
        
        glEnable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        
        glBegin(GL_QUADS)
        glTexCoord2f(0, 0); glVertex2f(x, y)
        glTexCoord2f(1, 0); glVertex2f(x + text_surface.get_width(), y)
        glTexCoord2f(1, 1); glVertex2f(x + text_surface.get_width(), 
                                      y + text_surface.get_height())
        glTexCoord2f(0, 1); glVertex2f(x, y + text_surface.get_height())
        glEnd()
        
        glDisable(GL_BLEND)
        glDisable(GL_TEXTURE_2D)
        glDeleteTextures([texture])

    def render_side_panel(self, selected_mesh):
        glColor4f(1.0, 1.0, 1.0, 0.3)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        
        glBegin(GL_QUADS)
        glVertex2f(self.window_width - self.panel_width, 0)
        glVertex2f(self.window_width, 0)
        glVertex2f(self.window_width, self.window_height)
        glVertex2f(self.window_width - self.panel_width, self.window_height)
        glEnd()
        
        glDisable(GL_BLEND)

        if selected_mesh:
            self._render_mesh_info(selected_mesh)
        else:
            self.render_text("Click a mesh", self.window_width - self.panel_width + 10, 20)
            self.render_text("to view details", self.window_width - self.panel_width + 10, 50)

    def _render_mesh_info(self, mesh):
        y_offset = 20
        self.render_text(f"GUID: {mesh.guid}", 
                         self.window_width - self.panel_width + 10, y_offset)
        y_offset += 30
        self.render_text(f"Color: RGB{mesh.color}", 
                         self.window_width - self.panel_width + 10, y_offset)
        y_offset += 30
        
        self.render_text("Metadata:", self.window_width - self.panel_width + 10, y_offset)
        y_offset += 30
        for key, value in mesh.metadata.items():
            self.render_text(f"{key}: {value}", 
                             self.window_width - self.panel_width + 20, y_offset)
            y_offset += 25
