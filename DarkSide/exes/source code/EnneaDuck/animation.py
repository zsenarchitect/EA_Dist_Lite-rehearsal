import random
import tkinter as tk
from PIL import Image as pim
import os
import math
import datetime
import time

class Animation:
    def __init__(self, parent):
        self.image_path = "{}\\images".format(os.path.dirname(os.path.abspath(__file__)))
        self.FPS = 12
        self.animation_wait_time = int(1000 / self.FPS)
        self.parent = parent
        self.cycle_animation_frame_index = 0
        self.current_event = "idle"
        self.walk_speed = 3  # Pixels per frame
        self.walk_threshold = 50  # Distance threshold to start walking
        self.last_event = None  # Track last event for change detection
        self.last_direction_change = 0  # Track time of last direction change
        self.direction_change_delay = 2.0  # Minimum seconds between direction changes
        self.min_direction_change_distance = 100  # Minimum pixels to move before changing direction
        self.last_log_time = 0  # Track time of last log
        self.log_interval = 1.0  # Log every second
        
        # Character selection (default to duck)
        self.current_character = "duck"

        # Initialize position tracking
        self.parent.x = self.parent.winfo_x()
        self.parent.y = self.parent.winfo_y()
        self.last_position = (self.parent.x, self.parent.y)

        self.stage_list = ["idle", "rotate", "swing", "attention", "walking_left", "walking_right"]
        self.load_character_assets()

        # number multipler here increae the chance of this item being randomly selected
        self.next_event_mapping = {
            "idle": ["idle"] * 15 + ["rotate"] + ["walking_left"] + ["walking_right"] + ["swing"] * 3,
            "rotate": ["idle"] * 3 + ["rotate"] * 0 + ["walking_left"] * 2 + ["walking_right"] + ["swing"] * 3,
            "walking_left": ["idle"] * 0 + ["rotate"] * 2 + ["walking_left"] * 0 + ["walking_right"] + ["swing"] * 3,
            "walking_right": ["idle"] * 10 + ["rotate"] * 2 + ["walking_left"] + ["walking_right"] + ["swing"] * 3,
            "swing": ["idle"] * 10 + ["rotate"] * 2 + ["walking_left"] + ["walking_right"] + ["swing"] * 10,
            "attention": ["idle"] * 0 + ["rotate"] * 10 + ["walking_left"] * 10 + ["walking_right"] * 10 + ["swing"] * 2 + ["attention"] * 8
        }
        self.reset_animation_data()

    def load_character_assets(self):
        """Load animation assets for the current character"""
        character_path = "{}\\{}".format(self.image_path, self.current_character)
        for stage in self.stage_list:
            gif_path = "{}\\{}.gif".format(character_path, stage)
            try:
                frame_count = self.count_frames_in_gif(gif_path)
                frames = [tk.PhotoImage(file=gif_path, format='gif -index %i' % (i)) for i in range(frame_count)]
                setattr(self, stage, frames)
            except Exception as e:
                print(f"Error loading {stage} for {self.current_character}: {e}")
                # Fallback to empty frames if file not found
                setattr(self, stage, [])

    def change_character(self, character):
        """Change the current character and reload assets
        
        Args:
            character (str): Character name ('duck' or 'cat')
        """
        if character in ["duck", "cat"] and character != self.current_character:
            self.current_character = character
            self.load_character_assets()
            self.reset_animation_data()
            print(f"Character changed to: {character}")

    def log_position(self):
        current_time = time.time()
        if current_time - self.last_log_time >= self.log_interval:
            duck_x = self.parent.winfo_x() + self.parent.window_width // 2
            duck_y = self.parent.winfo_y() + self.parent.window_height // 2
            dx = self.parent.mouse_x - duck_x
            dy = self.parent.mouse_y - duck_y
            distance = math.sqrt(dx * dx + dy * dy)
            
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] Position: {self.current_character.capitalize()}({duck_x}, {duck_y}), Mouse({self.parent.mouse_x}, {self.parent.mouse_y}), Distance: {distance:.1f}")
            self.last_log_time = current_time

    def log_action_change(self, new_action):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {self.current_character.capitalize()} action changed: {self.last_event} -> {new_action}")
        self.last_event = new_action

    def count_frames_in_gif(self, file_path):
        with pim.open(file_path) as img:
            try:
                return img.n_frames
            except AttributeError:
                # Fallback for some PIL versions
                return 1
        
    def reset_animation_data(self):
        # Check if current_event is valid
        if hasattr(self, self.current_event):
            self.frames = getattr(self, self.current_event)
        else:
            print(f"Error: '{self.current_event}' is not a valid attribute of the parent.")
            self.frames = []  # Set to an empty list or handle as needed
        self.current_event_length = len(self.frames)
        self.cycle_animation_frame_index = 0

    def update_animation(self):
        # Add a condition to prevent infinite recursion
        if self.cycle_animation_frame_index < len(self.frames):  # Ensure we don't exceed frame count
            self.parent.duck_label.configure(image=self.frames[self.cycle_animation_frame_index])
            self.cycle_animation_frame_index += 1  # Move to the next frame

            # Log position information
            self.log_position()

            # Calculate distance to mouse
            duck_x = self.parent.winfo_x() + self.parent.window_width // 2
            duck_y = self.parent.winfo_y() + self.parent.window_height // 2
            dx = self.parent.mouse_x - duck_x
            dy = self.parent.mouse_y - duck_y
            distance = math.sqrt(dx * dx + dy * dy)

            # Calculate distance moved since last position
            current_position = (self.parent.x, self.parent.y)
            distance_moved = math.sqrt((current_position[0] - self.last_position[0])**2 + 
                                     (current_position[1] - self.last_position[1])**2)

            # Check if follow cursor is enabled
            follow_cursor_enabled = self.parent.popup_menu.follow_cursor.get()

            # Only move if we're in a walking animation or if follow cursor is enabled
            if self.current_event in ["walking_left", "walking_right"] or follow_cursor_enabled:
                # If mouse is far enough or follow cursor is enabled, walk towards it
                if distance > self.walk_threshold or follow_cursor_enabled:
                    # Calculate direction
                    new_event = "walking_right" if dx > 0 else "walking_left"
                    current_time = time.time()
                    
                    # Only change direction if enough time has passed and we've moved enough distance
                    if (new_event != self.current_event and 
                        current_time - self.last_direction_change >= self.direction_change_delay and
                        distance_moved >= self.min_direction_change_distance):
                        self.current_event = new_event
                        self.log_action_change(new_event)
                        self.last_direction_change = current_time
                        self.last_position = current_position
                        self.reset_animation_data()
                    
                    # Calculate movement in both X and Y directions
                    if distance > 0:  # Avoid division by zero
                        # Normalize the direction vector
                        dx_normalized = dx / distance
                        dy_normalized = dy / distance
                        
                        # Use slower speed when follow cursor is enabled for more gentle movement
                        current_walk_speed = self.walk_speed * 0.3 if follow_cursor_enabled else self.walk_speed
                        
                        # Move in both directions proportionally
                        self.parent.x += dx_normalized * current_walk_speed
                        self.parent.y += dy_normalized * current_walk_speed
                    
                    # Update window position with integer coordinates
                    self.parent.geometry("+%d+%d" % (int(self.parent.x), int(self.parent.y)))
                else:
                    # If close to mouse and follow cursor is disabled, go back to idle
                    if not follow_cursor_enabled:
                        self.current_event = "idle"
                        self.log_action_change("idle")
                        self.reset_animation_data()

        else:
            self.cycle_animation_frame_index = 0  # Reset index or stop animation
            if self.current_event not in ["walking_left", "walking_right"]:
                new_event = random.choice(self.next_event_mapping[self.current_event])
                if new_event != self.current_event:
                    self.current_event = new_event
                    self.log_action_change(new_event)
            self.reset_animation_data()
        self.parent.after(self.animation_wait_time, self.update_animation)  # Schedule next update


