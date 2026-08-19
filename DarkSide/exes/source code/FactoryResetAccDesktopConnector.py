import sys
import os
import subprocess
import PyQt5.sip  # Add this import
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTextEdit, 
                            QPushButton, QVBoxLayout, QWidget, QMessageBox)
from PyQt5.QtCore import Qt
import time

note = r"""
# Factory Reset Instructions for ACC Desktop Connector

⚠️ **WARNING**: This process will delete all local changes that have not been uploaded to the server. Make sure to save out any important work in a local location before proceeding. Later you can move them back to ACC desktop connector to retry upload.

## Steps to Reset

1. **Shutdown ACC Desktop Connector**
   - Close the application completely

2. **Clean Up User Folders** 
   Delete the following folders:
   - Main DC folder: `C:\Users\[UserName]\DC`
   - Local data: `C:\Users\[UserName]\AppData\Local\Autodesk\Desktop Connector\Data`
   - Session data: `C:\Users\[UserName]\AppData\Local\Autodesk\DesktopConnector.Applicat_Url_[LongRandomString]`

3. **Run Cleanup Utility**
   - Execute `ShellCleanup.exe` located at:
   - `C:\Program Files\Autodesk\Desktop Connector\ShellCleanup.exe`
   - This will remove the Autodesk Blue Icon from File Explorer

4. **Restart Application**
   - Launch ACC Desktop Connector again
"""

class ResetGui(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🔄 EnneadTab Factory Reset Assistant (The 'Oops' Fixer)")
        self.setGeometry(100, 100, 800, 600)
        
        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Instructions display
        self.text_display = QTextEdit()
        self.text_display.setMarkdown(note)
        self.text_display.setReadOnly(True)
        layout.addWidget(self.text_display)
        
        # Buttons with EnneadTab-themed funny labels
        self.manual_btn = QPushButton("I'm an Pro, I'll Do It Myself! 💪")
        self.auto_btn = QPushButton("Help Me EnneadTab, You're My Only Hope! 🙈")
        
        layout.addWidget(self.manual_btn)
        layout.addWidget(self.auto_btn)
        
        # Connect buttons
        self.manual_btn.clicked.connect(self.manual_choice)
        self.auto_btn.clicked.connect(self.auto_reset)
        
    def manual_choice(self):
        QMessageBox.information(self, "Good Luck!", 
            "May the EnneadTab force be with you! Follow the instructions above carefully! 🚀")
        self.close()
        
    def auto_reset(self):
        try:

            
            # Ask user to confirm if Desktop Connector is closed
            message_box = QMessageBox(self)
            message_box.setWindowTitle("Confirm Closure")
            message_box.setText(
                "Please confirm that the Desktop Connector is closed before continuing.\n\n" +
                "Have you closed it?\n\n"
            )
            yes_button = message_box.addButton("Yes, continue", QMessageBox.YesRole)
            no_button = message_box.addButton("No, cancel", QMessageBox.NoRole)
            message_box.exec_()
            
            if message_box.clickedButton() == no_button:
                QMessageBox.information(self, "Process Aborted", 
                    "Please close the Desktop Connector and try again.")
                return
   
                
            # If we get here, Desktop Connector is not running, proceed with reset...
            
            # Delete folders
            username = os.getenv('USERNAME')
            folders_to_delete = [
                f"C:\\Users\\{username}\\DC",
                f"C:\\Users\\{username}\\AppData\\Local\\Autodesk\\Desktop Connector\\Data"
            ]
            
            # Find and delete session folder
            app_data = f"C:\\Users\\{username}\\AppData\\Local\\Autodesk"
            for folder in os.listdir(app_data):
                if folder.startswith("DesktopConnector.Applicat_Url_"):
                    folders_to_delete.append(os.path.join(app_data, folder))
            
            for folder in folders_to_delete:
                if os.path.exists(folder):
                    os.system(f'rd /s /q "{folder}"')
            
            # Run cleanup utility
            cleanup_path = "C:\\Program Files\\Autodesk\\Desktop Connector\\ShellCleanup.exe"
            if os.path.exists(cleanup_path):
                subprocess.run([cleanup_path])
            
            # Restart Desktop Connector
            dc_path = "C:\\Program Files\\Autodesk\\Desktop Connector\\DesktopConnector.Applications.Tray.exe"
            if os.path.exists(dc_path):
                subprocess.Popen([dc_path])
                
            QMessageBox.information(self, "Success!", 
                "All done! Your Desktop Connector has been reset and restarted! 🎉\n\n" +
                "Another happy landing, courtesy of EnneadTab! 😉\n\n" +
                "If anything goes wrong, remember: it's not a bug, it's a feature! 🦾")
            
        except Exception as e:
            QMessageBox.warning(self, "Oops!", 
                f"Something went wrong! Even EnneadTab has bad days! 😅\n\n" +
                "Try asking Sen Zhang for help, he probably broke something again! 😜\n\n" +
                f"Error: {str(e)}")
            print(f"Error: {str(e)}")
        
        self.close()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ResetGui()
    window.show()
    sys.exit(app.exec_())

