"""
This is the old one and no longer maintained.
"""
raise DeprecationWarning(
    "This script is deprecated and no longer maintained. "
    "Please use the updated version if available."
)


import os
import random
import tkinter as tk
from PIL import Image as PILImage
import math
import time
import threading
import requests
import winsound
from tkinter import ttk

class DesktopPet:
    def __init__(self):
        self.window = tk.Tk()
        self.setup_window()
        self.setup_animations()
        self.setup_interactions()
        
        # Animation state
        self.current_state = "idle"
        self.frame_index = 0
        
        # Movement properties
        self.move_speed = 1.5  # Reduced speed for gentler movement
        self.target_x = None
        self.target_y = None
        self.is_moving = False
        self.movement_threshold = 10  # Increased threshold for smoother movement
        self.last_cursor_move_time = time.time()
        self.is_stealing_cursor = False
        
        # Cursor tracking
        self.last_cursor_x = 0
        self.last_cursor_y = 0
        
        # Behavior properties
        self.behavior_states = ["idle", "random_walk", "follow_cursor", "steal_cursor", "sleep", "happy", "attention", "shake"]
        self.current_behavior = "idle"
        self.behavior_change_time = time.time()
        self.behavior_duration = random.uniform(5, 12)  # Longer durations for more relaxed behavior
        
        # Speech bubble
        self.setup_speech_bubble()
        
        # Start animation loop
        self.update_animation()
        # Start movement update
        self.update_movement()
        # Start behavior update
        self.update_behavior()
        
    def setup_window(self):
        """Configure the main window properties"""
        self.window.geometry("128x128+500+500")  # Initial size and position
        self.window.overrideredirect(True)  # Remove window border
        self.window.attributes('-topmost', True)  # Keep on top
        self.window.config(bg='green')  # Green for transparency
        self.window.wm_attributes('-transparentcolor', 'green')
        
    def setup_animations(self):
        """Load animation frames from the EnneaDuck assets directory"""
        self.animations = {}
        self.assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "EnneaDuck", "images")
        
        # Define available animations
        self.states = {
            "idle": {"frames": [], "duration": 200},  # Slower idle animation
            "walk_left": {"frames": [], "duration": 150},
            "walk_right": {"frames": [], "duration": 150},
            "sleep": {"frames": [], "duration": 300},  # Sleep state
            "happy": {"frames": [], "duration": 200},  # Happy state
            "attention": {"frames": [], "duration": 200},  # Attention state
            "shake": {"frames": [], "duration": 200}  # Shake state
        }
        
        # Map our states to EnneaDuck animations
        animation_map = {
            "idle": "idle.gif",
            "walk_left": "walking_left.gif",
            "walk_right": "walking_right.gif",
            "sleep": "sleep.gif",
            "happy": "walking_positive.gif",
            "attention": "attention.gif",
            "shake": "shake.gif"
        }
        
        # Load animations
        for state, gif_file in animation_map.items():
            gif_path = os.path.join(self.assets_dir, gif_file)
            if os.path.exists(gif_path):
                self.load_animation(state, gif_path)
            else:
                print(f"Warning: Animation file not found: {gif_path}")
                
        # Create label for displaying animations
        self.pet_label = tk.Label(self.window, bd=0, bg='green')
        self.pet_label.pack()
        
    def load_animation(self, state, gif_path):
        """Load frames from a GIF file"""
        try:
            with PILImage.open(gif_path) as img:
                frames = []
                frame_count = 0
                while True:
                    try:
                        img.seek(frame_count)
                        frames.append(tk.PhotoImage(file=gif_path, format=f'gif -index {frame_count}'))
                        frame_count += 1
                    except EOFError:
                        break
                self.states[state]["frames"] = frames
        except Exception as e:
            print(f"Failed to load animation {state}: {e}")
            
    def setup_interactions(self):
        """Setup mouse interactions"""
        self.window.bind('<Button-1>', self.start_drag)
        self.window.bind('<B1-Motion>', self.on_drag)
        self.window.bind('<ButtonRelease-1>', self.stop_drag)
        self.window.bind('<Motion>', self.update_cursor_position)
        self.window.bind('<Button-3>', self.show_menu)
        
        # Create right-click menu
        self.menu = tk.Menu(self.window, tearoff=0)
        self.menu.add_command(label="Exit", command=self.window.quit)
        
        # Dragging state
        self.is_dragging = False
        
    def start_drag(self, event):
        """Save initial position for dragging"""
        self.is_dragging = True
        self.drag_x = event.x
        self.drag_y = event.y
        
    def stop_drag(self, event):
        """Stop dragging"""
        self.is_dragging = False
        
    def on_drag(self, event):
        """Handle dragging the pet"""
        if self.is_dragging:
            x = self.window.winfo_x() - (self.drag_x - event.x)
            y = self.window.winfo_y() - (self.drag_y - event.y)
            self.window.geometry(f"+{x}+{y}")
        
    def update_cursor_position(self, event=None):
        """Update the target position based on cursor movement"""
        if not self.is_dragging:
            current_x = self.window.winfo_pointerx()
            current_y = self.window.winfo_pointery()
            
            # Check if cursor has moved
            if (current_x != self.last_cursor_x or current_y != self.last_cursor_y):
                self.last_cursor_move_time = time.time()
                self.last_cursor_x = current_x
                self.last_cursor_y = current_y
            
            # Update target position if following cursor
            if self.current_behavior in ["follow_cursor", "steal_cursor"]:
                self.target_x = current_x
                self.target_y = current_y
                self.is_moving = True
        
    def show_menu(self, event):
        """Show right-click menu"""
        self.menu.post(event.x_root, event.y_root)
        
    def setup_speech_bubble(self):
        """Setup the speech bubble window"""
        self.bubble_window = tk.Toplevel(self.window)
        self.bubble_window.overrideredirect(True)
        self.bubble_window.attributes('-topmost', True)
        self.bubble_window.withdraw()  # Hide initially
        
        # Create a frame with rounded corners
        self.bubble_frame = ttk.Frame(self.bubble_window, style='Bubble.TFrame')
        self.bubble_frame.pack(padx=10, pady=10)
        
        # Create the text label
        self.bubble_label = ttk.Label(self.bubble_frame, 
                                    wraplength=200,
                                    style='Bubble.TLabel')
        self.bubble_label.pack()
        
        # Configure style for rounded corners
        style = ttk.Style()
        style.configure('Bubble.TFrame', background='white')
        style.configure('Bubble.TLabel', background='white')
        
    def show_speech_bubble(self, text, duration=5):
        """Show a speech bubble with text for a duration"""
        # Position bubble above pet
        x = self.window.winfo_x() + self.window.winfo_width()//2 - 100
        y = self.window.winfo_y() - 100
        
        self.bubble_label.configure(text=text)
        self.bubble_window.geometry(f"+{x}+{y}")
        self.bubble_window.deiconify()
        
        # Play sound effect
        self.play_sound("talk")
        
        # Schedule bubble to hide
        self.window.after(duration * 1000, self.bubble_window.withdraw)
        
    def get_random_joke(self):
        """Get a random joke from an API, avoiding inappropriate content"""
        try:
            # Use misc, dark, and pun categories
            categories = ["Misc", "Dark", "Pun"]
            category = random.choice(categories)
            response = requests.get(f"https://v2.jokeapi.dev/joke/{category}?safe-mode&type=single")
            
            if response.status_code == 200:
                joke = response.json()
                joke_text = joke.get("joke")
                
                if not joke_text:
                    return None
                    
                # Filter out inappropriate content
                inappropriate_keywords = ["programmer", "coding", "computer", "nerd", "geek", "sex", "race", "gender"]
                if any(keyword.lower() in joke_text.lower() for keyword in inappropriate_keywords):
                    return None
                return joke_text
        except:
            return None
            
    def play_sound(self, sound_type):
        """Play a gentle sound effect"""
        sound_dir = os.path.join(os.path.dirname(__file__), "assets", "sounds")
        sound_files = {
            "talk": "soft_chime.wav",  # Gentle chime for talking
            "walk": "soft_step.wav",   # Soft footstep sound
            "steal": "soft_woosh.wav"  # Gentle whoosh sound
        }
        
        if sound_type in sound_files:
            sound_path = os.path.join(sound_dir, sound_files[sound_type])
            if os.path.exists(sound_path):
                try:
                    # Play sound at lower volume
                    winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                except:
                    pass
                    
    def get_cursor_position(self):
        """Get the current cursor position"""
        return (self.window.winfo_pointerx(), self.window.winfo_pointery())
        
    def update_cursor_movement_time(self):
        """Update the last time the cursor moved"""
        current_x, current_y = self.get_cursor_position()
        if hasattr(self, '_last_x') and hasattr(self, '_last_y'):
            if current_x != self._last_x or current_y != self._last_y:
                self.last_cursor_move_time = time.time()
        self._last_x = current_x
        self._last_y = current_y
        
    def update_behavior(self):
        """Update pet behavior based on time and cursor movement"""
        current_time = time.time()
        
        # Check if it's time to change behavior
        if current_time - self.behavior_change_time > self.behavior_duration:
            # Choose new behavior
            if self.current_behavior == "steal_cursor":
                # After stealing cursor, go back to idle
                self.current_behavior = "idle"
            else:
                # Randomly choose new behavior
                self.current_behavior = random.choice(self.behavior_states)
            
            # Set new duration
            self.behavior_duration = random.uniform(5, 12)
            self.behavior_change_time = current_time
            
            # Handle special behaviors
            if self.current_behavior == "steal_cursor":
                self.is_stealing_cursor = True
                self.play_sound("steal")
            elif self.current_behavior == "happy":
                self.play_sound("talk")
                joke = self.get_random_joke()
                if joke:  # Only show speech bubble if we got a valid joke
                    self.show_speech_bubble(joke)
            elif self.current_behavior == "attention":
                self.play_sound("talk")
            elif self.current_behavior == "shake":
                self.play_sound("walk")
        
        # Update animation state based on behavior
        if self.current_behavior == "random_walk" or self.current_behavior == "follow_cursor":
            if self.target_x and self.target_x < self.window.winfo_x():
                self.current_state = "walk_left"
            elif self.target_x and self.target_x > self.window.winfo_x():
                self.current_state = "walk_right"
            else:
                self.current_state = "idle"
        elif self.current_behavior == "steal_cursor":
            self.current_state = "walk_right" if self.target_x > self.window.winfo_x() else "walk_left"
        elif self.current_behavior == "sleep":
            self.current_state = "sleep"
        elif self.current_behavior == "happy":
            self.current_state = "happy"
        elif self.current_behavior == "attention":
            self.current_state = "attention"
        elif self.current_behavior == "shake":
            self.current_state = "shake"
        else:
            self.current_state = "idle"
        
        # Schedule next update
        self.window.after(100, self.update_behavior)
        
    def update_movement(self):
        """Update pet position to move towards target"""
        if not self.is_dragging and self.is_moving and self.target_x is not None:
            # Get current position (center of window)
            current_x = self.window.winfo_x() + self.window.winfo_width() // 2
            current_y = self.window.winfo_y() + self.window.winfo_height() // 2
            
            # Calculate distance to target
            dx = self.target_x - current_x
            dy = self.target_y - current_y
            distance = math.sqrt(dx * dx + dy * dy)
            
            # Only move if we're far enough from the target
            if distance > self.movement_threshold:
                # Calculate movement
                move_x = (dx / distance) * self.move_speed
                move_y = (dy / distance) * self.move_speed
                
                # Update position
                new_x = self.window.winfo_x() + int(move_x)
                new_y = self.window.winfo_y() + int(move_y)
                self.window.geometry(f"+{new_x}+{new_y}")
                
                # Update animation state based on movement direction
                if abs(move_x) > abs(move_y):
                    self.current_state = "walk_right" if move_x > 0 else "walk_left"
                    # Play walk sound occasionally
                    if random.random() < 0.1:  # 10% chance per update
                        self.play_sound("walk")
                else:
                    self.current_state = "idle"
            else:
                self.current_state = "idle"
                self.is_moving = False
        
        # Schedule next movement update
        self.window.after(20, self.update_movement)
        
    def update_animation(self):
        """Update the current animation frame"""
        if self.current_state in self.states and self.states[self.current_state]["frames"]:
            frames = self.states[self.current_state]["frames"]
            duration = self.states[self.current_state]["duration"]
            
            # Update current frame
            self.pet_label.configure(image=frames[self.frame_index])
            
            # Move to next frame
            self.frame_index = (self.frame_index + 1) % len(frames)
        
        # Schedule next update
        self.window.after(50, self.update_animation)
        
    def run(self):
        """Start the application"""
        # Start tracking cursor position
        self.window.bind('<Enter>', self.update_cursor_position)
        self.window.bind('<Leave>', self.update_cursor_position)
        
        # Start the main loop
        self.window.mainloop()

if __name__ == "__main__":
    pet = DesktopPet()
    pet.run()
