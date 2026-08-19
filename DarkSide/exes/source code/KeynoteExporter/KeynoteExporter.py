#!/usr/bin/env python3
"""
KeynoteExporter - GUI Entry Point

The splash screen, taskbar identity, and single-instance guard run BEFORE the
heavy ``src`` imports (pandas/openpyxl) so the user gets instant feedback on
double-click and can never open a second instance.
"""

import startup


def _run():
    startup.update_splash("Starting EnneadTab Keynote Exporter...")
    startup.set_app_user_model_id()

    # One instance per user session. A second launch briefly shows the splash,
    # tells the user it is already running, then exits.
    if not startup.acquire_single_instance("EnneadTab_KeynoteExporter"):
        startup.close_splash()
        startup.notify_already_running()
        return

    startup.update_splash("Loading modules...")
    from src.keynote_gui import main as gui_main  # heavy imports happen here

    startup.update_splash("Launching...")
    gui_main()  # closes the splash once the window is on screen


if __name__ == "__main__":
    _run()