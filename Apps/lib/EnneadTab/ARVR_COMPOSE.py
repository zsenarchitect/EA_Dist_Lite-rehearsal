# -*- coding: utf-8 -*-
"""Sheet composer helpers for EnneadTab-ARVR (Rhino and Revit share these).

A "composition" is one printable sheet: a site-plan image fitted onto a paper
size, plus the model datum (origin) and plan-north rotation on that sheet. It is
sent to the ARVR web app as a ONE-SHEET DRAWING SET, the contract the Revit
drawing-set exporter already uses (EnneadTab-ARVR lib/drawingSet.ts):

    anchor = {origin: {x, y} mm from sheet top-left, northYawDeg,
              scaleDenominator, paper, markerMm: 0}

The web app fits the plan PNG to the full paper (portrait), so the image this
module renders must have the paper's aspect ratio.

Pure Python 2.7 / 3 on purpose: only render_sheet_png touches .NET.
"""

import os
import json

# Mirrors EnneadTab-ARVR lib/paperAnchor/layout.ts PAPERS (portrait mm).
PAPERS = {
    "A4": (210.0, 297.0),
    "LETTER": (215.9, 279.4),
    "A3": (297.0, 420.0),
    "TABLOID": (279.4, 431.8),
}
DEFAULT_PAPER = "A4"
PX_PER_MM = 4  # same as the web composer, so tracking features match
SHEET_MARGIN_MM = 8.0
SETTINGS_NAME = "ARVR_compose_settings.json"

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")


def paper_size_mm(paper):
    """(width, height) in mm for a paper id; unknown ids fall back to A4."""
    return PAPERS.get(paper, PAPERS[DEFAULT_PAPER])


def fit_rect_mm(img_w, img_h, paper, margin_mm=SHEET_MARGIN_MM):
    """Where the plan image sits on the sheet: (x0, y0, w, h) in mm from top-left.

    Fitted inside the margin without distortion and centered.
    """
    pw, ph = paper_size_mm(paper)
    aw = pw - 2 * margin_mm
    ah = ph - 2 * margin_mm
    s = min(aw / float(img_w), ah / float(img_h))
    w = img_w * s
    h = img_h * s
    return (margin_mm + (aw - w) / 2.0, margin_mm + (ah - h) / 2.0, w, h)


def click_to_mm(x_px, y_px, view_w_px, view_h_px, paper):
    """Convert a click inside the on-screen sheet preview to mm from sheet top-left."""
    pw, ph = paper_size_mm(paper)
    x = min(max(x_px / float(view_w_px), 0.0), 1.0) * pw
    y = min(max(y_px / float(view_h_px), 0.0), 1.0) * ph
    return (x, y)


def clamp_origin(origin, paper):
    """Keep a saved origin on the selected sheet.

    An origin placed on A3 and then viewed on A4 would otherwise sit off the
    sheet. Returns (x, y) in mm from the top-left; None or garbage gives the center.
    """
    pw, ph = paper_size_mm(paper)
    try:
        x = float(origin[0])
        y = float(origin[1])
    except (TypeError, ValueError, IndexError):
        return (pw / 2.0, ph / 2.0)
    return (min(max(x, 0.0), pw), min(max(y, 0.0), ph))


def scale_denominator(real_width, drawn_width_mm, real_units_per_mm=1.0):
    """Print scale denominator (500 means 1:500).

    real_width is the plan's real-world width in model units; real_units_per_mm
    converts those units to mm (Rhino meters: 1000.0 mm per unit means pass
    real_units_per_mm=1000.0). drawn_width_mm is that same width on paper.
    Returns None when it cannot be computed.
    """
    if not real_width or not drawn_width_mm or real_width <= 0 or drawn_width_mm <= 0:
        return None
    return round(real_width * real_units_per_mm / float(drawn_width_mm), 1)


def build_manifest(set_name, model_size, plan_ext, paper, origin_mm, north_yaw_deg,
                   scale_den, sheet_name="Site plan", level="Site", created_at_ms=None):
    """One-sheet drawing-set manifest for POST /api/room/<id>. Raises ValueError on bad input."""
    if paper not in PAPERS:
        raise ValueError("Unknown paper '{}'. Use one of {}.".format(paper, sorted(PAPERS)))
    if plan_ext not in IMAGE_EXTENSIONS:
        raise ValueError("Plan image must be PNG or JPG.")
    if not scale_den or scale_den <= 0:
        raise ValueError("Scale denominator must be a positive number.")
    if not model_size or model_size <= 0:
        raise ValueError("Model size must be positive.")
    return {
        "version": 1,
        "setName": (set_name or "Site composition")[:120],
        "createdAt": created_at_ms,
        "sheets": [{
            "sheetNumber": "S-1",
            "sheetName": (sheet_name or "Site plan")[:120],
            "level": (level or "Site")[:64],
            "planBlobPath": "PLAN_PATH_PLACEHOLDER",
            "modelBlobPath": "MODEL_PATH_PLACEHOLDER",
            "modelSize": int(model_size),
            "anchor": {
                "origin": {"x": float(origin_mm[0]), "y": float(origin_mm[1])},
                "northYawDeg": float(north_yaw_deg),
                "scaleDenominator": float(scale_den),
                "paper": paper,
                "markerMm": 0,
            },
        }],
    }


def sheet_blob_paths(room_id, plan_ext):
    """Blob pathnames the server validates the manifest against."""
    base = "rooms/{}/drawing-set/sheets/0/".format(room_id)
    return base + "plan" + plan_ext, base + "model.glb"


# ---------------------------------------------------------------- persistence

def _settings_path():
    from EnneadTab import FOLDER
    return FOLDER.get_local_dump_folder_file(SETTINGS_NAME)


def load_settings(path=None):
    """Remembered composer settings; {} when none. The plan image persists across
    sessions until the user picks another one. A missing image file is dropped so
    the dialog shows 'no plan' instead of failing at upload time."""
    path = path or _settings_path()
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    plan = data.get("plan_path")
    if plan and not os.path.exists(plan):
        data["plan_missing"] = plan
        data.pop("plan_path", None)
    return data


def save_settings(settings, path=None):
    path = path or _settings_path()
    try:
        with open(path, "w") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception:
        return False


# -------------------------------------------------------------------- render

def render_sheet_png(plan_path, paper, out_path):
    """Draw the plan image onto a white sheet of the paper's aspect (IronPython/.NET).

    Returns (ok, (x0, y0, w, h) image rect in mm, error).
    """
    try:
        from System.Drawing import Bitmap, Graphics, Color, RectangleF  # pyright: ignore
        from System.Drawing.Drawing2D import InterpolationMode  # pyright: ignore
        from System.Drawing.Imaging import ImageFormat  # pyright: ignore
    except ImportError:
        return False, None, "Sheet rendering needs Rhino or Revit (System.Drawing)."
    src = None
    sheet = None
    try:
        src = Bitmap(plan_path)
        rect = fit_rect_mm(src.Width, src.Height, paper)
        pw, ph = paper_size_mm(paper)
        sheet = Bitmap(int(round(pw * PX_PER_MM)), int(round(ph * PX_PER_MM)))
        g = Graphics.FromImage(sheet)
        g.Clear(Color.White)
        g.InterpolationMode = InterpolationMode.HighQualityBicubic
        g.DrawImage(src, RectangleF(rect[0] * PX_PER_MM, rect[1] * PX_PER_MM,
                                    rect[2] * PX_PER_MM, rect[3] * PX_PER_MM))
        g.Dispose()
        sheet.Save(out_path, ImageFormat.Png)
        return True, rect, None
    except Exception as e:
        return False, None, str(e)
    finally:
        if src is not None:
            src.Dispose()
        if sheet is not None:
            sheet.Dispose()
