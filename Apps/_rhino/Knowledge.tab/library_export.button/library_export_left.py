__title__ = "LibraryExport"
__doc__ = """Export the filtered library catalog to a portable JSON file.

Key Features:
- Optional filter: free text plus tag:/category:/author: facet chips
- Portable shape: id, title, sourcePath, tags, category, parameters
- Save dialog; creates parent folders; UTF-8 JSON

Ports EnneadTab-For-Grasshopper#16 (catalog export)."""
__is_popular__ = False
import rhinoscriptsyntax as rs
import scriptcontext as sc

import os
import sys
import json
import datetime

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


def _safe_sidecar(entry):
    try:
        sidecar = catalog.load_sidecar(entry)
    except Exception:
        return None
    if not isinstance(sidecar, dict):
        return None
    return sidecar


def _export_row(entry):
    parameters = []
    raw_params = entry.get("parameters") or []
    if not raw_params:
        sidecar = _safe_sidecar(entry)
        if sidecar:
            raw_params = sidecar.get("parameters") or []
    for param in raw_params:
        if isinstance(param, dict):
            parameters.append({"name": param.get("name"), "type": param.get("type")})
    return {
        "id": entry.get("id"),
        "title": entry.get("title"),
        "sourcePath": entry.get("path"),
        "tags": list(entry.get("tags") or []),
        "category": entry.get("category"),
        "parameters": parameters,
    }


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_export():
    if catalog is None:
        RHINO_FORMS.notification(main_text=_MISSING_LIB_TEXT)
        return

    try:
        index_path, _settings_path = catalog.find_catalog_paths()
        entries = list(catalog.iter_entries(catalog.load_index(index_path)))
    except Exception as ex:
        RHINO_FORMS.notification(main_text="Could not load the library index: {0}".format(ex))
        return

    if not entries:
        RHINO_FORMS.notification(main_text="The library index has no entries to export.")
        return

    query = rs.GetString("Export filter (tag:/category:/author: chips allowed; blank = whole catalog)")
    if query is None:
        return

    free_text, lib_facets, author = _parse_facets(query)
    try:
        results = _apply_author_filter(
            list(catalog.search_entries(entries, query=free_text, facets=lib_facets)),
            author)
    except Exception as ex:
        RHINO_FORMS.notification(main_text="Search failed: {0}".format(ex))
        return

    document = {
        "exportedAt": datetime.datetime.utcnow().isoformat() + "Z",
        "entries": [_export_row(entry) for entry in results],
    }

    filename = rs.SaveFileName("Export filtered catalog",
                               "JSON files (*.json)|*.json||",
                               filename="ennead-library-catalog.json")
    if not filename:
        return

    try:
        folder = os.path.dirname(filename)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(filename, "w") as handle:
            handle.write(json.dumps(document, indent=2, sort_keys=True))
    except Exception as ex:
        RHINO_FORMS.notification(main_text="Export failed: {0}".format(ex))
        return

    count = len(document["entries"])
    RHINO_FORMS.notification(main_text="Exported {0} entr{1} to {2}.".format(count, "y" if count == 1 else "ies", filename))


if __name__ == "__main__":
    library_export()
