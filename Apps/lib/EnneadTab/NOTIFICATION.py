#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
EnneadTab Notification System

A sophisticated notification system providing customizable user alerts through
various channels including popups, sounds, and animated notifications. This module
offers both standard message notifications and fun, interactive notifications like
the signature duck popup.

Key Features:
    - Customizable popup notifications with animations
    - Fun, interactive duck notifications with sound effects
    - User preference management for notification styles
    - Rich text formatting with custom fonts
    - Animation timing control
    - Position and size customization
    - Background and font color customization

Note:
    All notifications respect user preferences and can be disabled through
    configuration settings.
"""
# 2026-08-21: signing-pipeline trigger touch (see senzhang-todo #4600) -- no behavior change.
# 2026-08-21: publish trigger touch after the EA_Dist clone repair (senzhang-todo #4456, #4634)
# -- no behavior change. Confirms production publish is green again end-to-end.
# 2026-08-21: publish trigger touch to ship PR #192 (the fleet went stale when run
# 32511676656 refused with no output) and to exercise the guard-output capture from
# PR #195 -- no behavior change. See senzhang-todo #4661.

import os
import random
import time

import SOUND
import DATA_FILE
import EXE
import IMAGE
import CONFIG
import FOLDER

# Persistent NotificationHost inbox (unique files; host drains them).
_MESSENGER_INBOX = "messenger_inbox"
_NOTIF_PREFIX = "notif_"
_MUTE_UNTIL_FILE = "notification_host_mute_until.txt"


def is_hate_messenger():
    """Check if standard notifications are disabled.
    
    Retrieves user preference for minimal popup notifications from configuration.

    Returns:
        bool: True if user has opted for minimal notifications
    """
    return  CONFIG.get_setting("radio_bt_popup_minimal", False)


def is_temporarily_muted():
    """True if user muted toasts for 1 hour from a toast mute icon."""
    path = FOLDER.get_local_dump_folder_file(_MUTE_UNTIL_FILE)
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r") as f:
            raw = f.read().strip()
        until = float(raw)
        if until > time.time():
            return True
        try:
            os.remove(path)
        except Exception:
            pass
        return False
    except Exception:
        return False

def is_hate_duck_pop():
    """Check if duck notifications are disabled.
    
    Retrieves user preference for duck popup notifications from configuration.

    Returns:
        bool: True if duck notifications are disabled
    """
    return not CONFIG.get_setting("toggle_bt_is_duck_allowed", False)

FUNFONTS = [
    "Berlin Sans FB",
    "Ravie",
    "Small Fonts",
    "Snap ITC",
    "Viner Hand ITC",
    "BankGothic Lt BT",
    "Bauhaus 93",
    "Bradley Hand ITC",
    "Broadway",
    "Chiller",
    "CityBlueprint",
    "Comic Sans MS",
    "CountryBlueprint"
    ]

def get_random_font():
    """Select a random decorative font.
    
    Chooses from a curated list of fun, decorative fonts suitable for
    notifications.

    Returns:
        str: Name of randomly selected font
    """
    return random.choice(FUNFONTS)


def _ensure_inbox_dir():
    inbox_dir = FOLDER.get_local_dump_folder_folder(_MESSENGER_INBOX)
    if not os.path.exists(inbox_dir):
        try:
            os.makedirs(inbox_dir)
        except Exception:
            pass
    return inbox_dir


def _write_inbox_item(data):
    """Atomically write one unique notification JSON into the host inbox.

    Always enqueues even if the host is down. Returns True on write success.
    """
    _ensure_inbox_dir()
    name = "{}{}_{}".format(
        _NOTIF_PREFIX,
        int(time.time() * 1000),
        random.randint(1000, 9999),
    )
    rel = os.path.join(_MESSENGER_INBOX, name)
    try:
        DATA_FILE.set_data(data, rel)
        path = FOLDER.get_local_dump_folder_file(rel)
        return os.path.exists(path)
    except Exception as e:
        print("Failed to write notification inbox item: {}".format(e))
        return False

def messenger(main_text,
             title=None,
             width=None,
             height=None,
             image=None,
             audio=None,
             animation_in_duration=None,
             animation_stay_duration=None,
             animation_fade_duration=None,
             x_offset=None,
             background_color=None,
             font_size=None,
             font_color=None,
             font_family=None,
             level=None,
             actions=None,
             youtube=None,
             sticky=False):
    """Display a customizable popup notification via NotificationHost.

    Writes a unique inbox JSON then wakes the persistent host if needed.

    Args:
        main_text (str): Message to display (supports line breaks)
        title (str, optional): Bold header line shown above main_text
        width (int, optional): Legacy size hint (ignored by host layout)
        height (int, optional): Legacy size hint (ignored by host layout)
        image (str, optional): Path to png/jpg/jpeg/gif/bmp/webp shown
            full-bleed at the top of the card (edge-to-edge, height follows
            aspect ratio). A YouTube watch/share URL here is also accepted
            (thumbnail + Open).
        audio (str, optional): Path or EnneadTab audio name (.wav) played as cue
        animation_in_duration: Legacy timing (optional)
        animation_stay_duration: Stay duration - seconds if < 100, else ms.
            Ignored when sticky=True.
        animation_fade_duration: Legacy timing (optional)
        x_offset (int, optional): Legacy offset (optional)
        background_color (str, optional): Legacy color (optional)
        font_size (int, optional): Text size in points
        font_color (str, optional): Legacy text color (optional)
        font_family (str, optional): Font name
        level (str, optional): info | success | warning | error
        actions (list, optional): Up to 2 action dicts with keys
            id, label, type (dismiss|open_path|open_url|copy), payload,
            tooltip (str, optional - explicit hover text for the action
            button; when omitted the host derives a short default from
            type, e.g. "Open {filename}" for open_path, "Open link" for
            open_url, "Copy to clipboard" for copy, "Dismiss this
            notification" for dismiss)
        youtube (str, optional): YouTube URL or 11-char video id. Host fetches
            a thumbnail into the toast and adds an Open action (no iframe).
        sticky (bool, optional): When True, the card never auto-dismisses on
            a timer - it stays until the user closes it, clicks mute, or
            clicks an action button. The action bar (if any) renders visible
            immediately instead of hover-gated. Use for CTA notifications
            that need an explicit response. Still non-blocking: this
            function returns immediately either way.

    Note:
        If notifications are disabled via user preferences, this function
        returns without action.
    """

    if is_hate_messenger():
        return

    if is_temporarily_muted():
        return
    
    if not isinstance(main_text, str):
        main_text = str(main_text)

    data = {}
    data["main_text"] = main_text
    if title:
        data["title"] = title
    if sticky:
        data["sticky"] = True
    if animation_in_duration is not None:
        data["animation_in_duration"] = animation_in_duration
    if animation_stay_duration is not None:
        data["animation_stay_duration"] = animation_stay_duration
    if animation_fade_duration is not None:
        data["animation_fade_duration"] = animation_fade_duration
    if width is not None:
        data["width"] = width
    if height is not None:
        data["height"] = height 
    if image is not None:
        data["image"] = image
    if youtube is not None:
        data["youtube"] = youtube
    if audio is not None:
        resolved = SOUND.get_audio_path_by_name(audio)
        if resolved:
            data["audio"] = resolved
        elif os.path.isfile(str(audio)):
            data["audio"] = str(audio)
    if x_offset is not None:
        data["x_offset"] = x_offset
    if font_color:
        data["font_color"] = font_color
    if font_family:
        data["font_family"] = font_family
    if font_size:
        data["font_size"] = font_size
    if background_color:
        data["background_color"] = background_color
    if level:
        data["level"] = level
    if actions:
        data["actions"] = actions

    wrote = _write_inbox_item(data)
    if not wrote:
        print("Failed to enqueue notification to NotificationHost inbox. Message: {}".format(main_text))
        return

    EXE.ensure_notification_host()


def duck_pop(main_text=None):
    """Display an animated duck notification with sound.
    
    Creates a fun, interactive notification featuring an animated duck
    with sound effects. Falls back to standard notification if duck
    notifications are disabled.

    Args:
        main_text (str, optional): Message to display. Defaults to "Quack!"

    Note:
        - Uses randomly selected duck images and sounds
        - Includes explosion animation effect
        - Falls back to messenger() if duck notifications are disabled
    """
    if is_hate_duck_pop():
   
        messenger(main_text)
        return
    
    if not main_text:
        main_text = "Quack!"

    data = {}
    data["main_text"] = main_text

    # when the ranking is ready, can progress to make better ranked duck
    data["duck_image"] = IMAGE.get_one_image_path_by_prefix("duck_pop")
    data["explosion_gif"] = IMAGE.get_image_path_by_name("duck_explosion.gif")
    data["audio"] = SOUND.get_one_audio_path_by_prefix("duck")
    DATA_FILE.set_data(data, "DUCK_POP") 

    EXE.try_open_app("DuckPop")
  

def unit_test():
    """Run comprehensive tests of notification system.
    
    Tests both standard and duck notifications with default settings.
    """
    duck_pop("Hello, Ennead!")
    messenger("Hello Ennead!", level="info")
    messenger(
        "Unit test with actions",
        level="success",
        actions=[
            {"id": "copy", "label": "Copy", "type": "copy", "payload": "Hello Ennead!"},
        ],
    )

def window_msg(title, message, image=None, duration=10):
    """Display a Windows 10 style toast notification in the corner.
    
    Creates a non-blocking toast notification that appears in the corner
    of the screen similar to native Windows 10 notifications.
    
    Args:
        title (str): Title text displayed at top of notification
        message (str): Main message text (supports line breaks)
        image (str, optional): Path to image or predefined type:
            None = Information icon
            "info" = Information icon
            "warning" = Warning icon
            "error" = Error icon
            Any other string = Custom icon path
        duration (int, optional): How long toast notifications stay visible (seconds)
    
    Note:
        Designed for compatibility with both IronPython and CPython environments.
        Uses Windows 10 toast notification APIs for a modern user experience.
        See: https://learn.microsoft.com/en-us/windows/apps/design/shell/tiles-and-notifications/toast-notifications-overview
    """
    print("Showing notification: {} - {}".format(title, message))
    
    # Use toast notification style (Windows 10 corner popup)
    try:
        # Try Windows 10 toast notifications via win10toast
        try:
            # For CPython with win10toast package
            from win10toast import ToastNotifier
            
            toaster = ToastNotifier()
            toaster.show_toast(
                title,
                message,
                icon_path=image if image and image not in ["info", "warning", "error"] else None,
                duration=duration,
                threaded=True  # Non-blocking
            )
            print("Notification sent via win10toast")
            return
        except ImportError:
            print("win10toast not available, trying next method")
            pass
        
        # Try Windows Forms notification (IronPython or alternative approach)
        try:
            import clr
            clr.AddReference("System.Windows.Forms")
            from System.Windows.Forms import NotifyIcon, ToolTipIcon, Form, Application
            from System.Drawing import Icon, SystemIcons
            
            form = Form()
            form.ShowInTaskbar = False
            
            notify_icon = NotifyIcon()
            notify_icon.Visible = True
            notify_icon.Text = title  # Tooltip text
            
            # Set appropriate icon
            if image == "error":
                notify_icon.Icon = SystemIcons.Error
            elif image == "warning":
                notify_icon.Icon = SystemIcons.Warning
            elif image == "info" or image is None:
                notify_icon.Icon = SystemIcons.Information
            else:
                # Try to load custom icon if path provided
                try:
                    notify_icon.Icon = Icon(image)
                except Exception:
                    notify_icon.Icon = SystemIcons.Information
            
            # Show balloon tip (toast notification)
            notify_icon.BalloonTipTitle = title
            notify_icon.BalloonTipText = message
            # Use longer duration for visibility
            notify_icon.ShowBalloonTip(duration * 1000)  # Convert to milliseconds
            print("Notification sent via Windows Forms")
            
            # Keep application running to show notification
            import threading
            def cleanup():
                import time
                time.sleep(duration)
                notify_icon.Visible = False
                notify_icon.Dispose()
                
            threading.Thread(target=cleanup).start()
            return
        except Exception as e:
            print("Windows Forms notification failed:", str(e))
            pass
            
        # If all else fails, use ctypes for basic Windows notification
        try:
            import ctypes
            from ctypes import wintypes
            import time
            
            # Load shell32.dll
            shell32 = ctypes.WinDLL('shell32.dll')
            user32 = ctypes.WinDLL('user32.dll')
            
            # Find an existing window or create a dummy one
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                hwnd = user32.GetDesktopWindow()
            
            # Define notification flag constants
            NIF_INFO = 0x00000010
            NIF_ICON = 0x00000002
            NIF_TIP = 0x00000004
            NIF_MESSAGE = 0x00000001
            NIIF_INFO = 0x00000001
            NIIF_WARNING = 0x00000002
            NIIF_ERROR = 0x00000003
            NIM_ADD = 0x00000000
            NIM_MODIFY = 0x00000001
            NIM_DELETE = 0x00000002
            
            # Determine icon type
            icon_flag = NIIF_INFO
            if image == "warning":
                icon_flag = NIIF_WARNING
            elif image == "error":
                icon_flag = NIIF_ERROR
            
            # Create notification data structure
            class NOTIFYICONDATA(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("hWnd", wintypes.HWND),
                    ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT),
                    ("uCallbackMessage", wintypes.UINT),
                    ("hIcon", wintypes.HANDLE),
                    ("szTip", ctypes.c_char * 128),
                    ("dwState", wintypes.DWORD),
                    ("dwStateMask", wintypes.DWORD),
                    ("szInfo", ctypes.c_char * 256),
                    ("uVersion", wintypes.UINT),
                    ("szInfoTitle", ctypes.c_char * 64),
                    ("dwInfoFlags", wintypes.DWORD),
                ]
            
            # Initialize notification data
            nid = NOTIFYICONDATA()
            nid.cbSize = ctypes.sizeof(nid)
            nid.hWnd = hwnd
            nid.uID = 0
            nid.uFlags = NIF_INFO | NIF_TIP | NIF_ICON
            nid.dwInfoFlags = icon_flag
            nid.szInfo = message.encode('utf-8')
            nid.szInfoTitle = title.encode('utf-8')
            nid.szTip = (title + ": " + message[:60]).encode('utf-8')
            
            # Show notification
            try:
                # Add notification icon first
                shell32.Shell_NotifyIconA(NIM_ADD, ctypes.byref(nid))
                print("Notification sent via ctypes")
                
                # Keep it visible for the specified duration
                time.sleep(duration)
                
                # Remove notification icon
                shell32.Shell_NotifyIconA(NIM_DELETE, ctypes.byref(nid))
            except Exception as e:
                print("Error showing notification:", str(e))
            
            return
        except Exception as e:
            print("Ctypes notification failed:", str(e))
            pass
            
    except Exception as e:
        # Fall back to console output if all toast methods fail
        print("Toast notification: {} - {}".format(title, message))
        print("(Note: Windows toast notification failed, displaying text instead)")
        print("Error: {}".format(str(e)))
        if image:
            print("Icon type: {}".format(image))

def test_window_msg():
    """Run tests of Windows 10 style toast notifications.
    
    Tests different notification styles with various icons and durations.
    """
    print("Testing toast notifications...")
    
    # Test standard notifications
    window_msg("Information", "This is an information message")
    window_msg("Warning", "This is a warning message", "warning")
    window_msg("Error", "This is an error message", "error")
    
    # Test with different durations
    window_msg("Quick Notification", "This notification disappears quickly", None, 3)
    window_msg("Long Notification", "This notification stays longer", None, 7)
    
    print("Toast notification tests complete!")

if __name__ == "__main__":
    duck_pop("Hello, Ennead!")
    # Test random font messenger
    font = get_random_font()
    messenger("Hello world with bigger text\nUsing [{}]".format(font), font_size=30, font_family=font)
    for font_name    in FUNFONTS:
        messenger("rapid fire test:"+font_name, font_family=font_name)
        # import time 
        # time.sleep(0.2)
    