#!/usr/bin/env python3
"""
KeynoteExporter GUI - Simple interface for the KeynoteExporter application
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
from datetime import datetime

# Import the pipeline function
from . import __version__
from .keynote_pipeline import run_pipeline
from .keynote_config import (
    KeynoteConfig,
    set_runtime_notes_suffix_override,
    set_runtime_notes_mode_override,
)


# Curated list of whitespace-like characters for NOTES markers.
# Based on common Unicode whitespace characters listed on emptycharacter.com,
# excluding line separators (which would break the TSV line structure).
# Zero-width space (U+200B) is the default and shown first.
WHITESPACE_MARKER_OPTIONS = [
    ("Zero-width space (U+200B)", "\u200b"),
    ("Hair space (U+200A)", "\u200a"),
    ("Thin space (U+2009)", "\u2009"),
    ("Six-per-em space (U+2006)", "\u2006"),
    ("Figure space (U+2007)", "\u2007"),
    ("Punctuation space (U+2008)", "\u2008"),
    ("Three-per-em space (U+2004)", "\u2004"),
    ("Four-per-em space (U+2005)", "\u2005"),
    ("En space (U+2002)", "\u2002"),
    ("Em space (U+2003)", "\u2003"),
    ("Medium mathematical space (U+205F)", "\u205f"),
    ("Ideographic space (U+3000)", "\u3000"),
    ("Zero-width non-joiner (U+200C)", "\u200c"),
    ("Zero-width joiner (U+200D)", "\u200d"),
    ("No-break space (U+00A0)", "\u00a0"),
]


# Modern dark palette - matches the startup splash screen.
PALETTE = {
    "bg":            "#1f2430",  # window background (same as splash)
    "surface":       "#272d3a",  # raised surfaces: entries, comboboxes
    "border":        "#3a4250",
    "accent":        "#5b9dff",  # primary accent (same blue as the splash bar)
    "accent_active": "#74acff",
    "text":          "#eceff4",
    "muted":         "#8a93a6",
    "ok":            "#4ade80",
    "warn":          "#fbbf24",
    "err":           "#f87171",
    "info":          "#60a5fa",
}


def apply_modern_theme(root):
    """Apply a cohesive dark theme to all ttk widgets (matches the splash look)."""
    P = PALETTE
    root.configure(bg=P["bg"])
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=P["bg"], foreground=P["text"],
                    fieldbackground=P["surface"], font=("Segoe UI", 10))
    style.configure("TFrame", background=P["bg"])
    style.configure("TLabel", background=P["bg"], foreground=P["text"])
    style.configure("Title.TLabel", background=P["bg"], foreground=P["text"],
                    font=("Segoe UI", 20, "bold"))

    # Secondary buttons
    style.configure("TButton", background=P["surface"], foreground=P["text"],
                    bordercolor=P["border"], focuscolor=P["accent"],
                    padding=(14, 8), font=("Segoe UI", 10))
    style.map("TButton",
              background=[("active", P["border"]), ("pressed", P["border"])],
              bordercolor=[("focus", P["accent"])])
    # Primary (accent) button
    style.configure("Accent.TButton", background=P["accent"], foreground="#10131a",
                    bordercolor=P["accent"], padding=(20, 8), font=("Segoe UI", 10, "bold"))
    style.map("Accent.TButton",
              background=[("active", P["accent_active"]), ("pressed", P["accent_active"])])

    # Inputs
    style.configure("TEntry", fieldbackground=P["surface"], foreground=P["text"],
                    bordercolor=P["border"], insertcolor=P["text"], padding=6)
    style.map("TEntry", bordercolor=[("focus", P["accent"])])
    style.configure("TCombobox", fieldbackground=P["surface"], background=P["surface"],
                    foreground=P["text"], arrowcolor=P["text"], bordercolor=P["border"], padding=5)
    style.map("TCombobox",
              fieldbackground=[("readonly", P["surface"])],
              foreground=[("readonly", P["text"])],
              bordercolor=[("focus", P["accent"])])

    # Grouping + selection controls
    style.configure("TLabelframe", background=P["bg"], bordercolor=P["border"])
    style.configure("TLabelframe.Label", background=P["bg"], foreground=P["muted"],
                    font=("Segoe UI", 9, "bold"))
    style.configure("TRadiobutton", background=P["bg"], foreground=P["text"], font=("Segoe UI", 10))
    style.map("TRadiobutton",
              background=[("active", P["bg"])],
              indicatorcolor=[("selected", P["accent"])])

    # Progress bar
    style.configure("TProgressbar", background=P["accent"], troughcolor=P["surface"],
                    bordercolor=P["bg"], lightcolor=P["accent"], darkcolor=P["accent"])
    return style


class KeynoteExporterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("EnneadTab Keynote Exporter  v{}".format(__version__))
        # Final size is computed from content in main() (never crop); keep a
        # reasonable floor here in case the GUI is created on its own.
        self.root.minsize(520, 600)
        self.root.resizable(True, True)
        
        # Set the window/taskbar icon. In a frozen onefile build the bundled files
        # live under sys._MEIPASS; in dev they sit next to the source. icon.ico must
        # be bundled at the root (--add-data icon.ico;.) for the taskbar icon to show,
        # and AppUserModelID must be set (see startup.set_app_user_model_id) so Windows
        # does not fall back to the host interpreter's generic icon.
        try:
            import sys
            base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            icon_path = os.path.join(base, "icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass  # Icon not critical, continue without it
        
        # Variables
        self.excel_file_path = tk.StringVar()
        self.output_folder_path = tk.StringVar()
        # NOTES marker configuration (whitespace or text prefix)
        try:
            config = KeynoteConfig()
            default_marker = config.get_notes_format_suffix()
        except Exception:
            # Fallback to zero-width space (U+200B) if config cannot be loaded
            default_marker = "\u200b"

        # Track the active marker string and how it is applied.
        # mode: "whitespace" (suffix) or "text" (prefix like "NOTE:")
        self._notes_marker_string = default_marker
        self.notes_mode_var = tk.StringVar(value="whitespace")

        # Map label -> char for whitespace options
        self._marker_label_to_char = {label: ch for (label, ch) in WHITESPACE_MARKER_OPTIONS}
        # Pick default label based on config, or fall back to hair space
        default_label = None
        for label, ch in WHITESPACE_MARKER_OPTIONS:
            if ch == default_marker:
                default_label = label
                break
        if default_label is None:
            default_label = WHITESPACE_MARKER_OPTIONS[0][0]
        self.notes_whitespace_label_var = tk.StringVar(value=default_label)
        # Custom text prefix (used when mode == "text")
        self.notes_custom_prefix_var = tk.StringVar(value="NOTE:")

        # Precompute initial button text based on marker
        self._copy_notes_button_text = self._make_copy_button_text(self._notes_marker_string)
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the user interface"""
        # Main frame (stretch with window so content is not cropped)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame = ttk.Frame(self.root, padding="30")
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        # Title
        title_label = ttk.Label(main_frame, text="EnneadTab Keynote Exporter",
                               style="Title.TLabel")
        title_label.grid(row=0, column=0, pady=(0, 30))
        
        # File selection
        ttk.Label(main_frame, text="Select Excel File:", font=("Segoe UI", 10)).grid(row=1, column=0, sticky=tk.W, pady=(0, 10))
        
        file_frame = ttk.Frame(main_frame)
        file_frame.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        
        self.file_entry = ttk.Entry(file_frame, textvariable=self.excel_file_path, width=40, font=("Segoe UI", 9))
        self.file_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        
        browse_button = ttk.Button(file_frame, text="Browse", command=self.browse_file)
        browse_button.grid(row=0, column=1)
        
        # File last modified label (tk.Label so we can set fg at runtime)
        self.file_modified_label = tk.Label(main_frame, text="", font=("Segoe UI", 9),
                                            bg=PALETTE["bg"], fg=PALETTE["muted"])
        self.file_modified_label.grid(row=3, column=0, sticky=tk.W, pady=(0, 25))

        # Output folder selection
        ttk.Label(main_frame, text="Select Output Folder (optional):", font=("Segoe UI", 10)).grid(row=4, column=0, sticky=tk.W, pady=(0, 10))

        output_frame = ttk.Frame(main_frame)
        output_frame.grid(row=5, column=0, sticky="ew", pady=(0, 5))

        self.output_entry = ttk.Entry(output_frame, textvariable=self.output_folder_path, width=40, font=("Segoe UI", 9))
        self.output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        output_browse_button = ttk.Button(output_frame, text="Browse", command=self.browse_output_folder)
        output_browse_button.grid(row=0, column=1)

        # Output info label
        self.output_info_label = tk.Label(main_frame, text="Leave empty to use the Excel file's folder.",
                                          font=("Segoe UI", 9), bg=PALETTE["bg"], fg=PALETTE["muted"])
        self.output_info_label.grid(row=6, column=0, sticky=tk.W, pady=(0, 15))
        
        # Export and Copy NOTES marker buttons
        action_frame = ttk.Frame(main_frame)
        action_frame.grid(row=7, column=0, pady=(10, 5))
        export_button = ttk.Button(action_frame, text="Export", command=self.export_data, style="Accent.TButton")
        export_button.grid(row=0, column=0, padx=(0, 10))
        self.copy_notes_char_btn = ttk.Button(
            action_frame,
            text=self._copy_notes_button_text,
            command=self.copy_notes_char,
        )
        self.copy_notes_char_btn.grid(row=0, column=1)
        self.root.bind("<Control-m>", lambda e: self.copy_notes_char())
        # NOTES marker options (whitespace vs custom prefix)
        marker_frame = ttk.LabelFrame(main_frame, text="NOTES key marker")
        marker_frame.grid(row=8, column=0, sticky="ew", pady=(10, 5))

        # Radio: whitespace marker (suffix)
        whitespace_radio = ttk.Radiobutton(
            marker_frame,
            text="Use whitespace marker (suffix):",
            variable=self.notes_mode_var,
            value="whitespace",
            command=self._on_notes_marker_changed,
        )
        whitespace_radio.grid(row=0, column=0, sticky="w")

        whitespace_combo = ttk.Combobox(
            marker_frame,
            textvariable=self.notes_whitespace_label_var,
            state="readonly",
            values=[label for (label, _ch) in WHITESPACE_MARKER_OPTIONS],
            width=40,
        )
        whitespace_combo.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        whitespace_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_notes_marker_changed())

        # Radio: text prefix (e.g. NOTE:123)
        text_radio = ttk.Radiobutton(
            marker_frame,
            text="Use text prefix (e.g. NOTE:123):",
            variable=self.notes_mode_var,
            value="text",
            command=self._on_notes_marker_changed,
        )
        text_radio.grid(row=1, column=0, sticky="w", pady=(5, 0))

        text_entry = ttk.Entry(
            marker_frame,
            textvariable=self.notes_custom_prefix_var,
            width=40,
        )
        text_entry.grid(row=1, column=1, sticky="ew", padx=(5, 0), pady=(5, 0))

        marker_frame.columnconfigure(1, weight=1)

        # Progress bar
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate', length=300)
        self.progress.grid(row=9, column=0, pady=10)
        
        # Status label (tk.Label so we can change foreground at runtime; ttk.Label does not support config(foreground=) on all platforms)
        self.status_label = tk.Label(main_frame, text="Ready", bg=PALETTE["bg"], fg=PALETTE["ok"], font=("Segoe UI", 9))
        self.status_label.grid(row=10, column=0, pady=10)
        
        # Simple info
        info_text = "Outputs include HTML, keynote TXT, and scope Excel files."
        info_label = tk.Label(main_frame, text=info_text, justify=tk.CENTER,
                              font=("Segoe UI", 9), bg=PALETTE["bg"], fg=PALETTE["muted"])
        info_label.grid(row=11, column=0, pady=20)
        
        # Configure grid weights so layout expands and doesn't crop
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(11, weight=1)
        file_frame.columnconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)
        
    def browse_file(self):
        """Open file dialog to select Excel file"""
        file_path = filedialog.askopenfilename(
            title="Select Excel File",
            filetypes=[("Excel files", "*.xlsx *.xlsm"), ("All files", "*.*")]
        )
        if file_path:
            self.excel_file_path.set(file_path)
            self.status_label.config(text="File selected", fg=PALETTE["ok"])
            
            # Display last modified timestamp
            try:
                modified_timestamp = os.path.getmtime(file_path)
                modified_date = datetime.fromtimestamp(modified_timestamp)
                
                # Calculate how old the file is
                now = datetime.now()
                age_days = (now - modified_date).days
                
                # Format the date string
                date_str = modified_date.strftime("%Y-%m-%d %I:%M %p")
                
                # Color code based on age (red if > 30 days, orange if > 7 days)
                if age_days > 30:
                    color = PALETTE["err"]
                    age_warning = f" (Warning: {age_days} days old!)"
                elif age_days > 7:
                    color = PALETTE["warn"]
                    age_warning = f" ({age_days} days old)"
                else:
                    color = PALETTE["muted"]
                    age_warning = f" ({age_days} days old)" if age_days > 0 else " (Today)"
                
                self.file_modified_label.config(
                    text=f"Last modified: {date_str}{age_warning}",
                    fg=color
                )
            except Exception:
                self.file_modified_label.config(
                    text="Unable to read file modification date",
                    fg=PALETTE["muted"]
                )
    def browse_output_folder(self):
        """Open directory dialog to select output folder"""
        folder_path = filedialog.askdirectory(
            title="Select Output Folder"
        )
        if folder_path:
            self.output_folder_path.set(folder_path)
            self.status_label.config(text="Output folder selected", fg=PALETTE["ok"])

    def _make_copy_button_text(self, marker: str) -> str:
        """Build user-facing label for the NOTES copy button based on marker string."""
        if not marker:
            return "Copy NOTES marker"
        if len(marker) == 1:
            # Single code point: show as U+XXXX
            code_hex = format(ord(marker), "04X")
            return f"Copy NOTES char (U+{code_hex})"
        # Multi-character text prefix
        display = marker
        if len(display) > 8:
            display = display[:8] + "..."
        return f'Copy NOTES text ("{display}")'

    def _get_current_notes_marker_string(self) -> str:
        """Compute the marker string based on current UI settings."""
        mode = self.notes_mode_var.get()
        if mode == "text":
            return self.notes_custom_prefix_var.get() or ""
        # Whitespace mode (suffix)
        label = self.notes_whitespace_label_var.get()
        marker = self._marker_label_to_char.get(label)
        if marker:
            return marker
        # Fallback to hair space
        return WHITESPACE_MARKER_OPTIONS[0][1]

    def _on_notes_marker_changed(self):
        """Update internal marker string and button label when UI selection changes."""
        self._notes_marker_string = self._get_current_notes_marker_string()
        # Update copy button UI
        new_text = self._make_copy_button_text(self._notes_marker_string)
        self.copy_notes_char_btn.config(text=new_text)

    def copy_notes_char(self):
        """Copy the NOTES marker (whitespace or text prefix) to clipboard for Revit schedule filters."""
        try:
            marker = self._get_current_notes_marker_string()
            if not marker:
                messagebox.showerror("Error", "No NOTES marker is configured.")
                return
            self.root.clipboard_clear()
            self.root.clipboard_append(marker)
            self.root.update_idletasks()
            orig_text = self.copy_notes_char_btn.cget("text")
            self.copy_notes_char_btn.config(text="Copied!")
            self.status_label.config(text="Copied NOTES marker to clipboard.", fg=PALETTE["ok"])
            self.root.after(1500, lambda: self.copy_notes_char_btn.config(text=orig_text))
        except Exception as e:
            messagebox.showerror("Error", "Copy failed: %s" % e)

    def export_data(self):
        """Export the keynote data"""
        if not self.excel_file_path.get():
            messagebox.showerror("Error", "Please select an Excel file first.")
            return
        
        if not os.path.exists(self.excel_file_path.get()):
            messagebox.showerror("Error", "Selected file does not exist.")
            return
        
        try:
            # Start progress bar
            self.progress.start()
            self.status_label.config(text="Exporting...", fg=PALETTE["info"])
            self.root.update()
            
            # Change to the KeynoteExporter directory
            original_cwd = os.getcwd()
            exporter_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            os.chdir(exporter_dir)
            
            # Configure NOTES marker overrides for this run
            marker = self._get_current_notes_marker_string()
            mode = self.notes_mode_var.get()
            # mode: "whitespace" => suffix, "text" => prefix
            if marker:
                if mode == "text":
                    set_runtime_notes_mode_override("prefix")
                else:
                    set_runtime_notes_mode_override("suffix")
                set_runtime_notes_suffix_override(marker)
            else:
                # Reset to YAML-configured defaults
                set_runtime_notes_mode_override(None)
                set_runtime_notes_suffix_override(None)

            # Run the pipeline
            selected_output = self.output_folder_path.get().strip()
            if selected_output:
                os.makedirs(selected_output, exist_ok=True)
                output_dir = selected_output
            else:
                output_dir = os.path.dirname(self.excel_file_path.get())

            result = run_pipeline(self.excel_file_path.get(), output_dir=output_dir)
            output_dir = result.get("output_dir", output_dir)
            created_files = result.get("files", [])
            if not created_files:
                raise RuntimeError("Pipeline completed without generating any files.")
            missing_files = [path for path in created_files if not os.path.exists(path)]
            if missing_files:
                raise FileNotFoundError(
                    "Some expected files were not created:\n" + "\n".join(missing_files)
                )
            if not os.path.isdir(output_dir):
                raise FileNotFoundError(f"Output directory not found: {output_dir}")
            
            # Stop progress bar
            self.progress.stop()
            self.status_label.config(text="Export completed successfully!", fg=PALETTE["ok"])
            
            # Show success message
            messagebox.showinfo(
                "Success",
                "Export completed successfully!\n\n"
                f"Output files created in:\n{output_dir}\n\n"
                "Created files:\n" + "\n".join(os.path.basename(p) for p in created_files),
            )
            
        except Exception as e:
            self.progress.stop()
            self.status_label.config(text="Export failed", fg=PALETTE["err"])
            messagebox.showerror("Error", f"Export failed:\n{str(e)}")
        
        finally:
            # Restore original working directory
            os.chdir(original_cwd)


def main():
    """Main function to run the GUI"""
    root = tk.Tk()

    # Apply the modern dark theme (matches the splash screen)
    apply_modern_theme(root)

    # Create and run the application
    KeynoteExporterGUI(root)
    
    # Size the window to fit its content so nothing is cropped, then center it.
    # winfo_reqheight() is the natural height the laid-out widgets need; the floors
    # just guard against an unusually small report.
    root.update_idletasks()
    width = max(root.winfo_reqwidth(), 540)
    height = max(root.winfo_reqheight(), 620)
    root.minsize(width, height)  # never allow shrinking below the content
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - width) // 2
    y = max((screen_height - height) // 2, 0)
    root.geometry(f"{width}x{height}+{x}+{y}")

    # The window is built and positioned - paint it, then close the PyInstaller
    # splash so the user never sees a gap between the splash and the real window.
    root.update()
    try:
        import pyi_splash
        if pyi_splash.is_alive():
            pyi_splash.close()
    except Exception:
        pass

    root.mainloop()


if __name__ == "__main__":
    main()