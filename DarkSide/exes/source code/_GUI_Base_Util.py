
import pyautogui

def rgb_to_hex(r, g, b):
    return '#{:02x}{:02x}{:02x}'.format(r, g, b)

class BaseGUI:

    BACKGROUND_COLOR = (80, 97, 81)# new green
    BACKGROUND_COLOR = (52, 78, 91) # original blue
    BACKGROUND_COLOR = (46,46,46)  
    BACKGROUND_COLOR_HEX = rgb_to_hex(*BACKGROUND_COLOR)
    TEXT_COLOR = (255, 255, 255)
    TEXT_COLOR_FADE = (150, 150, 150)
    TEXT_COLOR_WARNING = (252, 127, 3)
    TEXT_COLOR_BIG_WARNING = (242, 52, 39)

    
    FONT_TITLE = ("arialblack", 30)
    FONT_SUBTITLE = ("arialblack", 15)
    FONT_BODY = ("arial", 12)
    FONT_NOTE = ("arialblack", 10)

    run = True

    MAX_LIFE = 12 * 60 * 60 * 20


    
                
    def is_another_app_running(self, windowed_only = True):
        if not hasattr(self, 'app_title'):
            return False

        return is_another_app_running_by_title(self.app_title, windowed_only)

def is_another_app_running_by_title(title, windowed_only = True):

    if windowed_only:
        for window in pyautogui.getAllWindows():
            if title in window.title:
                print ("{} is running".format(title))
                return True
        return False
    else:
        import psutil
        for proc in psutil.process_iter(['name']):
            if title in proc.info['name']:
                return True
        return False