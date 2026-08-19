import sys
import os
import random
import tkinter as tk
import time
import winsound
import wave
import array
import tempfile
import shutil
import requests
import json
import math

import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import _Exe_Util
from animation import Animation
from popup import PopupMenu
from sync import Sync

EXE_NAME = u"EnneaDuck"

class EnneaDuck(tk.Tk):
    def __init__(self):
        super().__init__()
        self.animation = Animation(self)  # Initialize Animation first
        self.popup_menu = PopupMenu(self)  # Initialize PopupMenu
        self.sync = Sync(self)  # Initialize Sync
        self.setup_audio()
        self.setup_gui()  # Call setup_gui after initializing other elements
        self.joke_timer = None
        self.last_joke_time = 0
        self.volume_level = 0.3  # 30% volume
        self.temp_dir = tempfile.mkdtemp()
        self.joke_api_url = "https://v2.jokeapi.dev/joke/Any?blacklistFlags=nsfw,religious,political,racist,sexist,explicit"
        
        # Cursor idle tracking
        self.last_cursor_move_time = time.time()
        self.cursor_idle_threshold = 300  # 5 minutes in seconds
        self.is_cursor_idle = False
        self.last_cursor_pos = (0, 0)
        self.steal_cursor_timer = None
        self.circle_angle = 0  # For circular movement
        self.circle_radius = 100  # Radius of the circle
        self.circle_center = (0, 0)  # Center point of the circle
        
        # Mouse shake detection
        self.last_positions = []  # Store last 5 positions
        self.shake_threshold = 50  # Minimum distance for shake detection
        self.max_positions = 5  # Number of positions to track

    def __del__(self):
        """Cleanup temporary files on exit"""
        try:
            shutil.rmtree(self.temp_dir)
        except:
            pass

    def adjust_volume(self, audio_file, volume=0.3):
        """Adjust the volume of a WAV file
        
        Args:
            audio_file (str): Path to the WAV file
            volume (float): Volume level between 0.0 and 1.0
        
        Returns:
            str: Path to the volume-adjusted temporary file
        """
        try:
            # Create a temporary file
            temp_path = os.path.join(self.temp_dir, os.path.basename(audio_file))
            
            # Copy original file to temp location
            shutil.copy2(audio_file, temp_path)
            
            # Open and adjust volume
            with wave.open(temp_path, 'rb') as wav_file:
                # Read the wave file parameters
                params = wav_file.getparams()
                frames = wav_file.readframes(wav_file.getnframes())
                
                # Convert frames to array
                frame_array = array.array('h', frames)
                
                # Adjust volume
                for i in range(len(frame_array)):
                    frame_array[i] = int(frame_array[i] * volume)
                
                # Create new file
                with wave.open(temp_path, 'wb') as new_wav:
                    new_wav.setparams(params)
                    new_wav.writeframes(frame_array.tobytes())
            
            return temp_path
        except Exception as e:
            print(f"Error adjusting volume: {e}")
            return audio_file

    def setup_audio(self):
        """Setup audio files and paths"""
        self.audio_path = os.path.join(os.path.dirname(__file__), "audio")
        if not os.path.exists(self.audio_path):
            print(f"Warning: Audio directory not found at {self.audio_path}")
            return

        self.duck_sounds = [
            os.path.join(self.audio_path, "duck_1.wav"),
            os.path.join(self.audio_path, "duck_2.wav"),
            os.path.join(self.audio_path, "duck_3.wav")
        ]
        
        # Verify sound files exist
        self.duck_sounds = [sound for sound in self.duck_sounds if os.path.exists(sound)]
        if not self.duck_sounds:
            print("Warning: No valid duck sound files found")

    def play_random_duck_sound(self):
        """Play a random duck sound at reduced volume"""
        if not self.duck_sounds:
            return
            
        sound_file = random.choice(self.duck_sounds)
        try:
            # Adjust volume and get temporary file path
            temp_sound_file = self.adjust_volume(sound_file, self.volume_level)
            print(f"Playing sound: {sound_file} at {self.volume_level*100}% volume")
            winsound.PlaySound(temp_sound_file, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            print(f"Error playing sound: {e}")

    def create_popup_menu(self):
        self.popup_menu = tk.Menu(self, tearoff=0)
        self.popup_menu.add_command(label="Hello.", command=self.say_hello)
        self.popup_menu.add_command(label="Show queue.", command=self.show_queue)
        self.popup_menu.add_separator()
        self.popup_menu.add_command(label="Bye Me.", command=self.destroy)

    def do_popup(self, event):
        try:
            self.popup_menu.tk_popup(event.x_root, event.y_root)
        except Exception as e:
            pass
        finally:
            self.popup_menu.grab_release()

    def setup_gui(self):
        self.app_title = EXE_NAME
        self.window_width = 600
        self.window_height = 250

        # Get screen dimensions
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # Calculate center position
        self.x = (screen_width - self.window_width) // 2
        self.y = (screen_height - self.window_height) // 2

        self.mouse_x = screen_width // 2  # Initialize to screen center
        self.mouse_y = screen_height // 2  # Initialize to screen center

        self.bubble_life = 0
        self.last_time_check = 0
        self.user_name = _Exe_Util.get_username()
        self.last_hover_sound_time = 0  # Track last hover sound time
        self.hover_sound_cooldown = 2.0  # Cooldown in seconds
        
        self.title(EXE_NAME)
        self.geometry("{}x{}+{}+{}".format(self.window_width, self.window_height, self.x, self.y))
        self.config(background="green")
        self.overrideredirect(True)
        self.wm_attributes('-transparentcolor', 'green')
        self.wm_attributes('-topmost', True)

        self.bind('<Button-1>', self.save_last_click_pos)
        self.bind('<B1-Motion>', self.dragging)
        self.bind('<Motion>', self.update_mouse_position)  # Track mouse movement
        self.bind('<Enter>', self.on_mouse_enter)  # Handle mouse enter
        self.bind('<Leave>', self.on_mouse_leave)  # Handle mouse leave

        # Create a frame to contain the talk bubble and duck
        self.content_frame = tk.Frame(self, bg='green')
        self.content_frame.pack(expand=True, fill='both')

        self.talk_bubble = tk.Label(self.content_frame, 
                                  text="talk bubble text", 
                                  font=("Comic Sans MS", 18), 
                                  borderwidth=3, 
                                  relief="solid",
                                  wraplength=500,
                                  justify='left',
                                  bg='white',
                                  padx=10,
                                  pady=5)
        self.talk_bubble.pack(pady=15, padx=15, fill='x')
        self.hide_widget(self.talk_bubble)

        self.duck_label = tk.Label(self.content_frame, bd=0, bg='green')
        self.duck_label.pack(pady=15)
        self.duck_label.bind("<Button-3>", self.popup_menu.do_popup)
        self.duck_label.bind("<Button-1>", self.on_duck_click)

        self.after(1, self.animation.update_animation)
        self.after(1000, self.check_random_joke)  # Start checking for random jokes
        self.after(100, self.update_mouse_position)  # Start periodic mouse position updates

    def show_joke(self, joke):
        """Display a joke in the talk bubble with timed delivery
        
        Args:
            joke (str): The joke text to display
        """
        # Cancel any existing joke timers
        if self.joke_timer:
            self.after_cancel(self.joke_timer)
            
        # Format and display the joke
        if "\n" in joke:
            setup, delivery = joke.split("\n", 1)
            # Show setup first
            self.talk_bubble.configure(text=setup)
            self.show_widget(self.talk_bubble)
            self.play_random_duck_sound()
            
            # Schedule punchline after 10 seconds
            self.joke_timer = self.after(10000, lambda: self.show_punchline(delivery))
        else:
            # Single line joke - show for 15 seconds
            self.talk_bubble.configure(text=joke)
            self.show_widget(self.talk_bubble)
            self.play_random_duck_sound()
            self.joke_timer = self.after(15000, self.hide_widget, self.talk_bubble)

    def show_punchline(self, punchline):
        """Display the punchline of a joke
        
        Args:
            punchline (str): The punchline text to display
        """
        self.talk_bubble.configure(text=punchline)
        self.play_random_duck_sound()
        # Hide after 15 seconds
        self.joke_timer = self.after(15000, self.hide_widget, self.talk_bubble)

    def fetch_joke(self):
        """Fetch a joke from the JokeAPI
        
        Returns:
            str: The joke text or None if fetch fails
        """
        try:
            # Randomly choose between single and two-part jokes
            joke_type = "single" if random.random() < 0.5 else "twopart"
            response = requests.get(f"{self.joke_api_url}&type={joke_type}")
            if response.status_code == 200:
                joke_data = response.json()
                if joke_data["type"] == "single":
                    return joke_data["joke"]
                else:
                    return f"{joke_data['setup']}\n{joke_data['delivery']}"
            return None
        except Exception as e:
            print(f"Error fetching joke: {e}")
            return None

    def check_random_joke(self):
        """Check if it's time to show a random joke"""
        current_time = time.time()
        if current_time - self.last_joke_time > 60:  # Check every minute
            if random.random() < 0.1:  # 10% chance to tell a joke
                joke = self.fetch_joke()
                if joke:
                    self.show_joke(joke)
                    self.last_joke_time = current_time
        self.after(1000, self.check_random_joke)  # Check again in 1 second

    def on_duck_click(self, event):
        """Handle duck click events"""
        self.play_random_duck_sound()
        self.save_last_click_pos(event)
        if random.random() < 0.3:  # 30% chance to tell a joke on click
            joke = self.fetch_joke()
            if joke:  # Only show joke if fetch was successful
                self.show_joke(joke)

    def hide_widget(self, item):
        item.pack_forget()

    def show_widget(self, item):
        item.pack()

    def save_last_click_pos(self, event):
        self.last_click_x = event.x
        self.last_click_y = event.y
        self.play_random_duck_sound()

    def dragging(self, event):
        x, y = event.x - self.last_click_x + self.winfo_x(), event.y - self.last_click_y + self.winfo_y()
        self.geometry("+%s+%s" % (x, y))
        self.x, self.y = x, y
        # Play sound occasionally during drag
        if random.random() < 0.1:  # 10% chance to play sound during drag
            self.play_random_duck_sound()

    def detect_mouse_shake(self, new_pos):
        """Detect if mouse is being shaken
        
        Args:
            new_pos (tuple): Current mouse position (x, y)
            
        Returns:
            bool: True if mouse is being shaken
        """
        if len(self.last_positions) < self.max_positions:
            self.last_positions.append(new_pos)
            return False
            
        # Calculate total distance moved in last few positions
        total_distance = 0
        for i in range(len(self.last_positions) - 1):
            x1, y1 = self.last_positions[i]
            x2, y2 = self.last_positions[i + 1]
            total_distance += math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            
        # Update positions list
        self.last_positions.pop(0)
        self.last_positions.append(new_pos)
        
        return total_distance > self.shake_threshold

    def update_mouse_position(self, event=None):
        """Update the mouse position tracking
        
        Args:
            event (tk.Event, optional): Mouse event. Defaults to None.
        """
        current_time = time.time()
        if event:
            # Update from mouse event
            self.mouse_x = event.x_root
            self.mouse_y = event.y_root
            new_pos = (self.mouse_x, self.mouse_y)
            
            # Check for mouse shake
            if self.is_cursor_idle and self.detect_mouse_shake(new_pos):
                self.is_cursor_idle = False
                if self.steal_cursor_timer:
                    self.after_cancel(self.steal_cursor_timer)
                    self.steal_cursor_timer = None
                self.last_cursor_move_time = current_time
                self.hide_widget(self.talk_bubble)
                return
            
            self.last_cursor_pos = new_pos
            self.last_cursor_move_time = current_time
            self.is_cursor_idle = False
            if self.steal_cursor_timer:
                self.after_cancel(self.steal_cursor_timer)
                self.steal_cursor_timer = None
            self.hide_widget(self.talk_bubble)  # Hide countdown when mouse moves
        else:
            # Update from periodic check
            try:
                # Get cursor position relative to all monitors
                import win32api
                x, y = win32api.GetCursorPos()
                new_pos = (x, y)
                
                # Check for mouse shake
                if self.is_cursor_idle and self.detect_mouse_shake(new_pos):
                    self.is_cursor_idle = False
                    if self.steal_cursor_timer:
                        self.after_cancel(self.steal_cursor_timer)
                        self.steal_cursor_timer = None
                    self.last_cursor_move_time = current_time
                    self.hide_widget(self.talk_bubble)
                    return
                
                # Update mouse position for tracking
                self.mouse_x = x
                self.mouse_y = y
                
                # Check for cursor movement
                if new_pos != self.last_cursor_pos:
                    self.last_cursor_pos = new_pos
                    self.last_cursor_move_time = current_time
                    self.is_cursor_idle = False
                    if self.steal_cursor_timer:
                        self.after_cancel(self.steal_cursor_timer)
                        self.steal_cursor_timer = None
                    self.hide_widget(self.talk_bubble)  # Hide countdown when mouse moves
                else:
                    # Show countdown only in last 10 seconds and not in steal mode
                    remaining_time = int(self.cursor_idle_threshold - (current_time - self.last_cursor_move_time))
                    if 0 < remaining_time <= 10 and not self.is_cursor_idle and not self.steal_cursor_timer:
                        self.talk_bubble.configure(text=f"Stealing cursor in {remaining_time}s...")
                        self.show_widget(self.talk_bubble)
                    elif self.steal_cursor_timer:
                        self.hide_widget(self.talk_bubble)  # Hide countdown when in steal mode
                    
                    # Check if cursor is idle
                    if not self.is_cursor_idle and current_time - self.last_cursor_move_time > self.cursor_idle_threshold:
                        self.is_cursor_idle = True
                        # Set circle center to current position
                        self.circle_center = (self.winfo_x() + self.window_width // 2, 
                                           self.winfo_y() + self.window_height // 2)
                        self.steal_cursor_timer = self.after(100, self.steal_cursor)  # Move more frequently for smoother circle
            except:
                # Fallback to tkinter method if win32api fails
                try:
                    x = self.winfo_pointerx()
                    y = self.winfo_pointery()
                    if x >= 0 and y >= 0:  # Only update if coordinates are valid
                        new_pos = (x, y)
                        
                        # Check for mouse shake
                        if self.is_cursor_idle and self.detect_mouse_shake(new_pos):
                            self.is_cursor_idle = False
                            if self.steal_cursor_timer:
                                self.after_cancel(self.steal_cursor_timer)
                                self.steal_cursor_timer = None
                            self.last_cursor_move_time = current_time
                            self.hide_widget(self.talk_bubble)
                            return
                            
                        self.mouse_x = x
                        self.mouse_y = y
                        if new_pos != self.last_cursor_pos:
                            self.last_cursor_pos = new_pos
                            self.last_cursor_move_time = current_time
                            self.is_cursor_idle = False
                            if self.steal_cursor_timer:
                                self.after_cancel(self.steal_cursor_timer)
                                self.steal_cursor_timer = None
                            self.hide_widget(self.talk_bubble)  # Hide countdown when mouse moves
                except:
                    pass  # Ignore any errors during periodic updates
        
        # Schedule next update
        self.after(100, self.update_mouse_position)

    def steal_cursor(self):
        """Steal the cursor by moving it in a circle with the duck"""
        if self.is_cursor_idle:
            # Calculate new position on the circle
            self.circle_angle += 0.1  # Increment angle for circular motion
            if self.circle_angle >= 2 * math.pi:
                self.circle_angle = 0
                
            # Calculate new position
            new_x = self.circle_center[0] + self.circle_radius * math.cos(self.circle_angle)
            new_y = self.circle_center[1] + self.circle_radius * math.sin(self.circle_angle)
            
            # Ensure new position is within screen bounds
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            new_x = max(0, min(new_x, screen_width - self.window_width))
            new_y = max(0, min(new_y, screen_height - self.window_height))
            
            # Move duck to new position
            self.geometry(f"+{int(new_x)}+{int(new_y)}")
            
            # Update duck's animation state based on movement direction
            if math.cos(self.circle_angle) > 0:
                self.animation.current_event = "walking_right"
            else:
                self.animation.current_event = "walking_left"
            
            # Move cursor to duck's new position
            try:
                import win32api
                cursor_x = int(new_x + self.window_width // 2)
                cursor_y = int(new_y + self.window_height // 2)
                win32api.SetCursorPos((cursor_x, cursor_y))
                self.mouse_x = cursor_x
                self.mouse_y = cursor_y
                self.last_cursor_pos = (cursor_x, cursor_y)
            except:
                pass  # Ignore if win32api is not available
            
            # Schedule next steal attempt
            self.steal_cursor_timer = self.after(100, self.steal_cursor)  # Move every 100ms for smooth circle

    def on_mouse_enter(self, event):
        """Handle mouse entering the duck window"""
        current_time = time.time()
        if current_time - self.last_hover_sound_time >= self.hover_sound_cooldown:
            self.play_random_duck_sound()
            self.last_hover_sound_time = current_time

    def on_mouse_leave(self, event):
        """Handle mouse leaving the duck window"""
        pass  # No action needed when mouse leaves



