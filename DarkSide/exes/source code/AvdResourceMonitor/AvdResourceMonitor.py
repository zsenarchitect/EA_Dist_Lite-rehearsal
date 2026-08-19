import psutil
import time
import tkinter as tk
from PIL import Image
import socket
import os
import pystray
from pystray import MenuItem as item
import logging
import sys
import json
import re
from datetime import datetime

from py3nvml.py3nvml import nvmlInit, nvmlDeviceGetCount, nvmlDeviceGetHandleByIndex, nvmlDeviceGetUtilizationRates, nvmlShutdown

# Common Windows process descriptions
PROCESS_DESCRIPTIONS = {
    "MsMpEng.exe": "Windows Defender Antivirus Service",
    "chrome.exe": "Google Chrome Browser",
    "firefox.exe": "Mozilla Firefox Browser",
    "explorer.exe": "Windows File Explorer",
    "svchost.exe": "Windows Service Host",
    # Design Software
    "Revit.exe": "Autodesk Revit",
    "RevitWorker.exe": "Autodesk Revit Background Process",
    "acad.exe": "AutoCAD",
    "AutoCAD.exe": "AutoCAD",
    "rhino.exe": "Rhinoceros 3D",
    "Rhino.exe": "Rhinoceros 3D",
    "Rhino7.exe": "Rhinoceros 3D v7",
    "Rhino8.exe": "Rhinoceros 3D v8",
    "Enscape.exe": "Enscape Renderer",
    "EnscapeViewer.exe": "Enscape Viewer",
    "3dsmax.exe": "Autodesk 3ds Max",
    "SketchUp.exe": "SketchUp",
    "FormIt.exe": "Autodesk FormIt",
    "Navisworks.exe": "Autodesk Navisworks",
    "NavisworksManage.exe": "Autodesk Navisworks Manage",
    "Inventor.exe": "Autodesk Inventor",
    "Maya.exe": "Autodesk Maya",
    "Civil3D.exe": "Autodesk Civil 3D",
    "RhinoCompute.exe": "Rhino Compute Server",
    "Grasshopper.exe": "Grasshopper for Rhino",
    "TwinMotion.exe": "Epic TwinMotion",
    "V-Ray.exe": "V-Ray Renderer",
    "Corona.exe": "Corona Renderer",
    "Lumion.exe": "Lumion",
    "LumionPro.exe": "Lumion Pro",
    "DynamoSandbox.exe": "Dynamo BIM",
    "DynamoRevit.exe": "Dynamo for Revit",
    # Other Common Apps
    "photoshop.exe": "Adobe Photoshop",
    "illustrator.exe": "Adobe Illustrator",
    "excel.exe": "Microsoft Excel",
    "word.exe": "Microsoft Word",
    "powerpnt.exe": "Microsoft PowerPoint",
    "outlook.exe": "Microsoft Outlook",
    "teams.exe": "Microsoft Teams",
    "zoom.exe": "Zoom Meeting",
    "code.exe": "Visual Studio Code",
    "python.exe": "Python Interpreter",
    "node.exe": "Node.js Process",
    "WindowsTerminal.exe": "Windows Terminal",
    "notepad.exe": "Windows Notepad",
    "winlogon.exe": "Windows Logon",
    "dwm.exe": "Desktop Window Manager",
    "csrss.exe": "Windows Client/Server Runtime",
    "lsass.exe": "Windows Security Service",
    "taskmgr.exe": "Task Manager",
    "SearchHost.exe": "Windows Search",
    "RuntimeBroker.exe": "Windows Runtime Broker",
    "ShellExperienceHost.exe": "Windows Shell Experience",
    "SearchIndexer.exe": "Windows Search Indexer"
}

# Design software process patterns to always monitor
DESIGN_SOFTWARE_PATTERNS = {
    r"revit.*\.exe$": "Autodesk Revit Process",
    r"rhino\d*\.exe$": "Rhinoceros 3D",
    r"autocad.*\.exe$": "AutoCAD Process",
    r"enscape.*\.exe$": "Enscape Process",
    r"3dsmax.*\.exe$": "3ds Max Process",
    r"sketchup.*\.exe$": "SketchUp Process",
    r"formit.*\.exe$": "FormIt Process",
    r"navisworks.*\.exe$": "Navisworks Process",
    r"inventor.*\.exe$": "Inventor Process",
    r"maya.*\.exe$": "Maya Process",
    r"civil3d.*\.exe$": "Civil 3D Process",
    r"grasshopper.*\.exe$": "Grasshopper Process",
    r"twinmotion.*\.exe$": "TwinMotion Process",
    r"v-ray.*\.exe$": "V-Ray Process",
    r"corona.*\.exe$": "Corona Process",
    r"lumion.*\.exe$": "Lumion Process",
    r"dynamo.*\.exe$": "Dynamo Process"
}

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import _Exe_Util
import _GUI_Base_Util

# Set up logging
desktop_path = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop')
log_file = os.path.join(desktop_path, 'logging.txt')

# Ensure the Desktop directory exists
os.makedirs(desktop_path, exist_ok=True)
# Ensure the log file exists
if not os.path.exists(log_file):
    with open(log_file, 'w', encoding='utf-8') as f:
        f.write('')

logging.basicConfig(filename=log_file, level=logging.INFO, format='%(asctime)s - %(message)s')

DEFAULT_SETTINGS = {
    "cpu_threshold": 80,
    "gpu_threshold": 80,
    "disk_threshold": 80,
    "memory_threshold": 75,
    "user_threshold": 5,
    "uptime_threshold": 5*24 * 3600  # 5 days in seconds
}

AVD_MONITOR_SETTING_FILE = "avd_monitor_settings"
SETTINGS = _Exe_Util.get_data(AVD_MONITOR_SETTING_FILE) or DEFAULT_SETTINGS

class UsageMonitor(_GUI_Base_Util.BaseGUI):
    def __init__(self):
        self.app_title = "AVD Resource Monitor"
        self.root = tk.Tk()
        self.root.withdraw()  # Hide the main window

        folder = os.path.dirname(os.path.abspath(__file__))
        self.icon_image_normal_path = os.path.join(folder, "normal_icon.ico")
        self.icon_image_alert_path = os.path.join(folder, "alert_icon.ico")
        self.icon_image_normal = Image.open(self.icon_image_normal_path)
        self.icon_image_alert = Image.open(self.icon_image_alert_path)
        self.root.iconbitmap(self.icon_image_normal_path)  # Set window icon

        self.status_window = None
        self.settings_window = None
        self.pc_name = socket.gethostname()
        self.flashing = False

        self.cpu_usage = 0
        self.gpu_usage = 0
        self.disk_usage = 0
        self.memory_usage = 0
        self.is_recording = False
        self.recording_data = []

        nvmlInit()  # Initialize NVML for GPU monitoring

        self.tray_icon = None
        self.create_tray_icon()

        # Track start time
        self.start_time = time.time()

    def create_tray_icon(self):
        menu = pystray.Menu(
            item("AVD Resource Status", self.show_status),
            item("Settings", self.show_settings),
            pystray.Menu.SEPARATOR,
            item("Exit", self.exit_app)
        )

        self.tray_icon = pystray.Icon("AVD Usage Monitor", self.icon_image_normal, "Usage Monitor", menu)

        def on_clicked(icon, item):
            self.show_status()

        self.tray_icon.menu = menu
        self.tray_icon.icon = self.icon_image_normal
        self.tray_icon.title = "Usage Monitor"
        self.tray_icon.run_detached()

        # Start updating usage in the main thread
        self.root.after(1000, self.update_usage)

    def exit_app(self, icon=None, item=None):
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.quit()
        nvmlShutdown()  # Shutdown NVML

    def get_top_cpu_processes(self):
        """
        Get all processes with significant CPU usage (>0.5%) and all design software processes (even if below threshold).
        Returns a list of process info dicts.
        """
        processes = []
        design_processes = []
        cpu_count = psutil.cpu_count()  # Get number of CPU cores
        
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'username']):
            try:
                pinfo = proc.info
                normalized_cpu = pinfo['cpu_percent'] / cpu_count
                process_name = pinfo['name']
                
                # First try exact match from PROCESS_DESCRIPTIONS
                description = PROCESS_DESCRIPTIONS.get(process_name, None)
                is_design_software = False
                if not description:
                    for pattern, desc in DESIGN_SOFTWARE_PATTERNS.items():
                        if re.match(pattern, process_name, re.IGNORECASE):
                            description = desc
                            is_design_software = True
                            break
                else:
                    is_design_software = any(re.match(pattern, process_name, re.IGNORECASE) 
                                            for pattern in DESIGN_SOFTWARE_PATTERNS)
                if not description:
                    description = "Unknown Process"
                process_info = {
                    'pid': pinfo['pid'],
                    'name': process_name,
                    'description': description,
                    'cpu_percent': round(normalized_cpu, 1),
                    'username': pinfo['username']
                }
                # Record if design software or above threshold
                if is_design_software or normalized_cpu > 0.5:
                    processes.append(process_info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        # Sort by CPU usage descending
        return sorted(processes, key=lambda x: x['cpu_percent'], reverse=True)

    def save_cpu_data(self):
        """Save recorded CPU data to shared dump folder."""
        if not self.recording_data:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"CPU_DATA_{timestamp}.json"
        
        data = {
            'computer_name': self.pc_name,
            'username': os.getlogin(),
            'uptime': self.format_uptime(self.uptime_seconds),
            'recording_start': self.recording_data[0]['timestamp'],
            'recording_end': self.recording_data[-1]['timestamp'],
            'process_data': self.recording_data
        }
        
        dump_path = os.path.join(_Exe_Util.SHARED_DUMP_FOLDER, filename)
        _Exe_Util.set_data(data, dump_path)
        self.recording_data = []

    def update_usage(self):
        self.cpu_usage = psutil.cpu_percent(interval=1)
        self.gpu_usage = self.get_gpu_usage()
        self.disk_usage = self.get_disk_usage()
        self.memory_usage = self.get_memory_usage()
        self.users = psutil.users()
        self.uptime_seconds = time.time() - psutil.boot_time()

        # Handle CPU recording
        if self.cpu_usage > SETTINGS["cpu_threshold"]:
            if not self.is_recording:
                self.is_recording = True
                self.recording_data = []
            
            # Record data every 5 seconds
            if len(self.recording_data) == 0 or (time.time() - self.recording_data[-1]['timestamp']) >= 5:
                self.recording_data.append({
                    'timestamp': time.time(),
                    'cpu_usage': self.cpu_usage,
                    'top_processes': self.get_top_cpu_processes()
                })
        elif self.is_recording:
            self.is_recording = False
            self.save_cpu_data()

        if (self.cpu_usage > SETTINGS["cpu_threshold"] or 
            self.gpu_usage > SETTINGS["gpu_threshold"] or
            self.disk_usage > SETTINGS["disk_threshold"] or
            self.memory_usage["percent"] > SETTINGS["memory_threshold"] or
            len(self.users) > SETTINGS["user_threshold"] or
            self.uptime_seconds > SETTINGS["uptime_threshold"]):
            if not self.flashing:
                self.flashing = True
                self.flash_icon()
        else:
            self.flashing = False
            if self.tray_icon:
                self.tray_icon.icon = self.icon_image_normal

        if self.status_window is not None:
            self.update_status_window()

        # Log status
        status_message = self.get_status_message()
        logging.info(status_message)

        # Check if MAX_LIFE exceeded
        self.check_max_life()

        self.root.after(1000, self.update_usage)

    def get_gpu_usage(self):
        try:
            device_count = nvmlDeviceGetCount()
            if device_count > 0:
                handle = nvmlDeviceGetHandleByIndex(0)  # Assuming monitoring the first GPU
                utilization = nvmlDeviceGetUtilizationRates(handle)
                return utilization.gpu
        except Exception as e:
            logging.error("Failed to get GPU usage: {}".format(e))
        return 0

    def get_disk_usage(self):
        disk_usage = psutil.disk_usage('C:')
        return disk_usage.percent

    def get_memory_usage(self):
        memory_info = psutil.virtual_memory()
        return {"percent": memory_info.percent, "used_gb": memory_info.used / (1024 ** 3)}

    def flash_icon(self):
        if self.flashing:
            current_icon = self.tray_icon.icon
            if current_icon == self.icon_image_normal:
                self.tray_icon.icon = self.icon_image_alert
            else:
                self.tray_icon.icon = self.icon_image_normal
            self.root.after(200, self.flash_icon)  # Change icon every 200ms

    def show_status(self, icon=None, item=None):
        if self.status_window is None:
            self.status_window = tk.Toplevel(self.root)
            self.status_window.title("System Status")
            self.status_window.configure(bg=self.BACKGROUND_COLOR_HEX)
            self.status_window.iconbitmap(self.icon_image_normal_path)

            self.labels = {
                "pc_name": tk.Label(self.status_window, text="", font=("Helvetica", 12), anchor="w", justify="left", bg=self.BACKGROUND_COLOR_HEX, fg='white'),
                "num_users": tk.Label(self.status_window, text="", font=("Helvetica", 12), anchor="w", justify="left", bg=self.BACKGROUND_COLOR_HEX, fg='white'),
                "uptime": tk.Label(self.status_window, text="", font=("Helvetica", 12), anchor="w", justify="left", bg=self.BACKGROUND_COLOR_HEX, fg='white'),
                "cpu_usage": tk.Label(self.status_window, text="", font=("Helvetica", 12), anchor="w", justify="left", bg=self.BACKGROUND_COLOR_HEX, fg='white'),
                "gpu_usage": tk.Label(self.status_window, text="", font=("Helvetica", 12), anchor="w", justify="left", bg=self.BACKGROUND_COLOR_HEX, fg='white'),
                "disk_usage": tk.Label(self.status_window, text="", font=("Helvetica", 12), anchor="w", justify="left", bg=self.BACKGROUND_COLOR_HEX, fg='white'),
                "memory_usage": tk.Label(self.status_window, text="", font=("Helvetica", 12), anchor="w", justify="left", bg=self.BACKGROUND_COLOR_HEX, fg='white')
            }

            for label in self.labels.values():
                label.pack(padx=10, pady=2, fill='both', expand=True)

            self.status_window.protocol("WM_DELETE_WINDOW", self.close_status_window)

            self.update_status_window()

    def update_status_window(self):
        uptime_string = self.format_uptime(self.uptime_seconds)
        memory_usage_info = "{:.1f} GB ({:.2f}%)".format(self.memory_usage["used_gb"], self.memory_usage["percent"])

        self.labels["pc_name"].config(text="PC Name: {}".format(self.pc_name))
        self.labels["num_users"].config(text="Number of Users: {}".format(len(self.users)))
        self.labels["uptime"].config(text="Uptime: {}".format(uptime_string))
        self.labels["cpu_usage"].config(text="Current CPU: {:.2f}%".format(self.cpu_usage))
        self.labels["gpu_usage"].config(text="Current GPU: {:.2f}%".format(self.gpu_usage))
        self.labels["disk_usage"].config(text="C: Drive Usage: {:.2f}%".format(self.disk_usage))
        self.labels["memory_usage"].config(text="Memory Usage: {}".format(memory_usage_info))

        # Check thresholds and set colors independently
        self.set_label_color("cpu_usage", self.cpu_usage > SETTINGS["cpu_threshold"])
        self.set_label_color("gpu_usage", self.gpu_usage > SETTINGS["gpu_threshold"])
        self.set_label_color("disk_usage", self.disk_usage > SETTINGS["disk_threshold"])
        self.set_label_color("memory_usage", self.memory_usage["percent"] > SETTINGS["memory_threshold"])
        self.set_label_color("num_users", len(self.users) > SETTINGS["user_threshold"])
        self.set_label_color("uptime", self.uptime_seconds > SETTINGS["uptime_threshold"])

    def get_status_message(self):
        uptime_string = self.format_uptime(self.uptime_seconds)
        memory_usage_info = "{:.1f} GB ({:.2f}%)".format(self.memory_usage["used_gb"], self.memory_usage["percent"])
        return (
            "PC Name: {}\n"
            "Number of Users: {}\n"
            "Uptime: {}\n"
            "Current CPU: {:.2f}%\n"
            "Current GPU: {:.2f}%\n"
            "C: Drive Usage: {:.2f}%\n"
            "Memory Usage: {}"
        ).format(self.pc_name, len(self.users), uptime_string, self.cpu_usage, self.gpu_usage, self.disk_usage, memory_usage_info)

    def set_label_color(self, label_name, condition):
        if condition:
            self.labels[label_name].config(fg="orange", font=("Helvetica", 12, "bold"))
        else:
            self.labels[label_name].config(fg="white", font=("Helvetica", 12))

    def close_status_window(self):
        self.status_window.destroy()
        self.status_window = None

    def show_settings(self, icon=None, item=None):
        if self.settings_window is None:
            self.settings_window = tk.Toplevel(self.root)
            self.settings_window.title("Settings")
            self.settings_window.iconbitmap(self.icon_image_normal_path)  # Set window icon
            self.settings_window.configure(bg=self.BACKGROUND_COLOR_HEX)

            self.settings_vars = {
                "cpu_threshold": tk.IntVar(value=SETTINGS["cpu_threshold"]),
                "gpu_threshold": tk.IntVar(value=SETTINGS["gpu_threshold"]),
                "disk_threshold": tk.IntVar(value=SETTINGS["disk_threshold"]),
                "memory_threshold": tk.IntVar(value=SETTINGS["memory_threshold"]),
                "user_threshold": tk.IntVar(value=SETTINGS["user_threshold"]),
                "uptime_threshold": tk.IntVar(value=SETTINGS["uptime_threshold"] // 3600)  # Display in hours
            }

            row = 0
            for key, var in self.settings_vars.items():
                label_text = key.replace("_", " ").capitalize()
                if key == "uptime_threshold":
                    label_text += " (hours)"
                if key in ["cpu_threshold", "gpu_threshold", "disk_threshold", "memory_threshold"]:
                    label_text += " (%)"
                if key in ["cpu_threshold", "gpu_threshold"]:
                    label_text = label_text.upper()
                label = tk.Label(self.settings_window, text=label_text, anchor="w", justify="left", bg=self.BACKGROUND_COLOR_HEX, fg='white')
                label.grid(row=row, column=0, padx=10, pady=5, sticky="w")
                entry = tk.Entry(self.settings_window, textvariable=var, bg=self.BACKGROUND_COLOR_HEX, fg='white')
                entry.grid(row=row, column=1, padx=10, pady=5, sticky="w")
                row += 1

            tk.Button(self.settings_window, text="Save", command=self.save_settings, bg=self.BACKGROUND_COLOR_HEX, fg='white').grid(row=row, column=0, columnspan=2, pady=10)
            self.settings_window.protocol("WM_DELETE_WINDOW", self.close_settings_window)

    def save_settings(self):
        new_settings = {key: var.get() for key, var in self.settings_vars.items()}
        new_settings["uptime_threshold"] *= 3600  # Convert back to seconds

        SETTINGS.update(new_settings)
        _Exe_Util.set_data(SETTINGS, AVD_MONITOR_SETTING_FILE)

        logging.info("Settings updated: {}".format(SETTINGS))
        self.close_settings_window()

    def close_settings_window(self):
        self.settings_window.destroy()
        self.settings_window = None

    def format_uptime(self, seconds):
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, seconds = divmod(seconds, 60)
        
        uptime_string = []
        if days > 0:
            uptime_string.append("{} days".format(int(days)))
        if hours > 0 or days > 0:
            uptime_string.append("{} hours".format(int(hours)))
        uptime_string.append("{} minutes".format(int(minutes)))
        uptime_string.append("{} seconds".format(int(seconds)))
        
        return ", ".join(uptime_string)

    def check_max_life(self):
        elapsed_time = time.time() - self.start_time
        if elapsed_time > self.MAX_LIFE:
            logging.info("Maximum life exceeded. Shutting down the application.")
            self.exit_app()

    @_Exe_Util.try_catch_error
    def run(self):
        if self.is_another_app_running():
            self.root.destroy()
            return
        self.root.mainloop()


if __name__ == "__main__":
    app = UsageMonitor()
    app.run()
