__title__ = "LibraryViews"
__doc__ = """Saved named filtered views of the local library catalog.

Key Features:
- Save the current search (free text + tag:/category:/author: chips) as a named view
  (author: chips match the sidecar author; the shared lib has no author facet)
- Apply a saved view to filter the catalog
- Delete saved views; views persist in the library settings

Ports EnneadTab-For-Grasshopper#32 (bookmarkable filtered views)."""
__is_popular__ = False
import rhinoscriptsyntax as rs
import scriptcontext as sc

import os
import sys
import json

_rhino_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_library_dir = os.path.join(_rhino_folder, "Library")
if _library_dir not in sys.path:
    sys.path.append(_library_dir)

try:
    import catalog
except ImportError:
    catalog = None

from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE


_FACET_KEYS = ("tag", "category", "author")

_MISSING_LIB_TEXT = ("The shared library module (Apps/_rhino/Library/catalog.py) is not "
                     "installed yet. This button needs the shared-catalog-lib PR "
                     "(sen/osrhino-shared-catalog-lib) merged first.")


def _tokenize(text):
    tokens = []
    current = []
    in_quotes = False
    for ch in text:
        if ch == '"':
            in_quotes = not in_quotes
            continue
        if not in_quotes and ch.isspace():
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


def _parse_facets(text):
    chips = []
    free = []
    for token in _tokenize(text or ""):
        colon = token.find(":")
        key = token[:colon].strip().lower() if colon > 0 else ""
        value = token[colon + 1:].strip() if colon > 0 else ""
        if colon > 0 and colon < len(token) - 1 and key in _FACET_KEYS and value:
            chips.append((key, value))
        else:
            free.append(token)
    tags = [value for key, value in chips if key == "tag"]
    category = None
    author = None
    for key, value in chips:
        if key == "category":
            category = value
        elif key == "author":
            author = value
    lib_facets = {"tag": tags, "category": [category] if category else []}
    free_text = " ".join(free) if free else None
    return free_text, lib_facets, author


def _entry_author(entry):
    try:
        sidecar = catalog.load_sidecar(entry)
    except Exception:
        return ""
    if not isinstance(sidecar, dict):
        return ""
    for key in ("author", "Author"):
        value = sidecar.get(key)
        if value:
            return str(value)
    return ""


def _apply_author_filter(results, author):
    if not author:
        return results
    wanted = author.lower()
    return [entry for entry in results if wanted in _entry_author(entry).lower()]


def _get_views(settings):
    prefs = settings.get("rhino", {})
    views = prefs.get("views", {})
    if not isinstance(views, dict):
        return {}
    return views


def _save_views(settings, settings_path, views):
    prefs = settings.get("rhino", {})
    prefs["views"] = views
    settings["rhino"] = prefs
    folder = os.path.dirname(settings_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(settings_path, "w") as handle:
        json.dump(settings, handle, indent=2, sort_keys=True)


def _display_line(entry):
    title = entry.get("title") or "(untitled)"
    category = entry.get("category") or "Uncategorized"
    return "[{0}] {1}".format(category, title)


def _apply_view(entries, name, query):
    free_text, lib_facets, author = _parse_facets(query)
    results = _apply_author_filter(
        list(catalog.search_entries(entries, query=free_text, facets=lib_facets)),
        author)
    if not results:
        RHINO_FORMS.notification(main_text="View '{0}' matches no entries.".format(name))
        return
    lines = [_display_line(entry) for entry in results]
    RHINO_FORMS.select_from_list(lines,
                                 title="EnneadTab Library Views",
                                 message="View '{0}': {1} match(es) for '{2}'.".format(name, len(results), query or "(whole catalog)"),
                                 button_names=["Done"],
                                 multi_select=False)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_views():
    if catalog is None:
        RHINO_FORMS.notification(main_text=_MISSING_LIB_TEXT)
        return

    try:
        index_path, settings_path = catalog.find_catalog_paths()
        entries = list(catalog.iter_entries(catalog.load_index(index_path)))
        settings = catalog.load_settings(settings_path) or {}
    except Exception as ex:
        RHINO_FORMS.notification(main_text="Could not load the library index: {0}".format(ex))
        return

    if not entries:
        RHINO_FORMS.notification(main_text="The library index has no entries.")
        return

    views = _get_views(settings)
    action = RHINO_FORMS.select_from_list(["Apply a saved view",
                                           "Save a new view",
                                           "Delete saved views"],
                                          title="EnneadTab Library Views",
                                          message="{0} saved view(s)".format(len(views)),
                                          button_names=["Go"],
                                          multi_select=False)
    if not action:
        return

    if action[0] == "Save a new view":
        name = rs.GetString("Name for this view")
        if name is None:
            return
        name = name.strip()
        if not name:
            RHINO_FORMS.notification(main_text="View name cannot be empty.")
            return
        query = rs.GetString("Search query for this view (tag:/category:/author: chips allowed; blank = whole catalog)")
        if query is None:
            return
        overwritten = name in views
        views[name] = query.strip()
        try:
            _save_views(settings, settings_path, views)
        except Exception as ex:
            RHINO_FORMS.notification(main_text="Could not save the view: {0}".format(ex))
            return
        RHINO_FORMS.notification(main_text="View '{0}' saved{1}.".format(name, " (overwrote existing)" if overwritten else ""))
        return

    if not views:
        RHINO_FORMS.notification(main_text="No saved views yet. Save one first.")
        return

    names = sorted(views.keys())
    if action[0] == "Apply a saved view":
        picked = RHINO_FORMS.select_from_list(names,
                                              title="EnneadTab Library Views",
                                              message="Pick a view to apply",
                                              button_names=["Apply"],
                                              multi_select=False)
        if not picked:
            return
        try:
            _apply_view(entries, picked[0], views[picked[0]])
        except Exception as ex:
            RHINO_FORMS.notification(main_text="Could not apply the view: {0}".format(ex))
        return

    # Delete saved views
    picked = RHINO_FORMS.select_from_list(names,
                                          title="EnneadTab Library Views",
                                          message="Pick view(s) to delete",
                                          button_names=["Delete"],
                                          multi_select=True)
    if not picked:
        return
    for name in picked:
        views.pop(name, None)
    try:
        _save_views(settings, settings_path, views)
    except Exception as ex:
        RHINO_FORMS.notification(main_text="Could not delete the view(s): {0}".format(ex))
        return
    RHINO_FORMS.notification(main_text="Deleted {0} view(s).".format(len(picked)))


if __name__ == "__main__":
    library_views()
