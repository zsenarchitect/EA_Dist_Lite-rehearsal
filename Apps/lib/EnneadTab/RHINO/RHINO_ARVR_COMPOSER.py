# -*- coding: utf-8 -*-
"""Rhino sheet composer for EnneadTab-ARVR.

Compose a 3D model with a site plan on one printable sheet, then upload both
together. The plan image comes from a Rhino picture-surface object or an image
file, and is remembered across sessions until the user picks another one.
Logic lives in EnneadTab.ARVR_COMPOSE; this file is only the Eto dialog.
IronPython 2.7: no f-strings, no type hints.
"""

import os

try:
    import Rhino # pyright: ignore
    import rhinoscriptsyntax as rs # pyright: ignore
    import scriptcontext as sc # pyright: ignore
    import Eto # pyright: ignore
except:
    pass

from EnneadTab import ARVR, ARVR_COMPOSE, NOTIFICATION
from EnneadTab.RHINO import RHINO_UI

PAPER_IDS = ["A4", "LETTER", "A3", "TABLOID"]
PREVIEW_W = 300


def read_picture_surface(obj_id):
    """Read a Rhino picture surface: (image_path, width_mm, height_mm, min_x_mm, max_y_mm).

    Picture surfaces are plane surfaces whose material holds the bitmap. Sizes
    come from the surface's bounding box in the CPlane-aligned plan, converted
    from document units to mm. Raises ValueError with a user-readable reason.
    """
    robj = sc.doc.Objects.FindId(obj_id)
    if robj is None:
        raise ValueError("Object not found.")
    mat = robj.GetMaterial(True)
    tex = None
    if mat is not None:
        tex = mat.GetTexture(Rhino.DocObjects.TextureType.Bitmap)
    path = tex.FileName if tex is not None else None
    if not path or not os.path.exists(path):
        raise ValueError("That object has no image file on disk. Pick a picture surface "
                         "(Rhino _Picture command) whose image file still exists, or browse the image instead.")
    # Measure along the surface's own plane, and only accept a plan-aligned one:
    # the origin math below assumes world X/Y axes, so a rotated or tilted
    # picture would silently give a wrong scale and origin.
    geo = robj.Geometry
    srf = geo.Faces[0].UnderlyingSurface() if hasattr(geo, "Faces") else geo
    ok, plane = srf.TryGetPlane()
    if not ok:
        raise ValueError("That object is not a flat picture surface.")
    # Signed on purpose: a surface facing down or turned 180 degrees would mirror the
    # image, and a small rotation would skew the origin; tolerance is about 2.5 degrees.
    tol = 1e-3
    if (abs(plane.ZAxis.Z - 1.0) > tol or abs(plane.XAxis.X - 1.0) > tol):
        raise ValueError("Picture surface must lie flat, facing up, with its image upright in the Top view. "
                         "Rotate or flip it, or browse the image file instead.")
    bbox = geo.GetBoundingBox(True)
    k = Rhino.RhinoMath.UnitScale(sc.doc.ModelUnitSystem, Rhino.UnitSystem.Millimeters)
    w = (bbox.Max.X - bbox.Min.X) * k
    h = (bbox.Max.Y - bbox.Min.Y) * k
    if w <= 0 or h <= 0:
        raise ValueError("Picture surface has no plan extent. Pick one that lies flat on the CPlane.")
    return path, w, h, bbox.Min.X * k, bbox.Max.Y * k


class ComposerDialog(object):
    """Modal composer. get_model_path(exclude_ids) -> glb path or None; on_done(ok, room, url, err)."""

    def __init__(self, get_model_path, on_done, room_code_getter):
        self.get_model_path = get_model_path
        self.on_done = on_done
        self.room_code_getter = room_code_getter
        self.s = ARVR_COMPOSE.load_settings()
        self.img = None  # Eto bitmap of the plan
        self.img_size = None  # (w, h) px
        self.surface = self.s.get("surface")  # dict from picture surface, if that was the source

        self.dialog = Eto.Forms.Dialog[bool]()
        self.dialog.Title = "EnneadTab-ARVR :: Compose Model + Site Plan"
        self.dialog.Padding = Eto.Drawing.Padding(14)
        self.dialog.Resizable = True
        self.dialog.BackgroundColor = RHINO_UI.hex_to_eto_color("#0A0E1A")
        cyan = RHINO_UI.hex_to_eto_color("#00F0FF")
        dim = RHINO_UI.hex_to_eto_color("#8A99AD")
        yellow = RHINO_UI.hex_to_eto_color("#FFE600")
        magenta = RHINO_UI.hex_to_eto_color("#FF007F")
        white = RHINO_UI.hex_to_eto_color("#FFFFFF")
        panel = RHINO_UI.hex_to_eto_color("#121829")
        self.col_ok = RHINO_UI.hex_to_eto_color("#00FF66")
        self.col_warn = yellow
        self.col_err = magenta

        layout = Eto.Forms.DynamicLayout()
        layout.Spacing = Eto.Drawing.Size(8, 8)

        self.plan_lbl = Eto.Forms.Label()
        self.plan_lbl.Font = Eto.Drawing.Font("Consolas", 9)
        layout.AddRow(self.plan_lbl)

        def _btn(text, handler, color):
            b = Eto.Forms.Button()
            b.Text = text
            b.Font = Eto.Drawing.Font("Arial", 9)
            b.BackgroundColor = panel
            b.TextColor = color
            b.Height = 30
            b.Click += handler
            return b
        layout.AddRow(_btn("PICK PICTURE SURFACE IN RHINO", self.on_pick_surface, self.col_ok),
                      _btn("BROWSE IMAGE FILE", self.on_browse_image, cyan),
                      _btn("CLEAR", self.on_clear, dim))

        self.paper_dd = Eto.Forms.DropDown()
        for pid in PAPER_IDS:
            self.paper_dd.Items.Add(Eto.Forms.ListItem(Text=pid))
        self.paper_dd.SelectedIndex = max(0, PAPER_IDS.index(self.s.get("paper", "A4"))
                                          if self.s.get("paper", "A4") in PAPER_IDS else 0)
        self.paper_dd.SelectedIndexChanged += self.on_paper_changed

        self.scale_tb = Eto.Forms.TextBox()
        self.scale_tb.Width = 90
        self.scale_tb.Text = str(self.s.get("scale_den", ""))
        self.scale_tb.TextChanged += self.on_scale_typed
        self.scale_hint = Eto.Forms.Label()
        self.scale_hint.TextColor = dim
        self.scale_hint.Font = Eto.Drawing.Font("Arial", 8)

        def _lbl(t, col=dim):
            l = Eto.Forms.Label()
            l.Text = t
            l.TextColor = col
            return l
        layout.AddRow(_lbl("Paper"), self.paper_dd, _lbl("Scale 1:"), self.scale_tb, self.scale_hint)

        self.yaw_sl = Eto.Forms.Slider()
        self.yaw_sl.MinValue = -180
        self.yaw_sl.MaxValue = 180
        self.yaw_sl.Value = int(self.s.get("yaw", 0))
        self.yaw_sl.ValueChanged += self.on_yaw_changed
        self.yaw_lbl = _lbl("")
        layout.AddRow(_lbl("Rotate model on plan"), self.yaw_sl, self.yaw_lbl)

        layout.AddRow(_lbl("Click the sheet to place the model's origin:", yellow))
        self.canvas = Eto.Forms.Drawable()
        self.canvas.BackgroundColor = Eto.Drawing.Colors.White
        self.canvas.Paint += self.on_paint
        self.canvas.MouseDown += self.on_canvas_click
        layout.AddRow(self.canvas)

        self.status_lbl = _lbl("")
        layout.AddRow(self.status_lbl)
        self.btn_go = Eto.Forms.Button()
        self.btn_go.Text = "UPLOAD MODEL + SITE PLAN TOGETHER"
        self.btn_go.Font = Eto.Drawing.Font("Arial", 10, Eto.Drawing.FontStyle.Bold)
        self.btn_go.BackgroundColor = magenta
        self.btn_go.TextColor = white
        self.btn_go.Height = 36
        self.btn_go.Click += self.on_upload
        layout.AddRow(self.btn_go)

        scroller = Eto.Forms.Scrollable()
        scroller.Border = getattr(Eto.Forms.BorderType, "None")
        scroller.Content = layout
        self.dialog.Content = scroller
        self.dialog.MinimumSize = Eto.Drawing.Size(520, 560)

        if self.s.get("plan_path"):
            if not self._load_image(self.s["plan_path"]):
                # Unreadable image: report it as moved and drop its stale surface data.
                self.s["plan_missing"] = self.s.pop("plan_path")
                self.surface = None
        self._relayout()

    def show(self):
        return self.dialog.ShowModal(Rhino.UI.RhinoEtoApp.MainWindow)

    # ------------------------------------------------------------- state
    def _paper(self):
        i = self.paper_dd.SelectedIndex
        return PAPER_IDS[i] if 0 <= i < len(PAPER_IDS) else "A4"

    def _origin(self):
        return ARVR_COMPOSE.clamp_origin(self.s.get("origin"), self._paper())

    def _save(self):
        self.s["paper"] = self._paper()
        self.s["yaw"] = self.yaw_sl.Value
        self.s["scale_den"] = self.scale_tb.Text
        self.s["surface"] = self.surface
        ARVR_COMPOSE.save_settings(self.s)

    def _load_image(self, path):
        try:
            from System.IO import File, MemoryStream # pyright: ignore
            bmp = Eto.Drawing.Bitmap(MemoryStream(File.ReadAllBytes(path)))
        except Exception as e:
            NOTIFICATION.messenger("Could not read image: {}".format(e))
            return False
        self.img = bmp
        self.img_size = (bmp.Width, bmp.Height)
        self.s["plan_path"] = path
        return True

    def _relayout(self):
        pw, ph = ARVR_COMPOSE.paper_size_mm(self._paper())
        self.canvas.Size = Eto.Drawing.Size(PREVIEW_W, int(PREVIEW_W * ph / pw))
        if self.img is None:
            miss = self.s.get("plan_missing")
            self.plan_lbl.Text = ">> No site plan chosen" + (" (previous image moved: {})".format(miss) if miss else "")
            self.plan_lbl.TextColor = self.col_warn
        else:
            src = "picture surface" if self.surface else "file"
            self.plan_lbl.Text = ">> Plan ({}): {}".format(src, self.s.get("plan_path"))
            self.plan_lbl.TextColor = self.col_ok
        self._auto_scale()
        self.yaw_lbl.Text = "{} deg".format(self.yaw_sl.Value)
        self.canvas.Invalidate()

    def _auto_scale(self):
        """With a picture surface the real width is known, so the scale is computed, not typed."""
        if not (self.surface and self.img_size):
            self.scale_hint.Text = "type the print scale denominator (500 = 1:500)"
            return
        rect = ARVR_COMPOSE.fit_rect_mm(self.img_size[0], self.img_size[1], self._paper())
        den = ARVR_COMPOSE.scale_denominator(self.surface["w_mm"], rect[2])
        if den:
            self.scale_tb.Text = str(int(round(den)))
            self.scale_hint.Text = "from picture surface"

    def _place_origin_from_surface(self):
        """Put the origin where Rhino's world origin sits on the plan, if it is on the plan."""
        sf = self.surface
        if not (sf and self.img_size):
            return
        rect = ARVR_COMPOSE.fit_rect_mm(self.img_size[0], self.img_size[1], self._paper())
        fx = (0.0 - sf["min_x_mm"]) / sf["w_mm"]
        fy = (sf["max_y_mm"] - 0.0) / sf["h_mm"]
        if 0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0:
            self.s["origin"] = [rect[0] + fx * rect[2], rect[1] + fy * rect[3]]
        else:
            self.s["origin"] = None  # world origin is off the plan: leave centered, user clicks

    # ------------------------------------------------------------ handlers
    def on_pick_surface(self, sender, e):
        self.dialog.Visible = False
        try:
            oid = rs.GetObject("Pick the picture surface (site plan)", rs.filter.surface, preselect=True)
        finally:
            self.dialog.Visible = True
        if not oid:
            return
        try:
            path, w, h, min_x, max_y = read_picture_surface(oid)
        except ValueError as ex:
            NOTIFICATION.messenger(str(ex))
            return
        previous = (self.img, self.img_size, self.s.get("plan_path"))
        if self._load_image(path):
            # A non-uniformly scaled picture would give a wrong scale or origin: refuse it,
            # and keep the plan that was already chosen.
            if abs((w / h) / (self.img_size[0] / float(self.img_size[1])) - 1.0) > 0.03:
                NOTIFICATION.messenger("The picture surface is stretched: its shape does not match the image "
                                       "(more than 3%). Reset its scale, or browse the image file instead.")
                self.img, self.img_size, old_path = previous
                if old_path:
                    self.s["plan_path"] = old_path
                else:
                    self.s.pop("plan_path", None)
                self._relayout()
                return
            self.surface = {"w_mm": w, "h_mm": h, "min_x_mm": min_x, "max_y_mm": max_y}
            self.s["surface_id"] = str(oid)
            self.s.pop("plan_missing", None)
            self._place_origin_from_surface()
            self._save()
            self._relayout()

    def on_browse_image(self, sender, e):
        path = rs.OpenFileName("Select site plan image",
                               "Images (*.png;*.jpg;*.jpeg)|*.png;*.jpg;*.jpeg|All Files (*.*)|*.*")
        if path and self._load_image(path):
            self.surface = None
            self.s.pop("plan_missing", None)
            self.s["origin"] = None
            self._save()
            self._relayout()

    def on_clear(self, sender, e):
        self.img = None
        self.img_size = None
        self.surface = None
        for k in ("plan_path", "origin", "plan_missing"):
            self.s.pop(k, None)
        self._save()
        self._relayout()

    def on_paper_changed(self, sender, e):
        self._place_origin_from_surface()
        self._save()
        self._relayout()

    def on_scale_typed(self, sender, e):
        self._save()

    def on_yaw_changed(self, sender, e):
        self.yaw_lbl.Text = "{} deg".format(self.yaw_sl.Value)
        self._save()
        self.canvas.Invalidate()

    def on_canvas_click(self, sender, e):
        x, y = ARVR_COMPOSE.click_to_mm(e.Location.X, e.Location.Y,
                                        self.canvas.Width, self.canvas.Height, self._paper())
        self.s["origin"] = [x, y]
        self._save()
        self.canvas.Invalidate()

    def on_paint(self, sender, e):
        g = e.Graphics
        w = self.canvas.Width
        h = self.canvas.Height
        g.FillRectangle(Eto.Drawing.Colors.White, 0, 0, w, h)
        pw, ph = ARVR_COMPOSE.paper_size_mm(self._paper())
        if self.img is not None and self.img_size:
            r = ARVR_COMPOSE.fit_rect_mm(self.img_size[0], self.img_size[1], self._paper())
            g.DrawImage(self.img, r[0] / pw * w, r[1] / ph * h, r[2] / pw * w, r[3] / ph * h)
        ox, oy = self._origin()
        cx = ox / pw * w
        cy = oy / ph * h
        pen = Eto.Drawing.Pen(Eto.Drawing.Colors.Red, 2)
        g.DrawLine(pen, Eto.Drawing.PointF(cx - 9, cy), Eto.Drawing.PointF(cx + 9, cy))
        g.DrawLine(pen, Eto.Drawing.PointF(cx, cy - 9), Eto.Drawing.PointF(cx, cy + 9))
        # North tick: rotates with the slider so the user sees the model's heading.
        import math
        a = math.radians(self.yaw_sl.Value)
        g.DrawLine(pen, Eto.Drawing.PointF(cx, cy),
                   Eto.Drawing.PointF(cx + 24 * math.sin(a), cy - 24 * math.cos(a)))

    def _say(self, text, color):
        self.status_lbl.Text = text
        self.status_lbl.TextColor = color

    def on_upload(self, sender, e):
        try:
            if self.img is None or not self.s.get("plan_path"):
                self._say(">> Choose a site plan first.", self.col_warn)
                return
            try:
                den = float(self.scale_tb.Text)
            except ValueError:
                self._say(">> Enter the print scale as a number, e.g. 500 for 1:500.", self.col_warn)
                return
            exclude = [self.s["surface_id"]] if self.surface and self.s.get("surface_id") else []
            model = self.get_model_path(exclude)
            if not model:
                self._say(">> No model: select objects in Rhino or use Browse for a .glb, in the main dialog first.", self.col_warn)
                return
            self._say(">> Rendering sheet...", self.col_warn)
            sheet_png = os.path.join(ARVR.get_staging_directory(), "arvr_sheet.png")
            ok, rect, err = ARVR_COMPOSE.render_sheet_png(self.s["plan_path"], self._paper(), sheet_png)
            if not ok:
                self._say(">> Sheet render failed: {}".format(err), self.col_err)
                return
            self._say(">> Uploading model and plan...", self.col_warn)
            ok, room_id, url, err = ARVR.upload_composition(
                model, sheet_png, ".png", self._paper(), self._origin(), self.yaw_sl.Value, den,
                room_id=self.room_code_getter())
            if ok:
                self._save()
                self.on_done(ok, room_id, url, err)
                self.dialog.Close(True)
            else:
                # Tell the main dialog too, so it blanks the previous room's links and QR codes.
                self.on_done(False, room_id, url, err)
                self._say(">> Upload failed: {}".format(err), self.col_err)
        except Exception as ex:
            self._say(">> Error: {}".format(ex), self.col_err)
