__title__ = "Expected Host"
__doc__ = """Record which host document this Rhino model expects Grasshopper definitions to run against.

Definitions that drive the active Rhino document, a linked file (worksession attachment or model link), or an external host (Rhino.Inside.Revit) are not interchangeable. This tool stores the expectation in the document's user text (key ET_ExpectedHost) so the GH library explorer can hide definitions that don't match the current session.

Choices: activeRhinoDocument, linkedFile, externalHost, hostAgnostic.

Rhino-side companion to the GH library's host-model driver mode (feature 20).
"""
__is_popular__ = False

import rhinoscriptsyntax as rs

from EnneadTab import ERROR_HANDLE, LOG
from EnneadTab.RHINO import RHINO_FORMS

USER_TEXT_KEY = "ET_ExpectedHost"
OPTIONS = [
    ("activeRhinoDocument", "active Rhino document"),
    ("linkedFile", "linked file (worksession attachment or model link)"),
    ("externalHost", "external host (Rhino.Inside.Revit)"),
    ("hostAgnostic", "host-agnostic (works anywhere)"),
]


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def expected_host():
    current = rs.GetDocumentUserText(USER_TEXT_KEY) or ""
    labels = ["{} - {}".format(value, label) for value, label in OPTIONS]
    choice = RHINO_FORMS.select_from_list(
        labels,
        title=__title__,
        message="Current value: {}. Pick the expected host document:".format(
            current if current else "(not set)"))
    if choice is None:
        return

    value = choice.split(" - ")[0]
    rs.SetDocumentUserText(USER_TEXT_KEY, value)
    print("Expected host set to '{}' (document user text key {}).".format(value, USER_TEXT_KEY))
    rs.MessageBox(
        "Expected host set to '{}'.\nStored in document user text so it travels with this .3dm file.".format(value),
        buttons=0,
        title=__title__)


if __name__ == "__main__":
    expected_host()
