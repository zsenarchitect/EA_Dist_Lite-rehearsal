"""
EnneadTab OS UnInstaller — guided wizard (counterpart to EnneadTab_OS_Installer).

Wipes the user Documents ecosystem + AppData install artifacts only.
"""

from __future__ import annotations

import os
import random
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Optional

import enneadtab_os_uninstall_core as core


# Dark theme — calm charcoal + muted teal (avoid purple/glow defaults)
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
MODAL_W = 420
MODAL_H = 220
DUCK_ZOOM = 1
DUCK_GIF = "sleep.gif"


def _asset_path(filename):
    """Bundled DesktopPet duck assets (dev folder or PyInstaller _MEIPASS)."""
    if getattr(sys, "frozen", False):
        base = os.path.join(getattr(sys, "_MEIPASS", ""), "assets")
    else:
        base = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "EnneadTab_OS_UnInstaller_assets",
        )
    return os.path.join(base, filename)


class UninstallWizard(tk.Tk):
    STEPS = (
        "welcome",
        "rhino",
        "hosts",
        "review",
        "confirm",
        "progress",
        "done",
    )

    def __init__(self):
        super().__init__()
        self.title("EnneadTab UnInstaller")
        self.geometry("720x640")
        self.minsize(680, 560)
        self.configure(bg=BG)
        self.resizable(True, True)

        self.step_index = 0
        self.rhino_skipped = False
        self.wipe_result = None
        self._wipe_running = False
        self._mousewheel_bound = False

        self.understand_var = tk.BooleanVar(value=False)
        self.confirm_text_var = tk.StringVar(value="")
        self.confirm_text_var.trace_add("write", lambda *_: self._update_confirm_state())
        self._tear_job = None
        self._tear_items = []
        self._sad_duck_canvas = None
        self._duck_frames = []
        self._duck_frame_index = 0
        self._duck_anim_job = None
        self._duck_image_id = None
        self._last_typed_len = 0
        self._was_matched = False

        self._apply_dark_theme()
        self._build_chrome()
        self._show_step(0)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_dark_theme(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=BG, foreground=INK, fieldbackground=INPUT_BG)
        style.configure("TFrame", background=BG)
        style.configure(
            "TButton",
            background=BTN_BG,
            foreground=BTN_FG,
            bordercolor=BORDER,
            lightcolor=BTN_BG,
            darkcolor=BTN_BG,
            focuscolor=ACCENT,
            padding=(12, 6),
        )
        style.map(
            "TButton",
            background=[("active", "#3E4650"), ("disabled", "#2A2E34")],
            foreground=[("disabled", "#6B7280")],
        )
        style.configure(
            "Primary.TButton",
            background=BTN_PRIMARY_BG,
            foreground=BTN_PRIMARY_FG,
            bordercolor=ACCENT_DIM,
            lightcolor=BTN_PRIMARY_BG,
            darkcolor=BTN_PRIMARY_BG,
            padding=(14, 6),
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#4A8F7C"), ("disabled", "#2A564B")],
            foreground=[("disabled", "#A8C4BB")],
        )
        style.configure(
            "TEntry",
            fieldbackground=INPUT_BG,
            foreground=INK,
            insertcolor=INK,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
        )
        style.configure(
            "Vertical.TScrollbar",
            background=BTN_BG,
            troughcolor=CARD,
            bordercolor=CARD,
            arrowcolor=MUTED,
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", "#3E4650")],
        )

    def _build_chrome(self):
        # Grid keeps the action row permanently reserved — content can never cover it.
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = tk.Frame(self, bg=ACCENT, height=56)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        tk.Label(
            header,
            text="Remove EnneadTab from this PC",
            font=("Segoe UI", 14, "bold"),
            fg="#FFFFFF",
            bg=ACCENT,
        ).pack(side=tk.LEFT, padx=20, pady=14)

        self.step_label = tk.Label(
            header,
            text="",
            font=("Segoe UI", 10),
            fg="#B7D4CB",
            bg=ACCENT,
        )
        self.step_label.pack(side=tk.RIGHT, padx=20)

        self.body = tk.Frame(self, bg=BG)
        self.body.grid(row=1, column=0, sticky="nsew", padx=20, pady=(16, 8))

        divider = tk.Frame(self, bg=BORDER, height=1)
        divider.grid(row=2, column=0, sticky="ew", padx=20)

        self.footer = tk.Frame(self, bg=BG, height=64)
        self.footer.grid(row=3, column=0, sticky="ew", padx=20, pady=(10, 16))
        self.footer.grid_propagate(False)

        self.btn_back = ttk.Button(self.footer, text="Back", command=self._back, width=12)
        self.btn_cancel = ttk.Button(self.footer, text="Cancel", command=self._on_close, width=12)
        self.btn_next = ttk.Button(
            self.footer,
            text="Next",
            command=self._next,
            width=16,
            style="Primary.TButton",
        )

        self.btn_cancel.pack(side=tk.LEFT, pady=14)
        self.btn_next.pack(side=tk.RIGHT, pady=14)
        self.btn_back.pack(side=tk.RIGHT, padx=(0, 8), pady=14)

    def _clear_body(self):
        self._stop_tear_animation()
        if self._mousewheel_bound:
            try:
                self.unbind_all("<MouseWheel>")
            except Exception:
                pass
            self._mousewheel_bound = False
        for child in self.body.winfo_children():
            child.destroy()
        self._sad_duck_canvas = None

    def _modal(
        self,
        title,
        message,
        kind="info",
        yes_text="OK",
        no_text=None,
    ):
        """Dark in-app dialog — borderless; our header + buttons only."""
        result = {"ok": False}
        dlg = tk.Toplevel(self)
        dlg.withdraw()
        dlg.configure(bg=BORDER)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.overrideredirect(True)
        try:
            dlg.attributes("-topmost", True)
        except Exception:
            pass

        self.update_idletasks()
        px = self.winfo_rootx() + max(0, (self.winfo_width() - MODAL_W) // 2)
        py = self.winfo_rooty() + max(40, (self.winfo_height() - MODAL_H) // 2)
        dlg.geometry("{}x{}+{}+{}".format(MODAL_W, MODAL_H, px, py))

        accent = ACCENT
        if kind == "warn":
            accent = WARN
        elif kind == "danger":
            accent = DANGER
        elif kind == "confirm":
            accent = ACCENT

        shell = tk.Frame(dlg, bg=BG, highlightthickness=0)
        shell.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        header = tk.Frame(shell, bg=accent, height=44)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(
            header,
            text=title,
            font=("Segoe UI", 11, "bold"),
            fg="#FFFFFF",
            bg=accent,
        ).pack(side=tk.LEFT, padx=16, pady=10)

        def _close(ok):
            result["ok"] = bool(ok)
            try:
                dlg.grab_release()
            except Exception:
                pass
            dlg.destroy()

        tk.Label(
            header,
            text="✕",
            font=("Segoe UI", 11, "bold"),
            fg="#FFFFFF",
            bg=accent,
            cursor="hand2",
            padx=14,
        ).pack(side=tk.RIGHT)
        header.winfo_children()[-1].bind(
            "<Button-1>", lambda _e: _close(False if no_text else True)
        )

        # Drag borderless dialog by the header
        drag = {"x": 0, "y": 0}

        def _drag_start(event):
            drag["x"] = event.x_root - dlg.winfo_x()
            drag["y"] = event.y_root - dlg.winfo_y()

        def _drag_move(event):
            dlg.geometry("+{}+{}".format(event.x_root - drag["x"], event.y_root - drag["y"]))

        header.bind("<ButtonPress-1>", _drag_start)
        header.bind("<B1-Motion>", _drag_move)
        for child in header.winfo_children()[:-1]:
            child.bind("<ButtonPress-1>", _drag_start)
            child.bind("<B1-Motion>", _drag_move)

        body = tk.Frame(shell, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=(16, 8))
        tk.Label(
            body,
            text=message,
            font=("Segoe UI", 10),
            fg=INK,
            bg=BG,
            wraplength=MODAL_W - 48,
            justify=tk.LEFT,
            anchor="nw",
        ).pack(fill=tk.BOTH, expand=True)

        footer = tk.Frame(shell, bg=BG)
        footer.pack(fill=tk.X, padx=20, pady=(4, 16))

        if no_text:
            ttk.Button(
                footer,
                text=yes_text,
                command=lambda: _close(True),
                width=14,
                style="Primary.TButton",
            ).pack(side=tk.RIGHT)
            ttk.Button(
                footer,
                text=no_text,
                command=lambda: _close(False),
                width=12,
            ).pack(side=tk.RIGHT, padx=(0, 8))
        else:
            ttk.Button(
                footer,
                text=yes_text,
                command=lambda: _close(True),
                width=14,
                style="Primary.TButton",
            ).pack(side=tk.RIGHT)

        dlg.bind("<Escape>", lambda _e: _close(False if no_text else True))
        dlg.bind("<Return>", lambda _e: _close(True))
        dlg.deiconify()
        dlg.lift()
        dlg.focus_force()
        dlg.grab_set()
        self.wait_window(dlg)
        return result["ok"]

    def _card(self) -> tk.Frame:
        """Scrollable card so tall steps leave footer buttons visible."""
        outer = tk.Frame(self.body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        outer.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(outer, bg=CARD, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=CARD)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfigure(window_id, width=event.width)

        def _on_mousewheel(event):
            # Don't steal wheel/focus from editable fields
            widget = self.focus_get()
            if isinstance(widget, (tk.Entry, tk.Text, scrolledtext.ScrolledText)):
                return
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        self.bind_all("<MouseWheel>", _on_mousewheel)
        self._mousewheel_bound = True

        pad = tk.Frame(inner, bg=CARD)
        pad.pack(fill=tk.BOTH, expand=True, padx=24, pady=20)
        return pad

    def _plain_card(self) -> tk.Frame:
        """Non-scrolling card — needed so Entry widgets can receive keyboard input."""
        outer = tk.Frame(self.body, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        outer.pack(fill=tk.BOTH, expand=True)
        pad = tk.Frame(outer, bg=CARD)
        pad.pack(fill=tk.BOTH, expand=True, padx=24, pady=20)
        return pad

    def _heading(self, parent, text: str):
        tk.Label(
            parent,
            text=text,
            font=("Segoe UI", 13, "bold"),
            fg=INK,
            bg=CARD,
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(0, 10))

    def _para(self, parent, text: str, color: str = MUTED):
        tk.Label(
            parent,
            text=text,
            font=("Segoe UI", 10),
            fg=color,
            bg=CARD,
            anchor="w",
            justify=tk.LEFT,
            wraplength=620,
        ).pack(fill=tk.X, pady=(0, 8))

    def _bullet(self, parent, text: str, color: str = INK):
        tk.Label(
            parent,
            text="  •  " + text,
            font=("Segoe UI", 10),
            fg=color,
            bg=CARD,
            anchor="w",
            justify=tk.LEFT,
            wraplength=620,
        ).pack(fill=tk.X, pady=2)

    def _show_step(self, index: int):
        self.step_index = index
        name = self.STEPS[index]
        self.step_label.config(text="Step {} of {}".format(index + 1, len(self.STEPS)))
        self._clear_body()

        self.btn_back.config(state=tk.NORMAL if index > 0 and name not in ("progress", "done") else tk.DISABLED)
        self.btn_cancel.config(state=tk.DISABLED if name == "progress" else tk.NORMAL)
        self.btn_next.config(state=tk.NORMAL)

        if name == "welcome":
            self._step_welcome()
        elif name == "rhino":
            self._step_rhino()
        elif name == "hosts":
            self._step_hosts()
        elif name == "review":
            self._step_review()
        elif name == "confirm":
            self._step_confirm()
        elif name == "progress":
            self._step_progress()
        elif name == "done":
            self._step_done()

    def _step_welcome(self):
        card = self._card()
        self._heading(card, "Welcome")
        self._para(
            card,
            "This wizard removes EnneadTab from this computer.",
        )
        self._para(card, "What will be removed:", INK)
        self._bullet(card, "Your EnneadTab files under Documents")
        self._bullet(card, "Automatic EnneadTab updates at login")
        self._bullet(card, "Saved EnneadTab settings and sign-in info")
        self._bullet(card, "EnneadTab tools from Revit (via pyRevit)")

        self._para(card, "What will stay:", INK)
        self._bullet(card, "Revit, Rhino, AutoCAD, and pyRevit")
        self._bullet(card, "Project files on firm network drives")

        self._para(
            card,
            "Not sure? Email szhang@ennead.com before continuing.",
            MUTED,
        )
        self.btn_next.config(text="Next")

    def _step_rhino(self):
        card = self._card()
        self._heading(card, "Step 1 — Uninstall in Rhino first")
        self._para(
            card,
            "Rhino aliases, toolbars, and startup scripts can only be cleared inside Rhino.",
        )
        self._para(card, "Do this now:", INK)
        self._bullet(card, "Open Rhino")
        self._bullet(card, "Open the EnneadTab menu → click Uninstall")
        self._bullet(card, "Restart Rhino once, then close Rhino completely")
        self._para(
            card,
            "That Rhino button removes aliases/toolbars. This wizard removes the files afterward.",
        )

        btn_row = tk.Frame(card, bg=CARD)
        btn_row.pack(fill=tk.X, pady=(16, 0))

        ttk.Button(
            btn_row,
            text="I finished Rhino Uninstall",
            command=self._rhino_done,
        ).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            btn_row,
            text="I don't use Rhino",
            command=self._rhino_skip,
        ).pack(side=tk.LEFT)

        self.btn_next.config(state=tk.DISABLED, text="Next")

    def _rhino_done(self):
        self.rhino_skipped = False
        self._show_step(self.STEPS.index("hosts"))

    def _rhino_skip(self):
        if not self._modal(
            "Skip Rhino cleanup?",
            "Aliases and toolbars may remain in Rhino.\n\nContinue without Rhino Uninstall?",
            kind="confirm",
            yes_text="Continue",
            no_text="Go back",
        ):
            return
        self.rhino_skipped = True
        self._show_step(self.STEPS.index("hosts"))

    def _step_hosts(self):
        card = self._card()
        self._heading(card, "Step 2 — Close Revit and Rhino")
        self._para(
            card,
            "Leave both closed so files are not locked. This tool will not force-quit them.",
        )

        self.host_status = tk.Label(
            card,
            text="",
            font=("Segoe UI", 11, "bold"),
            bg=CARD,
            fg=INK,
            anchor="w",
            justify=tk.LEFT,
        )
        self.host_status.pack(fill=tk.X, pady=(8, 12))

        ttk.Button(card, text="Recheck", command=self._refresh_hosts).pack(anchor="w")
        self._refresh_hosts()
        self.btn_next.config(text="Next")

    def _refresh_hosts(self):
        status = core.hosts_running()
        revit_ok = not status["revit"]
        rhino_ok = not status["rhino"]
        revit_detail = ""
        rhino_detail = ""
        if status.get("revit_processes"):
            revit_detail = " ({})".format(", ".join(status["revit_processes"]))
        if status.get("rhino_processes"):
            rhino_detail = " ({})".format(", ".join(status["rhino_processes"]))
        lines = [
            "Revit:  {}".format(
                "Closed" if revit_ok else "Still running — please close it{}".format(revit_detail)
            ),
            "Rhino:  {}".format(
                "Closed" if rhino_ok else "Still running — please close it{}".format(rhino_detail)
            ),
        ]
        color = OK if revit_ok and rhino_ok else DANGER
        self.host_status.config(text="\n".join(lines), fg=color)
        self.btn_next.config(state=tk.NORMAL if revit_ok and rhino_ok else tk.DISABLED)

    def _step_review(self):
        card = self._card()
        self._heading(card, "Step 3 — Review what will be removed")
        detected = core.scan_detected_items()

        self._para(card, "Here is what this wizard found on your computer:", INK)
        self._bullet(
            card,
            "{} automatic update(s)".format(detected.get("task_count", 0)),
            MUTED,
        )
        self._bullet(
            card,
            "{} startup item(s)".format(detected.get("shortcut_count", 0)),
            MUTED,
        )

        folders = detected.get("folders") or []
        if folders:
            self._para(card, "Folders that will be removed:", INK)
            for item in folders:
                self._bullet(card, item, MUTED)
        else:
            self._para(card, "No EnneadTab folders were found (already clean).", MUTED)

        self._para(
            card,
            "Your Revit, Rhino, AutoCAD, pyRevit, and project files on network drives stay installed.",
            OK,
        )
        self.btn_next.config(text="Next")

    def _step_confirm(self):
        # Plain card — Entry inside Canvas create_window often cannot type on Windows.
        card = self._plain_card()
        self._heading(card, "Step 4 — Confirm uninstall")
        self._para(
            card,
            "This removes EnneadTab from this PC’s user folders. You can reinstall anytime from the EnneadTab Wiki if you change your mind.",
            DANGER,
        )

        # Sad mascot scene — DesktopPet duck + tears while typing UNINSTALL
        duck_row = tk.Frame(card, bg=CARD)
        duck_row.pack(fill=tk.X, pady=(2, 6))
        duck_size = 100 * DUCK_ZOOM
        self._sad_duck_canvas = tk.Canvas(
            duck_row,
            width=duck_size + 24,
            height=duck_size + 8,
            bg=CARD,
            highlightthickness=0,
            borderwidth=0,
        )
        self._sad_duck_canvas.pack(side=tk.LEFT)
        self._start_sad_duck()
        speech = tk.Frame(duck_row, bg=INPUT_BG, highlightbackground=BORDER, highlightthickness=1)
        speech.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0), pady=8)
        tk.Label(
            speech,
            text="Quack… Duck is sad to see you go.",
            font=("Segoe UI", 11, "italic"),
            fg=INK,
            bg=INPUT_BG,
            wraplength=360,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill=tk.X, padx=12, pady=10)

        tk.Checkbutton(
            card,
            text="I understand — check this box, then type UNINSTALL below",
            variable=self.understand_var,
            font=("Segoe UI", 10),
            bg=CARD,
            fg=INK,
            activebackground=CARD,
            activeforeground=INK,
            selectcolor=INPUT_BG,
            highlightthickness=0,
            command=self._update_confirm_state,
            anchor="w",
        ).pack(fill=tk.X, pady=(2, 8))

        confirm_box = tk.Frame(
            card,
            bg=INPUT_BG,
            highlightbackground=WARN,
            highlightcolor=WARN,
            highlightthickness=2,
        )
        confirm_box.pack(fill=tk.X, pady=(0, 12))

        inner = tk.Frame(confirm_box, bg=INPUT_BG)
        inner.pack(fill=tk.X, padx=14, pady=12)

        prompt = tk.Frame(inner, bg=INPUT_BG)
        prompt.pack(fill=tk.X)
        tk.Label(
            prompt,
            text="Type:",
            font=("Segoe UI", 10),
            fg=MUTED,
            bg=INPUT_BG,
            anchor="w",
        ).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(
            prompt,
            text="UNINSTALL",
            font=("Segoe UI", 16, "bold"),
            fg=WARN,
            bg=INPUT_BG,
            anchor="w",
        ).pack(side=tk.LEFT)

        self.confirm_hint = tk.Label(
            inner,
            text="",
            font=("Segoe UI", 9),
            fg=MUTED,
            bg=INPUT_BG,
            anchor="w",
        )
        self.confirm_hint.pack(fill=tk.X, pady=(6, 4))

        self.confirm_entry = tk.Entry(
            inner,
            textvariable=self.confirm_text_var,
            font=("Consolas", 14, "bold"),
            bg=BG,
            fg=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            highlightthickness=2,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            exportselection=False,
        )
        self.confirm_entry.pack(fill=tk.X, ipady=8, ipadx=8)
        self.confirm_entry.bind("<Button-1>", lambda _e: self.confirm_entry.focus_set())
        self.after(50, lambda: self.confirm_entry.focus_force())
        self._last_typed_len = 0
        self._was_matched = False
        self._tear_items = []

        self.btn_next.config(text="Start uninstall", command=self._start_wipe)
        self._update_confirm_state()

    def _stop_duck_animation(self):
        if self._duck_anim_job is not None:
            try:
                self.after_cancel(self._duck_anim_job)
            except Exception:
                pass
            self._duck_anim_job = None
        self._duck_frames = []
        self._duck_frame_index = 0
        self._duck_image_id = None

    def _start_sad_duck(self):
        """Show DesktopPet duck GIF (sleep = goodbye) with tear spawn near the eye."""
        self._stop_duck_animation()
        c = self._sad_duck_canvas
        if c is None:
            return
        c.delete("all")
        path = _asset_path(DUCK_GIF)
        frames = []
        if os.path.isfile(path):
            try:
                i = 0
                while True:
                    frame = tk.PhotoImage(file=path, format="gif -index {}".format(i))
                    if DUCK_ZOOM > 1:
                        frame = frame.zoom(DUCK_ZOOM, DUCK_ZOOM)
                    frames.append(frame)
                    i += 1
            except tk.TclError:
                pass
        self._duck_frames = frames
        cx = int(c.cget("width")) // 2
        cy = int(c.cget("height")) // 2
        # Eye is roughly upper-left on the pixel duck sprite
        self._tear_origin = (cx - 18 * DUCK_ZOOM // 2, cy - 12 * DUCK_ZOOM // 2)
        if frames:
            self._duck_image_id = c.create_image(cx, cy, image=frames[0], tags=("duck",))
            self._duck_frame_index = 0
            self._tick_duck_animation()
        else:
            c.create_text(
                cx,
                cy,
                text="(duck asset missing)",
                fill=MUTED,
                font=("Segoe UI", 9),
                tags=("duck",),
            )

    def _tick_duck_animation(self):
        c = self._sad_duck_canvas
        frames = self._duck_frames
        if c is None or not c.winfo_exists() or not frames or self._duck_image_id is None:
            self._duck_anim_job = None
            return
        self._duck_frame_index = (self._duck_frame_index + 1) % len(frames)
        try:
            c.itemconfigure(self._duck_image_id, image=frames[self._duck_frame_index])
        except Exception:
            self._duck_anim_job = None
            return
        self._duck_anim_job = self.after(120, self._tick_duck_animation)

    def _stop_tear_animation(self):
        if self._tear_job is not None:
            try:
                self.after_cancel(self._tear_job)
            except Exception:
                pass
            self._tear_job = None
        self._tear_items = []
        self._stop_duck_animation()

    def _spawn_tear(self):
        c = self._sad_duck_canvas
        if c is None or not c.winfo_exists():
            return
        ox, oy = getattr(self, "_tear_origin", (186, 52))
        x = ox + random.randint(-4, 6)
        y = oy
        w = random.randint(9, 12)
        h = random.randint(15, 20)
        cx = x + w / 2.0
        r = w / 2.0
        ccy = y + h - r  # center of the round bottom bulb
        # Teardrop: sharp point on top (vertex repeated so the spline keeps it
        # crisp), sides sweeping out to the widest point, rounding into the bulb.
        points = (
            cx, y,
            cx, y,
            x + w, y + h * 0.45,
            x + w, ccy,
            cx, y + h,
            x, ccy,
            x, y + h * 0.45,
        )
        tear = c.create_polygon(
            points,
            fill="#7EC8E3",
            outline="#5AABB8",
            width=2,
            smooth=True,
            splinesteps=24,
            tags=("tear",),
        )
        shine = c.create_oval(
            cx - r * 0.55,
            ccy - r * 0.35,
            cx - r * 0.05,
            ccy + r * 0.25,
            fill="#D6F0FA",
            outline="",
            tags=("tear",),
        )
        self._tear_items.append(
            {
                "id": tear,
                "shine": shine,
                "y": float(y),
                "speed": random.uniform(2.4, 3.8),
                "life": 0,
            }
        )
        if self._tear_job is None:
            self._animate_tears()

    def _animate_tears(self):
        c = self._sad_duck_canvas
        if c is None or not c.winfo_exists():
            self._tear_job = None
            return
        alive = []
        for tear in self._tear_items:
            step = tear["speed"]
            tear["y"] += step
            tear["life"] += 1
            try:
                c.move(tear["id"], 0, step)
                c.move(tear["shine"], 0, step)
            except Exception:
                continue
            max_y = int(c.cget("height")) - 8
            if tear["y"] < max_y and tear["life"] < 55:
                alive.append(tear)
            else:
                try:
                    c.delete(tear["id"])
                    c.delete(tear["shine"])
                except Exception:
                    pass
        self._tear_items = alive
        try:
            c.tag_raise("tear")
        except Exception:
            pass
        if self._tear_items or self.STEPS[self.step_index] == "confirm":
            self._tear_job = self.after(33, self._animate_tears)
        else:
            self._tear_job = None

    def _update_confirm_state(self):
        typed = self.confirm_text_var.get().strip()
        target = "UNINSTALL"
        upper = typed.upper()
        matched = upper == target
        prefix_ok = (not typed) or target.startswith(upper)
        ok = self.understand_var.get() and matched
        if self.STEPS[self.step_index] == "confirm":
            self.btn_next.config(state=tk.NORMAL if ok else tk.DISABLED)
            if hasattr(self, "confirm_entry"):
                if matched:
                    self.confirm_entry.config(highlightbackground=OK, highlightcolor=OK)
                    if hasattr(self, "confirm_hint"):
                        self.confirm_hint.config(
                            text="Looks good. The duck will miss you.",
                            fg=OK,
                        )
                    if not self._was_matched:
                        for _ in range(5):
                            self._spawn_tear()
                    self._was_matched = True
                elif typed and prefix_ok:
                    self.confirm_entry.config(highlightbackground=WARN, highlightcolor=WARN)
                    remaining = target[len(upper):]
                    if hasattr(self, "confirm_hint"):
                        self.confirm_hint.config(
                            text="Keep going… still need: {}".format(remaining),
                            fg=WARN,
                        )
                    if len(typed) > self._last_typed_len:
                        self._spawn_tear()
                        if len(typed) >= 5:
                            self._spawn_tear()
                    self._was_matched = False
                elif typed:
                    self.confirm_entry.config(highlightbackground=DANGER, highlightcolor=DANGER)
                    if hasattr(self, "confirm_hint"):
                        self.confirm_hint.config(text="Type UNINSTALL exactly.", fg=DANGER)
                    self._was_matched = False
                else:
                    self.confirm_entry.config(highlightbackground=BORDER, highlightcolor=ACCENT)
                    if hasattr(self, "confirm_hint"):
                        self.confirm_hint.config(text="", fg=MUTED)
                    self._was_matched = False
            self._last_typed_len = len(typed)

    def _start_wipe(self):
        if self._wipe_running:
            return
        self._stop_tear_animation()
        self._show_step(self.STEPS.index("progress"))

    def _step_progress(self):
        card = self._card()
        self._heading(card, "Uninstalling…")
        self._para(card, "Please wait. Do not close this window.")

        self.progress_log = scrolledtext.ScrolledText(
            card,
            height=12,
            font=("Segoe UI", 10),
            bg=INPUT_BG,
            fg=INK,
            insertbackground=INK,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            wrap=tk.WORD,
        )
        self.progress_log.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.progress_log.insert(tk.END, "Starting…\n")
        self.progress_log.config(state=tk.DISABLED)

        self.btn_next.config(state=tk.DISABLED, text="Working…")
        self.btn_back.config(state=tk.DISABLED)
        self._wipe_running = True

        thread = threading.Thread(target=self._run_wipe_thread, daemon=True)
        thread.start()

    def _append_log(self, message: str):
        def _ui():
            self.progress_log.config(state=tk.NORMAL)
            self.progress_log.insert(tk.END, message + "\n")
            self.progress_log.see(tk.END)
            self.progress_log.config(state=tk.DISABLED)

        self.after(0, _ui)

    def _run_wipe_thread(self):
        try:
            result = core.run_uninstall(
                log=self._append_log,
                rhino_skipped=self.rhino_skipped,
            )
        except Exception as exc:
            result = {
                "status": "failed",
                "details": str(exc),
                "leftovers": [],
                "notes": [],
                "report_path": core.STATUS_TXT,
                "log": [str(exc)],
            }
        self.wipe_result = result
        self.after(0, self._wipe_finished)

    def _wipe_finished(self):
        self._wipe_running = False
        self._show_step(self.STEPS.index("done"))

    def _step_done(self):
        card = self._card()
        result = self.wipe_result or {}
        status = result.get("status", "unknown")
        summary = result.get("summary") or ""

        if status == "success":
            self._heading(card, "Done")
            self._para(card, summary or "EnneadTab was removed from this PC.", OK)
            if core.should_self_remove_exe():
                self._para(
                    card,
                    "Closing this window also removes this UnInstaller helper.",
                    MUTED,
                )
        elif status == "partial":
            self._heading(card, "Almost done")
            self._para(
                card,
                summary or "Most of EnneadTab was removed. A few files were still in use.",
                WARN,
            )
            self._para(card, "Please:", INK)
            self._bullet(card, "Close Revit, Rhino, and any File Explorer windows in EnneadTab folders")
            self._bullet(card, "Restart Windows if those files stay locked")
            self._bullet(card, "Run this UnInstaller again")
        else:
            self._heading(card, "Something went wrong")
            self._para(card, summary or "Uninstall did not finish.", DANGER)
            self._para(
                card,
                "Email szhang@ennead.com and attach the report if you need help.",
                MUTED,
            )

        leftovers = result.get("leftovers") or []
        if leftovers:
            self._para(card, "Still on this PC:", INK)
            for item in leftovers:
                self._bullet(card, core.folder_label(item), MUTED)

        for note in result.get("notes") or []:
            self._bullet(card, note, MUTED)

        btn_row = tk.Frame(card, bg=CARD)
        btn_row.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(btn_row, text="Open details", command=self._open_report).pack(
            side=tk.LEFT, padx=(0, 8)
        )

        self.btn_back.config(state=tk.DISABLED)
        self.btn_cancel.config(state=tk.DISABLED)
        self.btn_next.config(text="Close", command=self._close_after_wipe, state=tk.NORMAL)

    def _close_after_wipe(self):
        result = self.wipe_result or {}
        if result.get("status") in ("success", "partial"):
            core.schedule_uninstaller_self_cleanup()
        self.destroy()

    def _open_report(self):
        path = (self.wipe_result or {}).get("report_path") or core.STATUS_TXT
        if os.path.exists(path):
            os.startfile(path)
        else:
            self._modal("Report", "Report file not found yet.", kind="info")

    def _back(self):
        if self.step_index <= 0 or self._wipe_running:
            return
        name = self.STEPS[self.step_index]
        if name in ("progress", "done"):
            return
        # From hosts, going back returns to rhino
        prev = self.step_index - 1
        if self.STEPS[self.step_index] == "hosts":
            prev = self.STEPS.index("rhino")
        self._show_step(prev)
        if self.STEPS[prev] == "confirm":
            self.btn_next.config(command=self._start_wipe)
        else:
            self.btn_next.config(command=self._next, text="Next")

    def _next(self):
        if self._wipe_running:
            return
        name = self.STEPS[self.step_index]
        if name == "rhino":
            self._modal(
                "Rhino step",
                "Choose “I finished Rhino Uninstall” or “I don’t use Rhino” below.",
                kind="info",
            )
            return
        if name == "hosts":
            status = core.hosts_running()
            if status["revit"] or status["rhino"]:
                self._modal(
                    "Still open",
                    "Close Revit and Rhino, then click Recheck.",
                    kind="warn",
                )
                return
        if name == "confirm":
            self._start_wipe()
            return
        if name == "done":
            self._close_after_wipe()
            return
        self._show_step(self.step_index + 1)
        if self.STEPS[self.step_index] == "confirm":
            self.btn_next.config(command=self._start_wipe, text="Start uninstall")
            self._update_confirm_state()
        else:
            self.btn_next.config(command=self._next, text="Next")

    def _on_close(self):
        if self._wipe_running:
            self._modal(
                "Please wait",
                "Uninstall is in progress. Closing is disabled until it finishes.",
                kind="info",
            )
            return
        name = self.STEPS[self.step_index]
        if name == "done":
            self._close_after_wipe()
            return
        if name not in ("progress",):
            if not self._modal(
                "Cancel uninstall?",
                "Nothing has been deleted yet. Leave the wizard?",
                kind="confirm",
                yes_text="Leave",
                no_text="Stay",
            ):
                return
        self.destroy()


def main() -> int:
    if core.maybe_relocate_and_relaunch():
        return 0
    app = UninstallWizard()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
