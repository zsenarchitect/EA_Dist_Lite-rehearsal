#!/usr/bin/python
# -*- coding: utf-8 -*-

import os
import pyautogui
import sys
import logging
import time
import threading
from pyautogui import ImageNotFoundException

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import _Exe_Util
import _GUI_Util

# Import pygame after path setup
import pygame

TITLE = u"EnneadTab OK Button Clicker"

class OKButtonClicker(_GUI_Util.BasePyGameGUI):
    def __init__(self):
        pygame.init()
        self.app_title = TITLE
        self.SCREEN_WIDTH = 800
        self.SCREEN_HEIGHT = 600
        self.content_folder = os.path.dirname(__file__)

        self.life_max = _GUI_Util.BasePyGameGUI.MAX_LIFE
        self.life_count = self.life_max

        self.taskbar_icon = "{}\\images\\icon.png".format(self.content_folder)
        
        # Auto-clicker settings
        self.clicking_active = False
        self.click_thread = None
        self.ok_button_image = None
        self.click_interval = 10  # seconds
        self.max_duration = 3600  # 1 hour in seconds
        self.start_time = None
        self.clicks_performed = 0
        self.last_click_time = None
        
        # GUI elements
        self.start_button = None
        self.stop_button = None
        self.test_button = None
        self.status_text = "Ready to start clicking"
        
        self.setup_GUI()

    def setup_GUI(self):
        if self.is_another_app_running():
            sys.exit()
        pygame.init()
        self.screen = pygame.display.set_mode((self.SCREEN_WIDTH, self.SCREEN_HEIGHT))
        pygame.display.set_caption(self.app_title)
        
        # Try to load icon, use default if not found
        try:
            icon = pygame.image.load(self.taskbar_icon)
            pygame.display.set_icon(icon)
        except:
            pass

        self.FONT_TITLE = pygame.font.SysFont(*_GUI_Util.BasePyGameGUI.FONT_TITLE)
        self.FONT_SUBTITLE = pygame.font.SysFont(*_GUI_Util.BasePyGameGUI.FONT_SUBTITLE)
        self.FONT_BODY = pygame.font.SysFont(*_GUI_Util.BasePyGameGUI.FONT_BODY)
        self.FONT_NOTE = pygame.font.SysFont(*_GUI_Util.BasePyGameGUI.FONT_NOTE)

        # Load logo
        try:
            EA_logo = pygame.image.load("{}\\images\\Ennead_Architects_Logo.png".format(self.content_folder)).convert_alpha()
            target_img_size = (100, 100)
            EA_logo = pygame.transform.scale(EA_logo, target_img_size)
            self.original_logo = EA_logo
            self.logo_rect = EA_logo.get_rect(center=(100, self.SCREEN_HEIGHT - 100))
        except:
            self.original_logo = None

        self.clock = pygame.time.Clock()
        self.FPS = 20

        # Create buttons
        try:
            quit_img = pygame.image.load("{}\\images\\button_quit.png".format(self.content_folder)).convert_alpha()
            self.quit_button = _GUI_Util.Button(self.SCREEN_WIDTH - 180, self.SCREEN_HEIGHT - 150, quit_img, 1)
        except:
            # Create a simple text button if image not found
            self.quit_button = TextButton(self.SCREEN_WIDTH - 150, self.SCREEN_HEIGHT - 100, "QUIT", self.FONT_BODY, self.TEXT_COLOR)
        
        # Create start/stop/test buttons
        self.start_button = TextButton(50, 200, "START CLICKING", self.FONT_BODY, (0, 255, 0))
        self.stop_button = TextButton(250, 200, "STOP CLICKING", self.FONT_BODY, (255, 0, 0))
        self.test_button = TextButton(450, 200, "TEST IMAGE", self.FONT_BODY, (0, 0, 255))
        
        # Load OK button image if it exists
        self.load_ok_button_image()

    def load_ok_button_image(self):
        """Load the OK button image from the images folder"""
        possible_paths = [
            "{}\\images\\OK_BUTTON.png".format(self.content_folder),
            "{}\\images\\ok_button.png".format(self.content_folder),
            "{}\\images\\ok_button.jpg".format(self.content_folder),
            "{}\\images\\button_ok.png".format(self.content_folder),
            "{}\\images\\button_ok.jpg".format(self.content_folder)
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                self.ok_button_image = path
                logger.info(f"Loaded OK button image: {path}")
                return
        
        logger.warning("No OK button image found. Please place an image of the OK button in the images folder.")

    def try_click_ok_button(self, confidence=0.6, retries=2):
        """Try to find and click the OK button"""
        if not self.ok_button_image:
            logger.warning("No OK button image loaded")
            return False
            
        for attempt in range(retries):
            try:
                logger.info(f"Attempt {attempt+1}: Looking for OK button with confidence {confidence}")
                
                # Try with grayscale first
                button_location = pyautogui.locateOnScreen(
                    self.ok_button_image, 
                    confidence=confidence, 
                    grayscale=True
                )
                
                # If not found with grayscale, try without
                if not button_location:
                    logger.info("Not found with grayscale, trying without...")
                    button_location = pyautogui.locateOnScreen(
                        self.ok_button_image, 
                        confidence=confidence, 
                        grayscale=False
                    )
                
                if button_location:
                    # Click the center of the found button
                    center = pyautogui.center(button_location)
                    pyautogui.click(center)
                    logger.info(f"OK button clicked at {center}")
                    self.clicks_performed += 1
                    self.last_click_time = time.time()
                    return True
                else:
                    logger.info("OK button not found on screen")
                    
            except ImageNotFoundException:
                logger.info("OK button image not found")
            except Exception as e:
                logger.error(f"Error clicking OK button: {e}")
            
            time.sleep(0.5)  # Brief pause before retry
        
        return False

    def auto_click_loop(self):
        """Main auto-clicking loop that runs in a separate thread"""
        self.start_time = time.time()
        logger.info("Auto-clicking started")
        
        while self.clicking_active:
            current_time = time.time()
            elapsed_time = current_time - self.start_time
            
            # Check if we've exceeded the maximum duration (1 hour)
            if elapsed_time >= self.max_duration:
                logger.info("Maximum duration reached (1 hour), stopping auto-clicker")
                self.clicking_active = False
                break
            
            # Try to click the OK button
            if self.try_click_ok_button():
                self.status_text = f"OK button clicked! Total clicks: {self.clicks_performed}"
            else:
                self.status_text = f"OK button not found. Total clicks: {self.clicks_performed}"
            
            # Wait for the specified interval (10 seconds)
            for _ in range(self.click_interval):
                if not self.clicking_active:
                    break
                time.sleep(1)
        
        logger.info("Auto-clicking stopped")
        self.status_text = f"Auto-clicking stopped. Total clicks performed: {self.clicks_performed}"

    def start_clicking(self):
        """Start the auto-clicking process"""
        if not self.clicking_active:
            self.clicking_active = True
            self.clicks_performed = 0
            self.click_thread = threading.Thread(target=self.auto_click_loop, daemon=True)
            self.click_thread.start()
            self.status_text = "Auto-clicking started..."

    def stop_clicking(self):
        """Stop the auto-clicking process"""
        if self.clicking_active:
            self.clicking_active = False
            self.status_text = "Stopping auto-clicker..."

    def test_image_recognition(self):
        """Test the image recognition without clicking"""
        if not self.ok_button_image:
            self.status_text = "No OK button image loaded"
            return
            
        logger.info("Testing image recognition...")
        self.status_text = "Testing image recognition..."
        
        try:
            # Try to find the image on screen
            button_location = pyautogui.locateOnScreen(
                self.ok_button_image, 
                confidence=0.6, 
                grayscale=True
            )
            
            if button_location:
                center = pyautogui.center(button_location)
                self.status_text = f"Image found at {center}! Ready to click."
                logger.info(f"Test successful - image found at {center}")
            else:
                # Try without grayscale
                button_location = pyautogui.locateOnScreen(
                    self.ok_button_image, 
                    confidence=0.6, 
                    grayscale=False
                )
                
                if button_location:
                    center = pyautogui.center(button_location)
                    self.status_text = f"Image found at {center} (no grayscale)! Ready to click."
                    logger.info(f"Test successful - image found at {center} without grayscale")
                else:
                    self.status_text = "Image not found on screen. Check if OK button is visible."
                    logger.warning("Test failed - image not found on screen")
                    
        except Exception as e:
            self.status_text = f"Test error: {str(e)}"
            logger.error(f"Test error: {e}")

    @_Exe_Util.try_catch_error
    def main(self):
        while self.run:
            self.reset_pointer()
            self.screen.fill(self.BACKGROUND_COLOR)

            # Update logo if available
            if self.original_logo:
                self.update_logo_angle()
            
            self.update_title()
            
            # Draw main content
            self.draw_text("OK Button Auto-Clicker", self.FONT_SUBTITLE, self.TEXT_COLOR)
            self.draw_text("", self.FONT_BODY, self.TEXT_COLOR)  # Empty line
            
            # Draw instructions
            self.draw_text("Instructions:", self.FONT_BODY, self.TEXT_COLOR)
            self.draw_text("1. Take a screenshot of the OK button you want to click", self.FONT_BODY, self.TEXT_COLOR)
            self.draw_text("2. Save it as 'ok_button.png' in the images folder", self.FONT_BODY, self.TEXT_COLOR)
            self.draw_text("3. Click START CLICKING to begin", self.FONT_BODY, self.TEXT_COLOR)
            self.draw_text("4. The app will click every 10 seconds for 1 hour", self.FONT_BODY, self.TEXT_COLOR)
            self.draw_text("", self.FONT_BODY, self.TEXT_COLOR)  # Empty line
            
            # Draw status
            self.draw_text(f"Status: {self.status_text}", self.FONT_BODY, self.TEXT_COLOR)
            
            if self.clicking_active:
                elapsed = time.time() - self.start_time if self.start_time else 0
                remaining = max(0, self.max_duration - elapsed)
                hours = int(remaining // 3600)
                minutes = int((remaining % 3600) // 60)
                seconds = int(remaining % 60)
                self.draw_text(f"Time remaining: {hours:02d}:{minutes:02d}:{seconds:02d}", self.FONT_BODY, self.TEXT_COLOR)
            
            # Draw buttons
            if self.start_button and self.start_button.draw(self.screen) and not self.clicking_active:
                self.start_clicking()
            
            if self.stop_button and self.stop_button.draw(self.screen) and self.clicking_active:
                self.stop_clicking()
            
            if self.test_button and self.test_button.draw(self.screen) and not self.clicking_active:
                self.test_image_recognition()
            
            self.update_footnote()
            self.check_exit()

            # Refresh display
            self.clock.tick(self.FPS)
            pygame.display.update()

        # Clean up
        self.stop_clicking()
        pygame.quit()

class TextButton:
    def __init__(self, x, y, text, font, color, bg_color=None):
        self.x = x
        self.y = y
        self.text = text
        self.font = font
        self.color = color
        self.bg_color = bg_color
        self.text_surface = font.render(text, True, color)
        self.rect = self.text_surface.get_rect()
        self.rect.topleft = (x, y)
        self.clicked = False

    def draw(self, surface):
        action = False
        pos = pygame.mouse.get_pos()

        # Check mouseover and clicked conditions
        if self.rect.collidepoint(pos):
            if pygame.mouse.get_pressed()[0] == 1 and self.clicked == False:
                self.clicked = True
                action = True

        if pygame.mouse.get_pressed()[0] == 0:
            self.clicked = False

        # Draw background if specified
        if self.bg_color:
            pygame.draw.rect(surface, self.bg_color, self.rect)
        
        # Draw button text
        surface.blit(self.text_surface, self.rect)

        return action

if __name__ == "__main__":
    OKButtonClicker().main()
