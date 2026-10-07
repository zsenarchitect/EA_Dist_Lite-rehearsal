# -*- coding: utf-8 -*-
__title__ = "LibraryProvenance"
__doc__ = """Show provenance for a catalog entry: will this definition open on my machine?

Rhino port of the Grasshopper provenance tab (EnneadTab-For-Grasshopper
PR #51): component count and component kinds (parsed from the .ghx XML
when available), the plugin assemblies the definition needs (from the
catalog index), and a best-effort check flagging required plugins that
are not installed (scans loaded assemblies plus the Grasshopper
Libraries folders for .gha files). Read-only; nothing is modified."""
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


def _ghx_provenance(ghx_path):
    """Best-effort provenance from a .ghx file: component count plus the
    distinct component kind names (mirrors GhxProvenanceExtractor, GH PR
    #51). Returns (count, kinds) or None when the file is missing or not
    parseable XML; never raises."""
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
        return (0, [])
    chunks_parent = definition.find("chunks")
    if chunks_parent is None:
        chunks_parent = definition
    kinds = []
    for obj in chunks_parent.findall("chunk"):
        if (obj.get("name") or "") != "Object":
            continue
        name = None
        for item in obj.findall("item"):
            if (item.get("name") or "").strip().lower() == "name":
                name = (item.text or "").strip()
                break
        if not name or name.lower() in ("group", "scribble"):
            continue
        kinds.append(name)
    return (len(kinds), sorted(set(kinds)))


def _normalize_plugin_name(name):
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _installed_plugin_names():
    """Best-effort set of normalized installed Grasshopper plugin names:
    loaded .NET assembly simple names plus *.gha / *.dll files under the
    Grasshopper Libraries and Yak package folders (mirrors the plugin-file
    walk in the merged OpenGrasshopperLibrary button)."""
    installed = set()
    try:
        import System  # pyright: ignore
        for asm in System.AppDomain.CurrentDomain.GetAssemblies():
            try:
                full = asm.GetName()
                norm = _normalize_plugin_name(full.Name)
                if norm:
                    installed.add(norm)
            except Exception:
                continue
    except Exception:
        pass
    app_data = os.environ.get("APPDATA", "")
    if app_data:
        folders = [os.path.join(app_data, "Grasshopper", "Libraries"),
                   os.path.join(app_data, "McNeel", "Rhinoceros", "packages")]
        for folder in folders:
            if not os.path.isdir(folder):
                continue
            for _root, _dirs, files in os.walk(folder):
                for file_name in files:
                    lowered = file_name.lower()
                    if lowered.endswith(".gha") or lowered.endswith(".dll"):
                        norm = _normalize_plugin_name(os.path.splitext(file_name)[0])
                        if norm:
                            installed.add(norm)
    return installed


def _is_installed(plugin_name, installed):
    # Fuzzy on purpose: index rows carry plugin names ("Kangaroo") while
    # assemblies/files are often suffixed ("KangarooSolver"). Equal or
    # either-contains-the-other counts as a match (best-effort).
    want = _normalize_plugin_name(plugin_name)
    if not want:
        return False
    if want in installed:
        return True
    for have in installed:
        if want in have or have in want:
            return True
    return False


def _param_group(param):
    for key in ("group", "Group", "GROUP"):
        if key in param:
            return param[key]
    return ""


def _pick_entry(entries):
    options = []
    for entry in entries:
        title = entry.get("title") or os.path.basename(entry.get("path") or "") or "?"
        path = entry.get("path") or ""
        options.append(u"{0}  ({1})".format(title, os.path.basename(path)))
    picked = RHINO_FORMS.select_from_list(
        options,
        title="Library Provenance",
        message="Pick a catalog entry to inspect: will it open on this machine?",
        button_names=["Inspect"],
        multi_select=False)
    if not picked:
        return None
    if isinstance(picked, (list, tuple)):
        picked = picked[0] if picked else None
    if picked is None:
        return None
    return entries[options.index(picked)]


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_provenance():
    if catalog is None:
        rs.MessageBox(_MISSING_LIB_TEXT)
        return

    index_path, _settings_path = catalog.find_catalog_paths()
    if not index_path:
        NOTIFICATION.messenger(
            main_text="Library catalog not found.\nIndex the Grasshopper library first, then run again.")
        return

    entries = catalog.iter_entries(catalog.load_index(index_path))
    if not entries:
        NOTIFICATION.messenger(main_text="The library catalog is empty.")
        return

    entry = _pick_entry(entries)
    if entry is None:
        return

    path = entry.get("path") or ""
    title = entry.get("title") or os.path.basename(path) or "?"

    # --- component count / kinds (mirrors DefinitionProvenanceReport) ---
    ghx = _ghx_provenance(path) if path.lower().endswith(".ghx") else None
    if ghx is not None:
        count_text = "{0} (from .ghx)".format(ghx[0])
    elif path.lower().endswith(".gh"):
        count_text = "(unknown -- binary .gh cannot be parsed statically)"
    else:
        count_text = "(unknown -- re-index with the Grasshopper plugin)"

    # --- plugin assemblies (mirrors ResolveAssemblies) ---
    if entry.get("pluginsKnown"):
        assemblies = sorted(set(p for p in (entry.get("pluginsRequired") or []) if p))
        assemblies_known = True
    else:
        assemblies = []
        assemblies_known = False

    # --- installed check ---
    installed = _installed_plugin_names()
    installed_checked = bool(installed)

    # --- third-party components (mirrors ResolveThirdParty) ---
    if ghx is not None and ghx[1]:
        third_party = ghx[1]
        third_party_note = ("detected component kinds from .ghx; third-party "
                            "status unknown without a live index")
    else:
        third_party = []
        third_party_note = None

    # --- render ---
    lines = []
    lines.append("Provenance -- will this open on my machine?")
    lines.append("  Entry: {0}".format(title))
    lines.append("  Components: {0}".format(count_text))

    if assemblies_known:
        lines.append("  Plugin assemblies ({0}):".format(len(assemblies)))
    else:
        lines.append("  Plugin assemblies (?):")
    if not assemblies_known:
        lines.append("    (unknown -- plugin requirements not detected for this entry)")
    elif not assemblies:
        lines.append("    (none detected -- native components only)")
    else:
        for plugin in assemblies:
            if not installed_checked:
                flag = ""
            elif _is_installed(plugin, installed):
                flag = "  [installed]"
            else:
                flag = "  [NOT INSTALLED]"
            lines.append("    - {0}{1}".format(plugin, flag))

    lines.append("  Third-party components ({0}):".format(len(third_party)))
    if third_party:
        for kind in third_party:
            lines.append("    - {0}".format(kind))
        if third_party_note:
            lines.append("    ({0})".format(third_party_note))
    else:
        lines.append("    (unknown -- plugin requirements not detected for this entry)")

    params = entry.get("parameters") or []
    inputs = sum(1 for p in params
                 if isinstance(p, dict) and str(_param_group(p)).lower() == "inputs")
    outputs = sum(1 for p in params
                  if isinstance(p, dict) and str(_param_group(p)).lower() == "outputs")
    lines.append("  Top-level params: {0} inputs, {1} outputs".format(inputs, outputs))

    RHINO_FORMS.notification(
        title="Library Provenance",
        main_text=title,
        sub_text="\n".join(lines),
        width=640,
        height=520)


if __name__ == "__main__":
    library_provenance()
