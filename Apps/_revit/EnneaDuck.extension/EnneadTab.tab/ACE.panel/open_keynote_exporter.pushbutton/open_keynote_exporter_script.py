#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Open the Keynote Exporter -- now a standalone web service.

The Keynote Exporter has been extracted from EnneadTab-OS into its own product at
https://enneadtab.com/keynote-exporter. This button opens it in your browser; the old
bundled .exe was retired to shrink the repo. Revit stays open and your model is untouched."""
__title__ = "Open Keynote Exporter"

import proDUCKtion # pyright: ignore 
proDUCKtion.validify()

import webbrowser

from EnneadTab import ERROR_HANDLE, LOG
from EnneadTab.REVIT import REVIT_APPLICATION
from Autodesk.Revit import DB # pyright: ignore 

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def open_keynote_exporter(doc):
    # Keynote Exporter is now the standalone service EnneadTab-KeynoteExporter
    # (enneadtab.com/keynote-exporter). The legacy bundled .exe was cut from
    # EnneadTab-OS to shrink the repo; this button now redirects to the web service.
    webbrowser.open("https://enneadtab.com/keynote-exporter")



################## main code below #####################
if __name__ == "__main__":
    open_keynote_exporter(DOC)







