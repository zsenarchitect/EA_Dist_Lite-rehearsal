#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Open EnneadTab-ARVR: Mobile Camera AR Overlay for 3D Models.

Beam an already-exported 3D model onto your smartphone camera in augmented reality:
- Auto-detect a staged .glb matching the active 3D view, or browse to pick an
  existing .glb / .gltf / .usdz you exported some other way
- Staged safely in local temporary dump directory
- Upload directly into cloud room session
- Scan QR code to launch mobile camera AR overlay with 1:1 scale
- Zero app installs needed on phone or headset

Note: this tool does not export the Revit 3D view itself (Revit has no native
glTF/GLB exporter). Export your model to .glb/.gltf/.usdz first, then use this
tool to stage & beam it.

Opens https://enneadtab.com/arvr
"""
__title__ = "AR/VR\nOverlay"

import os
import webbrowser

import clr # pyright: ignore
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")

import Microsoft.Win32 # pyright: ignore
from System import Uri, UriKind # pyright: ignore
from System.Windows import Visibility # pyright: ignore
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption # pyright: ignore
from pyrevit.forms import WPFWindow # pyright: ignore

import proDUCKtion # pyright: ignore 
proDUCKtion.validify()

from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION, FOLDER, ARVR
from EnneadTab.REVIT import REVIT_APPLICATION
from Autodesk.Revit import DB # pyright: ignore 

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()


class ARVROverlayWindow(WPFWindow):
    """Arcade-styled WPF Dialog for Revit ARVR export, staging, and web pairing."""

    def __init__(self, doc):
        xaml_path = os.path.join(os.path.dirname(__file__), "ARVR_Overlay_Form.xaml")
        WPFWindow.__init__(self, xaml_path)
        self.doc = doc

        # Generate default room code
        self.default_room_id = ARVR.generate_room_id()
        self.room_textbox.Text = self.default_room_id

        # Update active view info
        active_view = doc.ActiveView if doc else None
        if active_view and active_view.ViewType == DB.ViewType.ThreeD:
            self.status_text.Text = ">> Active View: [{}] - browse exported .glb/.gltf/.usdz to beam".format(active_view.Name)
        else:
            self.status_text.Text = ">> Switch to a 3D view or browse a local .glb/.gltf file"

    def get_room_id(self):
        txt = self.room_textbox.Text.strip()
        if not txt:
            txt = self.default_room_id
        return txt.upper()

    def _load_qr_image(self, image_control, file_path):
        if not file_path or not os.path.exists(file_path):
            return
        try:
            bmp = BitmapImage()
            bmp.BeginInit()
            bmp.CacheOption = BitmapCacheOption.OnLoad
            bmp.UriSource = Uri(file_path, UriKind.Absolute)
            bmp.EndInit()
            image_control.Source = bmp
        except Exception:
            pass

    def on_copy_mobile_clicked(self, sender, e):
        txt = self.mobile_link_textbox.Text
        if txt:
            try:
                from System.Windows import Clipboard # pyright: ignore
                Clipboard.SetText(txt)
                self.btn_copy_mobile.Content = "COPIED!"
                NOTIFICATION.messenger("Mobile AR Link copied to clipboard:\n{}".format(txt))
            except Exception:
                pass

    def on_copy_room_clicked(self, sender, e):
        txt = self.room_link_textbox.Text
        if txt:
            try:
                from System.Windows import Clipboard # pyright: ignore
                Clipboard.SetText(txt)
                self.btn_copy_room.Content = "COPIED!"
                NOTIFICATION.messenger("Desktop Room Hub Link copied to clipboard:\n{}".format(txt))
            except Exception:
                pass

    def _handle_upload_result(self, ok, room_id, url, err):
        if not ok:
            self.status_text.Text = ">> Upload failed: {}".format(err or "unknown error")
            return

        self.status_text.Text = ">> Beamed to Room {} - scan the BIG QR on your phone".format(room_id)
        
        mobile_url = ARVR.get_mobile_viewer_url(room_id)
        self.mobile_link_textbox.Text = mobile_url
        self.room_link_textbox.Text = url

        large_qr, small_qr = ARVR.download_qr_code_pair(room_id, url)
        if large_qr:
            self._load_qr_image(self.qr_mobile_image, large_qr)
        if small_qr:
            self._load_qr_image(self.qr_room_image, small_qr)

        self.share_link_card.Visibility = Visibility.Visible

    def on_export_view_clicked(self, sender, e):
        active_view = self.doc.ActiveView if self.doc else None
        if not active_view or active_view.ViewType != DB.ViewType.ThreeD:
            NOTIFICATION.messenger("Please open or activate a 3D view in Revit first, or browse an existing .glb file.")
            return

        staging_dir = ARVR.get_staging_directory()
        view_name = "".join(c for c in active_view.Name if c.isalnum() or c in (' ', '_', '-')).strip()
        if not view_name:
            view_name = "Revit_3D_View"
        out_base = os.path.join(staging_dir, view_name)

        # Check if already exported in staging
        out_glb = out_base + ".glb"
        if os.path.exists(out_glb) and os.path.getsize(out_glb) > 0:
            room_id = self.get_room_id()
            ok, r, u, err = ARVR.stage_and_upload(out_glb, room_id=room_id, auto_open_browser=False)
            self._handle_upload_result(ok, r, u, err)
            return

        # Guide user to pick / confirm exported glb
        NOTIFICATION.messenger(
            "Ready to stage & beam [{}]!\nPlease select the exported 3D model (.glb / .gltf / .usdz)...".format(active_view.Name))
        self.on_browse_model_clicked(sender, e)

    def on_browse_model_clicked(self, sender, e):
        dlg = Microsoft.Win32.OpenFileDialog()
        dlg.Title = "Select 3D Model to Stage & Beam into Mobile AR"
        dlg.Filter = "3D Models (*.glb;*.gltf;*.usdz)|*.glb;*.gltf;*.usdz|All Files (*.*)|*.*"
        if dlg.ShowDialog():
            filepath = dlg.FileName
            if filepath and os.path.exists(filepath):
                room_id = self.get_room_id()
                ok, r, u, err = ARVR.stage_and_upload(filepath, room_id=room_id, auto_open_browser=False)
                self._handle_upload_result(ok, r, u, err)

    def on_open_web_clicked(self, sender, e):
        room_id = self.get_room_id()
        ARVR.open_web_hub(room_id)
        self.Close()

    def on_close_clicked(self, sender, e):
        self.Close()


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main(doc):
    win = ARVROverlayWindow(doc)
    win.ShowDialog()


################## main code below #####################
if __name__ == "__main__":
    main(DOC)
