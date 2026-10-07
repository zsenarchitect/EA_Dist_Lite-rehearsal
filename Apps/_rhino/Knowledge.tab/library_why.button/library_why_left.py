__title__ = "LibraryWhy"
__doc__ = """Explain why a catalog search hit matches.

Key Features:
- Shows which fields and terms matched each hit
- One line per hit, e.g. matches via tag 'nesting' and title 'panel'
- Mirrors the Grasshopper match-explanation wording"""
__is_popular__ = False

import os
import sys

import rhinoscriptsyntax as rs # pyright: ignore
import scriptcontext as sc # pyright: ignore

from EnneadTab.RHINO import RHINO_FORMS
from EnneadTab import LOG, ERROR_HANDLE


# Shared catalog lib (PR #283 sen/osrhino-shared-catalog-lib):
# Apps/_rhino/Library/catalog.py. The documented import is
# "from Library import catalog"; Apps/_rhino is added to sys.path here
# because the lib PR does not touch startup.py.
_RHINO_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if _RHINO_DIR not in sys.path:
    sys.path.insert(0, _RHINO_DIR)
try:
    from Library import catalog as _catalog # pyright: ignore
except ImportError:
    # Fallback for a flat layout: import catalog.py directly.
    _LIBRARY_DIR = os.path.join(_RHINO_DIR, "Library")
    if _LIBRARY_DIR not in sys.path:
        sys.path.insert(0, _LIBRARY_DIR)
    import catalog as _catalog # pyright: ignore


def _contains(haystack, needle):
    # Case-insensitive contains, like GH's ReasonForToken.
    return bool(haystack) and needle.lower() in haystack.lower()


def _reason_for_token(entry, token):
    # Field priority mirrors GH LibraryMatchExplanation.ReasonForToken:
    # tag, title, category, description, parameter name, then path.
    # (The GH version also checks author; the shared catalog entry dict
    # carries no author field, so that reason is not available here.)
    for tag in entry.get("tags") or []:
        if _contains(tag, token):
            return "tag '{0}'".format(token)
    if _contains(entry.get("title"), token):
        return "title '{0}'".format(token)
    if _contains(entry.get("category"), token):
        return "category '{0}'".format(token)
    if _contains(entry.get("description"), token):
        return "description '{0}'".format(token)
    for param in entry.get("parameters") or []:
        name = param.get("name") if isinstance(param, dict) else None
        if _contains(name, token):
            return "parameter '{0}'".format(name)
    if _contains(entry.get("path"), token):
        return "path '{0}'".format(token)
    return None


def _add_unique(reasons, reason):
    if reason not in reasons:
        reasons.append(reason)


def _split_query(query):
    # Split "tag:xxx" / "category:yyy" chips (the facet syntax the shared
    # lib's search_entries understands, like GH PR #35) from plain keyword
    # tokens. Returns (keyword_query, facets).
    facets = {"tag": [], "category": []}
    tokens = []
    for raw in (query or "").split():
        lowered = raw.lower()
        if lowered.startswith("tag:") and len(raw) > 4:
            value = raw[4:].strip()
            if value:
                facets["tag"].append(value)
        elif lowered.startswith("category:") and len(raw) > 9:
            value = raw[9:].strip()
            if value:
                facets["category"].append(value)
        else:
            tokens.append(raw)
    return " ".join(tokens), facets


def _explain_match(entry, keyword_query, facets):
    # Mirrors GH LibraryMatchExplanation.Explain: facet reasons first, then
    # one reason per keyword token (whitespace-split), highest-priority
    # matching field wins per token.
    reasons = []
    if isinstance(facets, dict):
        for value in facets.get("category") or []:
            value = (value or "").strip()
            if value:
                _add_unique(reasons, "category '{0}'".format(value))
        for value in facets.get("tag") or []:
            value = (value or "").strip()
            if value:
                _add_unique(reasons, "tag '{0}'".format(value))
    for token in (keyword_query or "").split():
        reason = _reason_for_token(entry, token)
        if reason:
            _add_unique(reasons, reason)
    if not reasons:
        return ""
    return "matches via " + " and ".join(reasons)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_why():
    index_path, _ = _catalog.find_catalog_paths()
    if not index_path or not os.path.isfile(index_path):
        rs.MessageBox("No catalog index found yet.\n"
                      "Refresh the Grasshopper library first, then try again.",
                      buttons=0, title=__title__)
        return

    entries = list(_catalog.iter_entries(_catalog.load_index(index_path)))
    if not entries:
        rs.MessageBox("The catalog index is empty.",
                      buttons=0, title=__title__)
        return

    query = rs.GetString(
        "Catalog search (tip: tag:xxx or category:yyy chips work too)")
    if query is None:
        return
    query = query.strip()
    if not query:
        rs.MessageBox("Type a search term first.",
                      buttons=0, title=__title__)
        return

    keyword_query, facets = _split_query(query)
    hits = list(_catalog.search_entries(entries,
                                        query=keyword_query,
                                        facets=facets))
    if not hits:
        rs.MessageBox("No catalog entries match '{0}'.".format(query),
                      buttons=0, title=__title__)
        return

    options = []
    by_label = {}
    for hit in hits:
        title = hit.get("title") or hit.get("id") or "?"
        label = title
        suffix = 2
        while label in by_label:
            label = "{0} ({1})".format(title, suffix)
            suffix += 1
        options.append(label)
        by_label[label] = hit

    picked = RHINO_FORMS.select_from_list(
        options,
        title="EnneadTab Library Why",
        message="{0} hit{1} for '{2}'. Pick one for its explanation.".format(
            len(hits), "" if len(hits) == 1 else "s", query),
        button_names=["Explain"],
        multi_select=False)
    if not picked:
        return

    hit = by_label.get(picked)
    if hit is None:
        return
    explanation = _explain_match(hit, keyword_query, facets)
    title = hit.get("title") or hit.get("id") or "?"
    if explanation:
        text = "{0}\n\nWhy this matches: {1}".format(title, explanation)
    else:
        text = ("{0}\n\nNo field-level reason found for these terms.\n"
                "The hit may come from a facet filter.").format(title)
    rs.MessageBox(text, buttons=0, title=__title__)


if __name__ == "__main__":
    library_why()
