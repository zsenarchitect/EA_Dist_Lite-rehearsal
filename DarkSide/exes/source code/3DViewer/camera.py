from OpenGL.GL import *
from OpenGL.GLU import *
import math
import time

class Camera:
    def __init__(self):
        self.position = [0.0, 0.0, -5.0]
        self.rotation = [0.0, 0.0, 0.0]
        self.navigation_mode = "revit"  # Default mode
        self.spin_count = 0  # Track number of spins
        self.last_spin_time = 0  # Track timing for special effects
        
    def setup(self, viewport_width, viewport_height):
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        
        # Adjusted field of view and draw distance for sharper image
        gluPerspective(45, viewport_width / viewport_height, 0.1, 100.0)
        
        # Enable antialiasing for smoother edges
        glEnable(GL_MULTISAMPLE)
        glEnable(GL_LINE_SMOOTH)
        glHint(GL_LINE_SMOOTH_HINT, GL_NICEST)
        
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glTranslatef(*self.position)
        glRotatef(self.rotation[0], 1, 0, 0)  # Pitch
        glRotatef(self.rotation[1], 0, 1, 0)  # Yaw
        glRotatef(self.rotation[2], 0, 0, 1)  # Roll

    def handle_rotation(self, rel):
        self.rotation[1] += rel[0] * 0.5  # Yaw
        self.rotation[0] += rel[1] * 0.5  # Pitch
        
        # Add fun spinning effect
        self.spin_count += abs(rel[0]) / 360.0
        if self.spin_count >= 10:  # After 10 rotations
            # Reset and play dizzy animation
            self.spin_count = 0
            self.last_spin_time = time.time()
            self.position = [0.0, 0.0, -5.0]
            self.rotation = [0.0, 0.0, 0.0]

    def handle_pan(self, rel):
        self.position[0] += rel[0] * 0.01  # Pan left/right
        self.position[1] += rel[1] * 0.01  # Pan up/down

    def view_all(self, meshes):
        all_vertices = []
        for mesh in meshes:
            all_vertices.extend(mesh.vertices)
        
        if not all_vertices:
            return
            
        min_point = [float('inf')] * 3
        max_point = [float('-inf')] * 3
        
        for vertex in all_vertices:
            for i in range(3):
                min_point[i] = min(min_point[i], vertex[i])
                max_point[i] = max(max_point[i], vertex[i])
        
        center = [(min_point[i] + max_point[i]) / 2 for i in range(3)]
        size = max(max_point[i] - min_point[i] for i in range(3))
        
        self.position = [center[0], center[1], center[2] + size * 2]
        self.rotation = [0.0, 0.0, 0.0]

    def handle_mouse_input(self, buttons, mods, rel):
        if self.navigation_mode == "revit":
            if buttons[1]:  # Middle mouse button
                if mods & 1:  # Shift modifier
                    self.handle_rotation(rel)
                else:
                    self.handle_pan(rel)
        else:  # Rhino mode
            if buttons[2]:  # Right mouse button
                if mods & 1:  # Shift modifier
                    self.handle_pan(rel)
                else:
                    self.handle_rotation(rel)

    def toggle_navigation_mode(self):
        self.navigation_mode = "rhino" if self.navigation_mode == "revit" else "revit"
