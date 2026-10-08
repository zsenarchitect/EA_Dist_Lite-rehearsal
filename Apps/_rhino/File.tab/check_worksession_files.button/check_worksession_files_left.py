__title__ = "CheckWorksessionFiles"
__doc__ = """Check an expected list of model files against the disk and the active worksession.

Reports which expected files are missing on disk, which are not attached to the worksession, and which attached models were not expected -- then offers to attach the missing ones.
"""
__is_popular__ = False

import os

import rhinoscriptsyntax as rs
import scriptcontext as sc  # noqa

from EnneadTab import ERROR_HANDLE, LOG


def _collect_expected():
    paths = []
    while True:
        entry = rs.GetString(
            "Expected model file (.3dm/.rws). Press Enter with empty input when done"
            + (" [{0} so far]".format(len(paths)) if paths else ""))
        if entry is None:  # user cancelled
            return None
        entry = entry.strip().strip('"')
        if not entry:
            break
        if entry not in paths:
            paths.append(entry)
    return paths


def _attached_model_paths():
    try:
        return [p for p in sc.doc.Worksession.ModelPaths if p]
    except Exception:
        return []


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def check_worksession_files():
    expected = _collect_expected()
    if expected is None:
        print("Check cancelled.")
        return
    if not expected:
        rs.MessageBox("No expected files entered.", 0, __title__)
        return

    attached = _attached_model_paths()
    attached_set = set(p.lower() for p in attached)

    missing_on_disk = []
    not_attached = []
    ok = []
    for path in expected:
        if not os.path.exists(path):
            missing_on_disk.append(path)
        elif path.lower() not in attached_set:
            not_attached.append(path)
        else:
            ok.append(path)

    unexpected = [p for p in attached if p.lower() not in set(p.lower() for p in expected)]

    print("=== Worksession file check: {0} expected file(s) ===".format(len(expected)))
    for path in ok:
        print("  OK: '{0}' is attached.".format(path))
    for path in not_attached:
        print("  NOT ATTACHED: '{0}' exists on disk but is not in the worksession.".format(path))
    for path in missing_on_disk:
        print("  MISSING: '{0}' not found on disk.".format(path))
    for path in unexpected:
        print("  (attached but not expected: '{0}')".format(path))

    summary = ("{0} attached, {1} not attached, {2} missing on disk.".format(
        len(ok), len(not_attached), len(missing_on_disk)))

    if not_attached:
        answer = rs.MessageBox(
            summary + "\n\nAttach the {0} missing file(s) to the worksession now?".format(len(not_attached)),
            4 | 32,
            __title__)
        if answer == 6:  # Yes
            done = 0
            for path in not_attached:
                if rs.Command('-_Worksession _Attach "{0}" _Enter'.format(path), False):
                    done += 1
            print("Attach issued for {0} of {1} file(s).".format(done, len(not_attached)))
            summary += " Attach issued for {0} of {1}.".format(done, len(not_attached))
    else:
        rs.MessageBox(summary + "\n\nSee the command history for details.", 0, __title__)
        return

    rs.MessageBox(summary, 0, __title__)


if __name__ == "__main__":
    check_worksession_files()
