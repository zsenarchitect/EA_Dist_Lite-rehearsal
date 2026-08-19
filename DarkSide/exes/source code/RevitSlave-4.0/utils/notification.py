"""
RevitSlave4 Notification System
================================

Displays random loading messages as popup notifications.
Ported from RevitSlave-2.0 notification system.
"""

import random
import time
import math
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import Optional, List

# Global tracking for notification stacking
_active_notifications: List['LoadingNotification'] = []
MAX_VISIBLE_NOTIFICATIONS = 5  # Maximum notifications visible on screen
_notification_counter = 0  # Counter for unique notification IDs

def cleanup_all_notifications():
    """Clean up all active notifications (useful for shutdown)"""
    try:
        notifications_to_close = _active_notifications.copy()
        for notification in notifications_to_close:
            notification.close()
        _active_notifications.clear()
    except:
        pass

def _enforce_notification_limit():
    """Enforce the maximum notification limit by closing oldest notifications"""
    try:
        while len(_active_notifications) > MAX_VISIBLE_NOTIFICATIONS:
            # Close the oldest notification (first in list)
            oldest_notification = _active_notifications[0]
            oldest_notification.force_close()
            
            # Reposition remaining notifications to shift up and fill gaps
            _reposition_all_notifications()
    except:
        pass

def _reposition_all_notifications():
    """Reposition all active notifications to maintain compact stack"""
    try:
        for i, notification in enumerate(_active_notifications):
            if notification.is_alive and hasattr(notification, 'window'):
                # Calculate new position based on current index
                base_y = 50
                stack_spacing = notification.window_height + 10
                new_y = base_y + (i * stack_spacing)
                
                # Use direct positioning for reliability (faster and more reliable than animation)
                try:
                    notification.window.geometry("{}x{}+{}+{}".format(
                        notification.window_width,
                        notification.window_height,
                        notification.x,
                        new_y
                    ))
                except:
                    # If direct positioning fails, try animation
                    notification._animate_to_position(new_y)
    except:
        pass

def _get_loading_messages():
    """
    Load random messages from the loading screen message file.
    Returns a list of messages. Falls back to default if file not found.
    """
    try:
        # RevitSlave4: assets folder is at parent.parent level
        message_file = Path(__file__).parent.parent / "assets" / "_loading_screen_message.txt"
        
        if not message_file.exists():
            return ["Processing... Please wait...", "Working hard...", "Almost there..."]
        
        with open(str(message_file), 'r', encoding='utf-8') as f:
            messages = [line.strip() for line in f if line.strip()]
        
        return messages if messages else ["Processing..."]
        
    except Exception as e:
        # Gracefully fall back to default messages
        return ["Processing... Please wait..."]


def get_random_loading_message():
    """Get a random loading message"""
    messages = _get_loading_messages()
    return random.choice(messages)


class LoadingNotification:
    """
    Animated popup notification for loading messages.
    Based on MessageApp from Messenger.py
    
    CRITICAL: This class must NEVER crash the main application.
    All operations are wrapped in try-catch blocks.
    """
    
    def __init__(self, 
                 text=None,
                 animation_in_duration=0.5,
                 animation_stay_duration=5.0,
                 animation_fade_duration=2.0,
                 width=600,
                 height=160,
                 x_offset=0,
                 background_color="#2980B9",
                 font_size=26,
                 font_color="white",
                 font_family="Comic Sans MS"):
        """
        Initialize notification window.
        
        CRITICAL: If ANY part fails, the notification simply won't show.
        The main app will continue normally.
        """
        
        # Default to not alive (will be set to True only if fully initialized)
        self.is_alive = False
        self._after_id = None
        
        try:
            # If no text provided, get a random loading message
            try:
                if text is None:
                    text = get_random_loading_message()
            except:
                # If message loading fails, use fallback
                text = "Processing..."
            
            # Try to use existing Tk instance, or create Toplevel if one exists
            try:
                # Try to get existing root
                root = tk._default_root
                if root and root.winfo_exists():
                    # Use Toplevel instead of creating new Tk
                    self.window = tk.Toplevel(root)
                    self.window.withdraw()  # Hide initially
                else:
                    # No existing root, create new Tk
                    self.window = tk.Tk()
                    self.window.withdraw()  # Hide initially
            except:
                # Fallback: create new Tk
                self.window = tk.Tk()
                self.window.withdraw()  # Hide initially
            
            self.beginning_time = time.time()
            
            # Prefer single line, wider notifications
            max_notification_width = 2400  # Increased max width for single line preference (2x)
            min_notification_height = 120   # Minimum height for single line (2x)
            
            # First, try to measure text as single line (no wrapping)
            temp_label = tk.Label(
                self.window,
                text=text,
                font=(font_family, font_size, "normal"),
                justify="center"
            )
            temp_label.pack()
            self.window.update()
            
            # Get single-line text dimensions with padding
            text_width = temp_label.winfo_reqwidth() + 160  # More horizontal padding (2x)
            text_height = temp_label.winfo_reqheight() + 80  # Less vertical padding for single line (2x)
            temp_label.destroy()
            
            # Use larger of minimum size or measured text size, but cap at max width
            self.window_width = min(max(width, text_width), max_notification_width)
            self.window_height = max(min_notification_height, text_height)
            
            # Calculate wraplength only if needed (when we hit max width)
            self.calculated_wraplength = self.window_width - 160 if text_width > max_notification_width else 0
            
            # Calculate position with stacking support
            screen_width = self.window.winfo_screenwidth()
            screen_height = self.window.winfo_screenheight()
            
            # Base position (top-right corner, not center)
            self.x = screen_width - self.window_width - 20  # 20px from right edge
            base_y = 50  # Start 50px from top
            
            # Assign unique ID and calculate position
            global _notification_counter
            self.notification_id = _notification_counter
            _notification_counter += 1
            
            # Calculate stacked position based on current list length (will be updated after adding)
            stack_index = len(_active_notifications)
            stack_spacing = self.window_height + 10  # 10px gap between notifications
            self.y_final = base_y + (stack_index * stack_spacing)
            self.y_initial = -self.window_height  # Start off-screen above
            
            # Set initial geometry (off-screen)
            self.window.geometry("{}x{}+{}+{}".format(
                self.window_width,
                self.window_height,
                self.x,
                self.y_initial
            ))
            
            # Configure style with better contrast and readability
            self.style = ttk.Style()
            
            # Use regular tk.Label instead of ttk.Label for better text rendering
            self.message_label = tk.Label(
                self.window,
                text=text,
                font=(font_family, font_size, "bold"),  # Bold for better readability
                bg=background_color,
                fg=font_color,
                justify="center",
                anchor="center",
                wraplength=self.calculated_wraplength if self.calculated_wraplength > 0 else 0,
                padx=60,  # More padding for breathing room (2x)
                pady=40,  # (2x)
                borderwidth=3,
                relief="raised"  # Raised for 3D effect
            )
            self.message_label.pack(expand=True, fill='both')
            
            # Configure transparent background
            self.window.config(background="green")
            self.window.wm_attributes('-transparentcolor', 'green')
            self.window.wm_attributes('-topmost', True)
            self.window.overrideredirect(True)
            
            # Animation settings
            self.animation_in_duration = animation_in_duration
            self.animation_stay_duration = animation_stay_duration
            self.animation_fade_duration = animation_fade_duration
            
            self.is_alive = True
            
            # Add to active notifications list for stacking
            _active_notifications.append(self)
            
            # Recalculate position based on actual list position after adding
            self._recalculate_position()
            
            # Enforce notification limit (close oldest if we exceed max)
            _enforce_notification_limit()
            
            # Show window and start animation
            self.window.deiconify()
            self.window.after(1, self._update)
            
        except Exception as e:
            # If initialization fails, mark as not alive
            self.is_alive = False
            try:
                if hasattr(self, 'window'):
                    self.window.destroy()
            except:
                pass
    
    def _update(self):
        """Update animation frame"""
        if not self.is_alive:
            return
        
        try:
            time_passed = time.time() - self.beginning_time
            total_duration = (self.animation_in_duration + 
                            self.animation_stay_duration + 
                            self.animation_fade_duration + 2)
            
            # Kill if running too long
            if time_passed > total_duration:
                self.close()
                return
            
            # Slide-in animation
            if time_passed < self.animation_in_duration:
                progress = time_passed / self.animation_in_duration
                eased_progress = 1 - math.pow(1 - progress, 4)  # Ease-out
                y = int(self.y_initial - eased_progress * (self.y_initial - self.y_final))
                
                self.window.geometry("{}x{}+{}+{}".format(
                    self.window_width,
                    self.window_height,
                    self.x,
                    y
                ))
            
            # Fade-out animation
            elif time_passed > self.animation_in_duration + self.animation_stay_duration:
                progress = (time_passed - self.animation_in_duration - 
                          self.animation_stay_duration) / self.animation_fade_duration
                opacity = 1.0 - progress
                self.window.attributes("-alpha", max(0.0, min(1.0, opacity)))
            
            # Schedule next update with error handling
            if self.is_alive and hasattr(self, 'window'):
                try:
                    if self.window.winfo_exists():
                        self._after_id = self.window.after(16, self._update)  # ~60 FPS
                except:
                    # If scheduling fails, stop animation
                    pass
                
        except Exception as e:
            # If update fails, close gracefully
            self.close()
    
    def close(self):
        """Close the notification normally"""
        self._internal_close()

    def force_close(self):
        """Force close the notification (used when enforcing limits)"""
        self._internal_close()

    def _internal_close(self):
        """Internal close method"""
        self.is_alive = False
        try:
            if hasattr(self, 'window') and self._after_id and self.window.winfo_exists():
                try:
                    self.window.after_cancel(self._after_id)
                except:
                    pass
        finally:
            self._after_id = None
        
        # Remove from active notifications list
        try:
            if self in _active_notifications:
                _active_notifications.remove(self)
        except:
            pass
        
        # Reposition remaining notifications to fill the gap
        self._reposition_remaining_notifications()
        
        try:
            if hasattr(self, 'window'):
                self.window.destroy()
        except:
            pass
    
    def _reposition_remaining_notifications(self):
        """Reposition remaining notifications to fill gaps"""
        # Use the global repositioning function
        _reposition_all_notifications()
    
    def _recalculate_position(self):
        """Recalculate position based on current position in the list"""
        try:
            if not self.is_alive:
                return
                
            # Find current index in the active notifications list
            current_index = -1
            for i, notification in enumerate(_active_notifications):
                if notification.notification_id == self.notification_id:
                    current_index = i
                    break
            
            if current_index >= 0:
                # Calculate new position
                base_y = 50
                stack_spacing = self.window_height + 10
                new_y = base_y + (current_index * stack_spacing)
                
                # Update target position
                self.y_final = new_y
                
                # If window is already visible, move it immediately
                if hasattr(self, 'window') and self.window.winfo_viewable():
                    self.window.geometry("{}x{}+{}+{}".format(
                        self.window_width,
                        self.window_height,
                        self.x,
                        new_y
                    ))
        except:
            pass
    
    def _animate_to_position(self, target_y):
        """Move to a new Y position (direct positioning for reliability)"""
        try:
            if not self.is_alive or not hasattr(self, 'window'):
                return
                
            # Use direct positioning for reliability
            self.window.geometry("{}x{}+{}+{}".format(
                self.window_width,
                self.window_height,
                self.x,
                target_y
            ))
        except:
            pass
    
    def run(self):
        """Run the notification (blocking)"""
        if self.is_alive:
            try:
                self.window.mainloop()
            except:
                pass


def show_loading_notification(message=None, duration=5.0):
    """
    Show a loading notification with optional custom message.
    If message is None, a random loading message is shown.
    
    This is a non-blocking function - it creates the notification and returns immediately.
    The notification will auto-close after the specified duration.
    
    CRITICAL: This function will NEVER crash the app. All failures are silent.
    
    Args:
        message: Custom message text (None = random message)
        duration: How long to show the notification (seconds)
    
    Returns:
        True if notification was shown, False if failed
    """
    try:
        notification = LoadingNotification(
            text=message,
            animation_stay_duration=duration
        )
        return notification.is_alive
    except:
        # Gracefully fail - don't crash the app
        # Don't even try to log the error - that could fail too
        return False


def show_loading_notification_blocking(message=None, duration=5.0):
    """
    Show a loading notification (blocking version).
    Use this if you want to wait for the notification to finish.
    
    CRITICAL: This function will NEVER crash the app. All failures are silent.
    
    Args:
        message: Custom message text (None = random message)
        duration: How long to show the notification (seconds)
    
    Returns:
        True if notification was shown, False if failed
    """
    try:
        notification = LoadingNotification(
            text=message,
            animation_stay_duration=duration
        )
        if notification.is_alive:
            try:
                notification.run()
            except:
                # Even mainloop failure won't crash app
                pass
            return True
        return False
    except:
        # Gracefully fail - don't crash the app
        # Don't even try to log the error - that could fail too
        return False

