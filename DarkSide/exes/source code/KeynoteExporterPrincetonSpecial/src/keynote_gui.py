#!/usr/bin/env python3
"""
KeynoteExporterPrincetonSpecial GUI - Interface tailored for the PrincetonSpecial workflow.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
from datetime import datetime

# Import the pipeline function
from .keynote_pipeline import run_pipeline


class KeynoteExporterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("EnneadTab PrincetonSpecial Keynote Exporter")
        self.root.resizable(False, False)
        
        # Set icon
        try:
            icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except:
            pass  # Icon not critical, continue without it
        
        # Variables
        self.excel_file_path = tk.StringVar()
        self.output_folder_path = tk.StringVar()
        
        self.setup_ui()
        
        # Ensure the window is tall enough for all widgets
        self.root.update_idletasks()
        min_width = 520
        min_height = 470
        width = max(min_width, self.root.winfo_reqwidth())
        height = max(min_height, self.root.winfo_reqheight())
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(width, height)
        
    def setup_ui(self):
        """Setup the user interface"""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="30")
        main_frame.grid(row=0, column=0, sticky="nsew")
        
        # Title
        title_label = ttk.Label(main_frame, text="EnneadTab PrincetonSpecial Keynote Exporter",
                               font=("Segoe UI", 20, "bold"))
        title_label.grid(row=0, column=0, pady=(0, 30))
        
        # File selection
        ttk.Label(main_frame, text="Select PrincetonSpecial Excel File:", font=("Segoe UI", 10)).grid(row=1, column=0, sticky=tk.W, pady=(0, 10))
        
        file_frame = ttk.Frame(main_frame)
        file_frame.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        
        self.file_entry = ttk.Entry(file_frame, textvariable=self.excel_file_path, width=40, font=("Segoe UI", 9))
        self.file_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        
        browse_button = ttk.Button(file_frame, text="Browse", command=self.browse_file)
        browse_button.grid(row=0, column=1)
        
        # File last modified label
        self.file_modified_label = ttk.Label(main_frame, text="",
                                            font=("Segoe UI", 9), foreground="gray")
        self.file_modified_label.grid(row=3, column=0, sticky=tk.W, pady=(0, 25))

        # Output folder selection
        ttk.Label(main_frame, text="Select PrincetonSpecial Output Folder (optional):", font=("Segoe UI", 10)).grid(row=4, column=0, sticky=tk.W, pady=(0, 10))

        output_frame = ttk.Frame(main_frame)
        output_frame.grid(row=5, column=0, sticky="ew", pady=(0, 5))

        self.output_entry = ttk.Entry(output_frame, textvariable=self.output_folder_path, width=40, font=("Segoe UI", 9))
        self.output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        output_browse_button = ttk.Button(output_frame, text="Browse", command=self.browse_output_folder)
        output_browse_button.grid(row=0, column=1)

        # Output info label
        self.output_info_label = ttk.Label(main_frame, text="Leave empty to use the PrincetonSpecial Excel file's folder.",
                                           font=("Segoe UI", 9), foreground="gray")
        self.output_info_label.grid(row=6, column=0, sticky=tk.W, pady=(0, 15))
        
        # Export button
        export_button = ttk.Button(main_frame, text="Export", command=self.export_data)
        export_button.grid(row=7, column=0, pady=20)
        
        # Progress bar
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate', length=300)
        self.progress.grid(row=8, column=0, pady=10)
        
        # Status label
        self.status_label = ttk.Label(main_frame, text="PrincetonSpecial Ready", foreground="green")
        self.status_label.grid(row=9, column=0, pady=10)
        
        # Simple info
        info_text = "PrincetonSpecial outputs include HTML, keynote TXT, and scope Excel files."
        info_label = ttk.Label(main_frame, text=info_text, justify=tk.CENTER, 
                              font=("Segoe UI", 9), foreground="gray")
        info_label.grid(row=10, column=0, pady=20)
        
        # Configure grid weights
        main_frame.columnconfigure(0, weight=1)
        file_frame.columnconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)
        
    def browse_file(self):
        """Open file dialog to select Excel file"""
        file_path = filedialog.askopenfilename(
            title="Select PrincetonSpecial Excel File",
            filetypes=[("Excel files", "*.xlsx *.xlsm"), ("All files", "*.*")]
        )
        if file_path:
            self.excel_file_path.set(file_path)
            self.status_label.config(text="PrincetonSpecial file selected", foreground="green")
            
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
                    color = "red"
                    age_warning = f" (Warning: {age_days} days old!)"
                elif age_days > 7:
                    color = "orange"
                    age_warning = f" ({age_days} days old)"
                else:
                    color = "gray"
                    age_warning = f" ({age_days} days old)" if age_days > 0 else " (Today)"
                
                self.file_modified_label.config(
                    text=f"Last modified: {date_str}{age_warning}",
                    foreground=color
                )
            except Exception:
                self.file_modified_label.config(
                    text="Unable to read file modification date",
                    foreground="gray"
                )
    def browse_output_folder(self):
        """Open directory dialog to select output folder"""
        folder_path = filedialog.askdirectory(
            title="Select PrincetonSpecial Output Folder"
        )
        if folder_path:
            self.output_folder_path.set(folder_path)
            self.status_label.config(text="PrincetonSpecial output folder selected", foreground="green")

    def export_data(self):
        """Export the keynote data"""
        if not self.excel_file_path.get():
            messagebox.showerror("PrincetonSpecial Error", "Please select a PrincetonSpecial Excel file first.")
            return
        
        if not os.path.exists(self.excel_file_path.get()):
            messagebox.showerror("PrincetonSpecial Error", "Selected PrincetonSpecial file does not exist.")
            return
        
        try:
            # Start progress bar
            self.progress.start()
            self.status_label.config(text="PrincetonSpecial exporting...", foreground="blue")
            self.root.update()
            
            # Change to the KeynoteExporterPrincetonSpecial directory
            original_cwd = os.getcwd()
            exporter_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            os.chdir(exporter_dir)
            
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
            self.status_label.config(text="PrincetonSpecial export completed successfully!", foreground="green")
            
            # Show success message
            messagebox.showinfo(
                "PrincetonSpecial Success",
                "PrincetonSpecial export completed successfully!\n\n"
                f"PrincetonSpecial output files created in:\n{output_dir}\n\n"
                "Created files:\n" + "\n".join(os.path.basename(p) for p in created_files),
            )
            
        except Exception as e:
            self.progress.stop()
            self.status_label.config(text="PrincetonSpecial export failed", foreground="red")
            messagebox.showerror("PrincetonSpecial Error", f"PrincetonSpecial export failed:\n{str(e)}")
        
        finally:
            # Restore original working directory
            os.chdir(original_cwd)


def main():
    """Main function to run the GUI"""
    root = tk.Tk()
    
    # Set the style
    style = ttk.Style()
    style.theme_use('clam')
    
    # Create and run the application
    KeynoteExporterGUI(root)
    
    # Center the window properly
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width - width) // 2
    y = (screen_height - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")
    
    root.mainloop()


if __name__ == "__main__":
    main()