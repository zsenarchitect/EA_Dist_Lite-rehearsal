__title__ = "LibraryPurposeNotes"
__doc__ = """View and edit purpose notes for library definitions, keyed by document GUID.

Key Features:
- Pick a catalog entry and view its stored purpose note
- Edit the note; it is saved back into the entry's .ennead.json sidecar under an
  additive "purposeNotes" key, keyed by document GUID ("doc:<guid>" when the
  definition file is readable, "file:<path>" fallback) -- existing sidecar keys
  are never renamed or touched
- Note schema mirrors the GH definition-notes.json format:
  {"purposeNotes": {"doc:<guid>": {"text": "...", "updatedAt": "..."}}}

Ports EnneadTab-For-Grasshopper#55 (purpose notes keyed by document GUID)."""
__is_popular__ = False
import rhinoscriptsyntax as rs
import scriptcontext as sc
import os
import sys
import json
import datetime
try:
    import xml.etree.ElementTree as ET
except ImportError:
    ET = None
_rhino_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_library_dir = os.path.join(_rhino_folder, "Library")
if _library_dir not in sys.path: sys.path.append(_library_dir)
try:
    import catalog
except ImportError:
    catalog = None
from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE
_MISSING_LIB_TEXT = ("The shared library module (Apps/_rhino/Library/catalog.py) is not installed yet. "
                     "This button needs the shared-catalog-lib PR #283 (branch sen/osrhino-shared-catalog-lib) merged first.")
_NOTES_KEY = "purposeNotes"


def _display_line(entry):
    title = entry.get("title") or "(untitled)"
    category = entry.get("category") or "Uncategorized"
    return "[{0}] {1}".format(category, title)


def _read_ghx_document_id(ghx_path):
    """Minimal .ghx reader for the stable document key: the DocumentID item of
    the Definition chunk, or None when missing/unreadable. Mirrors the GH
    GhxDocumentKeyReader (borrow55)."""
    if ET is None:
        return None
    try:
        tree = ET.parse(ghx_path)
    except Exception:
        return None
    try:
        root = tree.getroot()
        for chunk in root.iter("chunk"):
            if (chunk.get("name") or "") != "Definition":
                continue
            for item in chunk.iter("item"):
                if (item.get("name") or "").lower() == "documentid":
                    text = (item.text or "").strip()
                    if text:
                        return text
    except Exception:
        return None
    return None


def _resolve_document_key(entry):
    """Stable document key for purpose notes: "doc:<guid>" when the definition
    file is readable, else a "file:<path>" fallback so notes still work for
    missing or unreadable files. Mirrors the GH DefinitionKeyResolver."""
    path = entry.get("path") or ""
    if path and os.path.isfile(path):
        doc_id = None
        try:
            if path.lower().endswith(".ghx"):
                doc_id = _read_ghx_document_id(path)
            # .gh binary archives are not parsed here; the path fallback covers them.
        except Exception:
            doc_id = None
        if doc_id:
            return "doc:" + doc_id
    return "file:" + (path if path else (entry.get("id") or ""))


def _sidecar_path(entry):
    path = entry.get("path") or ""
    if not path:
        return None
    return path + ".ennead.json"


def _get_notes(sidecar):
    notes = sidecar.get(_NOTES_KEY)
    if not isinstance(notes, dict):
        return {}
    return notes


def _save_notes(entry, sidecar, notes):
    sidecar_path = _sidecar_path(entry)
    if not sidecar_path:
        return False
    sidecar[_NOTES_KEY] = notes
    folder = os.path.dirname(sidecar_path)
    try:
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(sidecar_path, "w") as handle:
            json.dump(sidecar, handle, indent=2, sort_keys=True)
        return True
    except Exception:
        return False


def _pick_entry(entries):
    query = rs.GetString("Search library definitions (blank = show all)")
    if query is None:
        return None
    results = list(catalog.search_entries(entries, query=query.strip() or None))
    if not results:
        RHINO_FORMS.notification(main_text="No library definitions match the search.")
        return None
    lines = [_display_line(entry) for entry in results]
    picked = RHINO_FORMS.select_from_list(lines,
                                          title="EnneadTab Library Purpose Notes",
                                          message="Pick a definition to view its purpose note",
                                          button_names=["Pick"],
                                          multi_select=False)
    if not picked:
        return None
    return results[lines.index(picked[0])]


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_purpose_notes():
    if catalog is None:
        rs.MessageBox(_MISSING_LIB_TEXT)
        return

    try:
        index_path, _ = catalog.find_catalog_paths()
        entries = list(catalog.iter_entries(catalog.load_index(index_path)))
    except Exception as ex:
        RHINO_FORMS.notification(main_text="Could not load the library index: {0}".format(ex))
        return

    if not entries:
        RHINO_FORMS.notification(main_text="The library index has no entries.")
        return

    entry = _pick_entry(entries)
    if entry is None:
        return

    try:
        sidecar = catalog.load_sidecar(entry)
    except Exception:
        sidecar = {}
    if not isinstance(sidecar, dict):
        sidecar = {}

    key = _resolve_document_key(entry)
    notes = _get_notes(sidecar)
    current = notes.get(key)
    current_text = current.get("text") if isinstance(current, dict) else ""
    if not current_text:
        current_text = ""

    title = entry.get("title") or "(untitled)"
    message = "Key: {0}\n\n{1}".format(key, current_text if current_text else "(no purpose note yet)")
    actions = ["Edit note"]
    if current_text:
        actions.append("Delete note")
    action = RHINO_FORMS.select_from_list(actions,
                                          title="EnneadTab Library Purpose Notes",
                                          message="Purpose note for '{0}'.\n\n{1}".format(title, message),
                                          button_names=["Go"],
                                          multi_select=False)
    if not action:
        return

    if action[0] == "Delete note":
        confirmed = RHINO_FORMS.notification(title="EnneadTab Library Purpose Notes",
                                             main_text="Delete the purpose note for '{0}'?".format(title),
                                             button_name="Delete")
        if not confirmed:
            return
        notes.pop(key, None)
        if _save_notes(entry, sidecar, notes):
            RHINO_FORMS.notification(main_text="Purpose note deleted.")
        else:
            RHINO_FORMS.notification(main_text="Could not write the sidecar file.")
        return

    # Edit note
    try:
        new_text = rs.EditBox(current_text,
                              "Purpose note for '{0}' (key: {1})".format(title, key),
                              "EnneadTab Library Purpose Notes")
    except Exception:
        new_text = rs.GetString("Purpose note for '{0}'".format(title), current_text)
    if new_text is None:
        return
    new_text = new_text.strip()
    if not new_text:
        RHINO_FORMS.notification(main_text="Note is empty; nothing was saved. Use 'Delete note' to remove an existing note.")
        return
    notes[key] = {"text": new_text,
                  "updatedAt": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}
    if _save_notes(entry, sidecar, notes):
        RHINO_FORMS.notification(main_text="Purpose note saved for '{0}'.".format(title))
    else:
        RHINO_FORMS.notification(main_text="Could not write the sidecar file.")

library_purpose_notes()
