"""
EnneadTab for Revit — modern guided wizard (shared by installer + uninstaller).

Light 3-screen flow: welcome -> progress -> done. Self-contained chrome/theme
(copied from EnneadTab_OS_UnInstaller, trimmed) — it does NOT depend on the OS
wizard, so the two evolve independently. All work runs on a background thread;
the pyRevit attach/detach itself lives in enneadtab_for_revit_core.

Preview hook: set env EATAB_WIZARD_PREVIEW=welcome|progress|done to render a
single screen with dummy data (no real work) — used for screenshot verification.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

from enneadtab_for_revit_core import EnneadTabRevitInstallationManager

# Dark theme — same muted charcoal + teal palette as the OS wizards.
BG = "#1A1D21"
CARD = "#24282E"
INK = "#E8EAED"
MUTED = "#9AA3AD"
ACCENT = "#3D7A6A"
ACCENT_DIM = "#2A564B"
DANGER = "#E07A7A"
OK = "#7BC49A"
WARN = "#E0B86A"
BORDER = "#3A4048"
INPUT_BG = "#1E2228"
BTN_BG = "#323840"
BTN_FG = "#E8EAED"
BTN_PRIMARY_BG = "#3D7A6A"
BTN_PRIMARY_FG = "#FFFFFF"

SUPPORT_EMAIL = "design.technology@ennead.com"


class RevitWizard(tk.Tk):
    STEPS = ("welcome", "progress", "done")

    def __init__(self, is_installing: bool = True):
        super().__init__()
        self.is_installing = is_installing
        self.verb = "Install" if is_installing else "Uninstall"
        self.gerund = "Installing" if is_installing else "Uninstalling"

        self.title("EnneadTab for Revit {}".format("Installer" if is_installing else "UnInstaller"))
        self.geometry("640x560")
        self.minsize(600, 500)
        self.configure(bg=BG)

        self.step_index = 0
        self.result_ok = None
        self._work_running = False
        self._log_widget = None

        self.manager = EnneadTabRevitInstallationManager(
            is_installing=is_installing, log=self._log_from_worker
        )

        self._apply_dark_theme()
        self._build_chrome()

        preview = os.environ.get("EATAB_WIZARD_PREVIEW")
        if preview in self.STEPS:
            self._show_step(self.STEPS.index(preview), preview_only=True)
        else:
            self._show_step(0)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # theme + chrome
    # ------------------------------------------------------------------
    def _apply_dark_theme(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(".", background=BG, foreground=INK, fieldbackground=INPUT_BG)
        style.configure("TFrame", background=BG)
        style.configure(
            "TButton", background=BTN_BG, foreground=BTN_FG, bordercolor=BORDER,
            lightcolor=BTN_BG, darkcolor=BTN_BG, focuscolor=ACCENT, padding=(12, 6),
        )
        style.map(
            "TButton",
            background=[("active", "#3E4650"), ("disabled", "#2A2E34")],
            foreground=[("disabled", "#6B7280")],
        )
        style.configure(
            "Primary.TButton", background=BTN_PRIMARY_BG, foreground=BTN_PRIMARY_FG,
            bordercolor=ACCENT_DIM, lightcolor=BTN_PRIMARY_BG, darkcolor=BTN_PRIMARY_BG,
            padding=(14, 6),
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#4A8F7C"), ("disabled", "#2A564B")],
            foreground=[("disabled", "#A8C4BB")],
        )

    def _build_chrome(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = tk.Frame(self, bg=ACCENT, height=56)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        tk.Label(
            header,
            text="{} EnneadTab for Revit".format(self.verb),
            font=("Segoe UI", 14, "bold"), fg="#FFFFFF", bg=ACCENT,
        ).pack(side=tk.LEFT, padx=20, pady=14)
        self.step_label = tk.Label(header, text="", font=("Segoe UI", 10), fg="#B7D4CB", bg=ACCENT)
        self.step_label.pack(side=tk.RIGHT, padx=20)

        self.body = tk.Frame(self, bg=BG)
        self.body.grid(row=1, column=0, sticky="nsew", padx=24, pady=(18, 8))

        divider = tk.Frame(self, bg=BORDER, height=1)
        divider.grid(row=2, column=0, sticky="ew", padx=24)

        self.footer = tk.Frame(self, bg=BG, height=64)
        self.footer.grid(row=3, column=0, sticky="ew", padx=24, pady=(10, 16))
        self.footer.grid_propagate(False)

        self.btn_cancel = ttk.Button(self.footer, text="Cancel", command=self._on_close, width=12)
        self.btn_next = ttk.Button(self.footer, text="Next", command=self._next, width=16, style="Primary.TButton")
        self.btn_cancel.pack(side=tk.LEFT, pady=14)
        self.btn_next.pack(side=tk.RIGHT, pady=14)

    # ------------------------------------------------------------------
    # small content helpers
    # ------------------------------------------------------------------
    def _heading(self, parent, text):
        tk.Label(parent, text=text, font=("Segoe UI", 16, "bold"), fg=INK, bg=BG,
                 anchor="w", justify="left", wraplength=560).pack(anchor="w", pady=(0, 10))

    def _para(self, parent, text, fg=MUTED):
        tk.Label(parent, text=text, font=("Segoe UI", 10), fg=fg, bg=BG,
                 anchor="w", justify="left", wraplength=560).pack(anchor="w", pady=(0, 8))

    def _bullet(self, parent, text, fg=INK):
        row = tk.Frame(parent, bg=BG)
        row.pack(anchor="w", fill="x", pady=1)
        tk.Label(row, text="•", font=("Segoe UI", 10), fg=ACCENT, bg=BG).pack(side="left", anchor="n", padx=(4, 8))
        tk.Label(row, text=text, font=("Segoe UI", 10), fg=fg, bg=BG,
                 anchor="w", justify="left", wraplength=520).pack(side="left", anchor="w")

    def _clear_body(self):
        for child in self.body.winfo_children():
            child.destroy()
        self._log_widget = None

    # ------------------------------------------------------------------
    # navigation
    # ------------------------------------------------------------------
    def _show_step(self, index, preview_only=False):
        self.step_index = index
        step = self.STEPS[index]
        self.step_label.config(text="Step {} of {}".format(index + 1, len(self.STEPS)))
        self._clear_body()
        builder = getattr(self, "_step_" + step)
        builder(preview_only=preview_only)

    def _next(self):
        step = self.STEPS[self.step_index]
        if step == "welcome":
            self._show_step(self.STEPS.index("progress"))

    def _on_close(self):
        if self._work_running:
            return  # ignore close while working
        self.destroy()

    # ------------------------------------------------------------------
    # step: welcome
    # ------------------------------------------------------------------
    def _step_welcome(self, preview_only=False):
        self._heading(self.body, "{} EnneadTab for Revit".format(self.verb))
        if self.is_installing:
            self._para(self.body, "This will connect EnneadTab to pyRevit so the EnneadTab "
                                  "ribbon appears the next time you open Revit. It will:")
            self._bullet(self.body, "Check that pyRevit is installed (and install it if missing)")
            self._bullet(self.body, "Attach the EnneadTab extension to every installed Revit version")
            self._bullet(self.body, "Register EnneadTab in your pyRevit configuration")
        else:
            self._para(self.body, "This will disconnect EnneadTab from pyRevit. It will:")
            self._bullet(self.body, "Clear the EnneadTab extension from your pyRevit configuration")
            self._bullet(self.body, "Leave pyRevit itself and your other extensions untouched")
        self._para(self.body, " ")
        self._para(self.body, "Close Revit before continuing so the change takes effect cleanly.")

        status = tk.Label(self.body, text="", font=("Segoe UI", 10, "bold"), bg=BG, anchor="w")
        status.pack(anchor="w", pady=(10, 4))

        def refresh():
            running = self.manager.check_revit_running()
            if running:
                status.config(text="●  Revit is currently running — please close it.", fg=WARN)
            else:
                status.config(text="●  Revit is not running.", fg=OK)

        ttk.Button(self.body, text="Re-check Revit", command=refresh).pack(anchor="w", pady=(2, 0))
        if not preview_only:
            refresh()
        else:
            status.config(text="●  Revit is currently running — please close it.", fg=WARN)

        self.btn_next.config(text=self.verb, state="normal")

    # ------------------------------------------------------------------
    # step: progress
    # ------------------------------------------------------------------
    def _step_progress(self, preview_only=False):
        self._heading(self.body, "{} EnneadTab...".format(self.gerund))
        self._para(self.body, "This usually takes a few seconds. Please don't close this window.")

        log = scrolledtext.ScrolledText(
            self.body, height=12, bg=INPUT_BG, fg=INK, insertbackground=INK,
            relief="flat", font=("Consolas", 9), wrap="word", borderwidth=0,
        )
        log.pack(fill="both", expand=True, pady=(6, 0))
        log.configure(state="disabled")
        self._log_widget = log

        self.btn_cancel.config(state="disabled")
        self.btn_next.config(state="disabled", text="Working...")

        if preview_only:
            for line in ("Looking for EnneadTab OS...",
                         "Found pyRevit config: C:\\Users\\you\\AppData\\Roaming\\pyRevit\\pyRevit_config.ini",
                         "EnneadTab-for-Revit has been attached to pyRevit."):
                self._append_log(line)
            return

        self._work_running = True
        threading.Thread(target=self._run_worker, daemon=True).start()

    def _run_worker(self):
        ok = False
        try:
            ok = bool(self.manager.run())
        except Exception as e:  # never let the thread die silently
            self._log_from_worker("Unexpected error: {}".format(e))
            ok = False
        self.result_ok = ok
        self.after(0, self._work_finished)

    def _log_from_worker(self, msg):
        # called from the worker thread — marshal onto the UI thread
        try:
            self.after(0, lambda: self._append_log(msg))
        except Exception:
            pass

    def _append_log(self, msg):
        w = self._log_widget
        if w is None:
            return
        try:
            w.configure(state="normal")
            w.insert("end", msg + "\n")
            w.see("end")
            w.configure(state="disabled")
        except Exception:
            pass

    def _work_finished(self):
        self._work_running = False
        self._show_step(self.STEPS.index("done"))

    # ------------------------------------------------------------------
    # step: done
    # ------------------------------------------------------------------
    def _step_done(self, preview_only=False):
        ok = True if preview_only else bool(self.result_ok)
        if ok:
            self._heading(self.body, "{} complete".format(self.verb))
            if self.is_installing:
                self._para(self.body, "EnneadTab is attached to pyRevit. Open Revit and look for "
                                      "the EnneadTab ribbon tab.", fg=OK)
            else:
                self._para(self.body, "EnneadTab has been detached from pyRevit. You can close "
                                      "this window.", fg=OK)
        else:
            self._heading(self.body, "{} didn't finish".format(self.verb))
            self._para(self.body, "Something went wrong. Review the log above for details, then "
                                  "try again.", fg=DANGER)
            self._para(self.body, "If it keeps failing, contact {}.".format(SUPPORT_EMAIL))

        self.btn_cancel.pack_forget()
        self.btn_next.config(text="Close", state="normal", command=self.destroy)


def run(is_installing: bool) -> int:
    app = RevitWizard(is_installing=is_installing)
    app.mainloop()
    return 0
