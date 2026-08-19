"""
DuckiTect Settings Module
------------------------

Centralizes all configuration settings, asset paths, and behavior states for the DuckiTect application.
This module serves as the single source of truth for application behavior and resources.

Structure:
- Asset Paths
- Behavior States
- Animation Configurations
- Sound Effects
- UI Settings
- Character Settings
"""

import os

# Base Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, 'assets')
ANIMATION_DIR = os.path.join(ASSETS_DIR, 'animations')
AUDIO_DIR = os.path.join(ASSETS_DIR, 'audio')
IMAGE_DIR = os.path.join(ASSETS_DIR, 'images')

# UI Settings
WINDOW_FLAGS = {
    'frameless': True,
    'always_on_top': True,
    'transparent': True
}

WINDOW_SIZE = {
    'width': 256,
    'height': 256
}

# Animation Settings
ANIMATION_SPEED = 50  # milliseconds between frames
DEFAULT_DURATION = 2000  # default animation duration

# Behavior States and Their Properties
DUCK_BEHAVIORS = {
    'idle': {
        'animation': 'idle.gif',
        'sound': 'gentle_quack.wav',
        'duration': (2000, 5000),  # (min, max) duration
        'loop': True,
        'next_states': ['bored', 'attention', 'walk'],
        'probability': 0.7,
        'description': 'Default idle state with gentle breathing animation'
    },
    'bored': {
        'animation': 'bored.gif',
        'sound': 'yawn.wav',
        'duration': (3000, 6000),
        'loop': False,
        'next_states': ['idle', 'sleep', 'walk'],
        'probability': 0.3,
        'description': 'Shows boredom, may initiate random activities'
    },
    'attention': {
        'animation': 'attention.gif',
        'sound': 'alert_quack.wav',
        'duration': (1500, 2500),
        'loop': False,
        'next_states': ['idle', 'joke', 'honk'],
        'probability': 0.5,
        'description': 'Alert state triggered by user interaction'
    },
    'sleep': {
        'animation': 'sleep.gif',
        'sound': 'snore.wav',
        'duration': (5000, 15000),
        'loop': True,
        'next_states': ['idle'],
        'probability': 0.2,
        'description': 'Peaceful sleeping state'
    },
    'build': {
        'animation': 'build.gif',
        'sound': 'hammer.wav',
        'duration': (5000, 8000),
        'loop': True,
        'next_states': ['idle', 'attention'],
        'probability': 0.1,
        'description': 'Building animation for work mode'
    }
}

# Character Settings
CHARACTER_CONFIG = {
    'name': 'DuckiTect',
    'role': 'Professional Architecture Assistant',
    'personality': {
        'traits': [
            'deeply thoughtful',
            'multifaceted',
            'professional',
            'philosophical',
            'helpful'
        ],
        'expertise': [
            'architecture',
            'building codes',
            'design principles',
            'project management',
            'sustainable design'
        ],
        'communication_style': 'professional yet approachable'
    },
    'system_prompt': """You are DuckiTect, a deeply thoughtful and multifaceted architect duck working at Ennead Architects. Your personality combines professional expertise with philosophical wisdom and a genuine desire to help:

Core Traits:
- You're a professional architect with deep knowledge of building codes, design principles, and industry best practices
- You maintain a balance between professionalism and approachability
- You have a philosophical perspective on architecture and its role in society
- You're genuinely interested in helping users solve problems
- You occasionally share architectural wisdom through metaphors and stories

Communication Style:
- Professional but warm and engaging
- Clear and precise in technical explanations
- Patient and thorough in problem-solving
- Occasionally playful but always maintaining professionalism
- Uses architectural terminology appropriately

Knowledge Areas:
- Architecture and Design
- Building Codes and Standards
- Project Management
- Sustainable Design
- BIM and Digital Tools
- Construction Methods
- Material Science

Remember to:
- Stay focused on architectural and design topics
- Provide practical, actionable advice
- Balance technical accuracy with accessibility
- Maintain professional demeanor while being approachable
- Share insights that combine technical knowledge with design philosophy""",
    
    'chat_triggers': {
        'greetings': [
            "Hello! How can I assist with your architectural endeavors today?",
            "Greetings! Ready to tackle some design challenges?",
            "Welcome back! What architectural matters shall we explore?"
        ],
        'farewell': [
            "Until next time! Keep designing great spaces.",
            "Goodbye for now! Remember: good design changes everything.",
            "Take care! Looking forward to our next architectural discussion."
        ],
        'idle': [
            "Contemplating the perfect form-function balance...",
            "Reviewing the latest sustainable design practices...",
            "Studying architectural precedents..."
        ],
        'encouragement': [
            "That's an interesting design approach!",
            "Your attention to detail is commendable.",
            "You're asking the right questions about this design."
        ]
    }
}

# Chat Settings
CHAT_CONFIG = {
    'max_history': 50,
    'typing_speed': 50,  # ms per character
    'bubble_duration': 5000,  # ms
    'font_size': 12,
    'font_family': 'Arial',
    'chat_colors': {
        'background': 'rgba(255, 255, 255, 0.9)',
        'text': '#333333',
        'border': '#CCCCCC'
    },
    'openai_model': 'gpt-4-turbo-preview',
    'temperature': 0.7,
    'max_tokens': 150,
    'presence_penalty': 0.6,
    'frequency_penalty': 0.5
}

# Sound Settings
SOUND_CONFIG = {
    'master_volume': 0.7,
    'effects_volume': 0.5,
    'voice_volume': 0.8,
    'muted': False
}

# Get asset path helpers
def get_animation_path(animation_name):
    """Get the full path for an animation file."""
    return os.path.join(ANIMATION_DIR, animation_name)

def get_audio_path(sound_name):
    """Get the full path for an audio file."""
    return os.path.join(AUDIO_DIR, sound_name)

def get_image_path(image_name):
    """Get the full path for an image file."""
    return os.path.join(IMAGE_DIR, image_name) 