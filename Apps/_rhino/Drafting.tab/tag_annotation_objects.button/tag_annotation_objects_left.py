__title__ = "TagAnnotationObjects"
__doc__ = """Count and tag annotation objects in the active document.

Key Features:
- Counts dimensions, hatches, text, leaders and text dots
- Optionally stamps each with user text (EnneadTab_AnnotationKind)
- One-click audit of drawing/documentation outputs"""
__is_popular__ = False

import rhinoscriptsyntax as rs
import scriptcontext as sc
import Rhino

from EnneadTab import LOG, ERROR_HANDLE

USER_TEXT_KEY = "EnneadTab_AnnotationKind"

ANNOTATION_KINDS = (
    (Rhino.DocObjects.DimensionObject, "Dimensions"),
    (Rhino.DocObjects.HatchObject, "Hatches"),
    (Rhino.DocObjects.TextObject, "Text"),
    (Rhino.DocObjects.LeaderObject, "Leaders"),
    (Rhino.DocObjects.TextDotObject, "TextDots"),
)


def get_annotation_kind(object_id):
    rhino_object = sc.doc.Objects.Find(object_id)
    if rhino_object is None:
        return None
    for object_class, kind in ANNOTATION_KINDS:
        if isinstance(rhino_object, object_class):
            return kind
    return None


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def tag_annotation_objects():
    guids = rs.AllObjects()
    if not guids:
        rs.MessageBox("No objects in the active document.", 0, __title__)
        return

    counts = {}
    by_kind = {}
    for guid in guids:
        kind = get_annotation_kind(guid)
        if kind is None:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        by_kind.setdefault(kind, []).append(guid)

    if not counts:
        rs.MessageBox(
            "No annotation objects (dimensions, hatches, text, leaders, text dots) found.",
            0,
            __title__)
        return

    lines = ["Annotation objects in active document:", ""]
    for kind in sorted(counts):
        lines.append("  {0}: {1}".format(kind, counts[kind]))
    lines.append("")
    lines.append("Total: {0}".format(sum(counts.values())))
    report = "\n".join(lines)

    stamp = rs.MessageBox(
        report + "\n\nStamp each with user text '{0}'?".format(USER_TEXT_KEY),
        4,
        __title__)
    if stamp != 6:  # 6 = Yes
        return

    stamped = 0
    for kind in by_kind:
        for guid in by_kind[kind]:
            rs.SetUserText(guid, USER_TEXT_KEY, kind)
            stamped += 1

    rs.MessageBox(
        "Stamped {0} annotation objects with '{1}'.".format(stamped, USER_TEXT_KEY),
        0,
        __title__)


if __name__ == "__main__":
    tag_annotation_objects()
