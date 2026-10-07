__title__ = "LibraryAiBadges"
__doc__ = """Show the AI enrichment badge for a catalog entry.

Key Features:
- AI description, tags, category and confidence from the sidecar
- Display only: never calls an AI service
- Flags low-confidence entries queued for human review"""
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


# Mirrors GH LibraryEnrichmentReview.LowConfidenceThreshold (GH PR #40):
# confidence at or below 0.8 is queued for human review.
_LOW_CONFIDENCE_THRESHOLD = 0.8


def _get_sidecar(entry):
    try:
        sidecar = _catalog.load_sidecar(entry)
    except Exception:
        sidecar = None
    if not isinstance(sidecar, dict):
        sidecar = entry.get("sidecar")
    return sidecar if isinstance(sidecar, dict) else {}


def _format_badge(entry, sidecar):
    # Mirrors GH LibraryEnrichmentPresentation.FormatCategoryBadge:
    # AI category preferred, entry category as fallback, plus a
    # confidence marker. ASCII-only markers ([OK]/[REVIEW]) because the
    # repo's ironpython gate forbids non-ASCII bytes.
    ai_category = sidecar.get("aiCategory") or ""
    category = (ai_category or entry.get("category") or "").strip()
    confidence = sidecar.get("aiConfidence")
    if confidence is None:
        return category
    try:
        confident = float(confidence) > _LOW_CONFIDENCE_THRESHOLD
    except (TypeError, ValueError):
        confident = False
    marker = "[OK]" if confident else "[REVIEW]"
    if category:
        return "{0} {1}".format(category, marker)
    return marker


def _format_details(entry, sidecar):
    title = entry.get("title") or entry.get("id") or "?"
    description = sidecar.get("aiDescription")
    if not description:
        return ("{0}\n\n"
                "No AI enrichment recorded for this entry yet.".format(title))

    tags = sidecar.get("aiTags") or []
    tags = [str(t) for t in tags if t]
    confidence = sidecar.get("aiConfidence")

    lines = [title, ""]
    lines.append("Category: {0}".format(_format_badge(entry, sidecar)))
    if confidence is None:
        lines.append("Confidence: (unknown)")
    else:
        try:
            lines.append("Confidence: {0:.2f}".format(float(confidence)))
        except (TypeError, ValueError):
            lines.append("Confidence: {0}".format(confidence))
    lines.append("Tags: {0}".format(", ".join(tags) if tags else "(none)"))
    lines.append("")
    lines.append("Description:")
    lines.append(str(description))

    try:
        low = confidence is not None and \
            float(confidence) <= _LOW_CONFIDENCE_THRESHOLD
    except (TypeError, ValueError):
        low = False
    if low:
        lines.append("")
        lines.append("Note: low confidence -- queued for human review.")
    return "\n".join(lines)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def library_ai_badges():
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

    options = []
    by_label = {}
    for entry in entries:
        sidecar = _get_sidecar(entry)
        badge = _format_badge(entry, sidecar)
        title = entry.get("title") or entry.get("id") or "?"
        if sidecar.get("aiDescription"):
            label = "{0}  <{1}>".format(title, badge)
        else:
            label = "{0}  <no AI enrichment>".format(title)
        # Labels must stay unique even when titles collide.
        suffix = 2
        unique_label = label
        while unique_label in by_label:
            unique_label = "{0} ({1})".format(label, suffix)
            suffix += 1
        options.append(unique_label)
        by_label[unique_label] = entry

    picked = RHINO_FORMS.select_from_list(
        options,
        title="EnneadTab Library AI Badges",
        message="Pick an entry to see its AI enrichment badge.",
        button_names=["Show badge"],
        multi_select=False)
    if not picked:
        return

    entry = by_label.get(picked)
    if entry is None:
        return
    rs.MessageBox(_format_details(entry, _get_sidecar(entry)),
                  buttons=0, title=__title__)


if __name__ == "__main__":
    library_ai_badges()
