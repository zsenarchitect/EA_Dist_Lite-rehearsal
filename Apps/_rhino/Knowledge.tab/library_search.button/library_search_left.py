__title__ = "LibrarySearch"
__doc__ = """Search the local library catalog with faceted chips.

Key Features:
- One search box: free text plus tag:/category:/author: facet chips
- Quoted values supported, e.g. tag:"panel unit"
- Unknown key:value tokens are kept as free text, never dropped
- author: chips match the sidecar author (the shared lib has no author facet)

Ports EnneadTab-For-Grasshopper#35 (faceted search)."""
__is_popular__ = True
import rhinoscriptsyntax as rs
import scriptcontext as sc

import os
import sys

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
    """Whitespace-split keeping quoted spans together (quotes stripped)."""
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
    """Mirror of GH LibraryFacetQuery.Parse, adapted to the shared lib.

    Returns (free_text, lib_facets, author):
    - known chips (tag:/category:/author:) are pulled out; the rest stays free text
    - lib_facets = {"tag": [...], "category": [...]} for catalog.search_entries
      (OR-within each list, exact case-insensitive match, per the shared lib)
    - author: has no lib support, so it is returned separately and applied
      client-side as a case-insensitive substring match on the sidecar author
      (mirrors GH PR #35 semantics)
    """
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


def _facet_summary(lib_facets, author):
    parts = []
    for tag in lib_facets.get("tag", []):
        parts.append("tag:" + tag)
    for category in lib_facets.get("category", []):
        parts.append("category:" + category)
    if author:
        parts.append("author:" + author)
    return " ".join(parts)


def _display_line(entry):
    title = entry.get("title") or "(untitled)"
    category = entry.get("category") or "Uncategorized"
    return "[{0}] {1}".format(category, title)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_search():
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
        RHINO_FORMS.notification(main_text="The library index has no entries to search.")
        return

    query = rs.GetString("Library search (tag:/category:/author: chips allowed, blank = all entries)")
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

    if not results:
        RHINO_FORMS.notification(main_text="No entries match '{0}'.".format(query))
        return

    summary = _facet_summary(lib_facets, author)
    message = "{0} match(es)".format(len(results))
    if summary:
        message += " | facets: " + summary
    lines = [_display_line(entry) for entry in results]
    RHINO_FORMS.select_from_list(lines,
                                 title="EnneadTab Library Search",
                                 message=message,
                                 button_names=["Done"],
                                 multi_select=False)


if __name__ == "__main__":
    library_search()
