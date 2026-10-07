# -*- coding: utf-8 -*-
__title__ = "FlyThrough"
__doc__ = """Precise fly-through content pipeline (senzhang-todo #452).

Locks a camera path in the LIVE Rhino 3D viewport (operator-controlled, not
AI-guessed), exports keyframe stills for debug/approval, then renders a final
image set + optional video. Progress and failures land in Dump/FlyThrough/
monitor.log + job_status.json.

How to run
----------
1. Frame the start pose in a Perspective viewport.
2. Click this button -> Lock keyframe. Orbit/walk, lock again. Repeat.
   (Or Import named views to reuse cameras you already saved.)
3. Export keyframe stills and review before spending time on a full render.
4. Render final video + images. Opens the job folder when done.

Alias: FlyThrough / EA_FlyThrough

Note: This is EnneadTab-OS Rhino tooling. It is NOT the RenderPolisher
AI-from-stills / Veo path (deliberately repointed off RenderPolisher).
"""
__is_popular__ = True

import rhinoscriptsyntax as rs  # pyright: ignore

from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION, DATA_FILE
from EnneadTab.RHINO import RHINO_FLYTHROUGH as FT
from EnneadTab.RHINO import RHINO_FORMS


STICKY_WIDTH = "fly_through_width"
STICKY_HEIGHT = "fly_through_height"
STICKY_FPS = "fly_through_fps"
STICKY_DURATION = "fly_through_duration"


ACTIONS = [
    "1) Lock keyframe (capture live viewport camera)",
    "2) Import named views into path",
    "3) Export keyframe stills (debug / approval)",
    "4) Render final video + image set",
    "5) Configure resolution / fps / duration",
    "6) Show path status",
    "7) Clear path",
]


def _read_settings_prompt():
    width = DATA_FILE.get_sticky(STICKY_WIDTH, FT.DEFAULT_WIDTH)
    height = DATA_FILE.get_sticky(STICKY_HEIGHT, FT.DEFAULT_HEIGHT)
    fps = DATA_FILE.get_sticky(STICKY_FPS, FT.DEFAULT_FPS)
    duration = DATA_FILE.get_sticky(STICKY_DURATION, FT.DEFAULT_DURATION_SEC)
    res = rs.PropertyListBox(
        ["Width", "Height", "FPS", "Duration_sec"],
        [str(width), str(height), str(fps), str(duration)],
        message="Fly-through output settings",
        title="EnneadTab FlyThrough")
    if not res:
        return None
    try:
        width = int(res[0])
        height = int(res[1])
        fps = int(res[2])
        duration = float(res[3])
    except Exception:
        NOTIFICATION.messenger("Invalid settings — keep numbers only.")
        return None
    DATA_FILE.set_sticky(STICKY_WIDTH, width)
    DATA_FILE.set_sticky(STICKY_HEIGHT, height)
    DATA_FILE.set_sticky(STICKY_FPS, fps)
    DATA_FILE.set_sticky(STICKY_DURATION, duration)
    return width, height, fps, duration


def _import_named_views():
    all_views = rs.NamedViews() or []
    if not all_views:
        NOTIFICATION.messenger("No Named Views in this document.")
        return
    selected = RHINO_FORMS.select_from_list(
        sorted(all_views),
        message="Select Named Views to append to the fly-through path (order matters).",
        button_names=["Import"],
        multi_select=True)
    if not selected:
        return
    # select_from_list may return a single string when one item is picked
    try:
        _string_types = basestring  # IronPython 2 / Py2
    except NameError:
        _string_types = str
    if isinstance(selected, _string_types):
        selected = [selected]
    FT.safe_stage(FT.stage_import_named_views, selected)


def fly_through():
    choice = rs.ListBox(
        ACTIONS,
        message="Fly-through pipeline — lock path in the live viewport, stills first, then final.",
        title="EnneadTab FlyThrough")
    if not choice:
        return

    if choice.startswith("1)"):
        FT.safe_stage(FT.stage_lock_keyframe, True)
    elif choice.startswith("2)"):
        _import_named_views()
    elif choice.startswith("3)"):
        FT.safe_stage(FT.stage_export_keyframe_stills)
    elif choice.startswith("4)"):
        FT.safe_stage(FT.stage_render_final)
    elif choice.startswith("5)"):
        settings = _read_settings_prompt()
        if settings:
            width, height, fps, duration = settings
            FT.safe_stage(
                FT.stage_configure_settings, width, height, fps, duration)
    elif choice.startswith("6)"):
        FT.safe_stage(FT.stage_path_status)
    elif choice.startswith("7)"):
        confirm = rs.MessageBox(
            "Clear the locked fly-through path?",
            buttons=4,  # Yes/No
            title="EnneadTab FlyThrough")
        # rs.MessageBox Yes = 6
        if confirm == 6:
            FT.safe_stage(FT.stage_clear_path)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def fly_through_left():
    fly_through()


if __name__ == "__main__":
    fly_through_left()
