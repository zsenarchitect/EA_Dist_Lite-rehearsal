# -*- coding: utf-8 -*-
__title__ = "PhoneScanner"
__doc__ = """Connect your phone camera to Rhino for instant photo & sketch scanning.

Features:
- Open pairing portal with QR code & PIN
- Real-time staging dock in Rhino for incoming photos
- One-click PictureFrame insertion into active Rhino document
- One-click copy image to system clipboard
- Batch insert multiple scans
- Automatic cleanup of ephemeral images
"""

import os
import sys
import webbrowser
import time

try:
    import Rhino # pyright: ignore
    import rhinoscriptsyntax as rs
    import scriptcontext as sc
    import Eto # pyright: ignore
    from Eto import Forms, Drawing # pyright: ignore
except Exception:
    pass

from EnneadTab import LOG, ERROR_HANDLE, ENVIRONMENT, IMAGE, NOTIFICATION
from EnneadTab import PHONE_SCANNER
from EnneadTab.RHINO import RHINO_UI


class StagedPhotoItem(object):
    """Container for each staged photo item."""
    def __init__(self, photo_id, file_path, timestamp):
        self.photo_id = photo_id
        self.file_path = file_path
        self.timestamp = timestamp
        self.display_name = os.path.basename(file_path)
        self.size_info = ""
        try:
            w, h = PHONE_SCANNER.get_image_pixel_size(file_path)
            self.size_info = "{}x{} px".format(int(w), int(h))
        except Exception:
            pass


class PhoneScannerStagingForm(Forms.Form):
    """Non-blocking Eto Form that stages incoming photos from Phone Scanner."""

    def __init__(self, room_id):
        super(PhoneScannerStagingForm, self).__init__()
        self.room_id = room_id
        self.portal_url = PHONE_SCANNER.get_portal_url(room_id)
        self.pin = room_id.replace("rhino-", "").upper()
        self.staged_items = []
        self.last_poll_time = 0
        self.selected_item = None

        self.Title = "EnneadTab - Phone Scanner Staging [{}]".format(self.pin)
        self.Resizable = True
        self.Padding = Drawing.Padding(8)
        self.Size = Drawing.Size(820, 560)
        self.MinimumSize = Drawing.Size(640, 420)

        # Set dialog icon if available
        try:
            icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
            if os.path.exists(icon_path):
                self.Icon = Drawing.Icon(icon_path)
        except Exception:
            pass

        self._build_ui()
        self._init_timer()
        self.Closed += self._on_closed

    def _build_ui(self):
        root = Forms.DynamicLayout()
        root.Padding = Drawing.Padding(6)
        root.Spacing = Drawing.Size(6, 6)

        # 1. Top Header & Room Info Bar
        header = Forms.DynamicLayout()
        header.Padding = Drawing.Padding(8)
        header.Spacing = Drawing.Size(8, 4)
        try:
            header.BackgroundColor = RHINO_UI.hex_to_eto_color("#1E2333")
        except Exception:
            pass

        header.BeginHorizontal()

        # Title & PIN
        lbl_title = Forms.Label(Text="PHONE SCANNER")
        try:
            lbl_title.Font = Drawing.Font(Drawing.FontFamilies.Monospace, 12, Drawing.FontStyle.Bold)
            lbl_title.TextColor = RHINO_UI.hex_to_eto_color("#00F0FF")
        except Exception:
            pass
        header.Add(lbl_title)

        lbl_pin = Forms.Label(Text="[PIN: {}]".format(self.pin))
        try:
            lbl_pin.Font = Drawing.Font(Drawing.FontFamilies.Monospace, 11, Drawing.FontStyle.Bold)
            lbl_pin.TextColor = RHINO_UI.hex_to_eto_color("#FFE59C")
        except Exception:
            pass
        header.Add(lbl_pin)

        header.Add(None, xscale=True) # Spacer

        # Status Label
        self.lbl_status = Forms.Label(Text="WAITING FOR PHOTOS...")
        try:
            self.lbl_status.Font = Drawing.Font(Drawing.FontFamilies.Monospace, 9, Drawing.FontStyle.Bold)
            self.lbl_status.TextColor = RHINO_UI.hex_to_eto_color("#38EF7D")
        except Exception:
            pass
        header.Add(self.lbl_status)

        # Web portal button
        btn_portal = Forms.Button(Text="Open Web Portal")
        btn_portal.ToolTip = "Open the CRT QR Code Pairing Portal in browser"
        btn_portal.Click += self._on_open_portal_click
        header.Add(btn_portal)

        header.EndHorizontal()
        root.Add(header, xscale=True)

        # 2. Main Content Split: Left List of Photos, Right Preview
        content_layout = Forms.DynamicLayout()
        content_layout.Spacing = Drawing.Size(8, 0)
        content_layout.BeginHorizontal()

        # Left Column: List of staged photos
        left_layout = Forms.DynamicLayout()
        left_layout.Width = 320
        left_layout.BeginVertical()

        lbl_list_hdr = Forms.Label(Text="STAGED SCANS:")
        try:
            lbl_list_hdr.Font = Drawing.Font(Drawing.FontFamilies.Monospace, 9, Drawing.FontStyle.Bold)
            lbl_list_hdr.TextColor = RHINO_UI.hex_to_eto_color("#DAE8FD")
        except Exception:
            pass
        left_layout.Add(lbl_list_hdr)

        self.grid_view = Forms.GridView()
        self.grid_view.ShowHeader = True
        self.grid_view.AllowMultipleSelection = False
        self.grid_view.Height = 360

        col_name = Forms.GridColumn()
        col_name.HeaderText = "Image"
        col_name.Editable = False
        col_name.Width = 190
        col_name.DataCell = Forms.TextBoxCell(0)
        self.grid_view.Columns.Add(col_name)

        col_size = Forms.GridColumn()
        col_size.HeaderText = "Resolution"
        col_size.Editable = False
        col_size.Width = 110
        col_size.DataCell = Forms.TextBoxCell(1)
        self.grid_view.Columns.Add(col_size)

        self.grid_view.SelectedRowsChanged += self._on_grid_selection_changed
        left_layout.Add(self.grid_view, yscale=True)
        left_layout.EndVertical()
        content_layout.Add(left_layout)

        # Right Column: Preview ImageView & Meta
        right_layout = Forms.DynamicLayout()
        right_layout.BeginVertical()

        self.lbl_preview_info = Forms.Label(Text="Select a photo on the left to preview")
        try:
            self.lbl_preview_info.Font = Drawing.Font(Drawing.FontFamilies.Monospace, 9)
            self.lbl_preview_info.TextColor = RHINO_UI.hex_to_eto_color("#9A9A9A")
        except Exception:
            pass
        right_layout.Add(self.lbl_preview_info)

        self.image_preview = Forms.ImageView()
        self.image_preview.Size = Drawing.Size(460, 360)
        right_layout.Add(self.image_preview, xscale=True, yscale=True)

        right_layout.EndVertical()
        content_layout.Add(right_layout, xscale=True)

        content_layout.EndHorizontal()
        root.Add(content_layout, xscale=True, yscale=True)

        # 3. Bottom Action Toolbar
        toolbar = Forms.DynamicLayout()
        toolbar.Padding = Drawing.Padding(8, 6)
        toolbar.Spacing = Drawing.Size(8, 4)
        try:
            toolbar.BackgroundColor = RHINO_UI.hex_to_eto_color("#1E2333")
        except Exception:
            pass

        toolbar.BeginHorizontal()

        # Primary Action: Drop as PictureFrame
        self.btn_insert = Forms.Button(Text="Drop as PictureFrame")
        self.btn_insert.ToolTip = "Click to pick point and insert selected image as PictureFrame"
        self.btn_insert.Click += self._on_insert_click
        toolbar.Add(self.btn_insert)

        # Batch Insert All
        self.btn_insert_all = Forms.Button(Text="Insert All")
        self.btn_insert_all.ToolTip = "Insert all staged photos sequentially into viewport"
        self.btn_insert_all.Click += self._on_insert_all_click
        toolbar.Add(self.btn_insert_all)

        # Copy to Clipboard
        self.btn_copy = Forms.Button(Text="Copy Bitmap")
        self.btn_copy.ToolTip = "Copy selected image to Windows clipboard (Ctrl+V into Teams/Word)"
        self.btn_copy.Click += self._on_copy_click
        toolbar.Add(self.btn_copy)

        # Open in OS
        self.btn_open = Forms.Button(Text="Open File")
        self.btn_open.ToolTip = "Open image file in system image viewer"
        self.btn_open.Click += self._on_open_file_click
        toolbar.Add(self.btn_open)

        toolbar.Add(None, xscale=True) # Spacer

        # Clear staging
        self.btn_clear = Forms.Button(Text="Clear Staging")
        self.btn_clear.ToolTip = "Clear current list and remove staged files"
        self.btn_clear.Click += self._on_clear_click
        toolbar.Add(self.btn_clear)

        # Close
        btn_close = Forms.Button(Text="Close")
        btn_close.Click += lambda s, e: self.Close()
        toolbar.Add(btn_close)

        toolbar.EndHorizontal()
        root.Add(toolbar, xscale=True)

        self.Content = root
        RHINO_UI.apply_dark_style(self)

    def _init_timer(self):
        """Initialize polling timer for incoming photos."""
        self.timer = Forms.UITimer()
        self.timer.Interval = 1.2 # 1200ms
        self.timer.Elapsed += self._on_poll_tick
        self.timer.Start()

    def _on_poll_tick(self, sender, e):
        """Poll ephemeral room for new photos."""
        try:
            photos = PHONE_SCANNER.poll_room_photos(self.room_id, since=self.last_poll_time)
            if photos:
                for item in photos:
                    ts = item.get("timestamp", int(time.time() * 1000))
                    if ts > self.last_poll_time:
                        self.last_poll_time = ts

                    photo_id = item.get("id")
                    data_url = item.get("dataUrl")
                    if not data_url:
                        continue

                    # Check if already staged
                    if any(x.photo_id == photo_id for x in self.staged_items):
                        continue

                    file_path = PHONE_SCANNER.save_b64_image_to_temp(data_url, photo_id)
                    if file_path and os.path.exists(file_path):
                        staged_item = StagedPhotoItem(photo_id, file_path, ts)
                        self.staged_items.insert(0, staged_item)

                self._update_grid()
                self.lbl_status.Text = "ACTIVE: {} PHOTO(S) BEAMED".format(len(self.staged_items))
                try:
                    self.lbl_status.TextColor = RHINO_UI.hex_to_eto_color("#00F0FF")
                except Exception:
                    pass
        except Exception as ex:
            pass

    def _update_grid(self):
        """Update GridView datastore."""
        data_rows = []
        for item in self.staged_items:
            data_rows.append([item.display_name, item.size_info])
        self.grid_view.DataStore = data_rows

        # If nothing selected, select the top newest item
        if self.staged_items and self.selected_item is None:
            self.grid_view.SelectedRow = 0
            self._select_item(self.staged_items[0])

    def _on_grid_selection_changed(self, sender, e):
        row_idx = self.grid_view.SelectedRow
        if 0 <= row_idx < len(self.staged_items):
            self._select_item(self.staged_items[row_idx])

    def _select_item(self, item):
        self.selected_item = item
        if item and os.path.exists(item.file_path):
            try:
                bmp = Drawing.Bitmap(item.file_path)
                self.image_preview.Image = bmp
                self.lbl_preview_info.Text = "{0} - {1}".format(item.display_name, item.size_info)
            except Exception:
                try:
                    self.image_preview.Image = None
                    self.lbl_preview_info.Text = item.display_name
                except Exception:
                    pass
        else:
            self.image_preview.Image = None
            self.lbl_preview_info.Text = "No photo selected"

    def _on_open_portal_click(self, sender, e):
        webbrowser.open(self.portal_url)

    def _on_insert_click(self, sender, e):
        if not self.selected_item or not os.path.exists(self.selected_item.file_path):
            NOTIFICATION.messenger(main_text="Please select a photo to insert.")
            return

        img_path = self.selected_item.file_path
        obj_id = PHONE_SCANNER.insert_picture_frame(img_path, prompt_point=True)
        if obj_id:
            NOTIFICATION.messenger(main_text="PictureFrame added to Rhino document!", level="success")

    def _on_insert_all_click(self, sender, e):
        if not self.staged_items:
            NOTIFICATION.messenger(main_text="No staged photos to insert.")
            return

        count = 0
        offset_x = 0
        for item in reversed(self.staged_items):
            if os.path.exists(item.file_path):
                # Place with offset so they do not overlap completely
                plane = Rhino.Geometry.Plane.WorldXY
                plane.Origin = Rhino.Geometry.Point3d(offset_x, 0, 0)
                obj_id = PHONE_SCANNER.insert_picture_frame(item.file_path, plane=plane, prompt_point=False)
                if obj_id:
                    count += 1
                    w, h = PHONE_SCANNER.get_image_pixel_size(item.file_path)
                    offset_x += 60.0

        sc.doc.Views.Redraw()
        NOTIFICATION.messenger(main_text="Inserted {} PictureFrames into viewport!".format(count), level="success")

    def _on_copy_click(self, sender, e):
        if not self.selected_item or not os.path.exists(self.selected_item.file_path):
            NOTIFICATION.messenger(main_text="Please select a photo to copy.")
            return
        ok = PHONE_SCANNER.copy_image_to_clipboard(self.selected_item.file_path)
        if ok:
            NOTIFICATION.messenger(main_text="Image copied to clipboard! Paste with Ctrl+V", level="success")
        else:
            NOTIFICATION.messenger(main_text="Failed to copy image to clipboard.", level="warning")

    def _on_open_file_click(self, sender, e):
        if not self.selected_item or not os.path.exists(self.selected_item.file_path):
            return
        try:
            os.startfile(self.selected_item.file_path)
        except Exception as ex:
            ERROR_HANDLE.print_note("Could not open file: {}".format(ex))

    def _on_clear_click(self, sender, e):
        self.staged_items = []
        self.selected_item = None
        self.grid_view.DataStore = []
        self.image_preview.Image = None
        self.lbl_preview_info.Text = "Staging cleared"
        self.lbl_status.Text = "WAITING FOR PHOTOS..."
        PHONE_SCANNER.purge_staging_folder()

    def _on_closed(self, sender, e):
        try:
            if hasattr(self, "timer") and self.timer:
                self.timer.Stop()
                self.timer.Dispose()
        except Exception:
            pass


_CURRENT_SCANNER_FORM = [None]


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def phone_scanner():
    """Launch phone scanner pairing portal & staging dialog."""
    # Close any existing instance
    existing = _CURRENT_SCANNER_FORM[0]
    if existing is not None:
        try:
            existing.Close()
        except Exception:
            pass
        _CURRENT_SCANNER_FORM[0] = None

    room_id = PHONE_SCANNER.generate_room_id()
    portal_url = PHONE_SCANNER.get_portal_url(room_id)

    # 1. Open web pairing portal in browser
    try:
        webbrowser.open(portal_url)
    except Exception as ex:
        ERROR_HANDLE.print_note("Failed to open browser: {}".format(ex))

    # 2. Open Eto staging form
    try:
        form = PhoneScannerStagingForm(room_id)
        _CURRENT_SCANNER_FORM[0] = form
        form.Show()
    except Exception as ex:
        ERROR_HANDLE.print_note("Failed to launch staging form: {}".format(ex))


if __name__ == "__main__":
    phone_scanner()
