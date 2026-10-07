# -*- coding: utf-8 -*-
__title__ = "LibraryInsertModes"
__doc__ = """Open a catalog definition in Grasshopper -- three open modes.

Ports EnneadTab-For-Grasshopper PR #53 (insert as loose / group / cluster).
The Rhino-side equivalent of inserting into a canvas is opening the
definition in Grasshopper:

- Loose: open the .gh normally in Grasshopper.
- Grouped with model: copy the .gh into the current .3dm's folder, then open
  the copy (keeps the definition next to the model it belongs to).
- Pinned version: open a chosen pinned/versioned copy of the definition
  (sidecar "pinnedVersion", or versioned sibling files such as Foo.v2.gh).

Invocation: the Grasshopper plugin's explorer is a canvas component and
exposes no Rhino command entry point, so this button opens documents through
Grasshopper.Instances.DocumentServer.AddDocument(path, True) from Rhino
IronPython, loading the Grasshopper plug-in first with the _Grasshopper
command when it is not already loaded.

Depends on PR #283 (shared catalog lib); degrades gracefully if unmerged."""
__is_popular__ = False
import rhinoscriptsyntax as rs
import scriptcontext as sc
import os, sys, json, glob, shutil
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


_MODE_LOOSE = u"loose"
_MODE_GROUPED = u"grouped"
_MODE_PINNED = u"pinned"

_MODES = (
    (u"Open normally (loose)",
     u"Open the .gh in Grasshopper as-is.",
     _MODE_LOOSE),
    (u"Copy next to model, then open (grouped with model)",
     u"Copy the .gh into the current .3dm's folder and open the copy, "
     u"so the definition travels with the model.",
     _MODE_GROUPED),
    (u"Open a pinned version (cluster/pinned)",
     u"Pick from pinned/versioned copies of the definition instead of the "
     u"current file.",
     _MODE_PINNED),
)


def _utext(value):
    if value is None:
        return u""
    if isinstance(value, unicode):
        return value
    try:
        return unicode(value)
    except Exception:
        pass
    try:
        return str(value).decode("utf-8", "replace")
    except Exception:
        return u"?"


def _ci_get(mapping, name):
    """Case-insensitive dict read (the GH index/sidecar JSON is camelCase)."""
    if not isinstance(mapping, dict):
        return None
    wanted = name.lower()
    for key in mapping:
        try:
            if key.lower() == wanted:
                return mapping[key]
        except AttributeError:
            continue
    return None


def _entry_title(entry):
    title = _utext(entry.get("title"))
    return title if title else (_utext(entry.get("id")) or u"(untitled)")


def _open_in_grasshopper(definition_path):
    """Open a .gh in Grasshopper via the DocumentServer.

    The Grasshopper plugin's explorer is a canvas component and exposes no
    Rhino command entry point, so the Rhino-side equivalent of the GH
    insert modes is AddDocument. Returns (ok, message)."""
    try:
        import clr
    except ImportError:
        return False, u"Could not access the .NET runtime (clr)."
    try:
        clr.AddReference("Grasshopper")
    except Exception:
        # Grasshopper is not loaded in this Rhino session yet; running its
        # command loads the plug-in (this also shows the Grasshopper window).
        try:
            rs.Command("_Grasshopper", echo=False)
        except Exception as err:
            return False, u"Could not load Grasshopper: {0}".format(_utext(err))
        try:
            clr.AddReference("Grasshopper")
        except Exception as err:
            return False, (u"Grasshopper is still not available after running "
                           u"the _Grasshopper command: {0}").format(_utext(err))
    try:
        from Grasshopper import Instances
        server = Instances.DocumentServer
        if server is None:
            return False, u"Grasshopper DocumentServer is not available."
        document = server.AddDocument(definition_path, True)
    except Exception as err:
        return False, u"Could not open the definition in Grasshopper: {0}".format(_utext(err))
    if document is None:
        return False, u"Grasshopper returned no document for the file."
    return True, u""


def _find_pinned_versions(entry):
    """Discover pinned/versioned copies of a definition.

    Sources (first hit wins per source, all sources are offered):
    - the sidecar's additive "pinnedVersion" field (absolute path, or a path
      relative to the definition's folder; the GH plugin does not write this
      field yet, so it is honored forward-compatibly when present);
    - versioned sibling files next to the definition: Foo.v2.gh,
      Foo_v2.gh, Foo v2.gh, Foo-v2.gh;
    - a "versions" subfolder next to the definition containing *.gh files.

    Returns a list of (label, path) tuples, newest-looking first."""
    definition_path = _utext(entry.get("path"))
    if not definition_path:
        return []
    folder = os.path.dirname(definition_path)
    stem, ext = os.path.splitext(os.path.basename(definition_path))
    if not ext:
        ext = u".gh"
    found = []

    sidecar = catalog.load_sidecar(entry) or {}
    pinned = _utext(_ci_get(sidecar, "pinnedVersion")).strip()
    if pinned:
        pinned_path = pinned
        if not os.path.isabs(pinned_path):
            pinned_path = os.path.join(folder, pinned_path)
        if os.path.isfile(pinned_path):
            found.append((u'pinnedVersion (sidecar): {0}'.format(
                os.path.basename(pinned_path)), pinned_path))

    seen = set(os.path.normcase(p) for _label, p in found)
    patterns = [stem + u".v*.gh", stem + u"_v*.gh", stem + u" v*.gh", stem + u"-v*.gh"]
    siblings = []
    for pattern in patterns:
        try:
            siblings.extend(glob.glob(os.path.join(folder, pattern)))
        except Exception:
            continue
    versions_dir = os.path.join(folder, u"versions")
    if os.path.isdir(versions_dir):
        try:
            siblings.extend(glob.glob(os.path.join(versions_dir, u"*.gh")))
        except Exception:
            pass
    for path in sorted(siblings, reverse=True):
        try:
            norm = os.path.normcase(os.path.abspath(path))
        except Exception:
            continue
        if not os.path.isfile(path) or norm in seen:
            continue
        seen.add(norm)
        found.append((os.path.basename(path), os.path.abspath(path)))
    return found


def _resolve_grouped_copy(entry):
    """Copy the .gh into the current .3dm's folder. Returns (path, message)."""
    doc_path = rs.DocumentPath()
    doc_name = rs.DocumentName()
    if not doc_path or not doc_name:
        return None, (u"The current model has not been saved yet, so there is "
                      u"no .3dm folder to copy into. Save the model first, then "
                      u"retry 'grouped with model'.")
    definition_path = _utext(entry.get("path"))
    dest = os.path.join(doc_path, os.path.basename(definition_path))
    try:
        if os.path.abspath(dest) == os.path.abspath(definition_path):
            return dest, u""
        if os.path.isfile(dest):
            answer = rs.MessageBox(
                u"'{0}' already exists in the model folder.\n\nOverwrite it with "
                u"a fresh copy of the catalog definition?".format(
                    os.path.basename(dest)),
                buttons=4,  # Yes/No
                title=u"Library Insert Modes")
            if answer != 6:  # 6 == Yes
                return None, u"Cancelled: kept the existing copy untouched."
        shutil.copy2(definition_path, dest)
    except Exception as err:
        return None, u"Could not copy the definition: {0}".format(_utext(err))
    return dest, u""


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_insert_modes():
    if catalog is None:
        rs.MessageBox(_MISSING_LIB_TEXT); return

    index_path, _settings_path = catalog.find_catalog_paths()
    if not index_path:
        rs.MessageBox(u"No Grasshopper library index was found.\n\n"
                      u"Expected %LOCALAPPDATA%\\EnneadTab\\Grasshopper\\library-index.json "
                      u"(written by the EnneadTab for Grasshopper plugin's Refresh), or set "
                      u"ENNEAD_LIBRARY_INDEX to point at one.")
        return
    entries = catalog.iter_entries(catalog.load_index(index_path))
    # Insert/open needs a readable source file -- mirrors the GH explorer,
    # which enables Add-to-canvas only for entries with a source file.
    entries = [e for e in entries
               if _utext(e.get("path")) and os.path.isfile(_utext(e.get("path")))]
    if not entries:
        rs.MessageBox(u"The library index has no entries with a readable "
                      u"definition file.")
        return
    entries = catalog.sort_entries(entries, key="title", direction="asc")

    labels = [_entry_title(e) for e in entries]
    picked = RHINO_FORMS.select_from_list(
        labels,
        title=u"Library Insert Modes",
        message=u"Pick a catalog entry to open in Grasshopper.",
        button_names=[u"Next"],
        width=650,
        height=550,
        multi_select=False)
    if not picked:
        return
    entry = entries[labels.index(picked)]

    mode_labels = [u"{0}\n    {1}".format(label, desc) for label, desc, _mode in _MODES]
    picked_mode = RHINO_FORMS.select_from_list(
        mode_labels,
        title=u"Library Insert Modes",
        message=u"How should '{0}' be opened in Grasshopper?".format(_entry_title(entry)),
        button_names=[u"Open"],
        width=650,
        height=420,
        multi_select=False)
    if not picked_mode:
        return
    mode = _MODES[mode_labels.index(picked_mode)][2]

    target_path = _utext(entry.get("path"))
    note = u""
    if mode == _MODE_GROUPED:
        target_path, note = _resolve_grouped_copy(entry)
        if not target_path:
            rs.MessageBox(note, title=u"Library Insert Modes")
            return
    elif mode == _MODE_PINNED:
        candidates = _find_pinned_versions(entry)
        if not candidates:
            rs.MessageBox(u"No pinned or versioned copies found for '{0}'.\n\n"
                          u"Looked for a sidecar \"pinnedVersion\" field, versioned "
                          u"siblings (Foo.v2.gh, Foo_v2.gh, ...) and a versions/ "
                          u"subfolder next to the definition.".format(_entry_title(entry)),
                          title=u"Library Insert Modes")
            return
        candidate_labels = [label for label, _path in candidates]
        picked_candidate = RHINO_FORMS.select_from_list(
            candidate_labels,
            title=u"Library Insert Modes",
            message=u"Pick the pinned version to open.",
            button_names=[u"Open"],
            width=650,
            height=420,
            multi_select=False)
        if not picked_candidate:
            return
        target_path = candidates[candidate_labels.index(picked_candidate)][1]

    ok, message = _open_in_grasshopper(target_path)
    if not ok:
        rs.MessageBox(message, title=u"Library Insert Modes")
        return
    mode_word = { _MODE_LOOSE: u"normally",
                  _MODE_GROUPED: u"as a copy next to the model",
                  _MODE_PINNED: u"pinned version" }[mode]
    done = u"Opened '{0}' in Grasshopper ({1}).".format(
        os.path.basename(target_path), mode_word)
    if note:
        done += u"\n" + note
    rs.MessageBox(done, title=u"Library Insert Modes")


library_insert_modes()
