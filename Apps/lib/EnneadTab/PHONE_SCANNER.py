# -*- coding: utf-8 -*-
"""PHONE_SCANNER.py - Wireless mobile camera to Rhino & CAD staging bridge.

Supports both IronPython 2.7 (inside Rhino 7/8 and Revit) and Python 3.x.
Communicates with the EnneadTab Phone Scanner web service at
https://enneadtab.com/phone-scanner via ephemeral session rooms.
"""

import os
import sys
import json
import base64
import random
import time

from EnneadTab import ENVIRONMENT
from EnneadTab import FOLDER
from EnneadTab import ERROR_HANDLE
from EnneadTab import WEB_GUARD

# Web client runtime selection
_USE_DOTNET = False
try:
    from System.Net import WebRequest, WebException, ServicePointManager, SecurityProtocolType # pyright: ignore
    from System.IO import StreamReader # pyright: ignore
    from System.Text import Encoding # pyright: ignore
    _USE_DOTNET = True
except ImportError:
    pass

if not _USE_DOTNET:
    try:
        from urllib.request import urlopen, Request # pyright: ignore
        from urllib.error import HTTPError # pyright: ignore
    except ImportError:
        from urllib2 import urlopen, Request, HTTPError # pyright: ignore


PHONE_SCANNER_BASE_URL = "https://enneadtab.com/phone-scanner"
STAGING_FOLDER_NAME = "PhoneScanner_Staging"


def generate_room_id():
    """Generate a clean ephemeral session room ID prefixed with rhino-."""
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    random_token = "".join(random.choice(chars) for _ in range(6))
    return "rhino-{}".format(random_token)


def get_portal_url(room_id):
    """Return the web portal pairing URL."""
    return "{0}?room={1}".format(PHONE_SCANNER_BASE_URL, room_id)


def get_staging_dir():
    """Ensure and return the local staging dump directory for scanned images."""
    folder = FOLDER.get_local_dump_folder_folder(STAGING_FOLDER_NAME)
    if not os.path.exists(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return folder


def poll_room_photos(room_id, since=0, timeout_ms=8000):
    """Poll photos uploaded to the ephemeral room since a timestamp.

    Args:
        room_id (str): Ephemeral room ID.
        since (int): Millisecond Unix timestamp threshold.
        timeout_ms (int): Request timeout in milliseconds.

    Returns:
        list of dict: List of photo objects: [{'id': str, 'dataUrl': str, 'mimeType': str, 'timestamp': int}]
    """
    url = "{0}/api/room/{1}/poll?since={2}".format(PHONE_SCANNER_BASE_URL, room_id, since)
    
    if _USE_DOTNET:
        try:
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
            request = WebRequest.Create(url)
            request.Method = "GET"
            WEB_GUARD.harden_dotnet_request(request)
            request.Timeout = timeout_ms
            response = request.GetResponse()
            try:
                reader = StreamReader(response.GetResponseStream(), Encoding.UTF8)
                try:
                    text = reader.ReadToEnd()
                finally:
                    reader.Close()
                data = json.loads(text)
                return data.get("photos", [])
            finally:
                response.Close()
        except Exception:
            return []
    else:
        try:
            req = Request(url)
            opener = WEB_GUARD.no_redirect_opener()
            if opener is not None:
                resp = opener.open(req, timeout=timeout_ms // 1000)
            else:
                resp = urlopen(req, timeout=timeout_ms // 1000)
            try:
                text = resp.read()
                if isinstance(text, bytes):
                    text = text.decode("utf-8")
                data = json.loads(text)
                return data.get("photos", [])
            finally:
                resp.close()
        except Exception:
            return []


def save_b64_image_to_temp(data_url, photo_id=None):
    """Save a Base64 data URL string to a temporary local image file.

    Args:
        data_url (str): Data URL (e.g. 'data:image/jpeg;base64,...').
        photo_id (str, optional): Identifier for the photo.

    Returns:
        str: Absolute path to the saved local image file, or None on failure.
    """
    if not data_url or not isinstance(data_url, (str, unicode) if sys.version_info[0] == 2 else str):
        return None

    try:
        if "," in data_url:
            header, b64_str = data_url.split(",", 1)
        else:
            header, b64_str = "", data_url

        ext = ".jpg"
        if "png" in header.lower():
            ext = ".png"
        elif "webp" in header.lower():
            ext = ".webp"

        clean_id = (photo_id or "scan_{}".format(int(time.time() * 1000))).replace(":", "_").replace("/", "_")
        filename = "{0}{1}".format(clean_id, ext)
        dest_path = os.path.join(get_staging_dir(), filename)

        raw_bytes = base64.b64decode(b64_str)
        with open(dest_path, "wb") as f:
            f.write(raw_bytes)

        return dest_path
    except Exception as e:
        ERROR_HANDLE.print_note("Failed to save scanned image: {}".format(e))
        return None


def get_image_pixel_size(file_path):
    """Return (width, height) pixel dimensions of an image file."""
    if not os.path.exists(file_path):
        return (100.0, 100.0)

    try:
        import clr
        clr.AddReference("System.Drawing")
        import System.Drawing as SD
        with_lock = SD.Image.FromFile(file_path)
        try:
            return (float(with_lock.Width), float(with_lock.Height))
        finally:
            with_lock.Dispose()
    except Exception:
        pass

    try:
        from PIL import Image
        with Image.open(file_path) as img:
            return (float(img.width), float(img.height))
    except Exception:
        pass

    return (100.0, 100.0)


def insert_picture_frame(image_path, plane=None, width=None, height=None, prompt_point=True):
    """Insert the given image as a PictureFrame into the active Rhino document.

    Args:
        image_path (str): Full path to image on disk.
        plane (Rhino.Geometry.Plane, optional): Target plane (default: WorldXY).
        width (float, optional): Model width of picture frame.
        height (float, optional): Model height of picture frame.
        prompt_point (bool): If True and plane is None, asks user to click insertion point.

    Returns:
        System.Guid or None: Added Rhino object Guid.
    """
    if not os.path.exists(image_path):
        ERROR_HANDLE.print_note("Cannot insert picture frame: file not found at {}".format(image_path))
        return None

    try:
        import Rhino
        import scriptcontext as sc
    except ImportError:
        ERROR_HANDLE.print_note("Rhino is not available in the current environment.")
        return None

    px_w, px_h = get_image_pixel_size(image_path)
    aspect = (px_h / px_w) if px_w > 0 else 1.0

    if width is None and height is None:
        unit_scale = 50.0
        width = unit_scale
        height = unit_scale * aspect
    elif width is not None and height is None:
        height = width * aspect
    elif height is not None and width is None:
        width = height / aspect

    if plane is None:
        plane = Rhino.Geometry.Plane.WorldXY
        if prompt_point:
            gp = Rhino.Input.Custom.GetPoint()
            gp.SetCommandPrompt("Select insertion point for Scanned PictureFrame")
            get_res = gp.Get()
            if get_res == Rhino.Input.GetResult.Point:
                target_pt = gp.Point()
                view = sc.doc.Views.ActiveView
                if view:
                    cplane = view.ActiveViewport.ConstructionPlane()
                    plane = Rhino.Geometry.Plane(target_pt, cplane.XAxis, cplane.YAxis)
                else:
                    plane.Origin = target_pt
            else:
                return None

    try:
        obj_id = sc.doc.Objects.AddPictureFrame(
            plane,
            image_path,
            False,
            width,
            height,
            False,
            False
        )
    except Exception:
        try:
            obj_id = sc.doc.Objects.AddPictureFrame(plane, image_path, False, width, height, False, False)
        except Exception:
            obj_id = sc.doc.Objects.AddPictureFrame(plane, image_path, width, height, False, False, False, False)

    if obj_id:
        sc.doc.Views.Redraw()
        return obj_id
    return None


def copy_image_to_clipboard(image_path):
    """Copy image to Windows clipboard for immediate pasting."""
    from EnneadTab import IMAGE
    return IMAGE.copy_image_to_clipboard(image_path)


def purge_staging_folder():
    """Clean up old temporary scanned images in the dump folder."""
    staging_dir = get_staging_dir()
    if not os.path.exists(staging_dir):
        return
    now = time.time()
    for fname in os.listdir(staging_dir):
        fpath = os.path.join(staging_dir, fname)
        try:
            if os.path.isfile(fpath) and (now - os.path.getmtime(fpath)) > 7200:
                os.remove(fpath)
        except Exception:
            pass
