import os
import random
import logging
import sys
import traceback
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QMenu
from PyQt5.QtCore import Qt, QTimer, QPoint, QUrl
from PyQt5.QtGui import QPixmap, QMovie, QCursor
from state_manager import PetState
from animations import AnimationManager
from chat_manager import ChatManager
import math
from PyQt5.QtMultimedia import QSoundEffect
from PyQt5.QtMultimediaWidgets import QVideoWidget

# Get logger for DuckPet module
logger = logging.getLogger('DuckiTect.Pet')

class DuckPet(QMainWindow):
    """
    Main class for the Duck Desktop Pet.
    Handles window management, animations, and user interactions.
    """
    
    def __init__(self):
        super().__init__()
        logger.info("Initializing DuckiTect Pet")
        self.init_ui()
        self.setup_timers()
        self.setup_managers()
        self.walking_direction = 1  # 1 for right, -1 for left
        self.is_walking = False
        logger.info("DuckiTect Pet initialized successfully")
        
    def init_ui(self):
        """Initialize the user interface and window properties."""
        # Set window properties
        self.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint |
            Qt.SubWindow
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Create main label for displaying animations
        self.pet_label = QLabel(self)
        self.setCentralWidget(self.pet_label)
        
        # Set initial size (will be updated based on animations)
        self.resize(128, 128)
        
        # Initialize position
        screen_rect = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen_rect.width() - self.width() - 100,
            screen_rect.height() - self.height() - 100
        )
        
    def setup_timers(self):
        """Setup timers for various automated behaviors."""
        # Main activity timer
        self.activity_timer = QTimer(self)
        self.activity_timer.timeout.connect(self.update_activity)
        self.activity_timer.start(15000)  # Check every 15 seconds instead of 5
        
        # Mouse chase timer
        self.chase_timer = QTimer(self)
        self.chase_timer.timeout.connect(self.update_chase)
        
        # Walking timer
        self.walk_timer = QTimer(self)
        self.walk_timer.timeout.connect(self.update_walk)
        
    def setup_managers(self):
        """Initialize various managers for handling different aspects of the pet."""
        self.state = PetState()
        self.animation_manager = AnimationManager()
        self.animation_manager.set_label(self.pet_label)  # Set the label for animations
        self.chat_manager = ChatManager(self)
        
        # Start with idle animation
        self.animation_manager.play_animation("idle")
        
    def mousePressEvent(self, event):
        """Handle mouse press events for dragging."""
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
            
    def mouseMoveEvent(self, event):
        """Handle mouse move events for dragging."""
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()
            
    def contextMenuEvent(self, event):
        """Handle right-click menu."""
        logger.debug("Opening context menu")
        menu = QMenu(self)
        
        # Add menu actions
        vacation_action = menu.addAction("Go Vacation")
        vacation_action.triggered.connect(self.start_vacation)
        
        chat_action = menu.addAction("Chat with Duck")
        chat_action.triggered.connect(self.start_chat)
        
        selected_action = menu.exec_(event.globalPos())
        
        if selected_action == chat_action:
            logger.info("Chat option selected from context menu")
            self.chat_manager.show_chat_window()
        
    def start_vacation(self):
        """Handle the vacation animation and close the application."""
        # Disable activity timer during vacation
        self.activity_timer.stop()
        
        # Create a timer for smooth movement
        self.vacation_timer = QTimer(self)
        self.vacation_timer.timeout.connect(self._update_vacation_position)
        
        # Get screen width for calculating end position
        self.screen_width = QApplication.primaryScreen().availableGeometry().width()
        
        # Initialize wave animation parameters
        self.wave_amplitude = 20  # Height of the wave
        self.wave_frequency = 0.1  # Speed of the wave
        self.wave_time = 0  # Time counter for wave motion
        
        # Set movement speed and start timer
        self.vacation_speed = 5
        self.vacation_timer.start(30)  # Update every 30ms for smooth animation
        
        # Set initial y position and ensure duck faces right
        self.initial_y = self.pos().y()
        self.animation_manager.set_facing_direction(True)
        
        # Play fly away animation
        self.animation_manager.play_animation("fly_away")
        
    def _update_vacation_position(self):
        """Update the position during vacation animation."""
        current_pos = self.pos()
        new_x = current_pos.x() + self.vacation_speed
        
        # Calculate wave motion
        self.wave_time += self.wave_frequency
        wave_offset = math.sin(self.wave_time) * self.wave_amplitude
        new_y = self.initial_y + wave_offset
        
        # Move the duck
        self.move(new_x, int(new_y))
        
        # If duck is completely off screen, close the application
        if new_x > self.screen_width:
            self.vacation_timer.stop()
            QApplication.quit()  # Properly quit the application
        
    def start_chat(self):
        """Open the chat interface."""
        self.chat_manager.show_chat_window()
        
    def start_walking(self):
        """Start the walking animation and movement."""
        try:
            logger.debug("=== Starting walking animation ===")
            self.is_walking = True
            # Randomly choose direction
            self.walking_direction = random.choice([-1, 1])
            logger.debug(f"Selected walking direction: {self.walking_direction} (-1=left, 1=right)")
            
            # Set the facing direction in animation manager
            logger.debug(f"Setting facing direction: {'right' if self.walking_direction == 1 else 'left'}")
            self.animation_manager.set_facing_direction(self.walking_direction == 1)
            
            logger.debug("Playing walk animation")
            self.animation_manager.play_animation("walk")
            
            logger.debug("Starting walk timer")
            self.walk_timer.start(50)  # Update every 50ms
            
            # Play walking sound
            logger.debug("Playing walk sound")
            self.play_sound('walk')
            
            # Stop walking after random duration (3-8 seconds)
            walk_duration = random.randint(3000, 8000)
            logger.debug(f"Scheduled walk stop after {walk_duration}ms")
            QTimer.singleShot(walk_duration, self.stop_walking)
        except Exception as e:
            logger.error(f"Error in start_walking: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
        
    def stop_walking(self):
        """Stop the walking animation and movement."""
        try:
            if self.is_walking:
                logger.debug("=== Stopping walk animation ===")
                self.is_walking = False
                logger.debug("Stopping walk timer")
                self.walk_timer.stop()
                logger.debug("Switching to idle animation")
                self.animation_manager.play_animation("idle")
                logger.debug("Triggering activity update")
                self.update_activity()
        except Exception as e:
            logger.error(f"Error in stop_walking: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
        
    def update_walk(self):
        """Update position during walking."""
        try:
            if not self.is_walking:
                return
                
            current_pos = self.pos()
            screen_rect = QApplication.primaryScreen().availableGeometry()
            
            # Calculate new position
            walk_speed = 3
            new_x = current_pos.x() + (walk_speed * self.walking_direction)
            
            # Log position details
            logger.debug(f"Walk Update - Current X: {current_pos.x()}, New X: {new_x}, Direction: {self.walking_direction}")
            logger.debug(f"Screen bounds - Left: 0, Right: {screen_rect.width() - self.width()}")
            
            # Check screen boundaries and reverse direction if needed
            if new_x < 0:
                logger.debug("Hit left screen boundary - reversing direction")
                new_x = 0
                self.walking_direction = 1  # Change direction to right
                self.animation_manager.set_facing_direction(True)
            elif new_x > screen_rect.width() - self.width():
                logger.debug("Hit right screen boundary - reversing direction")
                new_x = screen_rect.width() - self.width()
                self.walking_direction = -1  # Change direction to left
                self.animation_manager.set_facing_direction(False)
                
            logger.debug(f"Moving to new position - X: {new_x}, Y: {current_pos.y()}")
            self.move(new_x, current_pos.y())
        except Exception as e:
            logger.error(f"Error in update_walk: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
        
    def update_activity(self):
        """Randomly select and perform a new activity."""
        logger.debug("Updating activity state")
        if self.is_walking:
            return
            
        # Add walking to possible activities
        activities = ["idle", "bored", "walk"]
        
        if not self.state.is_busy():
            new_activity = random.choice(activities)
            self.state.set_activity(new_activity)
            
            if new_activity == "walk":
                self.start_walking()
            elif new_activity == "bored":
                logger.info("Duck is bored, initiating random conversation")
                self.chat_manager.start_random_chat(self)
            else:
                self.animation_manager.play_animation(new_activity)
            
            self.update_animation(new_activity)
        
    def update_chase(self):
        """Update position when chasing the mouse."""
        if self.state.is_chasing():
            cursor_pos = QCursor.pos()
            self.move_towards(cursor_pos)
            
    def move_towards(self, target_pos):
        """Move the pet towards a target position."""
        current_pos = self.pos()
        dx = target_pos.x() - current_pos.x()
        dy = target_pos.y() - current_pos.y()
        
        # Calculate new position with smooth movement
        speed = 5
        angle = math.atan2(dy, dx)
        new_x = current_pos.x() + speed * math.cos(angle)
        new_y = current_pos.y() + speed * math.sin(angle)
        
        self.move(int(new_x), int(new_y)) 

    def play_sound(self, sound_name):
        """Play a sound effect based on the type."""
        try:
            logger.debug("Attempting to play sound: {}".format(sound_name))
            
            # Map requested sounds to available files
            sound_map = {
                'thinking': 'thinking.wav',  # Specific thinking sound
                'response': 'response.wav',  # Specific response sound
                'error': 'error.wav',  # Error sound
                'join': 'join.wav',  # Sound for starting chat
                'walk': 'walk.wav',  # Sound for walking
                'jump': 'jump.wav',  # Sound for jumping
                'spring': 'jump_happy_spring.wav',  # Happy spring sound
                'bored': 'bored.wav',  # Bored state sound
                'default': 'duck_default.wav'  # Default duck sound
            }
            
            # Get mapped sound file or use default
            sound_file = sound_map.get(sound_name, sound_map['default'])
            logger.debug("Selected sound file: {}".format(sound_file))
            
            # Get absolute path to audio file
            sound_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                                    "assets", "audio", sound_file)
            sound_path = os.path.normpath(sound_path)
            
            if not os.path.exists(sound_path):
                logger.warning("Sound file not found: {}".format(sound_path))
                return
            
            logger.debug("Loading sound from: {}".format(sound_path))
            
            effect = QSoundEffect()
            # Convert to URL with proper encoding and forward slashes
            url_path = sound_path.replace('\\', '/')
            if not url_path.startswith('/'):
                url_path = '/' + url_path
            url = QUrl.fromLocalFile(url_path)
            
            if not url.isValid():
                logger.error("Invalid URL created: {}".format(url.toString()))
                return
            
            effect.setSource(url)
            effect.setVolume(0.5)  # Set volume to 50%
            
            # Wait for loading and check status
            if effect.status() == QSoundEffect.Error:
                logger.error("Sound effect error: {}".format(effect.status()))
                return
            
            effect.play()
            logger.debug("Sound played successfully: {}".format(sound_file))
            
        except Exception as e:
            import traceback
            logger.error("Error playing sound {}: {}".format(sound_name, str(e)))
            logger.error("Traceback: {}".format(traceback.format_exc()))

    def update_animation(self, state):
        logger.debug("Updating animation for state: {}".format(state))
        try:
            self.animation_manager.play_animation(state)
            logger.info("Animation updated successfully")
        except Exception as e:
            logger.error("Error updating animation: {}".format(str(e))) 