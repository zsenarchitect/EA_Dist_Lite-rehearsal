import tkinter as tk
import signal
import sys
import math
import random
import time
import _Exe_Util
from typing import Optional, Tuple

# Global debug mode flag
DEBUG_MODE = True

class TopProgressBar:
    def __init__(self):
        self.update_every_x_secs = 10
        self.root = tk.Tk()
        
        # Animation parameters
        self._setup_animation_params()
        
        # Window configuration
        self._setup_window()
        
        # Progress tracking
        self._setup_progress_tracking()
        
        # Event bindings
        self._setup_event_bindings()
        
        # Start update loop
        self.update_progress()
    
    def _setup_window(self):
        """Configure the main window properties"""
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True, '-transparentcolor', '#1a1a1a')
        self.screen_width = self.root.winfo_screenwidth()
        self.root.geometry(f"{self.screen_width}x{self.min_height}+0+0")
        
        # Create canvas with transparent background
        self.canvas = tk.Canvas(self.root, height=self.min_height, width=self.screen_width, 
                              bg='#1a1a1a', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
    
    def _setup_animation_params(self):
        """Initialize animation-related parameters"""
        self.min_height = 2
        self.max_height = 6
        self.hover_height = 20
        self.current_height = self.min_height
        self.height_offset = 0
        self.color_offset = 0
        self.is_hovering = False
        self.animation_speed = 0.1
        self.color_shift_speed = 0.001
    
    def _setup_progress_tracking(self):
        """Initialize progress tracking variables"""
        self.current_progress = 0
        self.debug_progress = 0.0
        self.is_active = True
        self.additional_label = None
        self.counter = 0
        self.total = 0
        self.start_time = time.time()
    
    def _setup_event_bindings(self):
        """Setup event handlers and signal handlers"""
        self.canvas.bind('<Enter>', self.on_enter)
        self.canvas.bind('<Leave>', self.on_leave)
        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)
    
    def generate_color(self) -> str:
        """Generate a smooth shifting color using HSV to RGB conversion"""
        hue = (self.color_offset * 30) % 360
        h = hue / 360
        s = 1.0
        v = 1.0
        
        i = math.floor(h * 6)
        f = h * 6 - i
        p = v * (1 - s)
        q = v * (1 - f * s)
        t = v * (1 - (1 - f) * s)
        
        if i % 6 == 0: r, g, b = v, t, p
        elif i % 6 == 1: r, g, b = q, v, p
        elif i % 6 == 2: r, g, b = p, v, t
        elif i % 6 == 3: r, g, b = p, q, v
        elif i % 6 == 4: r, g, b = t, p, v
        else: r, g, b = v, p, q
        
        return '#{:02x}{:02x}{:02x}'.format(int(r*255), int(g*255), int(b*255))
    
    def _get_elapsed_time_str(self) -> str:
        """Format elapsed time into a readable string"""
        elapsed_seconds = time.time() - self.start_time
        hours = int(elapsed_seconds // 3600)
        minutes = int((elapsed_seconds % 3600) // 60)
        seconds = int(elapsed_seconds % 60)
        
        time_parts = []
        if hours > 0:
            time_parts.append("{:02d}h".format(hours))
        if minutes > 0 or hours > 0:
            time_parts.append("{:02d}m".format(minutes))
        time_parts.append("{:02d}s".format(seconds))
        
        return "".join(time_parts)
    
    def _draw_progress_bar(self, progress_width: float, current_color: str):
        """Draw the progress bar with current progress"""
        if progress_width > 0:
            # Draw main progress bar
            self.canvas.create_rectangle(0, 0, progress_width, self.current_height, 
                                      fill=current_color, outline='')
            
            if self.is_hovering:
                self._draw_hover_elements(progress_width)
    
    def _draw_hover_elements(self, progress_width: float):
        """Draw elements that appear on hover"""
        # Draw progress percentage
        label_text = "{:.1f}%".format(self.current_progress)
        if self.additional_label:
            label_text = "{} - {:.1f}%".format(self.additional_label, self.current_progress)
        
        label_x = min(progress_width, self.screen_width - 50) - 3
        self.canvas.create_text(
            label_x, self.current_height/2,
            text=label_text,
            fill='black',
            font=('Arial', 8),
            anchor='e'
        )
        
        # Draw counter and time
        x = self.screen_width - 10 if self.current_progress < 20 else 10
        align = 'e' if self.current_progress < 20 else 'w'
        y = self.current_height/2
        
        time_str = self._get_elapsed_time_str()
        text = "{} of {}: {}".format(self.counter, self.total, time_str)
        
        text_item = self.canvas.create_text(
            x, y,
            text=text,
            fill='black',
            font=('Arial', 8),
            anchor=align,
            tags='progress_text'
        )
        
        if align == 'e':
            self._add_text_background(text_item)
    
    def _add_text_background(self, text_item):
        """Add white background to text when needed"""
        bbox = self.canvas.bbox(text_item)
        padding = 2
        self.canvas.create_rectangle(
            bbox[0] - padding,
            bbox[1] - padding,
            bbox[2] + padding,
            bbox[3] + padding,
            fill='white',
            outline='',
            tags='text_bg'
        )
        self.canvas.tag_raise(text_item)
    
    def handle_exit(self, signum, frame):
        """Handle program exit"""
        print("Closing progress bar...")
        self.root.quit()
        sys.exit(0)
    
    def on_enter(self, event):
        self.is_hovering = True
    
    def on_leave(self, event):
        self.is_hovering = False
    
    def update_progress(self):
        """Update progress bar state and appearance"""
        if DEBUG_MODE:
            self._update_debug_progress()
        else:
            self._update_real_progress()
        
        self._update_animation()
        self._draw_frame()
        
        # Schedule next update
        self.root.after(self.update_every_x_secs, self.update_progress)
    
    def _update_debug_progress(self):
        """Update progress in debug mode"""
        if random.random() > 0.9:
            self.debug_progress += random.uniform(0, 0.5)
        if self.debug_progress >= 100:
            self.handle_exit(None, None)
        
        self.current_progress = self.debug_progress
        self.additional_label = "Debug Mode"
        print(self.current_progress)
    
    def _update_real_progress(self):
        """Update progress from real data"""
        try:
            data = _Exe_Util.get_data('progressbar')
            if data:
                self.current_progress = data.get('progress', 0)
                self.is_active = data.get('is_active', False)
                self.additional_label = data.get("label", None)
                self.counter = data.get("counter", 0)
                self.total = data.get("total", 0)
                self.start_time = data.get("start_time", 0)
            
            if self.current_progress >= 100 or not self.is_active:
                self.handle_exit(None, None)
        except:
            pass
    
    def _update_animation(self):
        """Update animation parameters"""
        self.height_offset = (self.height_offset + 0.05) % (2 * math.pi)
        target_height = self.hover_height if self.is_hovering else (
            self.min_height + (math.sin(self.height_offset) + 1) * (self.max_height - self.min_height) / 2
        )
        
        self.current_height += (target_height - self.current_height) * self.animation_speed
        self.color_offset = (self.color_offset + self.color_shift_speed) % (2 * math.pi)
    
    def _draw_frame(self):
        """Draw the current frame"""
        self.root.geometry(f"{self.screen_width}x{int(self.current_height)}+0+0")
        self.canvas.configure(height=self.current_height)
        self.canvas.delete("all")
        
        progress_width = (self.screen_width * self.current_progress) / 100
        current_color = self.generate_color()
        self._draw_progress_bar(progress_width, current_color)
    
    def run(self):
        """Start the main event loop"""
        self.root.mainloop()

@_Exe_Util.try_catch_error
def main():
    app = TopProgressBar()
    app.run()

if __name__ == "__main__":
    main()
