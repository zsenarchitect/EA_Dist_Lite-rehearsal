import os
from PyQt5.QtGui import QMovie, QPixmap, QPainter, QPen, QColor, QBrush, QTransform
from PyQt5.QtCore import QSize, Qt, QPoint
from PyQt5.QtMultimedia import QSound
import logging
import traceback
import random

logger = logging.getLogger(__name__)

class AnimationManager:
    """
    Manages animations and sound effects for the pet.
    Handles loading, playing, and transitioning between different animations.

    Available Animations:
    - idle: Basic idle animation
    - walk: Walking animation (auto-flips based on direction)
    - sleep: Sleeping animation with transition effects
    - farm: Farming activity animation
    - read: Reading activity animation
    - build: Building activity animation
    - joke: Joking animation
    - bored: Bored state animation
    - fly_away: Flying away animation
    - attention: Attention-getting animation
    - shake: Shaking animation
    - rotate: Rotation animation
    - swing: Swinging animation
    - honk: Honking animation

    Available Sound Effects:
    - walk: Walking sound
    - bored: Bored state sound
    - error: Error notification
    - thinking: Thinking process
    - response: Response sound
    - jump: Jump action sound
    - jump_happy: Happy jumping sound
    - join: Joining sound
    - duck_default, duck_1, duck_2, duck_3: Various duck sounds

    Response Features:
    - Table/Chart display using matplotlib
    - Text-to-speech with Donald Duck voice effect
    - Autoplay control for speech
    """
    
    def __init__(self):
        self.current_animation = None
        self.label = None
        self.base_path = os.path.join(os.path.dirname(__file__), "assets")
        self.facing_right = True  # Track which direction the duck is facing
        self.tts_autoplay = False  # Control text-to-speech autoplay
        
        # Initialize text-to-speech engine
        self.tts_engine = None
        self.init_tts_engine()
        
        # Create a default duck image if no animations are available
        self.default_image = QPixmap(128, 128)
        self.default_image.fill(Qt.transparent)
        
        # Draw a simple duck shape
        painter = QPainter(self.default_image)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Set up the brush and pen
        painter.setPen(QPen(QColor(0, 0, 0), 2))
        painter.setBrush(QBrush(QColor(255, 223, 0)))  # Yellow color
        
        # Draw body (circle)
        painter.drawEllipse(30, 40, 60, 50)
        
        # Draw head (circle)
        painter.drawEllipse(75, 30, 40, 40)
        
        # Draw beak (triangle)
        painter.setBrush(QBrush(QColor(255, 140, 0)))  # Orange color
        points = [
            QPoint(115, 45),
            QPoint(135, 50),
            QPoint(115, 55)
        ]
        painter.drawPolygon(points)
        
        painter.end()
        
        # Store flipped version of default image
        self.default_image_flipped = self.default_image.transformed(QTransform().scale(-1, 1))
        
        # Define animation paths relative to assets directory
        self.animations = {
            "idle": "animations/idle.gif",
            "walk_right": "animations/walking_right.gif",
            "walk_left": "animations/walking_left.gif",
            "walk_positive": "animations/walking_positive.gif",
            "walk_negative": "animations/walking_negative.gif",
            "sleep": "animations/sleep.gif",
            "sleep_to_idle": "animations/sleep_to_idle.gif",
            "idle_to_sleep": "animations/idle_to_sleep.gif",
            "farm": "animations/farm.gif",
            "read": "animations/read.gif",
            "build": "animations/build.gif",
            "joke": "animations/joke.gif",
            "bored": "animations/bored.gif",
            "fly_away": "animations/fly_away.gif",
            "attention": "animations/attention.gif",
            "shake": "animations/shake.gif",
            "rotate": "animations/rotate.gif",
            "swing": "animations/swing.gif",
            "honk": "animations/honk.gif"
        }
        
        # Define sound effects
        self.sounds = {
            "walk": "audio/walk.wav",
            "bored": "audio/bored.wav",
            "error": "audio/error.wav",
            "thinking": "audio/thinking.wav",
            "response": "audio/response.wav",
            "jump": "audio/jump.wav",
            "jump_happy": "audio/jump_happy_spring.wav",
            "join": "audio/join.wav",
            "duck_default": "audio/duck_default.wav",
            "duck_1": "audio/duck_1.wav",
            "duck_2": "audio/duck_2.wav",
            "duck_3": "audio/duck_3.wav"
        }
        
        # Add visualization paths
        self.viz_path = os.path.join(self.base_path, "visualizations")
        self.directories = [
            os.path.join(self.base_path, "animations"),
            os.path.join(self.base_path, "audio"),
            os.path.join(self.base_path, "images"),
            self.viz_path
        ]
        
        self.create_asset_directories()
        
    def create_asset_directories(self):
        """Create the necessary asset directories if they don't exist."""
        for directory in self.directories:
            if not os.path.exists(directory):
                os.makedirs(directory)
    
    def set_label(self, label):
        """
        Set the QLabel widget to display animations on.
        
        Args:
            label (QLabel): The label widget to display animations
        """
        self.label = label
        # Set default image
        self.label.setPixmap(self.default_image if self.facing_right else self.default_image_flipped)
    
    def setup_controls(self, parent_widget):
        """
        Set up control buttons for the animation manager.
        
        Args:
            parent_widget (QWidget): Parent widget to add controls to
        """
        try:
            from PyQt5.QtWidgets import QPushButton, QHBoxLayout
            
            # Create control layout
            control_layout = QHBoxLayout()
            
            # Create autoplay toggle button
            self.autoplay_button = QPushButton("🔊 Autoplay: Off", parent_widget)
            self.autoplay_button.setCheckable(True)
            self.autoplay_button.setChecked(False)
            self.autoplay_button.clicked.connect(self._toggle_autoplay)
            
            # Add to layout
            control_layout.addWidget(self.autoplay_button)
            
            # Add layout to parent
            if hasattr(parent_widget, 'layout') and parent_widget.layout():
                parent_widget.layout().addLayout(control_layout)
            
            logger.debug("Control buttons set up successfully")
            
        except Exception as e:
            logger.error(f"Error setting up controls: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            
    def _toggle_autoplay(self):
        """Handle autoplay toggle button click."""
        try:
            is_enabled = self.autoplay_button.isChecked()
            self.set_tts_autoplay(is_enabled)
            self.autoplay_button.setText(f"🔊 Autoplay: {'On' if is_enabled else 'Off'}")
        except Exception as e:
            logger.error(f"Error toggling autoplay: {str(e)}")
    
    def set_facing_direction(self, facing_right):
        """Set which direction the duck is facing."""
        try:
            logger.debug(f"=== Setting facing direction: {'right' if facing_right else 'left'} ===")
            if self.facing_right != facing_right:
                logger.debug("Direction changed - flipping animation")
                self.facing_right = facing_right
                if self.current_animation:
                    logger.debug(f"Current animation: {self.current_animation}")
                    # Store current frame if it's a movie
                    current_frame = self.current_animation.currentFrameNumber() if isinstance(self.current_animation, QMovie) else None
                    logger.debug(f"Current frame: {current_frame}")
                    # Restart animation with new direction
                    self.play_animation(self.current_state)
                    # Restore frame if it was a movie
                    if current_frame is not None:
                        logger.debug(f"Restoring to frame: {current_frame}")
                        self.current_animation.jumpToFrame(current_frame)
            else:
                logger.debug("Direction unchanged - no flip needed")
        except Exception as e:
            logger.error(f"Error in set_facing_direction: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
    
    def play_animation(self, state):
        """
        Play the specified animation state.
        
        Args:
            state (str): The animation state to play. Available states are documented in class docstring.
            
        Special handling:
        - Walking animations automatically use the correct directional variant
        - Sleep transitions are handled automatically (idle_to_sleep, sleep_to_idle)
        """
        try:
            logger.debug(f"=== Playing animation: {state} ===")
            self.current_state = state
            
            # Handle directional walking animations
            if state == "walk":
                state = "walk_right" if self.facing_right else "walk_left"
            
            # Get animation path
            animation_path = os.path.join(self.base_path, self.animations.get(state, ''))
            logger.debug(f"Animation path: {animation_path}")
            
            # Check if animation exists
            if not os.path.exists(animation_path):
                logger.debug(f"Animation file not found, using default image")
                self.label.setPixmap(self.default_image if self.facing_right else self.default_image_flipped)
                return
            
            # Create and configure movie
            logger.debug("Creating QMovie for animation")
            movie = QMovie(animation_path)
            if not movie.isValid():
                logger.error(f"Invalid animation file: {animation_path}")
                self.label.setPixmap(self.default_image if self.facing_right else self.default_image_flipped)
                return
                
            # Set movie properties
            movie.setCacheMode(QMovie.CacheAll)
            movie.setSpeed(100)
            
            # If facing left and not already a left-facing animation, create transformed version
            if not self.facing_right and not state.endswith("_left"):
                logger.debug("Flipping animation for left-facing direction")
                transform = QTransform().scale(-1, 1)
                movie.setScaledSize(movie.scaledSize())
                movie.frameChanged.connect(lambda: self._update_flipped_frame(movie, transform))
            
            # Set and start the animation
            logger.debug("Setting animation on label")
            self.label.setMovie(movie)
            self.current_animation = movie
            movie.start()
            
            # Play associated sound if available
            sound_path = os.path.join(self.base_path, self.sounds.get(state, ''))
            if os.path.exists(sound_path):
                QSound.play(sound_path)
            
            logger.debug("Animation started successfully")
            
        except Exception as e:
            logger.error(f"Error in play_animation: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            
    def _update_flipped_frame(self, movie, transform):
        """Update the current frame with a flipped version for left-facing animations."""
        try:
            current_pixmap = movie.currentPixmap()
            flipped_pixmap = current_pixmap.transformed(transform)
            self.label.setPixmap(flipped_pixmap)
        except Exception as e:
            logger.error(f"Error in _update_flipped_frame: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
    
    def stop_animation(self):
        """Stop the current animation if any is playing."""
        if self.current_animation:
            self.current_animation.stop()
            self.current_animation = None
            self.label.setPixmap(self.default_image if self.facing_right else self.default_image_flipped) 

    def init_tts_engine(self):
        """Initialize text-to-speech engine with pyttsx3."""
        try:
            import pyttsx3
            self.tts_engine = pyttsx3.init()
            # Configure for Donald Duck voice effect
            self.tts_engine.setProperty('rate', 150)  # Speed
            self.tts_engine.setProperty('pitch', 200)  # Higher pitch for duck effect
            logger.debug("Text-to-speech engine initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize TTS engine: {str(e)}")
            self.tts_engine = None

    def set_tts_autoplay(self, enabled):
        """
        Enable or disable text-to-speech autoplay.
        
        Args:
            enabled (bool): Whether to enable autoplay
        """
        self.tts_autoplay = enabled
        logger.debug(f"TTS autoplay {'enabled' if enabled else 'disabled'}")

    def display_response(self, response_data, response_type="text"):
        """
        Display AI response with optional visualization and speech.
        
        Args:
            response_data: The response data to display (text, dict for table, or plot data)
            response_type (str): Type of response - "text", "table", or "chart"
        """
        try:
            # Handle different response types
            if response_type == "table":
                self._display_table(response_data)
            elif response_type == "chart":
                self._display_chart(response_data)
            
            # Extract text content for speech
            text_content = response_data if response_type == "text" else str(response_data)
            
            # Play duck sound before speaking
            self._play_random_duck_sound()
            
            # Speak text if autoplay is enabled
            if self.tts_autoplay and self.tts_engine:
                self.speak_text(text_content)
                
        except Exception as e:
            logger.error(f"Error displaying response: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")

    def _display_table(self, table_data):
        """Display data as a table using matplotlib."""
        try:
            import matplotlib.pyplot as plt
            import pandas as pd
            
            # Convert data to pandas DataFrame
            df = pd.DataFrame(table_data)
            
            # Create table visualization
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.axis('tight')
            ax.axis('off')
            table = ax.table(cellText=df.values, colLabels=df.columns, cellLoc='center')
            
            # Save and display
            plt.savefig(os.path.join(self.viz_path, 'response_table.png'))
            plt.close()
            
        except Exception as e:
            logger.error(f"Error creating table visualization: {str(e)}")

    def _display_chart(self, chart_data):
        """Display data as a chart using matplotlib."""
        try:
            import matplotlib.pyplot as plt
            
            # Create chart based on data type
            plt.figure(figsize=(8, 4))
            if isinstance(chart_data, dict):
                plt.bar(chart_data.keys(), chart_data.values())
            else:
                plt.plot(chart_data)
            
            # Save and display
            plt.savefig(os.path.join(self.viz_path, 'response_chart.png'))
            plt.close()
            
        except Exception as e:
            logger.error(f"Error creating chart visualization: {str(e)}")

    def speak_text(self, text):
        """
        Speak text with Donald Duck voice effect.
        
        Args:
            text (str): Text to speak
        """
        try:
            if self.tts_engine:
                # Play speaking animation
                self.play_animation("honk")
                # Speak text
                self.tts_engine.say(text)
                self.tts_engine.runAndWait()
                # Return to idle
                self.play_animation("idle")
        except Exception as e:
            logger.error(f"Error in text-to-speech: {str(e)}")

    def _play_random_duck_sound(self):
        """Play a random duck sound effect."""
        try:
            duck_sounds = ["duck_default", "duck_1", "duck_2", "duck_3"]
            sound = random.choice(duck_sounds)
            sound_path = os.path.join(self.base_path, self.sounds.get(sound, ''))
            if os.path.exists(sound_path):
                QSound.play(sound_path)
        except Exception as e:
            logger.error(f"Error playing duck sound: {str(e)}")

    def transition_to(self, state):
        """
        Transition to a new animation state.
        
        Args:
            state (str): The state to transition to
        """
        try:
            logger.debug(f"Transitioning to state: {state}")
            self.play_animation(state)
        except Exception as e:
            logger.error(f"Error in transition_to: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")

    def update(self):
        """Update the current animation frame."""
        try:
            if self.current_animation and isinstance(self.current_animation, QMovie):
                self.current_animation.jumpToNextFrame()
        except Exception as e:
            logger.error(f"Error in update: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}") 