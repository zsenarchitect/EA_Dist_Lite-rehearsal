__title__ = "Block Fidelity"
__doc__ = """Classify blocks as embedded, linked, or proxy and stamp them into document user text.

Why this matters: Grasshopper definitions behave very differently against block-heavy models depending on whether their components round-trip blocks (names, materials, user strings, GUIDs preserved) or silently explode instances to raw geometry. This tool gives you the block side of that picture: which definitions are safe to edit here, and which are proxies pointing at missing files.

Features:
- Classifies all block definitions (embedded / linked / proxy)
- Shows a report with counts per class
- Stamps each block's fidelity into document user text (ET_BlockFidelity:<name>) so the GH library catalog can read it

Rhino-side companion to the GH library's block-fidelity badge (feature 19).
"""
__is_popular__ = False

import os

import rhinoscriptsyntax as rs

from EnneadTab import ERROR_HANDLE, LOG
from EnneadTab.RHINO import RHINO_FORMS

USER_TEXT_PREFIX = "ET_BlockFidelity:"


def _classify(name):
    """embedded: stored in this file. linked: external file found. proxy: linked but the source file is missing."""
    if rs.IsBlockEmbedded(name):
        return "embedded"
    path = rs.BlockPath(name)
    if path and os.path.exists(path):
        return "linked"
    return "proxy"


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def block_fidelity():
    names = rs.BlockNames()
    if not names:
        rs.MessageBox("No block definitions in this document.", buttons=0, title=__title__)
        return

    rows = sorted((name, _classify(name)) for name in names)
    counts = {}
    for _, fidelity in rows:
        counts[fidelity] = counts.get(fidelity, 0) + 1

    options = ["[{}] {}".format(fidelity.upper(), name) for name, fidelity in rows]
    choice = RHINO_FORMS.select_from_list(
        options,
        title=__title__,
        message="{} block definition(s): {} embedded, {} linked, {} proxy. Pick one to inspect, or Cancel to finish.".format(
            len(rows),
            counts.get("embedded", 0),
            counts.get("linked", 0),
            counts.get("proxy", 0)))
    if choice is not None:
        name, fidelity = rows[options.index(choice)]
        rs.MessageBox(
            "Block '{}' is {}.\n{}".format(
                name,
                fidelity.upper(),
                {
                    "embedded": "Geometry lives in this file; safe to explode and re-make.",
                    "linked": "References an external file; edits belong in the source file.",
                    "proxy": "The linked source file is MISSING; resolve it before editing.",
                }[fidelity]),
            buttons=0,
            title=__title__)

    if rs.MessageBox(
            "Stamp the fidelity of {} block definition(s) into document user text (ET_BlockFidelity:<name>)?".format(len(rows)),
            buttons=4,
            title=__title__) != 6:
        return

    for name, fidelity in rows:
        rs.SetDocumentUserText(USER_TEXT_PREFIX + name, fidelity)
    print("Stamped {} block fidelities into document user text.".format(len(rows)))


if __name__ == "__main__":
    block_fidelity()
