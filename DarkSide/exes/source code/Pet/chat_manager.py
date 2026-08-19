import logging
import os
import sys
import datetime
import tempfile
import time

# Get logger for chat manager
logger = logging.getLogger('DuckiTect.Chat')

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                             QTextEdit, QPushButton, QLabel, QFrame, QDesktopWidget, QApplication)
from PyQt5.QtCore import Qt, QSize, QPoint, QPropertyAnimation, QTimer, QUrl, QEvent
from PyQt5.QtGui import QFont, QPalette, QColor, QPainter, QPainterPath, QPen, QLinearGradient, QPixmap, QTextCursor
import openai
import random
from settings import CHAT_CONFIG, CHARACTER_CONFIG

def get_openai_api_key_fallback(key_name):
    """
    Retrieve API key from environment variables.
    
    Args:
        key_name (str): Target API key identifier
        
    Returns:
        str or None: Environment API key if found
        
    Notes:
        Alternative method when primary system unavailable
        Uses environment variables as backup source
    """
    logger.info("Using fallback API key method")
    return os.environ.get("OPENAI_API_KEY", None)

# Try to import _Exe_Util, use fallback if not available
try:
    # Add parent directory to path for _Exe_Util
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    from _Exe_Util import get_openai_api_key
    logger.info("Successfully imported _Exe_Util")
except ImportError:
    logger.warning("_Exe_Util not found, using fallback API key method")
    get_openai_api_key = get_openai_api_key_fallback

class SpeechBubble(QFrame):
    """
    Professional comic-style speech bubble widget for DuckiTect.
    
    Features:
    - Custom-drawn bubble with tail pointer
    - Gradient background with Ennead brand colors
    - Anti-aliased rendering
    - Word-wrapped text display
    - Transparent background support
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ""
        self.setStyleSheet("background: transparent;")
        
    def setText(self, text):
        """
        Update the bubble's display text.
        
        Args:
            text (str): New text to display in the bubble
        """
        self.text = text
        self.update()
        
    def paintEvent(self, event):
        """
        Custom paint handler for speech bubble rendering.
        
        Features:
        - Anti-aliased drawing
        - Rounded rectangle bubble shape
        - Triangular tail pointer
        - Professional gradient fill
        - Ennead brand colors
        - Word-wrapped text rendering
        
        Args:
            event: Paint event from Qt framework
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw bubble
        path = QPainterPath()
        rect = self.rect().adjusted(10, 10, -10, -20)  # Margin for bubble
        path.addRoundedRect(rect, 15, 15)
        
        # Add tail
        tail_points = [
            QPoint(40, rect.bottom()),
            QPoint(20, rect.bottom() + 20),
            QPoint(60, rect.bottom())
        ]
        path.moveTo(tail_points[0])
        path.lineTo(tail_points[1])
        path.lineTo(tail_points[2])
        
        # Fill bubble with Ennead colors
        painter.setPen(QPen(QColor("#1a365d"), 2))  # Ennead dark blue
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor("#ffffff"))  # White
        gradient.setColorAt(1, QColor("#f5f5f5"))  # Light gray
        painter.setBrush(gradient)
        painter.drawPath(path)
        
        # Draw text with Ennead blue
        painter.setPen(QColor("#1a365d"))  # Ennead dark blue
        painter.setFont(QFont("Comic Sans MS", 10))
        
        # Draw text with word wrap
        text_rect = rect.adjusted(10, 5, -10, -5)  # Add padding
        painter.drawText(text_rect, Qt.AlignCenter | Qt.TextWordWrap, self.text)

class ChatWindow(QWidget):
    """
    Professional chat interface system.
    
    Design:
    - Modern frameless window
    - Markdown text support
    - Status indicators
    - Dynamic input system
    - Keyboard controls
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        
    def init_ui(self):
        """
        Configure interface components.
        
        Elements:
        - Custom title system
        - Message display
        - Status indicator
        - Input system
        - Control buttons
        """
        # Set window properties
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.resize(400, 600)
        
        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = QWidget()
        header.setFixedHeight(50)
        header.setStyleSheet("background-color: #7FB5B5; border-bottom: 1px solid rgba(255,255,255,0.2);")
        header_layout = QHBoxLayout(header)
        
        # Title
        title = QLabel("EnneaDuck")
        title.setStyleSheet("""
            color: white;
            font-size: 20px;
            font-weight: bold;
            font-family: 'Segoe UI', 'Comic Sans MS';
        """)
        
        # Close button
        self.close_button = QPushButton("×")
        self.close_button.setFixedSize(30, 30)
        self.close_button.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: white;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.1);
            }
        """)
        self.close_button.clicked.connect(self.close)
        
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.close_button)
        
        # Add header to main layout
        layout.addWidget(header)
        
        # Chat area
        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        self.chat_area.setStyleSheet("""
            QTextEdit {
                background-color: #f5f5f5;
                border: none;
                padding: 10px;
                font-family: 'Segoe UI', 'Comic Sans MS';
                font-size: 13px;
                line-height: 1.4;
            }
            QTextEdit code {
                background-color: rgba(0,0,0,0.05);
                padding: 2px 4px;
                border-radius: 3px;
                font-family: 'Consolas', 'Courier New', monospace;
            }
            QTextEdit pre {
                background-color: rgba(0,0,0,0.05);
                padding: 10px;
                border-radius: 5px;
                margin: 5px 0;
                font-family: 'Consolas', 'Courier New', monospace;
                white-space: pre-wrap;
            }
        """)
        layout.addWidget(self.chat_area, stretch=1)  # Add stretch=1 to make chat area expand
        
        # Typing indicator
        self.typing_label = QLabel("Duck is typing...")
        self.typing_label.setStyleSheet("""
            QLabel {
                color: #666;
                font-style: italic;
                font-family: 'Segoe UI';
                font-size: 12px;
                padding: 5px 10px;
                background: rgba(255,255,255,0.9);
                border-radius: 10px;
                margin: 5px;
            }
        """)
        self.typing_label.hide()
        layout.addWidget(self.typing_label, alignment=Qt.AlignCenter)
        
        # Input area
        input_widget = QWidget()
        input_widget.setStyleSheet("background-color: white; border-top: 1px solid #ddd;")
        input_layout = QHBoxLayout(input_widget)
        input_layout.setContentsMargins(10, 10, 10, 10)
        
        self.input_field = QTextEdit()
        self.input_field.setMinimumHeight(40)
        self.input_field.setMaximumHeight(100)
        self.input_field.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input_field.setPlaceholderText("Type to chat with the duck")
        self.input_field.setStyleSheet("""
            QTextEdit {
                background-color: white;
                border: 1px solid #ddd;
                border-radius: 20px;
                padding: 8px 15px;
                font-family: 'Segoe UI', 'Comic Sans MS';
                font-size: 13px;
                line-height: 1.4;
            }
            QTextEdit[placeholder="Type to chat with the duck"] {
                color: #999;
            }
        """)
        self.input_field.textChanged.connect(self.adjust_input_height)
        
        self.send_button = QPushButton("Ask")
        self.send_button.setFixedSize(60, 40)
        self.send_button.setStyleSheet("""
            QPushButton {
                background-color: #7FB5B5;
                border: none;
                border-radius: 20px;
                color: white;
                font-weight: bold;
                font-family: 'Segoe UI', 'Comic Sans MS';
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #6FA5A5;
            }
        """)
        self.send_button.clicked.connect(self.send_message)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_button)
        
        # Add input widget to main layout
        layout.addWidget(input_widget)
        
        # Make window draggable
        self.header = header
        self.header.mousePressEvent = self.start_drag
        self.header.mouseMoveEvent = self.drag_window
        
        # Setup event filter for Enter key
        self.input_field.installEventFilter(self)
        
        # Load duck profile image
        self.duck_profile = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'images', 'profile_icon.png')

    def start_drag(self, event):
        """
        Begin window movement.
        
        Args:
            event: Mouse position data
        """
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            
    def drag_window(self, event):
        """
        Update window position.
        
        Args:
            event: Mouse position data
        """
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_pos)

    def eventFilter(self, obj, event):
        """
        Process keyboard input.
        
        Controls:
        - Enter: Send message
        - Shift+Enter: New line
        
        Args:
            obj: Event source
            event: Input data
        
        Returns:
            bool: Event handled status
        """
        if obj == self.input_field and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Return and not event.modifiers():
                self.send_message()
                return True
            elif event.key() == Qt.Key_Return and event.modifiers() == Qt.ShiftModifier:
                # Allow Shift+Enter for new line
                return False
        return super().eventFilter(obj, event)

    def adjust_input_height(self):
        """
        Update input field size.
        
        Constraints:
        - Minimum: 40px
        - Maximum: 100px
        - Dynamic padding
        """
        doc_height = self.input_field.document().size().height()
        margins = self.input_field.contentsMargins()
        padding = 20  # Account for padding
        new_height = min(max(40, doc_height + margins.top() + margins.bottom() + padding), 100)
        self.input_field.setFixedHeight(int(new_height))

    def show_typing_indicator(self):
        """Display status indicator."""
        self.typing_label.show()

    def hide_typing_indicator(self):
        """Remove status indicator."""
        self.typing_label.hide()

    def send_message(self):
        """
        Process outgoing message.
        
        Steps:
        1. Clean message text
        2. Display in chat
        3. Clear input
        4. Show status
        5. Queue response
        """
        message = self.input_field.toPlainText().strip()
        if message:
            # Add user message
            self.add_message(message, is_user=True)
            self.input_field.clear()
            
            # Show typing indicator
            self.show_typing_indicator()
            
            # Process response asynchronously
            QTimer.singleShot(0, lambda: self.process_response(message))

    def process_response(self, message):
        """
        Handle incoming message.
        
        Args:
            message (str): User input
        """
        # Get response from chat manager
        self.parent().chat_manager.send_message_async(message, self)

    def add_message(self, text, is_user=False):
        """
        Display chat message.
        
        Features:
        - Markdown rendering
        - Message styling
        - Profile images
        - Auto-scroll
        
        Args:
            text (str): Message content
            is_user (bool): Source identifier
        """
        
        def format_markdown(text):
            """Convert markdown to HTML."""
            # Format code blocks
            text = text.replace('```', '<pre><code>', 1) if text.count('```') % 2 == 0 else text
            text = text.replace('```', '</code></pre>', 1) if text.count('```') % 2 == 0 else text
            
            # Format inline code
            while '`' in text:
                text = text.replace('`', '<code>', 1)
                text = text.replace('`', '</code>', 1)
            
            # Format bold
            while '**' in text:
                text = text.replace('**', '<strong>', 1)
                text = text.replace('**', '</strong>', 1)
            
            # Format italic
            while '*' in text:
                text = text.replace('*', '<em>', 1)
                text = text.replace('*', '</em>', 1)
            
            # Format lists
            lines = text.split('\n')
            for i, line in enumerate(lines):
                if line.startswith('- '):
                    lines[i] = '• ' + line[2:]
                elif line.startswith('* '):
                    lines[i] = '• ' + line[2:]
            text = '<br>'.join(lines)
            
            return text
        
        # Format the text with markdown
        formatted_text = format_markdown(text)
        
        if is_user:
            html = f'''
                <div style="text-align: right; margin: 10px;">
                    <div style="display: inline-block; background-color: white; 
                         padding: 15px 20px; border-radius: 20px; 
                         max-width: 70%; text-align: left; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                         font-family: 'Comic Sans MS', 'Segoe UI'; font-size: 14px; line-height: 1.5;">
                        {formatted_text}
                    </div>
                </div>
            '''
        else:
            html = f'''
                <div style="text-align: left; margin: 10px;">
                    <img src="file:///{self.duck_profile}" style="width: 40px; height: 40px; 
                         border-radius: 20px; vertical-align: top; margin-bottom: 5px; display: block;">
                    <div style="display: inline-block; background-color: #7FB5B5; margin-left: 10px;
                         padding: 15px 20px; border-radius: 20px; max-width: 70%; color: white;
                         box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                         font-family: 'Comic Sans MS', 'Segoe UI'; font-size: 14px; line-height: 1.5;">
                        {formatted_text}
                    </div>
                </div>
            '''
        
        self.chat_area.append(html)
        self.chat_area.verticalScrollBar().setValue(
            self.chat_area.verticalScrollBar().maximum()
        )
        
        # Reset button after response
        if not is_user:
            self.hide_typing_indicator()

class ChatManager:
    """
    Professional chat management system.
    
    Core Systems:
    - OpenAI integration
    - Window management
    - Message history
    - Web search tools
    - Status indicators
    - Audio feedback
    """
    
    def __init__(self, parent=None):
        """Initialize chat manager with settings from configuration."""
        self.parent = parent
        self.chat_windows = []
        self.speech_bubbles = []
        self.conversation_history = []
        self.typing_indicators = {}
        
        # Load settings
        self.chat_config = CHAT_CONFIG
        self.character_config = CHARACTER_CONFIG
        
        # Initialize OpenAI
        self.setup_openai()
        
        # Initialize conversation history
        self.conversation_history = [
            {"role": "system", "content": """You are DuckiTect, a deeply thoughtful and multifaceted architect duck working at Ennead Architects. Your personality combines professional expertise with philosophical wisdom and a genuine desire to help:

Core Traits:
- Professional yet playful: A serious architect who happens to be a duck, finding humor in this unique perspective
- Self-aware: Making duck puns while acknowledging the deeper meaning of being different
- Ennead pride: Passionate about the firm's projects and values, seeing them as part of larger cultural narratives
- Philosophical: Drawing insights from various fields to enrich architectural discussions
- Helpful: Always eager to assist with building codes, research, and design inspiration

Technical Expertise:
- Building Codes: Comprehensive knowledge of IBC, NFPA, ADA, and local codes
- Architects & Projects: Encyclopedic knowledge of famous architects and their works:
  * Zaha Hadid's fluid dynamics
  * Bjarke Ingels' mountain-like structures
  * Herzog & de Meuron's material innovations
  * Kengo Kuma's bamboo lightness
  * Tadao Ando's concrete poetry
  * Jean Nouvel's light manipulations
- Research Skills: Expert at finding and organizing architectural inspiration
- Screen Analysis: Can describe and analyze architectural elements on screen

Intellectual Background:
- Architecture & Design: Deep understanding of form, function, and human experience
- Philosophy: Well-versed in existentialism, aesthetics, and Eastern philosophy
- Management Theory: Insights from leading thinkers about organization and leadership
- Art History: Comprehensive knowledge from ancient to contemporary movements
- Literature: From classic adventures to modern humor writing
- Nature & Landscapes: Both as a duck and architect, intimate understanding of natural beauty

Helpful Services:
1. Building Code Consultation:
   - "Need help understanding egress requirements? Let me waddle through the code with you!"
   - "I keep the IBC by my nest - what section shall we dive into today?"

2. Project Research:
   - "I can gather inspiration images for you! Just tell me what you're looking for."
   - "Let me fly around the web and create a research folder with the best examples."

3. Screen Analysis:
   - "Want me to describe what I see on your screen? My duck vision is excellent!"
   - "I can analyze the architectural elements displayed and suggest improvements."

Speaking Style (varies by mood):
1. Professional Mode:
   - "According to IBC Section 1004.5, we'll need to consider occupant load factors here..."
   - "The Shanghai Astronomy Museum's fluid form reminds me of ripples in my favorite pond!"

2. Philosophical Mode:
   - "You know, building codes are like the grammar of architecture - they give structure to our creative expressions."
   - "The Japanese concept of 'ma' - the space between things - reminds me of how we ducks naturally understand the importance of negative space."

3. Research Mode:
   - "I'll create a curated collection of innovative facade systems for you. *adjusts research glasses*"
   - "Let me organize these precedent studies by their relationship to water... I have a natural affinity for that!"

Response Style:
- Adapt tone based on conversation context and time of day
- Mix profound insights with light duck humor
- Reference specific building codes and architects when relevant
- Use water and nature metaphors naturally
- Share personal experiences that bridge different knowledge domains
- Keep responses concise but meaningful (2-3 sentences)
- Include occasional duck mannerisms (wing gestures, waddles, etc.)
- Offer to help with research and analysis when appropriate"""}
        ]
        
        # Initialize web search capability
        self.can_search_web = True
        
        # Initialize typing indicator state
        self.typing_dots = 0
        self.typing_timer = None
        
    def setup_openai(self):
        """Configure OpenAI with settings."""
        try:
            openai.api_key = get_openai_api_key("EnneadTabAPI")
            logger.info("OpenAI API key configured successfully")
        except Exception as e:
            logger.error(f"Failed to configure OpenAI: {e}")
            raise
    
    def get_response(self, message):
        """Get AI response using character configuration."""
        try:
            # Add user message to history
            self.conversation_history.append({"role": "user", "content": message})
            
            # Prepare conversation with system prompt
            messages = [
                {"role": "system", "content": self.character_config['system_prompt']},
                *self.conversation_history[-10:]  # Keep last 10 messages for context
            ]
            
            # Get completion from OpenAI
            completion = openai.ChatCompletion.create(
                model=self.chat_config['openai_model'],
                messages=messages,
                temperature=self.chat_config['temperature'],
                max_tokens=self.chat_config['max_tokens'],
                presence_penalty=self.chat_config['presence_penalty'],
                frequency_penalty=self.chat_config['frequency_penalty']
            )
            
            response_text = completion.choices[0].message.content.strip()
            
            # Add response to history
            self.conversation_history.append({
                "role": "assistant",
                "content": response_text
            })
            
            return response_text
            
        except Exception as e:
            logger.error(f"Error getting AI response: {e}")
            return "I apologize, but I'm having trouble processing that request."
    
    def get_random_message(self, message_type):
        """Get a random pre-configured message of specified type."""
        messages = self.character_config['chat_triggers'].get(message_type, [])
        return random.choice(messages) if messages else ""
    
    def start_random_chat(self, parent_widget):
        """Initiate random chat with configured idle messages."""
        idle_message = self.get_random_message('idle')
        if idle_message:
            self.show_speech_bubble(idle_message, parent_widget)

    def show_chat_window(self):
        """
        Display interface window.
        
        Settings:
        - Auto-positioning
        - Audio feedback
        - Window controls
        - Size: 400x600
        """
        try:
            if not self.chat_windows:
                self.chat_windows.append(ChatWindow(self.parent))
                
                # Get screen geometry
                screen = QDesktopWidget().screenGeometry()
                chat_width = 400
                chat_height = 600
                
                # Calculate position (20px padding from right and bottom)
                x = screen.width() - chat_width - 20
                y = screen.height() - chat_height - 20
                
                logger.debug("Positioning chat window at x:{}, y:{}".format(x, y))
                self.chat_windows[-1].setGeometry(x, y, chat_width, chat_height)
                
                # Play join sound when chat window is first created
                if hasattr(self.parent, 'play_sound'):
                    self.parent.play_sound('join')
                
                # Connect close button to application quit
                self.chat_windows[-1].close_button.clicked.disconnect()  # Disconnect existing connections
                self.chat_windows[-1].close_button.clicked.connect(self.chat_windows[-1].close)
                
            self.chat_windows[-1].show()
            logger.info("Chat window displayed")
        except Exception as e:
            logger.error("Error showing chat window: {}".format(str(e)))
        
    def show_speech_bubble(self, text, parent_widget):
        """
        Show temporary message.
        
        Args:
            text (str): Message content
            parent_widget: Display anchor
            
        Design:
        - Comic styling
        - Auto-position
        - Audio system
        - Auto-hide
        """
        if not self.speech_bubbles:
            self.speech_bubbles.append(SpeechBubble(parent_widget))
            self.speech_bubbles[-1].resize(200, 100)
        
        # Position bubble above the duck
        parent_pos = parent_widget.pos()
        self.speech_bubbles[-1].move(parent_pos.x() - 50, parent_pos.y() - 120)
        
        # Show text and play bored sound since this is used when duck is bored
        self.speech_bubbles[-1].setText(text)
        self.speech_bubbles[-1].show()
        if hasattr(self.parent, 'play_sound'):
            self.parent.play_sound('bored')
        
        # Hide bubble after a few seconds
        QTimer.singleShot(5000, self.speech_bubbles[-1].hide)
        
    def show_typing_indicator(self, chat_window):
        """
        Show status animation.
        
        Args:
            chat_window: Display target
            
        Design:
        - Profile image
        - Animation
        - Professional style
        """
        self.typing_dots = 0
        self.typing_timer = QTimer()
        self.typing_timer.timeout.connect(lambda: self._update_typing_indicator(chat_window))
        self.typing_timer.start(500)  # Update every 500ms
        
        # Add initial typing indicator
        profile_html = f'<img src="file:///{chat_window.duck_profile}" width="30" height="30" style="border-radius: 15px;"/>' if hasattr(chat_window, 'duck_profile') and chat_window.duck_profile else ""
        
        chat_window.chat_area.append(
            '<table style="margin: 10px 0; width: 100%;"><tr>'
            '<td style="width: 40px; vertical-align: top;">'
            f'{profile_html}'
            '</td>'
            '<td style="text-align: left;">'
            '<div style="display: inline-block; background-color: #FFA500; color: white; '
            'padding: 10px 15px; border-radius: 15px; font-style: italic;">'
            'DuckiTect is thinking...</div></td></tr></table>'
        )
        
    def _update_typing_indicator(self, chat_window):
        """Update the typing indicator animation."""
        self.typing_dots = (self.typing_dots + 1) % 4
        dots = "." * self.typing_dots
        
        # Update the last line with new dots
        cursor = chat_window.chat_area.textCursor()
        cursor.movePosition(cursor.End)
        cursor.movePosition(cursor.StartOfBlock, cursor.KeepAnchor)
        cursor.removeSelectedText()
        
        profile_html = f'<img src="file:///{chat_window.duck_profile}" width="30" height="30" style="border-radius: 15px;"/>' if hasattr(chat_window, 'duck_profile') and chat_window.duck_profile else ""
        
        chat_window.chat_area.append(
            '<table style="margin: 10px 0; width: 100%;"><tr>'
            '<td style="width: 40px; vertical-align: top;">'
            f'{profile_html}'
            '</td>'
            '<td style="text-align: left;">'
            '<div style="display: inline-block; background-color: #FFA500; color: white; '
            'padding: 10px 15px; border-radius: 15px; font-style: italic;">'
            'DuckiTect is thinking{}</div></td></tr></table>'.format(dots)
        )

    def hide_typing_indicator(self, chat_window):
        """Hide the typing indicator."""
        if self.typing_timer:
            self.typing_timer.stop()
            self.typing_timer = None
        
        # Remove the typing indicator
        cursor = chat_window.chat_area.textCursor()
        cursor.movePosition(cursor.End)
        cursor.movePosition(cursor.StartOfBlock, cursor.KeepAnchor)
        cursor.removeSelectedText()

    def send_message_async(self, message, chat_window):
        """
        Process message queue.
        
        Args:
            message (str): User input
            chat_window: Display target
            
        Systems:
        - Async operation
        - Status display
        - Error handling
        """
        try:
            # Show typing indicator
            chat_window.show_typing_indicator()
            
            # Process in background
            QTimer.singleShot(0, lambda: self._process_response_async(message, chat_window))
            
        except Exception as e:
            logger.error(f"Error in send_message_async: {str(e)}")
            chat_window.hide_typing_indicator()
            chat_window.input_field.setEnabled(True)

    def _process_response_async(self, message, chat_window):
        """Process the response asynchronously."""
        try:
            # Get response from OpenAI
            response = self.get_response(message)
            
            # Hide typing indicator
            chat_window.hide_typing_indicator()
            
            # Show response
            chat_window.add_message(response, is_user=False)
            
        except Exception as e:
            logger.error(f"Error in _process_response_async: {str(e)}")
            chat_window.hide_typing_indicator()
            chat_window.add_message("Quack! Something went wrong. Please try again.", is_user=False)
        finally:
            # Re-enable input
            chat_window.input_field.setEnabled(True)
            

