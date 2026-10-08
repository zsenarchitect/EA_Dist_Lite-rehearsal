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
- Compose a .glb with a site-plan image on one printable sheet and upload both together

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
from System.Windows.Controls import Canvas # pyright: ignore
from System.Windows.Shapes import Line # pyright: ignore
from System.Windows.Media import Brushes # pyright: ignore
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption # pyright: ignore
from pyrevit.forms import WPFWindow # pyright: ignore
from pyrevit import forms # pyright: ignore

import proDUCKtion # pyright: ignore 
proDUCKtion.validify()

from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION, FOLDER, ARVR, ARVR_COMPOSE
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

        self._init_compose()

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

    # ---- Explode / build sequence (mirrors the Rhino layer sequence) ----
    # Revit has no layers, so the build axis is Levels or Phases. The result is the
    # same rooms/<id>/sequence/sequence.json sidecar the camera viewers already play;
    # it matches mesh ancestor node names against the level/phase names. NOTE: that
    # match only hits if the GLB you beamed was exported with grouping nodes named
    # after the levels/phases (same caveat as Rhino layers); otherwise the viewer
    # falls back to its own top-level parts.
    def on_sequence_clicked(self, sender, e):
        from EnneadTab import ARVR_SEQUENCE
        doc = self.doc
        if not doc:
            self.status_text.Text = ">> No open Revit document."
            return
        room = self.get_room_id()

        axis = forms.SelectFromList.show(
            ["By Level", "By Phase"],
            multiselect=False,
            title="Explode / build sequence grouped by:",
            button_name="Group By")
        if not axis:
            return

        try:
            if axis.lower().startswith("by level"):
                levels = (DB.FilteredElementCollector(doc).OfClass(DB.Level)
                          .WhereElementIsNotElementType().ToElements())
                if not levels:
                    NOTIFICATION.messenger("No levels found in this model.")
                    return
                picked = forms.SelectFromList.show(
                    levels, multiselect=True, name_attr="Name",
                    title="Pick the levels in your sequence (ordered bottom to top automatically):",
                    button_name="Pick Levels")
                if not picked:
                    return
                pairs = [(lv.Name, float(lv.Elevation)) for lv in picked]
                manifest = ARVR_SEQUENCE.build_revit_level_manifest(pairs)
            else:
                phases = DB.FilteredElementCollector(doc).OfClass(DB.Phase).ToElements()
                if not phases:
                    NOTIFICATION.messenger("No phases found in this model.")
                    return
                picked = forms.SelectFromList.show(
                    phases, multiselect=True, name_attr="Name",
                    title="Pick the phases in build order (oldest construction -> newest):",
                    button_name="Pick Phases")
                if not picked:
                    return
                # The pick order from the dialog is not authoritative; sort into true
                # build order (oldest -> newest) by phase creation id.
                ordered = sorted(picked, key=lambda p: p.Id.IntegerValue)
                manifest = ARVR_SEQUENCE.build_revit_phase_manifest([p.Name for p in ordered])
        except Exception as ex:
            self.status_text.Text = ">> Sequence read failed: {}".format(ex)
            return

        ok, err = ARVR.upload_sequence(room, manifest)
        if ok:
            self.status_text.Text = (
                ">> Sequence of {} groups added to Room {}: EXPLODE and BUILD appear in the camera viewers".format(
                    len(manifest["groups"]), room))
        else:
            self.status_text.Text = ">> Sequence upload failed: {}".format(err)

    # ---- Compose model + site plan on one sheet (mirrors the Rhino composer) ----
    # Revit has no picture-surface pick, so the plan always comes from an image
    # file; it is remembered across sessions until the user picks another one.
    PAPER_IDS = ["A4", "LETTER", "A3", "TABLOID"]

    def _init_compose(self):
        self._ready = False
        self.cs = ARVR_COMPOSE.load_settings()
        paper = self.cs.get("paper", "A4")
        self.paper_combo.SelectedIndex = self.PAPER_IDS.index(paper) if paper in self.PAPER_IDS else 0
        self.scale_textbox.Text = str(self.cs.get("scale_den", "500"))
        self.yaw_slider.Value = float(self.cs.get("yaw", 0))
        self.yaw_text.Text = "{} deg".format(int(self.yaw_slider.Value))
        self._ready = True
        self._refresh_sheet()

    def _paper(self):
        i = self.paper_combo.SelectedIndex
        return self.PAPER_IDS[i] if 0 <= i < len(self.PAPER_IDS) else "A4"

    def _origin(self):
        return ARVR_COMPOSE.clamp_origin(self.cs.get("origin"), self._paper())

    def _save_compose(self):
        self.cs["paper"] = self._paper()
        self.cs["scale_den"] = self.scale_textbox.Text
        self.cs["yaw"] = int(self.yaw_slider.Value)
        ARVR_COMPOSE.save_settings(self.cs)

    def _refresh_sheet(self):
        plan = self.cs.get("plan_path")
        if not plan:
            miss = self.cs.get("plan_missing")
            self.plan_status_text.Text = ">> No site plan chosen" + (
                " (previous image moved: {})".format(miss) if miss else "")
            self.sheet_image.Source = None
            self.origin_canvas.Children.Clear()
            return
        self.plan_status_text.Text = ">> Plan: {}".format(plan)
        pw, ph = ARVR_COMPOSE.paper_size_mm(self._paper())
        self.sheet_grid.Height = 240.0 * ph / pw
        preview = os.path.join(ARVR.get_staging_directory(), "arvr_sheet_preview.png")
        ok, rect, err = ARVR_COMPOSE.render_sheet_png(plan, self._paper(), preview)
        if not ok:
            self.plan_status_text.Text = ">> Could not read image: {}".format(err)
            return
        self._load_qr_image(self.sheet_image, preview)
        self._draw_origin()

    def _draw_origin(self):
        self.origin_canvas.Children.Clear()
        pw, ph = ARVR_COMPOSE.paper_size_mm(self._paper())
        ox, oy = self._origin()
        cx = ox / pw * 240.0
        cy = oy / ph * (240.0 * ph / pw)
        for x1, y1, x2, y2 in ((cx - 9, cy, cx + 9, cy), (cx, cy - 9, cx, cy + 9)):
            ln = Line()
            ln.X1, ln.Y1, ln.X2, ln.Y2 = x1, y1, x2, y2
            ln.Stroke = Brushes.Red
            ln.StrokeThickness = 2
            self.origin_canvas.Children.Add(ln)

    def on_compose_changed(self, sender, e):
        if not getattr(self, "_ready", False):
            return
        self._save_compose()
        self._refresh_sheet()

    def on_yaw_changed(self, sender, e):
        if not getattr(self, "_ready", False):
            return
        self.yaw_text.Text = "{} deg".format(int(self.yaw_slider.Value))
        self._save_compose()

    def on_pick_plan_clicked(self, sender, e):
        dlg = Microsoft.Win32.OpenFileDialog()
        dlg.Title = "Select site plan image"
        dlg.Filter = "Images (*.png;*.jpg;*.jpeg)|*.png;*.jpg;*.jpeg|All Files (*.*)|*.*"
        if dlg.ShowDialog() and dlg.FileName and os.path.exists(dlg.FileName):
            self.cs["plan_path"] = dlg.FileName
            self.cs.pop("plan_missing", None)
            self.cs["origin"] = None
            self._save_compose()
            self._refresh_sheet()

    def on_clear_plan_clicked(self, sender, e):
        for k in ("plan_path", "origin", "plan_missing"):
            self.cs.pop(k, None)
        self._save_compose()
        self._refresh_sheet()

    def on_sheet_clicked(self, sender, e):
        pos = e.GetPosition(self.sheet_image)
        x, y = ARVR_COMPOSE.click_to_mm(pos.X, pos.Y, self.sheet_image.ActualWidth,
                                        self.sheet_image.ActualHeight, self._paper())
        self.cs["origin"] = [x, y]
        self._save_compose()
        self._draw_origin()

    def on_upload_compose_clicked(self, sender, e):
        plan = self.cs.get("plan_path")
        if not plan:
            self.status_text.Text = ">> Choose a site plan image first."
            return
        try:
            den = float(self.scale_textbox.Text)
        except ValueError:
            self.status_text.Text = ">> Enter the print scale as a number, e.g. 500 for 1:500."
            return
        dlg = Microsoft.Win32.OpenFileDialog()
        dlg.Title = "Select the .glb model to compose with the site plan"
        dlg.Filter = "GLB model (*.glb)|*.glb"
        if not dlg.ShowDialog() or not dlg.FileName:
            return
        # Clear the previous composition's links and QR codes: a failure below must not leave them looking current.
        self.mobile_link_textbox.Text = ""
        self.room_link_textbox.Text = ""
        self.qr_mobile_image.Source = None
        self.qr_room_image.Source = None
        self.share_link_card.Visibility = Visibility.Collapsed
        sheet_png = os.path.join(ARVR.get_staging_directory(), "arvr_sheet.png")
        ok, rect, err = ARVR_COMPOSE.render_sheet_png(plan, self._paper(), sheet_png)
        if not ok:
            self.status_text.Text = ">> Sheet render failed: {}".format(err)
            return
        self.status_text.Text = ">> Uploading model and plan..."
        ok, room_id, url, err = ARVR.upload_composition(
            dlg.FileName, sheet_png, ".png", self._paper(), self._origin(), int(self.yaw_slider.Value), den,
            room_id=self.get_room_id())
        if not ok:
            self.status_text.Text = ">> Upload failed: {}".format(err or "unknown error")
            return
        self.status_text.Text = ">> Composed sheet in Room {}: print it at 100%, then scan the QR".format(room_id)
        self.mobile_link_textbox.Text = url
        self.room_link_textbox.Text = "{}?room={}".format(ARVR.ARVR_URL_BASE, room_id)
        qr = ARVR.download_qr_code(url, size=240)
        if qr:
            self._load_qr_image(self.qr_mobile_image, qr)
        # Never leave the previous room's QR in the small slot.
        self.qr_room_image.Source = None
        room_qr = ARVR.download_qr_code(self.room_link_textbox.Text, size=80)
        if room_qr:
            self._load_qr_image(self.qr_room_image, room_qr)
        self.share_link_card.Visibility = Visibility.Visible

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
