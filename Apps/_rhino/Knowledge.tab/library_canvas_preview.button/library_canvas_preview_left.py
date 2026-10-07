# -*- coding: utf-8 -*-
__title__ = "LibraryCanvasPreview"
__doc__ = """Show a static summary of a Grasshopper definition's canvas without opening Grasshopper.

Rhino port of the static canvas preview (EnneadTab-For-Grasshopper PR
#33): a .ghx file is plain XML, so its canvas is summarized directly --
component type counts and names, group and scribble counts, document id,
and canvas bounds -- plus the plugin assemblies the catalog index knows
about. Binary .gh files cannot be parsed this way and are skipped with a
note. Read-only; nothing is opened or modified."""
__is_popular__ = False

import os
import sys
import xml.etree.ElementTree as ET

import rhinoscriptsyntax as rs  # pyright: ignore
import scriptcontext as sc  # pyright: ignore

# The shared catalog lib lives at Apps/_rhino/Library. Toolbar scripts do
# not get _rhino on sys.path by themselves, so resolve it from this file.
_rhino_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_library_dir = os.path.join(_rhino_folder, "Library")
if _library_dir not in sys.path:
    sys.path.append(_library_dir)
try:
    import catalog  # pyright: ignore
except ImportError:
    catalog = None

from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE, NOTIFICATION

_MISSING_LIB_TEXT = ("The shared library module (Apps/_rhino/Library/catalog.py) is not installed yet. "
                     "This button needs the shared-catalog-lib PR #283 (branch sen/osrhino-shared-catalog-lib) merged first.")

_BROWSE_OPTION = "Browse for a .ghx file..."


def _parse_point2d(text):
    # Mirrors GhxCanvasPreviewExtractor.TryParsePoint2d (GH PR #33).
    try:
        parts = (text or "").split(",")
        if len(parts) != 2:
            return None
        return (float(parts[0].strip()), float(parts[1].strip()))
    except (TypeError, ValueError):
        return None


def _parse_rectangle2d(text):
    # Mirrors GhxCanvasPreviewExtractor.TryParseRectangle2d (GH PR #33).
    try:
        parts = (text or "").split(",")
        if len(parts) != 4:
            return None
        values = [float(p.strip()) for p in parts]
        if values[2] <= 0 or values[3] <= 0:
            return None
        return tuple(values)
    except (TypeError, ValueError):
        return None


def _read_items(object_chunk):
    # Mirrors the C# ReadItems: first <item> wins per name, case-insensitive.
    items = {}
    for item in object_chunk.findall("item"):
        name = item.get("name")
        if not name:
            continue
        lowered = name.strip().lower()
        if lowered and lowered not in items:
            items[lowered] = (item.text or "").strip()
    return items


def extract_ghx(ghx_path):
    """Parse a .ghx file into a canvas summary dict; None when the file is
    missing, unreadable, or not parseable XML (never raises -- mirrors
    GhxCanvasPreviewExtractor.TryExtract, GH PR #33)."""
    if not ghx_path or not os.path.isfile(ghx_path):
        return None
    try:
        root = ET.parse(ghx_path).getroot()
    except Exception:
        return None

    definition = None
    for chunk in root.iter("chunk"):
        if (chunk.get("name") or "") == "Definition":
            definition = chunk
            break
    if definition is None:
        return {"document_id": None, "components": [], "groups": [],
                "scribbles": [], "bounds": None, "empty": True}

    document_id = None
    for item in definition.findall("item"):
        if (item.get("name") or "").strip().lower() == "documentid":
            text = (item.text or "").strip()
            if text:
                document_id = text
            break

    # Object chunks live inside the Definition chunk's <chunks> wrapper in
    # real GHX; tolerate them as direct children too (hand-written XML).
    chunks_parent = definition.find("chunks")
    if chunks_parent is None:
        chunks_parent = definition

    components = []  # (name, nickname, x, y)
    groups = []      # (nickname, (x, y, w, h))
    scribbles = []   # (text, (x, y))
    for obj in chunks_parent.findall("chunk"):
        if (obj.get("name") or "") != "Object":
            continue
        items = _read_items(obj)
        name = items.get("name", "")
        if not name:
            continue
        lowered = name.lower()
        if lowered == "group":
            border = _parse_rectangle2d(items.get("border"))
            if border is not None:
                groups.append((items.get("nickname", ""), border))
        elif lowered == "scribble":
            pivot = _parse_point2d(items.get("pivot"))
            text = items.get("text", "")
            if pivot is not None and text:
                scribbles.append((text, pivot))
        else:
            pivot = _parse_point2d(items.get("pivot"))
            if pivot is not None:
                nickname = items.get("nickname", "") or name
                components.append((name, nickname, pivot))

    points = []
    for _name, _nick, pivot in components:
        points.append(pivot)
    for _text, pivot in scribbles:
        points.append(pivot)
    for _nick, (x, y, w, h) in groups:
        points.extend([(x, y), (x + w, y + h)])
    bounds = None
    if points:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        bounds = (min(xs), min(ys), max(xs), max(ys))

    return {"document_id": document_id, "components": components,
            "groups": groups, "scribbles": scribbles, "bounds": bounds,
            "empty": False}


def _pick_ghx(entries):
    ghx_entries = []
    for entry in entries:
        path = entry.get("path") or ""
        if path.lower().endswith(".ghx"):
            label = (entry.get("title") or os.path.basename(path))
            ghx_entries.append((u"{0}  ({1})".format(label, os.path.basename(path)), entry))

    options = [label for label, _entry in ghx_entries]
    options.append(_BROWSE_OPTION)
    picked = RHINO_FORMS.select_from_list(
        options,
        title="Canvas Preview",
        message="Pick a catalog .ghx definition to summarize (parsed as XML, Grasshopper stays closed).",
        button_names=["Preview"],
        multi_select=False)
    if not picked:
        return None, None
    if isinstance(picked, (list, tuple)):
        picked = picked[0] if picked else None
    if picked is None:
        return None, None
    if picked == _BROWSE_OPTION:
        path = rs.OpenFileName("Select a .ghx file", "Grasshopper XML (*.ghx)|*.ghx||")
        if not path:
            return None, None
        return None, path
    index = options.index(picked)
    entry = ghx_entries[index][1]
    return entry, entry.get("path")


def _format_report(entry, ghx_path, data):
    lines = []
    lines.append("Canvas preview -- {0}".format(os.path.basename(ghx_path)))
    lines.append("")
    if data.get("empty"):
        lines.append("(valid .ghx but no canvas objects found)")
        return "\n".join(lines)
    if data.get("document_id"):
        lines.append("Document id: {0}".format(data["document_id"]))
    components = data["components"]
    groups = data["groups"]
    scribbles = data["scribbles"]
    lines.append("Components: {0}   Groups: {1}   Scribbles: {2}".format(
        len(components), len(groups), len(scribbles)))
    bounds = data.get("bounds")
    if bounds:
        lines.append("Canvas bounds: ({0:.0f}, {1:.0f}) to ({2:.0f}, {3:.0f})".format(*bounds))
    lines.append("")

    kind_counts = {}
    for name, _nick, _pivot in components:
        kind_counts[name] = kind_counts.get(name, 0) + 1
    lines.append("Component types ({0} distinct):".format(len(kind_counts)))
    for name in sorted(kind_counts, key=lambda n: (-kind_counts[n], n.lower())):
        lines.append("  {0} x{1}".format(name, kind_counts[name]))
    lines.append("")

    if groups:
        lines.append("Groups:")
        for nickname, _border in groups:
            lines.append("  {0}".format(nickname or "(unnamed)"))
        lines.append("")
    if scribbles:
        lines.append("Scribbles:")
        for text, _pivot in scribbles[:10]:
            preview = text if len(text) <= 60 else text[:57] + "..."
            lines.append("  {0}".format(preview))
        if len(scribbles) > 10:
            lines.append("  ... and {0} more".format(len(scribbles) - 10))
        lines.append("")

    lines.append("Plugin assemblies (from catalog index):")
    if entry is not None and entry.get("pluginsKnown"):
        plugins = [p for p in (entry.get("pluginsRequired") or []) if p]
        if plugins:
            for plugin in sorted(set(plugins)):
                lines.append("  - {0}".format(plugin))
        else:
            lines.append("  (none detected -- native components only)")
    else:
        lines.append("  (unknown -- re-index with the Grasshopper plugin to detect)")
    return "\n".join(lines)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_canvas_preview():
    if catalog is None:
        rs.MessageBox(_MISSING_LIB_TEXT)
        return

    index_path, _settings_path = catalog.find_catalog_paths()
    entries = []
    if index_path:
        entries = catalog.iter_entries(catalog.load_index(index_path))

    entry, ghx_path = _pick_ghx(entries)
    if not ghx_path:
        return

    if ghx_path.lower().endswith(".gh"):
        NOTIFICATION.messenger(
            main_text="Binary .gh files cannot be previewed statically.\n"
                      "Save the definition as .ghx (XML) and try again.")
        return

    data = extract_ghx(ghx_path)
    if data is None:
        NOTIFICATION.messenger(
            main_text="Could not parse as .ghx XML:\n{0}".format(ghx_path))
        return

    RHINO_FORMS.notification(
        title="Canvas Preview",
        main_text=os.path.basename(ghx_path),
        sub_text=_format_report(entry, ghx_path, data),
        width=640,
        height=520)


if __name__ == "__main__":
    library_canvas_preview()
