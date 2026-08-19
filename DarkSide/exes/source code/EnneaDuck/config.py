"""
Configuration settings for EnneaDuck application.
"""

import os

# Application Settings
APP_NAME = "EnneaDuck"
APP_VERSION = "1.0.0"
FPS = 12
ANIMATION_WAIT_TIME = int(1000 / FPS)

# Window Settings
WINDOW_WIDTH = 600
WINDOW_HEIGHT = 250
TRANSPARENT_COLOR = "green"

# Audio Settings
VOLUME_LEVEL = 0.3  # 30% volume
AUDIO_DIRECTORY = "audio"
AUDIO_FILES = ["duck_1.wav", "duck_2.wav", "duck_3.wav"]

# Animation Settings
IMAGES_DIRECTORY = "images"
ANIMATION_STAGES = [
    "idle",
    "rotate",
    "swing",
    "attention",
    "walking_left",
    "walking_right"
]

# Movement Settings
WALK_SPEED = 3  # Pixels per frame
WALK_THRESHOLD = 50  # Distance threshold to start walking
DIRECTION_CHANGE_DELAY = 2.0  # Minimum seconds between direction changes
MIN_DIRECTION_CHANGE_DISTANCE = 100  # Minimum pixels to move before changing direction

# UI Settings
FONT_FAMILY = "Comic Sans MS"
FONT_SIZE = 18
BUBBLE_WRAP_LENGTH = 400
BUBBLE_DISPLAY_TIME = 30000  # 30 seconds

# Joke Settings
JOKE_CHECK_INTERVAL = 60  # Check every minute
JOKE_CHANCE = 0.1  # 10% chance to tell a joke
CLICK_JOKE_CHANCE = 0.3  # 30% chance to tell a joke on click

# File Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_PATH = os.path.join(BASE_DIR, AUDIO_DIRECTORY)
IMAGES_PATH = os.path.join(BASE_DIR, IMAGES_DIRECTORY)

# Default Jokes
DEFAULT_JOKES = [
    "Why did the duck cross the road? To prove he wasn't chicken!",
    "What's the difference between a duck and a psychopath? One's a quack, the other's a quack with a knife.",
    "Why did the duck go to therapy? It had too many existential quacks.",
    "What do you call a duck that's always late? A procrasti-quacker.",
    "Why did the duck join the mafia? It wanted to be a quackster.",
    "What's a duck's favorite horror movie? The Quacking Dead.",
    "Why did the duck become a detective? It was good at quack investigations.",
    "What do you call a duck that's always angry? A quackhead.",
    "Why did the duck start a cult? It had too many followers.",
    "What's a duck's favorite crime? Identity theft - it's always impersonating other birds.",
    "Why did the duck become a hacker? It was tired of being a sitting duck.",
    "What do you call a duck that's always scheming? A masterquacker.",
    "Why did the duck become a lawyer? It was good at quack justice.",
    "What's a duck's favorite weapon? A quack-47.",
    "Why did the duck become a spy? It was good at quack operations.",
    "What do you call a duck that's always plotting? A quackspiracy theorist.",
    "Why did the duck become a scientist? It wanted to study quack physics.",
    "What's a duck's favorite game? Quack and seek.",
    "Why did the duck become a magician? It was good at quack illusions.",
    "What do you call a duck that's always suspicious? A quack investigator."
] 