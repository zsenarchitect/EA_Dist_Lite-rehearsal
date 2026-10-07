# -*- coding: utf-8 -*-
__title__ = "ARVROverlay"
__doc__ = """EnneadTab-ARVR: Zero-Install Mobile Camera AR Overlay for 3D Models.

Beam your 3D models onto your smartphone camera in augmented reality:
- Pick objects in the viewport right from this dialog if nothing is preselected
- Export selected Rhino objects to .GLB
- Stage model in local temp folder
- Direct upload to cloud room session
- Shows the phone-ready QR code and link right here, no browser hop needed
- Pick existing local .GLB / .GLTF / .USDZ file to beam
- Launch Web Hub (https://enneadtab.com/arvr)
"""

__is_popular__ = True

import os
import webbrowser

try:
    import Rhino # pyright: ignore
    import rhinoscriptsyntax as rs # pyright: ignore
    import scriptcontext as sc # pyright: ignore
    import Eto # pyright: ignore
except:
    pass

from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION, FOLDER, ARVR
from EnneadTab.RHINO import RHINO_UI

class ARVRExportDialog(object):
    """Arcade-styled dialog for Rhino ARVR Export, Staging & Web Beaming."""

    def __init__(self):
        self.dialog = Eto.Forms.Dialog[bool]()
        self.dialog.Title = "EnneadTab-ARVR :: Mobile AR Overlay Hub"
        self.dialog.Resizable = True
        self.dialog.Padding = Eto.Drawing.Padding(16)
        self.dialog.Width = 700
        self.dialog.MinimumSize = Eto.Drawing.Size(560, 480)
        # Cap height to the working area so laptop screens do not push the
        # bottom (QR links / CLOSE) off-screen. Scrollable below covers the rest.
        dialog_h = 820
        try:
            work = Eto.Forms.Screen.PrimaryScreen.WorkingArea
            max_h = int(work.Height * 0.9)
            if max_h > 0 and max_h < dialog_h:
                dialog_h = max(self.dialog.MinimumSize.Height, max_h)
        except Exception:
            pass
        self.dialog.Height = dialog_h

        # Colors
        self.col_bg = RHINO_UI.hex_to_eto_color("#0A0E1A")
        self.col_panel = RHINO_UI.hex_to_eto_color("#121829")
        self.col_cyan = RHINO_UI.hex_to_eto_color("#00F0FF")
        self.col_magenta = RHINO_UI.hex_to_eto_color("#FF007F")
        self.col_yellow = RHINO_UI.hex_to_eto_color("#FFE600")
        self.col_green = RHINO_UI.hex_to_eto_color("#00FF66")
        self.col_white = RHINO_UI.hex_to_eto_color("#FFFFFF")
        self.col_dim = RHINO_UI.hex_to_eto_color("#8A99AD")

        self.dialog.BackgroundColor = self.col_bg

        layout = Eto.Forms.DynamicLayout()
        layout.Padding = Eto.Drawing.Padding(10)
        layout.Spacing = Eto.Drawing.Size(8, 8)

        # Header Title
        title_lbl = Eto.Forms.Label()
        title_lbl.Text = "View Model in AR / VR"
        title_lbl.Font = Eto.Drawing.Font("Consolas", 14, Eto.Drawing.FontStyle.Bold)
        title_lbl.TextColor = self.col_cyan
        title_lbl.TextAlignment = Eto.Forms.TextAlignment.Center
        layout.AddRow(title_lbl)

        # Subtitle
        sub_lbl = Eto.Forms.Label()
        sub_lbl.Text = "Send your Rhino model to your phone - no app install needed"
        sub_lbl.Font = Eto.Drawing.Font("Arial", 9)
        sub_lbl.TextColor = self.col_dim
        sub_lbl.TextAlignment = Eto.Forms.TextAlignment.Center
        layout.AddRow(sub_lbl)
        layout.AddSeparateRow()

        # Selection Status
        self.sel_objs = rs.SelectedObjects() if 'rs' in globals() else []
        sel_count = len(self.sel_objs) if self.sel_objs else 0

        status_box = Eto.Forms.GroupBox()
        status_box.Text = "Selection Status"
        status_box.TextColor = self.col_yellow
        status_box.BackgroundColor = self.col_panel
        status_box.Padding = Eto.Drawing.Padding(10)

        status_layout = Eto.Forms.DynamicLayout()
        status_layout.Spacing = Eto.Drawing.Size(6, 6)

        self.status_lbl = Eto.Forms.Label()
        self.status_lbl.Font = Eto.Drawing.Font("Consolas", 9)
        status_layout.AddRow(self.status_lbl)
        self._refresh_selection_status()

        # Pick objects directly from this dialog when nothing is preselected,
        # instead of forcing a Cancel-reselect-reopen round trip.
        self.btn_pick = Eto.Forms.Button()
        self.btn_pick.Text = "PICK OBJECTS IN VIEWPORT"
        self.btn_pick.Font = Eto.Drawing.Font("Arial", 8)
        self.btn_pick.BackgroundColor = self.col_bg
        self.btn_pick.TextColor = self.col_green
        self.btn_pick.Height = 26
        self.btn_pick.Click += self.on_pick_click
        status_layout.AddRow(self.btn_pick)

        # Room ID input
        room_row = Eto.Forms.DynamicLayout()
        room_row.Spacing = Eto.Drawing.Size(6, 6)
        r_lbl = Eto.Forms.Label()
        r_lbl.Text = "Room Code (Optional):"
        r_lbl.TextColor = self.col_dim
        r_lbl.Font = Eto.Drawing.Font("Arial", 9)
        self.room_tb = Eto.Forms.TextBox()
        self.room_tb.PlaceholderText = "Auto-generated (or enter 6-char code)"
        self.room_tb.BackgroundColor = self.col_bg
        self.room_tb.TextColor = self.col_cyan
        self.room_tb.Width = 320
        room_row.AddRow(r_lbl, self.room_tb)
        status_layout.AddRow(room_row)

        status_box.Content = status_layout
        layout.AddRow(status_box)
        layout.AddSeparateRow()

        # Action Buttons
        self.btn_export = Eto.Forms.Button()
        self.btn_export.Text = "SEND SELECTED OBJECTS TO YOUR PHONE"
        self.btn_export.Font = Eto.Drawing.Font("Arial", 10, Eto.Drawing.FontStyle.Bold)
        self.btn_export.BackgroundColor = self.col_magenta
        self.btn_export.TextColor = self.col_white
        self.btn_export.Height = 36
        self.btn_export.Click += self.on_export_click
        layout.AddRow(self.btn_export)

        self.btn_browse = Eto.Forms.Button()
        self.btn_browse.Text = "BROWSE LOCAL MODEL (.GLB/.GLTF/.USDZ) && BEAM"
        self.btn_browse.Font = Eto.Drawing.Font("Arial", 9)
        self.btn_browse.BackgroundColor = self.col_panel
        self.btn_browse.TextColor = self.col_cyan
        self.btn_browse.Height = 32
        self.btn_browse.Click += self.on_browse_click
        layout.AddRow(self.btn_browse)

        self.btn_web = Eto.Forms.Button()
        self.btn_web.Text = "OPEN AR/VR WEB HUB (BROWSER)"
        self.btn_web.Font = Eto.Drawing.Font("Arial", 9)
        self.btn_web.BackgroundColor = self.col_panel
        self.btn_web.TextColor = self.col_yellow
        self.btn_web.Height = 32
        self.btn_web.Click += self.on_web_click
        layout.AddRow(self.btn_web)

        # Share Link / inline Dual QR Codes:
        # 1. Big QR: Mobile AR viewer directly in space
        # 2. Small QR: Desktop Room Hub
        result_box = Eto.Forms.GroupBox()
        result_box.Text = "Share Links & QR Codes"
        result_box.TextColor = self.col_green
        result_box.BackgroundColor = self.col_panel
        result_box.Padding = Eto.Drawing.Padding(10)

        # One shared TableLayout for both QR columns. Because both columns live
        # in the SAME rows, each title / QR slot / link box / copy button is
        # automatically aligned across columns (the old two nested
        # DynamicLayouts had independent row heights, so the 100px QR sat
        # higher than the 180px one and its link + button drifted off).
        qr_cols = Eto.Forms.TableLayout()
        qr_cols.Spacing = Eto.Drawing.Size(16, 6)

        QR_SLOT = 180  # both QRs sit centered in an identical square slot

        m_title = Eto.Forms.Label()
        m_title.Text = "[ 1. MOBILE AR VIEWER ]"
        m_title.Font = Eto.Drawing.Font("Consolas", 10, Eto.Drawing.FontStyle.Bold)
        m_title.TextColor = self.col_green
        r_title = Eto.Forms.Label()
        r_title.Text = "[ 2. ROOM CONTROL PAGE ]"
        r_title.Font = Eto.Drawing.Font("Consolas", 10, Eto.Drawing.FontStyle.Bold)
        r_title.TextColor = self.col_yellow

        m_desc = Eto.Forms.Label()
        m_desc.Text = "Big QR - scan with phone camera"
        m_desc.Font = Eto.Drawing.Font("Arial", 8)
        m_desc.TextColor = self.col_dim
        r_desc = Eto.Forms.Label()
        r_desc.Text = "Small QR - desktop browser hub"
        r_desc.Font = Eto.Drawing.Font("Arial", 8)
        r_desc.TextColor = self.col_dim

        self.qr_mobile_view = Eto.Forms.ImageView()
        self.qr_mobile_view.Size = Eto.Drawing.Size(QR_SLOT, QR_SLOT)
        self.qr_room_view = Eto.Forms.ImageView()
        self.qr_room_view.Size = Eto.Drawing.Size(100, 100)

        def _qr_slot(image_view):
            # Fixed-height panel + vertical ScaleHeight spacers center the
            # smaller Room QR in the same 180px band as the Mobile QR, so the
            # link TextBox and COPY button rows below stay Y-aligned.
            # (A single-row TableLayout only centered horizontally - the 100px
            # QR sat at the top of the slot and the CTAs still lined up via the
            # shared parent rows, but looked vertically unbalanced.)
            table = Eto.Forms.TableLayout()
            table.Spacing = Eto.Drawing.Size(0, 0)

            top = Eto.Forms.TableRow()
            top.ScaleHeight = True
            top.Cells.Add(Eto.Forms.TableCell(None, True))
            table.Rows.Add(top)

            mid = Eto.Forms.TableRow()
            mid.ScaleHeight = False
            mid.Cells.Add(Eto.Forms.TableCell(None, True))
            mid.Cells.Add(Eto.Forms.TableCell(image_view, False))
            mid.Cells.Add(Eto.Forms.TableCell(None, True))
            table.Rows.Add(mid)

            bot = Eto.Forms.TableRow()
            bot.ScaleHeight = True
            bot.Cells.Add(Eto.Forms.TableCell(None, True))
            table.Rows.Add(bot)

            wrap = Eto.Forms.Panel()
            wrap.Height = QR_SLOT
            wrap.Content = table
            return wrap

        self.mobile_link_tb = Eto.Forms.TextBox()
        self.mobile_link_tb.ReadOnly = True
        self.mobile_link_tb.PlaceholderText = "Mobile AR Viewer URL..."
        self.mobile_link_tb.TextColor = self.col_cyan
        self.mobile_link_tb.BackgroundColor = self.col_bg
        self.mobile_link_tb.Font = Eto.Drawing.Font("Consolas", 8)

        self.room_link_tb = Eto.Forms.TextBox()
        self.room_link_tb.ReadOnly = True
        self.room_link_tb.PlaceholderText = "Desktop Room Hub URL..."
        self.room_link_tb.TextColor = self.col_yellow
        self.room_link_tb.BackgroundColor = self.col_bg
        self.room_link_tb.Font = Eto.Drawing.Font("Consolas", 8)

        self.btn_copy_mobile = Eto.Forms.Button()
        self.btn_copy_mobile.Text = "COPY MOBILE AR LINK"
        self.btn_copy_mobile.Font = Eto.Drawing.Font("Arial", 8)
        self.btn_copy_mobile.BackgroundColor = self.col_bg
        self.btn_copy_mobile.TextColor = self.col_green
        self.btn_copy_mobile.Height = 26
        self.btn_copy_mobile.Click += self.on_copy_mobile_click

        self.btn_copy_room = Eto.Forms.Button()
        self.btn_copy_room.Text = "COPY ROOM PAGE LINK"
        self.btn_copy_room.Font = Eto.Drawing.Font("Arial", 8)
        self.btn_copy_room.BackgroundColor = self.col_bg
        self.btn_copy_room.TextColor = self.col_yellow
        self.btn_copy_room.Height = 26
        self.btn_copy_room.Click += self.on_copy_room_click

        # Each row: (left cell, right cell), both columns scale equally.
        for left, right in (
            (m_title, r_title),
            (m_desc, r_desc),
            (_qr_slot(self.qr_mobile_view), _qr_slot(self.qr_room_view)),
            (self.mobile_link_tb, self.room_link_tb),
            (self.btn_copy_mobile, self.btn_copy_room),
        ):
            qr_cols.Rows.Add(Eto.Forms.TableRow(Eto.Forms.TableCell(left, True), Eto.Forms.TableCell(right, True)))

        result_layout = Eto.Forms.DynamicLayout()
        result_layout.Spacing = Eto.Drawing.Size(12, 8)
        result_layout.AddRow(qr_cols)

        result_box.Content = result_layout
        layout.AddRow(result_box)

        # Footer close button (same full-width treatment as the buttons above,
        # so the button block presents one consistent left/right edge)
        btn_close = Eto.Forms.Button()
        btn_close.Text = "CLOSE"
        btn_close.Font = Eto.Drawing.Font("Arial", 9)
        btn_close.BackgroundColor = self.col_bg
        btn_close.TextColor = self.col_dim
        btn_close.Height = 32
        btn_close.Click += lambda s, e: self.dialog.Close(False)
        layout.AddRow(btn_close)

        # Scrollable with ExpandContentHeight=False so the layout keeps its
        # natural preferred height. ExpandContentHeight=True + a trailing
        # yscale spacer (the previous attempt) made PreferredHeight track the
        # viewport, so scrollbars never appeared and the QR/CTA block was
        # still cropped on short screens. Width still expands to fill.
        scroller = Eto.Forms.Scrollable()
        scroller.Border = getattr(Eto.Forms.BorderType, "None")
        scroller.ExpandContentWidth = True
        scroller.ExpandContentHeight = False
        scroller.BackgroundColor = self.col_bg
        scroller.Content = layout
        self.dialog.Content = scroller

    def show(self):
        return self.dialog.ShowModal(Rhino.UI.RhinoEtoApp.MainWindow)

    def _refresh_selection_status(self):
        sel_count = len(self.sel_objs) if self.sel_objs else 0
        if sel_count > 0:
            self.status_lbl.Text = ">> {} object(s) selected ready to export".format(sel_count)
            self.status_lbl.TextColor = self.col_green
        else:
            self.status_lbl.Text = ">> No objects selected (use Pick below, or Browse a local file)"
            self.status_lbl.TextColor = self.col_yellow

    def on_pick_click(self, sender, e):
        # Hide the modal dialog so the Rhino viewport can accept clicks;
        # ShowModal's nested message loop keeps pumping underneath, so
        # re-showing after GetObjects() returns resumes right where we left off.
        self.dialog.Visible = False
        try:
            objs = rs.GetObjects("Select objects to beam to AR/VR", preselect=False, select=True)
        finally:
            self.dialog.Visible = True

        self.sel_objs = objs if objs else []
        self._refresh_selection_status()

    def _set_image(self, image_view, file_path):
        """Safely load an image into an Eto ImageView without locking the file handle."""
        if not file_path or not os.path.exists(file_path):
            return
        try:
            from System.IO import File, MemoryStream # pyright: ignore
            data_bytes = File.ReadAllBytes(file_path)
            ms = MemoryStream(data_bytes)
            image_view.Image = Eto.Drawing.Bitmap(ms)
        except:
            try:
                image_view.Image = Eto.Drawing.Bitmap(file_path)
            except:
                pass

    def _copy_text(self, text):
        """Copy text to clipboard across IronPython and CPython."""
        if not text:
            return
        try:
            from System.Windows.Forms import Clipboard # pyright: ignore
            Clipboard.SetText(text)
        except:
            try:
                import subprocess
                p = subprocess.Popen(['clip'], stdin=subprocess.PIPE)
                p.communicate(text.encode('utf-8'))
            except:
                pass

    def on_copy_mobile_click(self, sender, e):
        txt = self.mobile_link_tb.Text
        if txt:
            self._copy_text(txt)
            self.btn_copy_mobile.Text = "COPIED TO CLIPBOARD!"
            NOTIFICATION.messenger("Mobile AR Link copied to clipboard:\n{}".format(txt))

    def on_copy_room_click(self, sender, e):
        txt = self.room_link_tb.Text
        if txt:
            self._copy_text(txt)
            self.btn_copy_room.Text = "COPIED TO CLIPBOARD!"
            NOTIFICATION.messenger("Desktop Room Hub Link copied to clipboard:\n{}".format(txt))

    def _handle_upload_result(self, ok, room_id, url, err):
        if not ok:
            self.status_lbl.Text = ">> Upload failed: {}".format(err or "unknown error")
            self.status_lbl.TextColor = self.col_magenta
            return

        self.status_lbl.Text = ">> Beamed to Room {} - scan the BIG QR on your phone".format(room_id)
        self.status_lbl.TextColor = self.col_green

        mobile_url = ARVR.get_mobile_viewer_url(room_id)
        self.mobile_link_tb.Text = mobile_url
        self.room_link_tb.Text = url

        try:
            self.btn_web.Text = "OPEN ROOM {} IN BROWSER".format(room_id)
        except:
            pass

        try:
            large_qr, small_qr = ARVR.download_qr_code_pair(room_id, url)
            if large_qr:
                self._set_image(self.qr_mobile_view, large_qr)
            if small_qr:
                self._set_image(self.qr_room_view, small_qr)
        except Exception as e:
            pass

    def on_export_click(self, sender, e):
        try:
            objs = rs.SelectedObjects()
            if not objs:
                rs.Command("-_SelAll ")
                objs = rs.SelectedObjects()
                if not objs:
                    NOTIFICATION.messenger("No objects found to export. Please select objects in Rhino first, or use Pick Objects above.")
                    return

            # Prepare export target path in staging folder
            doc_name = rs.DocumentName()
            if doc_name:
                clean_name = os.path.splitext(doc_name)[0]
            else:
                clean_name = "Rhino_Model"

            staging_dir = ARVR.get_staging_directory()
            out_path = os.path.join(staging_dir, clean_name + ".glb")

            # Delete any leftover file from a previous run first. Without this, a
            # failed export here would silently re-upload a stale .glb from an
            # earlier successful export instead of reporting failure.
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except Exception:
                    pass

            # Use RhinoDoc.ExportSelected directly (same proven pattern as
            # File.tab/external_trimmer.button) instead of scripting -_Export
            # with blind _Enter presses -- that macro approach has no way to
            # know how many dialogs a given selection will trigger.
            rs.SelectObjects(objs)
            try:
                exported = sc.doc.ExportSelected(out_path)
            except Exception as export_err:
                exported = False
                NOTIFICATION.messenger("Export raised an error: {}".format(export_err))

            if not exported or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
                NOTIFICATION.messenger("Could not export geometry to .GLB. Please check Rhino export formats or use Browse.")
                return

            room_input = self.room_tb.Text.strip() if self.room_tb.Text else None
            ok, room_id, url, err = ARVR.stage_and_upload(out_path, room_id=room_input, auto_open_browser=False)
            self._handle_upload_result(ok, room_id, url, err)
        except Exception as ex:
            NOTIFICATION.messenger("Export error: {}".format(ex))
        except:
            NOTIFICATION.messenger("Unexpected error during export.")

    def on_browse_click(self, sender, e):
        try:
            filter_str = "3D Models (*.glb;*.gltf;*.usdz)|*.glb;*.gltf;*.usdz|All Files (*.*)|*.*"
            filepath = rs.OpenFileName("Select 3D Model to Beam to AR/VR", filter_str)
            if not filepath or not os.path.exists(filepath):
                return

            room_input = self.room_tb.Text.strip() if self.room_tb.Text else None
            ok, room_id, url, err = ARVR.stage_and_upload(filepath, room_id=room_input, auto_open_browser=False)
            self._handle_upload_result(ok, room_id, url, err)
        except Exception as ex:
            NOTIFICATION.messenger("Browse error: {}".format(ex))
        except:
            NOTIFICATION.messenger("Unexpected error during browse.")

    def on_web_click(self, sender, e):
        room_input = self.room_tb.Text.strip() if self.room_tb.Text else None
        ARVR.open_web_hub(room_input)
        self.dialog.Close(True)

@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def arvr_overlay():
    dlg = ARVRExportDialog()
    dlg.show()

if __name__ == "__main__":
    arvr_overlay()
