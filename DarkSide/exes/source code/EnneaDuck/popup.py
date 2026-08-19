import tkinter as tk
import requests
import os

class PopupMenu:
    def __init__(self, parent):
        self.parent = parent
        self.follow_cursor = tk.BooleanVar(value=True)  # Default to True (checked)
        self.character_selection = tk.StringVar(value="duck")  # Default to duck
        self.create_popup_menu()
        
    def get_dark_joke(self):
        try:
            response = requests.get("https://v2.jokeapi.dev/joke/Dark?type=single")
            if response.status_code == 200:
                return response.json()["joke"]
            return "Why did the duck cross the road? To prove he wasn't chicken!"
        except:
            return "Why did the duck cross the road? To prove he wasn't chicken!"

    def create_popup_menu(self):
        self.popup_menu = tk.Menu(self.parent, tearoff=0)
        self.popup_menu.add_command(label="Hello.", command=self.say_hello)
        self.popup_menu.add_command(label="Show queue.", command=self.show_queue)
        self.popup_menu.add_separator()
        
        # Character selection submenu
        self.character_menu = tk.Menu(self.popup_menu, tearoff=0)
        self.character_menu.add_radiobutton(label="Duck", variable=self.character_selection, 
                                          value="duck", command=self.change_character)
        self.character_menu.add_radiobutton(label="Cat", variable=self.character_selection, 
                                          value="cat", command=self.change_character)
        self.popup_menu.add_cascade(label="Character", menu=self.character_menu)
        
        self.popup_menu.add_checkbutton(label="Follow Cursor", 
                                       variable=self.follow_cursor, 
                                       command=self.toggle_follow_cursor)
        self.popup_menu.add_separator()
        self.popup_menu.add_command(label="Bye Me.", command=self.parent.destroy)

    def change_character(self):
        """Change the character and update the animation"""
        character = self.character_selection.get()
        self.parent.animation.change_character(character)
        
        # Update the talk bubble to show character change
        character_name = character.capitalize()
        self.parent.talk_bubble.configure(text=f"Changed to {character_name}!")
        self.parent.bubble_life = 30 * 12  # 30 seconds at 12 FPS
        self.parent.hide_widget(self.parent.duck_label)
        self.parent.show_widget(self.parent.talk_bubble)
        self.parent.show_widget(self.parent.duck_label)
        self.parent.play_random_duck_sound()

    def toggle_follow_cursor(self):
        """Toggle the follow cursor functionality"""
        if self.follow_cursor.get():
            self.parent.talk_bubble.configure(text="Following cursor enabled!")
        else:
            self.parent.talk_bubble.configure(text="Following cursor disabled!")
        
        self.parent.bubble_life = 30 * 12  # 30 seconds at 12 FPS
        self.parent.hide_widget(self.parent.duck_label)
        self.parent.show_widget(self.parent.talk_bubble)
        self.parent.show_widget(self.parent.duck_label)
        self.parent.play_random_duck_sound()

    def do_popup(self, event):
        try:
            self.popup_menu.tk_popup(event.x_root, event.y_root)
        except Exception as e:
            pass
        finally:
            self.popup_menu.grab_release()

    def say_hello(self):
        joke = self.get_dark_joke()
        self.parent.talk_bubble.configure(text=joke)
        self.parent.bubble_life = 15 * 12  # 15 seconds at 12 FPS
        self.parent.hide_widget(self.parent.duck_label)
        self.parent.show_widget(self.parent.talk_bubble)
        self.parent.show_widget(self.parent.duck_label)
        self.parent.play_random_duck_sound()

    def show_queue(self):
        self.parent.talk_bubble.configure(text="No queue to show.")
        self.parent.bubble_life = 30 * 12  # 30 seconds at 12 FPS
        self.parent.hide_widget(self.parent.duck_label)
        self.parent.show_widget(self.parent.talk_bubble)
        self.parent.show_widget(self.parent.duck_label)
        self.parent.play_random_duck_sound()
