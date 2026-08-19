# OK Button Clicker

An automated tool that finds and clicks OK buttons on screen using image recognition.

## Features

- **Image Recognition**: Uses pyautogui to find OK buttons on screen
- **Automated Clicking**: Clicks every 10 seconds for up to 1 hour
- **Simple GUI**: Easy-to-use interface with start/stop controls
- **Real-time Status**: Shows click count and time remaining
- **Safe Operation**: Can be terminated at any time

## How to Use

1. **Prepare the OK Button Image**:
   - Take a screenshot of the OK button you want to click
   - Save it as `ok_button.png` in the `images` folder
   - The image should be clear and distinctive

2. **Run the Application**:
   - Double-click `OKButtonClicker.exe` to start
   - The GUI will show instructions and status

3. **Start Auto-Clicking**:
   - Click "START CLICKING" to begin the automated process
   - The app will search for the OK button every 10 seconds
   - It will automatically stop after 1 hour or when you click "STOP CLICKING"

4. **Monitor Progress**:
   - Watch the status updates in the GUI
   - See how many clicks have been performed
   - Monitor the time remaining

## Technical Details

- **Click Interval**: 10 seconds between attempts
- **Maximum Duration**: 1 hour (3600 seconds)
- **Image Recognition**: Uses OpenCV with confidence threshold of 0.8
- **Threading**: Runs clicking in a separate thread to keep GUI responsive
- **Error Handling**: Comprehensive logging and error recovery

## File Structure

```
OKButtonClicker/
├── OKButtonClicker.py          # Main application
├── images/
│   ├── icon.ico               # Application icon
│   └── ok_button.png          # Your OK button image (add this)
└── README.md                  # This file
```

## Requirements

- Windows 10/11
- Python 3.x (for development)
- pyautogui, pygame, opencv-python (included in exe)

## Building the Executable

The application is configured to be built using PyInstaller with the configuration file `OKButtonClicker.sexyDuck`.

## Troubleshooting

- **Button not found**: Make sure the OK button image is clear and matches exactly
- **False clicks**: Adjust the confidence threshold in the code if needed
- **Performance issues**: The app uses minimal resources and runs in background

## Safety Notes

- The application will only click when the OK button is found
- It automatically stops after 1 hour to prevent indefinite running
- You can stop it at any time using the GUI
- Always test with a safe application first
