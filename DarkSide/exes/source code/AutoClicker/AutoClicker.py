#!/usr/bin/python
# -*- coding: utf-8 -*-

import os
import pyautogui
import sys
import logging
import pygame
import cv2
from pyautogui import ImageNotFoundException
import time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import _Exe_Util
import _GUI_Util

TITLE = u"EnneadTab Auto Clicker."

def try_click_ref_image(ref_image, confidence=0.3, region=None, retries=3):
    for attempt in range(retries):
        try:
            logger.info(f"Attempt {attempt+1}: Attempting to locate image: {ref_image}")

            # Check if the image exists
            if not os.path.exists(ref_image):
                logger.error(f"Image path {ref_image} does not exist.")
                return False

            # Locate image on screen with adjustable confidence level, grayscale, and optional region
            icon = pyautogui.locateOnScreen(ref_image, confidence=confidence, grayscale=True, region=region)
            logger.info(f"Icon location: {icon}")
            if not icon:
                logger.info("Button not found.")
                continue  # Retry if not found

            pyautogui.click(pyautogui.center(icon))
            logger.info("Button clicked.")
            return True

        except ImageNotFoundException as e:
            logger.error("Image not found. Ensure the image is on the screen and the path is correct.", exc_info=True)
            continue  # Retry on failure
        except Exception as e:
            logger.error("Failed to locate or click the button.", exc_info=True)
            continue  # Retry on failure

        time.sleep(1)  # Brief pause before retrying

    logger.error("Failed to locate and click the image after multiple attempts.")
    return False

def take_screenshot(save_path):
    screenshot = pyautogui.screenshot()
    screenshot.save(save_path)
    logger.info(f"Screenshot saved at {save_path}")

class AutoClicker(_GUI_Util.BasePyGameGUI):
    def __init__(self):
        pygame.init()  # Ensure pygame is initialized
        self.app_title = TITLE
        self.SCREEN_WIDTH = 700
        self.SCREEN_HEIGHT = 500
        self.content_folder = os.path.dirname(__file__)

        self.life_max = _GUI_Util.BasePyGameGUI.MAX_LIFE
        self.life_count = self.life_max

        self.taskbar_icon = "{}\\images\\icon.png".format(self.content_folder)

        self.setup_GUI()

    @_Exe_Util.try_catch_error
    def main(self):
        while self.run:
            self.reset_pointer()  # move pointer to initial position
            self.screen.fill(self.BACKGROUND_COLOR)  # fill background color before drawing anything else

            self.update_logo_angle()  # update animated logo
            self.update_title()
            self.draw_text("This tool actively looks for images on your screen.", self.FONT_BODY, self.TEXT_COLOR)
            self.draw_text("And clicks it to bypass the warning popup.", self.FONT_BODY, self.TEXT_COLOR)

            if hasattr(self, "list_of_ref_images") and self.list_of_ref_images:
                for i, image in enumerate(self.list_of_ref_images):
                    self.draw_text(" {}. {}".format(i+1, image), self.FONT_BODY, self.TEXT_COLOR)
            if self.life_count % 12 == 0: 
                self.job_data = _Exe_Util.get_data("auto_click_data")
                self.ref_images = self.job_data.get("ref_images", [])
                if self.ref_images:
                    self.ref_images = list(set(self.ref_images))
                    for image in self.ref_images:
                        if not os.path.exists(image) or try_click_ref_image(image):
                            self.job_data["ref_images"] = self.ref_images.remove(image)
                        _Exe_Util.set_data(self.job_data, "auto_click_data")
                    self.list_of_ref_images = self.ref_images[:]
                if not self.ref_images:
                    self.run = False

            self.update_footnote()
            self.check_exit()

            # refresh all drawings by order
            self.clock.tick(self.FPS)
            pygame.display.update()

        pygame.quit()

if __name__ == "__main__":
    AutoClicker().main()
