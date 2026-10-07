__title__ = "AttachRefreshWorksession"
__doc__ = """Attach worksession files or refresh the current worksession.

Key Features:
- Lists the files currently attached to the worksession
- Attach one or more .3dm / .rws files to the current worksession
- Refresh attached worksession files in one click
- Skips files that are already attached

Mirrors the widely-shared dharman Discourse snippets
('-Worksession Attach / Refresh' via rs.Command).
"""
__is_popular__ = False

import rhinoscriptsyntax as rs
import scriptcontext as sc

from EnneadTab import LOG, ERROR_HANDLE


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def attach_refresh_worksession():
    attached = get_attached_paths()

    if attached:
        message = "Currently attached ({}):\n{}".format(
            len(attached), "\n".join(attached))
    else:
        message = "No files are currently attached to the worksession."

    action = rs.ListBox(
        ["Refresh worksession", "Attach files..."],
        message + "\n\nPick an action:",
        __title__)
    if not action:
        return

    if action == "Refresh worksession":
        refresh_worksession()
    else:
        attach_files(attached)


def get_attached_paths():
    try:
        paths = sc.doc.Worksession.ModelPaths
    except Exception:
        return []
    if not paths:
        return []
    return [str(p) for p in paths if p]


def refresh_worksession():
    ok = rs.Command("-_Worksession _Refresh _Enter", echo=False)
    if ok:
        rs.MessageBox("Worksession refreshed.", 0, __title__)
    else:
        rs.MessageBox(
            "Worksession refresh command did not complete. "
            "See the command history for details.",
            0, __title__)


def attach_files(already_attached):
    filter = "Rhino 3D Models (*.3dm)|*.3dm|Worksession (*.rws)|*.rws||"
    paths = rs.OpenFileNames("Select files to attach to the worksession", filter)
    if not paths:
        return

    known = set(p.lower() for p in already_attached)
    attached_count = 0
    skipped = []
    failed = []
    for path in paths:
        if path.lower() in known:
            skipped.append(path)
            continue
        # Quote the path so folders with spaces still work; the trailing
        # _Enter accepts dwg import options (harmless for .3dm).
        ok = rs.Command(
            '-_Worksession _Attach "{}" _Enter _Enter'.format(path), echo=False)
        if ok:
            attached_count += 1
            known.add(path.lower())
        else:
            failed.append(path)

    lines = ["Attached {} file(s).".format(attached_count)]
    if skipped:
        lines.append("Skipped (already attached): {}".format(len(skipped)))
    if failed:
        lines.append("Failed:")
        lines.extend("  " + p for p in failed)
    rs.MessageBox("\n".join(lines), 0, __title__)


if __name__ == "__main__":
    attach_refresh_worksession()
