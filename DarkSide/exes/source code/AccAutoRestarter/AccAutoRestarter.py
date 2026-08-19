import psutil
import time
import os
import logging
import threading
import traceback
from PIL import Image
import pystray
import msvcrt  # Only for Windows
import tkinter as tk
from PIL import Image, ImageTk
import msvcrt  # Use msvcrt for file locking on Windows
import datetime
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import _Exe_Util

# Set up logging

log_file = _Exe_Util.get_file_in_dump_folder("AccAutoRestarter_log.txt")

# Use RotatingFileHandler to ensure the log file grows continuously
from logging.handlers import RotatingFileHandler
handler = RotatingFileHandler(log_file, maxBytes=10**9, backupCount=10)
logging.basicConfig(handlers=[handler], level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

PROCESS_NAME = "DesktopConnector.Applications.Tray.exe"
RESTART_INTERVAL = 1 * 60 * 60  # 1 hour in seconds
ALERT_INTERVAL = 2 * 60  # 2 minutes in seconds

# Get the directory of the current script
script_dir = os.path.dirname(os.path.abspath(__file__))
app_name = "AccAutoRestarter"

LOCK_FILE_PATH = _Exe_Util.get_file_in_dump_folder("AccAutoRestarter.lock")
LOCK_UPDATE_INTERVAL = 30  # seconds
LOCK_TIMEOUT = 60  # seconds

def update_lock_file():
    with open(LOCK_FILE_PATH, 'w') as lock_file:
        lock_file.write(str(datetime.datetime.now()))
        lock_file.flush()
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)

def check_if_already_running():
    if os.path.exists(LOCK_FILE_PATH):
        try:
            with open(LOCK_FILE_PATH, 'r') as lock_file:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                lock_file.seek(0)
                timestamp = lock_file.read().strip()
                last_update = datetime.datetime.fromisoformat(timestamp)
                
                if (datetime.datetime.now() - last_update).total_seconds() < LOCK_TIMEOUT:
                    return True
        except IOError:
            return True
        except ValueError:
            # Handle the case where the timestamp is not in ISO format
            return True
    return False

def stop_process(process_name):
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['name'] == process_name:
            proc.kill()
            logging.info(f"Stopped process: {process_name} (PID: {proc.info['pid']})")

def start_process(process_path):
    os.startfile(process_path)
    logging.info(f"Started process: {process_path}")

def main(icon):
    logging.info("Main function started.")
    process_path = os.path.join(os.environ['ProgramFiles'], 'Autodesk', 'Desktop Connector', PROCESS_NAME)
    alert_icon_path = os.path.join(script_dir, "alert_icon.ico")
    normal_icon_path = os.path.join(script_dir, "normal_icon.ico")
    alerting = False

    while True:
        try:
            for remaining in range(RESTART_INTERVAL, 0, -1):
                if remaining % 10 == 0:
                    update_lock_file()
                icon.title = f"Next ACC connector auto restart in {remaining // 60} minutes and {remaining % 60} seconds.\nRight click to exit."
                if remaining == ALERT_INTERVAL:
                    alerting = True
                if alerting:
                    icon.icon = Image.open(alert_icon_path if remaining % 2 == 0 else normal_icon_path)
                time.sleep(1)
            stop_process(PROCESS_NAME)
            
            logging.info("Pausing for 30 seconds before restarting")
            time.sleep(30)  # Wait 30 seconds before restarting
            start_process(process_path)
            icon.icon = Image.open(normal_icon_path)
            alerting = False
        except Exception as e:
            logging.error(f"Exception occurred: {traceback.format_exc()}")
            break  # Break the loop if an exception occurs
    logging.info("Main function exited.")

def create_image(path):
    return Image.open(path)

def on_quit(icon, item):
    logging.info("User has quit the tray icon.")
    icon.stop()
    os._exit(0)

def setup_tray():
    logging.info("Setting up tray icon.")
    icon = pystray.Icon(app_name)  # Set the tray app title to app_name
    icon.icon = create_image(os.path.join(script_dir, "normal_icon.ico"))
    icon.menu = pystray.Menu(
        pystray.MenuItem(f"Quit EnneadTab {app_name}", on_quit)  # Update menu item to use app_name
    )
    thread = threading.Thread(target=main, args=(icon,))
    thread.daemon = True
    thread.start()
    icon.run()
    logging.info("Tray icon setup completed.")

if __name__ == "__main__":
    logging.info("AccAutoRestarter application opened.")
    if not check_if_already_running():
        setup_tray()
    else:
        logging.info("AccAutoRestarter is already running.")
    logging.info("Main script execution completed.")
