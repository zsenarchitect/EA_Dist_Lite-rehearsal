#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
RelationshipTree
A desktop application for creating and managing relationship diagrams between items.
Features:
- Interactive node creation and editing
- Drag-and-drop connections
- Department-based color coding
- JSON import/export
- Integration with other EnneadTab tools
- Animated connections
- Node physics for automatic layout
"""

import sys
import json
import uuid
import os
import math
import random
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLabel, QColorDialog,
                            QInputDialog, QMessageBox, QDialog, QFormLayout,
                            QLineEdit, QComboBox, QScrollArea, QFrame)
from PyQt5.QtCore import Qt, QPointF, QTimer, QRectF, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QBrush, QFont, QIcon, QCursor, QLinearGradient, QRadialGradient

import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _Exe_Util
import _GUI_Util

# Constants
DATA_FILE = "relationship_tree_data"
DEFAULT_DEPARTMENT_COLORS = {
    "Inpatient": "#50FA7B",     # Bright green
    "Outpatient": "#8BE9FD",    # Bright cyan
    "Surgery": "#FFB86C",       # Bright orange
    "Laboratory": "#FF79C6",    # Bright pink
    "Radiology": "#BD93F9",     # Bright purple
    "Support": "#FF5555",       # Bright red
    "Administration": "#F1FA8C", # Bright yellow
    "Emergency": "#FFB86C",     # Bright orange
    "Other": "#6272A4"          # Muted blue-grey
}

# Theme colors
THEME = {
    "background": "#1E1E2E",
    "foreground": "#FFFFFF",  # Brighter white for better readability
    "primary": "#89B4FA",
    "secondary": "#F5C2E7",
    "accent": "#FAB387",
    "error": "#FF5555",  # Brighter red
    "success": "#50FA7B",  # Brighter green
    "warning": "#FFB86C",  # Brighter orange
    "info": "#8BE9FD",  # Brighter blue
    "button": "#45475A",  # Lighter button background
    "button_hover": "#585B70",  # Lighter hover state
    "button_pressed": "#6C7086",  # Lighter pressed state
    "node_border": "#FFFFFF",  # White border for better visibility
    "connection": "#FFFFFF",  # White connections
    "connection_hover": "#FF5555",  # Bright red for hover
    "legend_bg": "#282A36",  # Darker background for legend
    "legend_border": "#6C7086"  # Lighter border for legend
}

class Node:
    """Represents a node in the relationship diagram."""
    def __init__(self, name, department, position, color=None):
        self.id = str(uuid.uuid4())
        self.name = name
        self.department = department
        self.position = position
        self.color = color or DEFAULT_DEPARTMENT_COLORS.get(department, "#CCCCCC")
        self.radius = 30
        self.velocity = QPointF(0, 0)
        self.force = QPointF(0, 0)

    def to_dict(self):
        """Convert node to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "department": self.department,
            "position": {"x": self.position.x(), "y": self.position.y()},
            "color": self.color
        }

    @classmethod
    def from_dict(cls, data):
        """Create node from dictionary data."""
        return cls(
            name=data["name"],
            department=data["department"],
            position=QPointF(data["position"]["x"], data["position"]["y"]),
            color=data.get("color")
        )

class Connection:
    """Represents a connection between two nodes."""
    def __init__(self, from_node, to_node):
        self.from_node = from_node
        self.to_node = to_node
        self.dash_offset = 0
        self.hovered = False
        self.flow_phase = 0  # For flowing animation effect

    def to_dict(self):
        """Convert connection to dictionary for JSON serialization."""
        return {
            "from": self.from_node.id,
            "to": self.to_node.id
        }
        
    def length(self):
        """Calculate the length of the connection."""
        return math.sqrt(
            (self.to_node.position.x() - self.from_node.position.x())**2 +
            (self.to_node.position.y() - self.from_node.position.y())**2
        )
        
    def contains_point(self, point, threshold=5):
        """Check if a point is near the connection line."""
        # Calculate the distance from point to line segment
        x, y = point.x(), point.y()
        x1, y1 = self.from_node.position.x(), self.from_node.position.y()
        x2, y2 = self.to_node.position.x(), self.to_node.position.y()
        
        # Calculate the distance from point to line segment
        line_length = self.length()
        if line_length == 0:
            return False
            
        # Calculate the distance from point to line
        u = ((x - x1) * (x2 - x1) + (y - y1) * (y2 - y1)) / (line_length * line_length)
        
        # Clamp u to line segment
        u = max(0, min(1, u))
        
        # Calculate the closest point on the line segment
        closest_x = x1 + u * (x2 - x1)
        closest_y = y1 + u * (y2 - y1)
        
        # Calculate the distance from point to closest point
        distance = math.sqrt((x - closest_x)**2 + (y - closest_y)**2)
        
        return distance <= threshold

class NodeEditDialog(QDialog):
    """Dialog for editing node properties."""
    def __init__(self, node, departments, parent=None):
        super().__init__(parent)
        self.node = node
        self.departments = departments
        self.setup_ui()
        
    def setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Edit Node")
        self.setMinimumWidth(300)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {THEME["background"]};
                color: {THEME["foreground"]};
            }}
            QLabel {{
                color: {THEME["foreground"]};
            }}
            QLineEdit, QComboBox {{
                background-color: {THEME["button"]};
                color: {THEME["foreground"]};
                border: 1px solid {THEME["button_pressed"]};
                border-radius: 4px;
                padding: 5px;
            }}
            QPushButton {{
                background-color: {THEME["button"]};
                color: {THEME["foreground"]};
                border: 1px solid {THEME["button_pressed"]};
                border-radius: 4px;
                padding: 5px;
            }}
            QPushButton:hover {{
                background-color: {THEME["button_hover"]};
            }}
            QPushButton:pressed {{
                background-color: {THEME["button_pressed"]};
            }}
        """)
        
        layout = QFormLayout(self)
        
        # Name field
        self.name_edit = QLineEdit(self.node.name)
        layout.addRow("Name:", self.name_edit)
        
        # Department dropdown
        self.dept_combo = QComboBox()
        self.dept_combo.addItems(self.departments.keys())
        current_index = list(self.departments.keys()).index(self.node.department) if self.node.department in self.departments else 0
        self.dept_combo.setCurrentIndex(current_index)
        self.dept_combo.currentTextChanged.connect(self.update_color_preview)
        layout.addRow("Department:", self.dept_combo)
        
        # Color preview
        self.color_preview = QFrame()
        self.color_preview.setFixedSize(50, 20)
        self.color_preview.setStyleSheet(f"background-color: {self.node.color}; border: 1px solid {THEME['node_border']};")
        layout.addRow("Color:", self.color_preview)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        layout.addRow("", button_layout)
        
    def update_color_preview(self):
        """Update the color preview when department changes."""
        dept = self.dept_combo.currentText()
        color = self.departments.get(dept, "#CCCCCC")
        self.color_preview.setStyleSheet(f"background-color: {color}; border: 1px solid {THEME['node_border']};")
        
    def get_values(self):
        """Get the edited values."""
        return {
            "name": self.name_edit.text(),
            "department": self.dept_combo.currentText()
        }

class LegendWidget(QWidget):
    """Widget for displaying the department color legend."""
    def __init__(self, departments, parent=None):
        super().__init__(parent)
        self.departments = departments
        self.setMinimumWidth(200)
        self.setMaximumWidth(250)  # Add maximum width
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {THEME["legend_bg"]};
                color: {THEME["foreground"]};
                border: 2px solid {THEME["legend_border"]};  # Make border more visible
                border-radius: 8px;
                margin: 5px;
                padding: 10px;
            }}
        """)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw title with larger font and padding
        painter.setPen(QColor(THEME["foreground"]))
        title_font = QFont("Arial", 14, QFont.Bold)
        painter.setFont(title_font)
        painter.drawText(15, 35, "Departments")
        
        # Draw department items with more spacing
        y = 70  # Start lower to give more space after title
        for dept, color in self.departments.items():
            # Draw color box with larger size
            painter.setPen(QPen(QColor(THEME["node_border"]), 2))
            painter.setBrush(QBrush(QColor(color)))
            painter.drawRect(15, y, 25, 25)  # Larger color boxes
            
            # Draw department name with larger font
            painter.setPen(QColor(THEME["foreground"]))
            painter.setFont(QFont("Arial", 11))  # Larger font for department names
            painter.drawText(50, y + 17, dept)  # Adjusted text position
            
            y += 35  # More spacing between items
            
        # Set fixed height based on number of departments
        self.setFixedHeight(y + 20)  # Add padding at bottom

class Canvas(QWidget):
    """The main drawing canvas for the relationship diagram."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodes = []
        self.connections = []
        self.departments = DEFAULT_DEPARTMENT_COLORS.copy()
        self.setMouseTracking(True)
        self.dragging_node = None
        self.connecting_node = None
        self.temp_connection_end = None
        self.connection_mode = False  # Toggle for connection mode
        self.delete_mode = False  # Toggle for delete mode
        self.hovered_connection = None
        self.physics_enabled = False
        self.setMinimumSize(800, 600)
        self.setFocusPolicy(Qt.StrongFocus)  # Enable key focus
        
        # Animation timer
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.update_animation)
        self.animation_timer.start(50)  # 20 FPS
        
        # Physics timer
        self.physics_timer = QTimer(self)
        self.physics_timer.timeout.connect(self.update_physics)
        self.physics_timer.start(16)  # ~60 FPS
        
        # Key logging
        self.key_log_enabled = True
        self.last_key_press = None
        self.key_press_time = 0
        
    def keyPressEvent(self, event):
        """Handle key press events for logging."""
        if self.key_log_enabled:
            key_name = event.key()
            key_text = event.text()
            
            # Get key name in a readable format
            if key_name == Qt.Key_Control:
                key_name = "Ctrl"
            elif key_name == Qt.Key_Shift:
                key_name = "Shift"
            elif key_name == Qt.Key_Alt:
                key_name = "Alt"
            elif key_name == Qt.Key_Space:
                key_name = "Space"
            elif key_name == Qt.Key_Return or key_name == Qt.Key_Enter:
                key_name = "Enter"
            elif key_name == Qt.Key_Escape:
                key_name = "Esc"
            elif key_name == Qt.Key_Backspace:
                key_name = "Backspace"
            elif key_name == Qt.Key_Delete:
                key_name = "Delete"
            elif key_name == Qt.Key_Left:
                key_name = "Left"
            elif key_name == Qt.Key_Right:
                key_name = "Right"
            elif key_name == Qt.Key_Up:
                key_name = "Up"
            elif key_name == Qt.Key_Down:
                key_name = "Down"
            elif key_name == Qt.Key_Tab:
                key_name = "Tab"
            elif key_name == Qt.Key_CapsLock:
                key_name = "CapsLock"
            elif key_name == Qt.Key_F1:
                key_name = "F1"
            elif key_name == Qt.Key_F2:
                key_name = "F2"
            elif key_name == Qt.Key_F3:
                key_name = "F3"
            elif key_name == Qt.Key_F4:
                key_name = "F4"
            elif key_name == Qt.Key_F5:
                key_name = "F5"
            elif key_name == Qt.Key_F6:
                key_name = "F6"
            elif key_name == Qt.Key_F7:
                key_name = "F7"
            elif key_name == Qt.Key_F8:
                key_name = "F8"
            elif key_name == Qt.Key_F9:
                key_name = "F9"
            elif key_name == Qt.Key_F10:
                key_name = "F10"
            elif key_name == Qt.Key_F11:
                key_name = "F11"
            elif key_name == Qt.Key_F12:
                key_name = "F12"
            elif key_text:
                key_name = key_text
            else:
                key_name = f"Key({key_name})"
            
            # Log modifiers
            modifiers = []
            if event.modifiers() & Qt.ControlModifier:
                modifiers.append("Ctrl")
            if event.modifiers() & Qt.ShiftModifier:
                modifiers.append("Shift")
            if event.modifiers() & Qt.AltModifier:
                modifiers.append("Alt")
            if event.modifiers() & Qt.MetaModifier:
                modifiers.append("Meta")
                
            # Combine modifiers and key
            if modifiers:
                key_str = "+".join(modifiers + [key_name])
            else:
                key_str = key_name
                
            # Log the key press
            print(f"Key pressed: {key_str}")
            self.last_key_press = key_str
            self.key_press_time = QTimer.currentTime()
            
            # Special key handling
            if key_name == "C":  # Toggle connection mode with C key
                self.connection_mode = not self.connection_mode
                if self.connection_mode:
                    self.delete_mode = False
                print(f"Connection mode: {'enabled' if self.connection_mode else 'disabled'}")
                
            elif key_name == "D":  # Toggle delete mode with D key
                self.delete_mode = not self.delete_mode
                if self.delete_mode:
                    self.connection_mode = False
                print(f"Delete mode: {'enabled' if self.delete_mode else 'disabled'}")
                
            elif key_name == "P":  # Toggle physics with P key
                self.physics_enabled = not self.physics_enabled
                if not self.physics_enabled:
                    # Reset velocities
                    for node in self.nodes:
                        node.velocity = QPointF(0, 0)
                        node.force = QPointF(0, 0)
                print(f"Physics: {'enabled' if self.physics_enabled else 'disabled'}")
                
            elif key_name == "L":  # Toggle key logging with L key
                self.key_log_enabled = not self.key_log_enabled
                print(f"Key logging: {'enabled' if self.key_log_enabled else 'disabled'}")
                
        # Call parent method to handle other key events
        super().keyPressEvent(event)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw connections first (so they appear under nodes)
        for connection in self.connections:
            self.draw_connection(painter, connection)
            
        # Draw temporary connection if creating one
        if self.connecting_node and self.temp_connection_end:
            painter.setPen(QPen(QColor(THEME["connection"]), 2, Qt.DashLine))
            painter.drawLine(
                self.connecting_node.position,
                self.temp_connection_end
            )
            
        # Draw nodes last (so they appear on top)
        for node in self.nodes:
            self.draw_node(painter, node)
            
        # Draw cursor indicator if in connection mode
        if self.connection_mode:
            painter.setPen(QPen(QColor(THEME["accent"]), 2, Qt.DashLine))
            painter.drawEllipse(self.mapFromGlobal(self.cursor().pos()), 10, 10)
            
        # Draw scissors cursor if in delete mode and hovering over a connection
        if self.delete_mode and self.hovered_connection:
            cursor_pos = self.mapFromGlobal(self.cursor().pos())
            painter.setPen(QPen(QColor(THEME["error"]), 2))
            painter.drawLine(cursor_pos - QPointF(5, 5), cursor_pos + QPointF(5, 5))
            painter.drawLine(cursor_pos - QPointF(5, -5), cursor_pos + QPointF(5, -5))
            
        # Draw last key press in the corner
        if self.key_log_enabled and self.last_key_press:
            # Only show for 2 seconds after key press
            if QTimer.currentTime() - self.key_press_time < 2000:
                painter.setPen(QColor(THEME["foreground"]))
                painter.setFont(QFont("Arial", 10))
                painter.drawText(10, 20, f"Last key: {self.last_key_press}")
    
    def draw_node(self, painter, node):
        """Draw a node on the canvas."""
        # Draw node circle
        painter.setPen(QPen(QColor(THEME["node_border"]), 2))
        painter.setBrush(QBrush(QColor(node.color)))
        painter.drawEllipse(node.position, node.radius, node.radius)
        
        # Draw node name
        painter.setPen(QColor(THEME["foreground"]))
        text_rect = painter.fontMetrics().boundingRect(node.name)
        text_pos = QPointF(
            node.position.x() - text_rect.width() / 2,
            node.position.y() + text_rect.height() / 2
        )
        painter.drawText(text_pos, node.name)
        
    def draw_connection(self, painter, connection):
        """Draw a connection between two nodes."""
        # Calculate line direction and length
        dx = connection.to_node.position.x() - connection.from_node.position.x()
        dy = connection.to_node.position.y() - connection.from_node.position.y()
        length = math.sqrt(dx*dx + dy*dy)
        
        if length == 0:
            return
            
        # Create gradient for softer look
        gradient = QLinearGradient(
            connection.from_node.position,
            connection.to_node.position
        )
        
        # Set gradient colors based on hover state
        if connection.hovered:
            base_color = QColor(THEME["connection_hover"])
            fade_color = QColor(THEME["connection_hover"])
        else:
            base_color = QColor(THEME["connection"])
            fade_color = QColor(THEME["connection"])
        
        # Make colors semi-transparent for softer look
        base_color.setAlpha(200)
        fade_color.setAlpha(150)
        
        gradient.setColorAt(0, base_color)
        gradient.setColorAt(0.5, fade_color)
        gradient.setColorAt(1, base_color)
        
        # Create pen with gradient and rounded caps
        pen = QPen()
        pen.setBrush(gradient)
        pen.setWidth(3)  # Slightly thicker line
        pen.setStyle(Qt.CustomDashLine)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        
        # Create smooth dash pattern
        dash_length = 15
        gap_length = 10
        total_length = dash_length + gap_length
        
        # Calculate number of segments
        num_segments = max(3, int(length / total_length))
        segment_length = length / num_segments
        
        # Create smooth dash pattern with varying lengths
        dash_pattern = []
        for i in range(num_segments):
            # Vary dash and gap lengths using sine wave
            phase = (i / num_segments * math.pi * 2 + connection.flow_phase) % (math.pi * 2)
            dash_variation = math.sin(phase) * 5  # Vary by ±5 pixels
            gap_variation = math.cos(phase) * 3   # Vary by ±3 pixels
            
            dash_pattern.append(dash_length + dash_variation)
            dash_pattern.append(gap_length + gap_variation)
        
        pen.setDashPattern(dash_pattern)
        pen.setDashOffset(connection.dash_offset)
        
        painter.setPen(pen)
        painter.drawLine(
            connection.from_node.position,
            connection.to_node.position
        )
        
        # Draw glowing connection points
        glow_radius = 6
        for point in [connection.from_node.position, connection.to_node.position]:
            # Draw outer glow
            glow = QRadialGradient(point, glow_radius)
            glow_color = QColor(base_color)
            glow_color.setAlpha(100)
            glow.setColorAt(0, glow_color)
            glow_color.setAlpha(0)
            glow.setColorAt(1, glow_color)
            
            painter.setPen(Qt.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(point, glow_radius, glow_radius)
            
            # Draw center point
            painter.setBrush(QBrush(base_color))
            painter.drawEllipse(point, 3, 3)

    def update_animation(self):
        """Update animation state."""
        # Update dash offset for flowing effect
        for connection in self.connections:
            connection.dash_offset = (connection.dash_offset + 0.5) % 25  # Slower movement
            connection.flow_phase = (connection.flow_phase + 0.05) % (math.pi * 2)  # Smooth phase transition
        self.update()
        
    def update_physics(self):
        """Update physics simulation."""
        if not self.physics_enabled:
            return
            
        # Reset forces
        for node in self.nodes:
            node.force = QPointF(0, 0)
            
        # Apply repulsion forces between nodes
        for i, node1 in enumerate(self.nodes):
            for node2 in self.nodes[i+1:]:
                dx = node2.position.x() - node1.position.x()
                dy = node2.position.y() - node1.position.y()
                distance = math.sqrt(dx*dx + dy*dy)
                
                if distance < 1:
                    distance = 1
                    
                # Repulsion force (stronger when closer)
                force = 1000 / (distance * distance)
                node1.force += QPointF(-dx/distance * force, -dy/distance * force)
                node2.force += QPointF(dx/distance * force, dy/distance * force)
                
        # Apply spring forces for connections
        for connection in self.connections:
            dx = connection.to_node.position.x() - connection.from_node.position.x()
            dy = connection.to_node.position.y() - connection.from_node.position.y()
            distance = math.sqrt(dx*dx + dy*dy)
            
            if distance < 1:
                distance = 1
                
            # Spring force (stronger when longer)
            target_length = 150  # Ideal connection length
            force = 0.01 * (distance - target_length)
            
            connection.from_node.force += QPointF(dx/distance * force, dy/distance * force)
            connection.to_node.force += QPointF(-dx/distance * force, -dy/distance * force)
            
        # Apply forces to velocities and positions
        for node in self.nodes:
            # Skip nodes being dragged
            if node == self.dragging_node:
                continue
                
            # Update velocity (with damping)
            node.velocity += node.force * 0.1
            node.velocity *= 0.9  # Damping
            
            # Update position
            node.position += node.velocity
            
            # Keep nodes within bounds
            node.position.setX(max(node.radius, min(self.width() - node.radius, node.position.x())))
            node.position.setY(max(node.radius, min(self.height() - node.radius, node.position.y())))
            
        self.update()
        
    def get_node_at_position(self, pos):
        """Find a node at the given position."""
        for node in self.nodes:
            if (node.position - pos).manhattanLength() <= node.radius:
                return node
        return None
        
    def get_connection_at_position(self, pos):
        """Find a connection at the given position."""
        for connection in self.connections:
            if connection.contains_point(pos):
                return connection
        return None
        
    def mousePressEvent(self, event):
        """Handle mouse press events."""
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            
            if self.delete_mode:
                # Check if clicking on a connection to delete it
                connection = self.get_connection_at_position(pos)
                if connection:
                    self.connections.remove(connection)
                    self.update()
                    return
                    
            node = self.get_node_at_position(pos)
            if node:
                if self.connection_mode:
                    # Start connecting
                    self.connecting_node = node
                    self.temp_connection_end = pos
                else:
                    # Start dragging
                    self.dragging_node = node
                self.update()
                
    def mouseMoveEvent(self, event):
        """Handle mouse move events."""
        pos = event.pos()
        
        # Update hovered connection
        if self.delete_mode:
            self.hovered_connection = self.get_connection_at_position(pos)
            if self.hovered_connection:
                self.setCursor(Qt.CrossCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
        
        if self.dragging_node:
            self.dragging_node.position = pos
            self.update()
        elif self.connecting_node:
            self.temp_connection_end = pos
            self.update()
        elif self.connection_mode:
            # Update cursor indicator
            self.update()
            
    def mouseReleaseEvent(self, event):
        """Handle mouse release events."""
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            
            if self.dragging_node:
                self.dragging_node = None
            elif self.connecting_node:
                target_node = self.get_node_at_position(pos)
                if target_node and target_node != self.connecting_node:
                    # Check if connection already exists
                    connection_exists = False
                    for conn in self.connections:
                        if (conn.from_node == self.connecting_node and conn.to_node == target_node) or \
                           (conn.from_node == target_node and conn.to_node == self.connecting_node):
                            connection_exists = True
                            break
                            
                    if not connection_exists:
                        # Create new connection
                        self.connections.append(Connection(self.connecting_node, target_node))
                        print(f"Created connection from {self.connecting_node.name} to {target_node.name}")
                
                self.connecting_node = None
                self.temp_connection_end = None
                self.update()
                
    def mouseDoubleClickEvent(self, event):
        """Handle mouse double click events."""
        if event.button() == Qt.LeftButton:
            node = self.get_node_at_position(event.pos())
            if node:
                self.edit_node(node)
                
    def edit_node(self, node):
        """Edit a node's properties."""
        dialog = NodeEditDialog(node, self.departments, self)
        if dialog.exec_() == QDialog.Accepted:
            values = dialog.get_values()
            node.name = values["name"]
            node.department = values["department"]
            node.color = self.departments[node.department]
            self.update()

    def set_connection_mode(self, enabled):
        """Toggle connection mode on/off."""
        self.connection_mode = enabled
        if enabled:
            self.delete_mode = False
        self.update()
        
    def set_delete_mode(self, enabled):
        """Toggle delete mode on/off."""
        self.delete_mode = enabled
        if enabled:
            self.connection_mode = False
        self.update()
        
    def set_physics_enabled(self, enabled):
        """Toggle physics simulation on/off."""
        self.physics_enabled = enabled
        if not enabled:
            # Reset velocities
            for node in self.nodes:
                node.velocity = QPointF(0, 0)
                node.force = QPointF(0, 0)

class RelationshipTreeApp(QMainWindow):
    """Main application window for the Relationship Tree tool."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EnneadTab Relationship Diagram Maker")
        self.setMinimumSize(1024, 768)
        
        # Set application style
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {THEME["background"]};
                color: {THEME["foreground"]};
            }}
            QPushButton {{
                background-color: {THEME["button"]};
                color: {THEME["foreground"]};
                border: 1px solid {THEME["button_pressed"]};
                border-radius: 4px;
                padding: 8px 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {THEME["button_hover"]};
            }}
            QPushButton:pressed {{
                background-color: {THEME["button_pressed"]};
            }}
            QPushButton:checked {{
                background-color: {THEME["accent"]};
                color: {THEME["background"]};
            }}
        """)
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setSpacing(10)  # Add spacing between panels
        main_layout.setContentsMargins(10, 10, 10, 10)  # Add margins
        
        # Create canvas first
        self.canvas = Canvas()
        
        # Create left panel for legend with fixed width
        left_panel = QWidget()
        left_panel.setFixedWidth(250)  # Fixed width for legend panel
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        self.legend = LegendWidget(self.canvas.departments)
        left_layout.addWidget(self.legend)
        left_layout.addStretch()
        main_layout.addWidget(left_panel)
        
        # Create right panel for canvas and toolbar
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        
        # Create toolbar
        toolbar = QHBoxLayout()
        self.add_node_btn = QPushButton("Add Node")
        self.save_btn = QPushButton("Save")
        self.load_btn = QPushButton("Load")
        self.add_department_btn = QPushButton("Add Department")
        self.connection_mode_btn = QPushButton("Connection Mode")
        self.connection_mode_btn.setCheckable(True)
        self.connection_mode_btn.setChecked(False)
        self.delete_mode_btn = QPushButton("Delete Mode")
        self.delete_mode_btn.setCheckable(True)
        self.delete_mode_btn.setChecked(False)
        self.physics_btn = QPushButton("Physics")
        self.physics_btn.setCheckable(True)
        self.physics_btn.setChecked(False)
        
        toolbar.addWidget(self.add_node_btn)
        toolbar.addWidget(self.add_department_btn)
        toolbar.addWidget(self.connection_mode_btn)
        toolbar.addWidget(self.delete_mode_btn)
        toolbar.addWidget(self.physics_btn)
        toolbar.addWidget(self.save_btn)
        toolbar.addWidget(self.load_btn)
        toolbar.addStretch()
        right_layout.addLayout(toolbar)
        
        # Add canvas to right panel
        right_layout.addWidget(self.canvas)
        
        # Add right panel to main layout
        main_layout.addWidget(right_panel, 1)
        
        # Connect signals
        self.add_node_btn.clicked.connect(self.add_node)
        self.add_department_btn.clicked.connect(self.add_department)
        self.save_btn.clicked.connect(self.save_diagram)
        self.load_btn.clicked.connect(self.load_diagram)
        self.connection_mode_btn.toggled.connect(self.canvas.set_connection_mode)
        self.delete_mode_btn.toggled.connect(self.canvas.set_delete_mode)
        self.physics_btn.toggled.connect(self.canvas.set_physics_enabled)
        
        # Load initial data if available
        self.load_diagram()
    
    def add_node(self):
        """Add a new node to the canvas."""
        name, ok = QInputDialog.getText(
            self, "Add Node", "Enter node name:"
        )
        if ok and name:
            departments = list(self.canvas.departments.keys())
            department, ok = QInputDialog.getItem(
                self, "Add Node", "Select department:",
                departments, 0
            )
            if ok and department:
                # Create node at center of canvas
                position = QPointF(
                    self.canvas.width() / 2,
                    self.canvas.height() / 2
                )
                node = Node(name, department, position)
                self.canvas.nodes.append(node)
                self.canvas.update()
                
    def add_department(self):
        """Add a new department with color."""
        name, ok = QInputDialog.getText(
            self, "Add Department", "Enter department name:"
        )
        if ok and name:
            color = QColorDialog.getColor()
            if color.isValid():
                self.canvas.departments[name] = color.name()
                self.legend.departments = self.canvas.departments
                self.legend.update()
                self.canvas.update()
                
    def save_diagram(self):
        """Save the diagram to a JSON file."""
        data = {
            "nodes": [node.to_dict() for node in self.canvas.nodes],
            "connections": [conn.to_dict() for conn in self.canvas.connections],
            "departments": self.canvas.departments
        }
        _Exe_Util.set_data(data, DATA_FILE)
        QMessageBox.information(self, "Success", "Diagram saved successfully!")
        
    def load_diagram(self):
        """Load the diagram from a JSON file."""
        data = _Exe_Util.get_data(DATA_FILE)
        if data:
            # Clear existing data
            self.canvas.nodes = []
            self.canvas.connections = []
            
            # Load departments
            self.canvas.departments = data.get("departments", DEFAULT_DEPARTMENT_COLORS)
            self.legend.departments = self.canvas.departments
            self.legend.update()
            
            # Load nodes
            node_map = {}
            for node_data in data.get("nodes", []):
                node = Node.from_dict(node_data)
                node_map[node.id] = node
                self.canvas.nodes.append(node)
                
            # Load connections
            for conn_data in data.get("connections", []):
                from_node = node_map.get(conn_data["from"])
                to_node = node_map.get(conn_data["to"])
                if from_node and to_node:
                    self.canvas.connections.append(Connection(from_node, to_node))
                    
            self.canvas.update()

def main():
    app = QApplication(sys.argv)
    window = RelationshipTreeApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main() 