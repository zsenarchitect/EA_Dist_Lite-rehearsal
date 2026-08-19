import tkinter as tk
from tkinter import filedialog, messagebox

from pathlib import Path
import _Exe_Util
import time  # Add this at the top with other imports

class EnscapeRenamer:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Enscape Image Renamer")
        self.window.geometry("600x400")
        self.setup_gui()

    def setup_gui(self):
        # Main frame with padding
        main_frame = tk.Frame(self.window, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Instructions
        instructions = tk.Label(
            main_frame, 
            text="Select Enscape images to rename.\nWill remove 'Enscape_YYYY-MM-DD-HH-MM-SS_' prefix.",
            pady=10
        )
        instructions.pack(fill=tk.X)

        # Select files button
        select_btn = tk.Button(
            main_frame,
            text="Select Images",
            command=self.select_files,
            padx=20,
            pady=10
        )
        select_btn.pack(fill=tk.X, pady=5)

        # Rename button
        rename_btn = tk.Button(
            main_frame,
            text="Rename Files",
            command=self.rename_files,
            padx=20,
            pady=5
        )
        rename_btn.pack(fill=tk.X, pady=20)
        # Create a frame to contain the listbox and scrollbars
        list_frame = tk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=10)

        # Add scrollbars
        y_scrollbar = tk.Scrollbar(list_frame)
        y_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        x_scrollbar = tk.Scrollbar(list_frame, orient=tk.HORIZONTAL)
        x_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        # List box for selected files with scrollbars
        self.file_list = tk.Listbox(
            list_frame, 
            width=70, 
            height=15,
            xscrollcommand=x_scrollbar.set,
            yscrollcommand=y_scrollbar.set
        )
        self.file_list.pack(fill=tk.BOTH, expand=True)

        # Configure scrollbars
        x_scrollbar.config(command=self.file_list.xview)
        y_scrollbar.config(command=self.file_list.yview)


    def select_files(self):
        files = filedialog.askopenfilenames(
            title="Select Enscape Images",
            filetypes=[("Image files", "*.png *.jpg *.jpeg")]
        )
        self.file_list.delete(0, tk.END)
        for file in files:
            self.file_list.insert(tk.END, file)

    def rename_files(self):
        files = list(self.file_list.get(0, tk.END))
        if not files:
            messagebox.showwarning("No Files", "Please select files first!")
            return

        # Sort files by modification time (oldest first)
        files.sort(key=lambda x: Path(x).stat().st_mtime)

        for file_path in files:
            try:
                # Add small delay between operations
                time.sleep(0.1)  # 100ms delay
                
                # Convert to raw string and create Path object
                path = Path(str(file_path).strip())
                path = path.absolute()  # Get absolute path
                
                # Get new name by removing Enscape prefix
                new_name = path.name
                if new_name.startswith("Enscape_"):
                    new_name = new_name.split("_", 2)[-1]
                
                new_path = path.parent / new_name

                # Check if file exists
                if new_path.exists():
                    response = messagebox.askyesno(
                        "File Exists",
                        f"{new_name} already exists.\nDo you want to override?"
                    )
                    if not response:
                        continue
                    try:
                        new_path.unlink()  # Delete the existing file
                    except Exception as e:
                        messagebox.showerror(
                            "Error",
                            f"Failed to delete existing file {new_name}\nError: {str(e)}"
                        )
                        continue

                # Use string paths for rename operation
                path.rename(str(new_path))
            except Exception as e:
                messagebox.showerror(
                    "Error",
                    f"Failed to rename {path.name}\nError: {str(e)}"
                )
                continue

        messagebox.showinfo("Success", "Renaming completed!")
        self.file_list.delete(0, tk.END)


    def main(self):
        self.window.mainloop()

@_Exe_Util.try_catch_error
def main():
    app = EnscapeRenamer()
    app.main()


if __name__ == "__main__":
    main()