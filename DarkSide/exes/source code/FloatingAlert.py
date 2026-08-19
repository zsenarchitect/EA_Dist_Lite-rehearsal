"""create a floating alert window, 
it is a small 5px green dot at the right middle of the screen, when got a notification it 
grow to 100px red circle(smooth animation) and alert by grow and shrink radius slowly.
When mouse is hovering over it, it will grow to right aligned text showing the notification.
When mouse move away it will return to previous stage.

it know it got a notification by checking a json file in desktop folder, if it exists it 
will turn on alert, otherwise it is minimal."""

import tkinter as tk  # Import tkinter for GUI
import os
import json

import _Exe_Util

class FloatingAlert:
    def __init__(self):
        self.root = tk.Tk()  # Create the main window
        self.root.overrideredirect(True)  # Remove window borders
        self.root.attributes("-topmost", True)  # Keep the window on top
        self.screen_width = self.root.winfo_screenwidth()
        self.size = 5  # Initial size
        self.growing = False  # Animation variable

        self.setup_ui()  # Setup the UI components
        self.start_animation(None)  # Start animation regardless of notifications

    def setup_ui(self):
        self.root.geometry(f"5x5+{self.screen_width - 50}+500")  # Set initial size and position
        self.dot = tk.Canvas(self.root, width=100, height=100, bg='white', highlightthickness=0)
        self.dot.pack()

        # Draw the initial dot
        self.dot_id = self.dot.create_oval(0, 0, self.size, self.size, fill='green', outline='')

        # Bind mouse events
        self.dot.bind("<Enter>", self.start_animation)
        self.dot.bind("<Leave>", self.stop_animation)

        # Schedule self-destruction after 10 seconds
        self.root.after(100000, self.self_destruct)  # 100000 ms = 100 seconds

    def check_notification(self):
        return _Exe_Util.get_data("floating_alert_data")

    def create_floating_alert(self):
        self.root.mainloop()  # Start the GUI loop
        self.check_notifications_periodically()  # Start periodic check

    def check_notifications_periodically(self):
        if self.check_notification():  # Check for notifications
            self.start_animation(None)  # Start animation if notification exists
        self.root.after(2000, self.check_notifications_periodically)  # Check every 2 seconds

    def animate(self):
        if self.growing:
            self.size += 3  # Increase size by 3 for more dramatic growth
            if self.size >= 100:  # Change max size to 100
                self.growing = False
        else:
            self.size -= 3  # Decrease size by 3 for faster shrink
            if self.size <= 5:
                self.growing = True

        # Update the oval's size
        self.dot.coords(self.dot_id, (50 - self.size // 2, 50 - self.size // 2, 
                                       50 + self.size // 2, 50 + self.size // 2))
        self.dot.itemconfig(self.dot_id, fill='red' if self.size >= 100 else 'green')
        self.root.after(50, self.animate)  # Repeat every 50 ms for faster animation

    def start_animation(self, event):
        print("Mouse hovering over the alert!")  # Log when mouse hovers
        self.growing = True
        self.animate()

    def stop_animation(self, event):
        self.growing = False
        self.size = 5  # Reset size to minimum
        self.dot.coords(self.dot_id, (50 - self.size // 2, 50 - self.size // 2, 
                                       50 + self.size // 2, 50 + self.size // 2))
        self.dot.itemconfig(self.dot_id, fill='green')  # Reset to green dot

    def self_destruct(self):
        self.root.destroy()  # Close the window

# Call the class to create the alert
if __name__ == "__main__":
    alert = FloatingAlert()
    alert.create_floating_alert()