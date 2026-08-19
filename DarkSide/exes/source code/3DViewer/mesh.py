from OpenGL.GL import *

def load_mesh():
    mesh_data = {
        "meshes": [
            # Pyramid (left position - no change needed)
            {
                "guid": "pyramid123",
                "color": [0, 255, 0],  # Green
                "metadata": {
                    "name": "Pyramid",
                    "area": 800
                },
                "vertices": [
                    [-3.0, -1.0, -1.0],  # Shifted left
                    [-1.0, -1.0, -1.0],
                    [-1.0, -1.0, 1.0],
                    [-3.0, -1.0, 1.0],
                    [-2.0, 1.0, 0.0]   # Top point
                ],
                "faces": [
                    [0, 1, 4],  # Front
                    [1, 2, 4],  # Right
                    [2, 3, 4],  # Back
                    [3, 0, 4],  # Left
                    [0, 2, 1],  # Base1
                    [0, 3, 2]   # Base2
                ]
            },
            # Cube (middle position)
            {
                "guid": "cube456",
                "color": [255, 0, 0],  # Red
                "metadata": {
                    "name": "Cube",
                    "area": 1234
                },
                "vertices": [
                    [0.0, -1.0, -1.0],  # Centered at origin
                    [2.0, -1.0, -1.0],
                    [2.0, 1.0, -1.0],
                    [0.0, 1.0, -1.0],
                    [0.0, -1.0, 1.0],
                    [2.0, -1.0, 1.0],
                    [2.0, 1.0, 1.0],
                    [0.0, 1.0, 1.0]
                ],
                "faces": [
                    [0, 1, 2], [2, 3, 0],  # Front
                    [1, 5, 6], [6, 2, 1],  # Right
                    [7, 6, 5], [5, 4, 7],  # Back
                    [4, 0, 3], [3, 7, 4],  # Left
                    [4, 5, 1], [1, 0, 4],  # Bottom
                    [3, 2, 6], [6, 7, 3]   # Top
                ]
            },
            # House (right position)
            {
                "guid": "house789",
                "color": [0, 0, 255],  # Blue
                "metadata": {
                    "name": "House",
                    "area": 1500
                },
                "vertices": [
                    [3.0, -1.0, -1.0],  # Shifted right
                    [5.0, -1.0, -1.0],
                    [5.0, -1.0, 1.0],
                    [3.0, -1.0, 1.0],
                    [3.0, 1.0, -1.0],
                    [5.0, 1.0, -1.0],
                    [5.0, 1.0, 1.0],
                    [3.0, 1.0, 1.0],
                    [4.0, 2.0, 0.0]      # Roof top point
                ],
                "faces": [
                    [0, 1, 5], [5, 4, 0],  # Front wall
                    [1, 2, 6], [6, 5, 1],  # Right wall
                    [2, 3, 7], [7, 6, 2],  # Back wall
                    [3, 0, 4], [4, 7, 3],  # Left wall
                    [4, 5, 8],            # Front roof
                    [5, 6, 8],            # Right roof
                    [6, 7, 8],            # Back roof
                    [7, 4, 8],            # Left roof
                    [0, 2, 1], [0, 3, 2]  # Floor
                ]
            }
        ]
    }
    return mesh_data

class Mesh:
    def __init__(self, mesh_data):
        self.guid = mesh_data["guid"]
        self.color = mesh_data["color"]
        self.metadata = mesh_data["metadata"]
        self.vertices = mesh_data["vertices"]
        self.faces = mesh_data["faces"]

    def render(self):
        glPushMatrix()
        
        # First render the faces
        r, g, b = self.color[0]/255.0, self.color[1]/255.0, self.color[2]/255.0
        glColor3f(r, g, b)
        
        glMaterialfv(GL_FRONT, GL_SPECULAR, (1.0, 1.0, 1.0, 1.0))
        glMaterialf(GL_FRONT, GL_SHININESS, 50.0)
        
        # Render faces
        glBegin(GL_TRIANGLES)
        for face in self.faces:
            v0 = self.vertices[face[0]]
            v1 = self.vertices[face[1]]
            v2 = self.vertices[face[2]]
            
            edge1 = [v1[i] - v0[i] for i in range(3)]
            edge2 = [v2[i] - v0[i] for i in range(3)]
            normal = [
                edge1[1] * edge2[2] - edge1[2] * edge2[1],
                edge1[2] * edge2[0] - edge1[0] * edge2[2],
                edge1[0] * edge2[1] - edge1[1] * edge2[0]
            ]
            
            length = (normal[0]**2 + normal[1]**2 + normal[2]**2)**0.5
            if length > 0:
                normal = [n/length for n in normal]
                glNormal3f(*normal)
                
            for vertex_id in face:
                vertex = self.vertices[vertex_id]
                glVertex3f(*vertex)
        glEnd()
        
        # Now render the edges
        glDisable(GL_LIGHTING)  # Disable lighting for edges
        glColor3f(0.7, 0.7, 0.7)  # Light grey color
        glLineWidth(1.0)  # Set edge width
        
        # Create a set of unique edges
        edges = set()
        for face in self.faces:
            # Add all three edges of the triangle
            edges.add(tuple(sorted([face[0], face[1]])))
            edges.add(tuple(sorted([face[1], face[2]])))
            edges.add(tuple(sorted([face[2], face[0]])))
        
        # Draw edges
        glBegin(GL_LINES)
        for edge in edges:
            v1 = self.vertices[edge[0]]
            v2 = self.vertices[edge[1]]
            glVertex3f(*v1)
            glVertex3f(*v2)
        glEnd()
        
        glEnable(GL_LIGHTING)  # Re-enable lighting
        glPopMatrix()
