# -*- coding: utf-8 -*-
"""Shared EnneadTab Grasshopper catalog reader for Rhino ports.

One implementation of the Grasshopper definition-catalog formats
(``library-index.json``, ``library-settings.json``, ``*.ennead.json``
sidecars) reused by every Rhino toolbar button that needs catalog data,
instead of each port duplicating parsing/search/sort logic.

See ``catalog.py`` for the interface and ``README.md`` for the formats,
path resolution, and dependency notes.
"""

try:
    from .catalog import (
        find_catalog_paths,
        load_index,
        load_settings,
        iter_entries,
        load_sidecar,
        search_entries,
        sort_entries,
        validate_sidecar,
    )
except ImportError:  # IronPython 2.7 fallback when imported as a top-level module
    from catalog import (
        find_catalog_paths,
        load_index,
        load_settings,
        iter_entries,
        load_sidecar,
        search_entries,
        sort_entries,
        validate_sidecar,
    )

__all__ = [
    "find_catalog_paths",
    "load_index",
    "load_settings",
    "iter_entries",
    "load_sidecar",
    "search_entries",
    "sort_entries",
    "validate_sidecar",
]
