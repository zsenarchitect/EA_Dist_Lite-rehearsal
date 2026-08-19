import hashlib
import os
import json
import shutil
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


class PathShortener:
    def __init__(self, project_root, target_root, lookup_file_name="path_lookup", progress_callback=None):
        self.project_root = project_root
        self.target_root = target_root
        self.lookup_file_name = lookup_file_name
        self.path_lookup = self.load_lookup_table(project_root)
        self.target_lookup_file = os.path.join(target_root, lookup_file_name)
        self.progress_callback = progress_callback
        self.shortened_paths = []  # To track all shortened file paths
        self.total_affected_files = 0  # To track how many files were affected by shortening
        self.copy_errors = []  # To track files that couldn't be copied due to errors

    # Save the lookup table to a data file in both project root and target root with pretty print
    def save_lookup_table(self):
        lookup_file_original = os.path.join(self.project_root, self.lookup_file_name)
        with open(lookup_file_original, "w") as f:
            json.dump(self.path_lookup, f, indent=4)  # Pretty-printing the JSON

        with open(self.target_lookup_file, "w") as f:
            json.dump(self.path_lookup, f, indent=4)  # Pretty-printing the JSON

    # Load the lookup table from a data file if exists, otherwise return an empty dict
    def load_lookup_table(self, path):
        lookup_file = os.path.join(path, self.lookup_file_name)
        if not os.path.exists(lookup_file):
            return {}
        with open(lookup_file, "r") as f:
            return json.load(f)

    # Shorten the middle path part after the first two folder levels
    def shorten_middle_path_hash(self, full_path):
        # Extract the part after the project root
        relative_path = os.path.relpath(full_path, self.project_root)
        path_parts = relative_path.split(os.sep)
        
        # Only shorten paths deeper than two levels (ignoring the first two levels)
        if len(path_parts) <= 3:
            # If it's within two levels, return as is (don't shorten)
            return os.path.join(self.target_root, relative_path)
        
        # For paths deeper than two levels, hash the middle part
        root_levels = os.path.join(self.target_root, path_parts[0], path_parts[1])
        middle_part = os.sep.join(path_parts[2:-1])
        final_name = path_parts[-1]
        
        # Shorten the middle part using a hash
        short_hash = hashlib.sha256(middle_part.encode()).hexdigest()[:10]

        # Store the original middle part in the dictionary
        self.path_lookup[short_hash] = middle_part

        # Return the new shortened path
        shortened_path = os.path.join(root_levels, short_hash, final_name)

        # Add to shortened paths and increase the affected file count
        self.shortened_paths.append(shortened_path)
        self.total_affected_files += 1
        
        return shortened_path

    # Copy all project files and folders, shortening where necessary, and handle errors
    def copy_project_files(self):
        file_count = sum(len(files) for _, _, files in os.walk(self.project_root))
        copied_count = 0

        for root, dirs, files in os.walk(self.project_root):
            for file_name in files:
                full_file_path = os.path.join(root, file_name)
                
                try:
                    # Get the shortened path (if necessary)
                    new_file_path = self.shorten_middle_path_hash(full_file_path)
                    
                    # Create necessary directories in the target folder
                    new_file_dir = os.path.dirname(new_file_path)
                    os.makedirs(new_file_dir, exist_ok=True)

                    # Copy the file to the new location
                    shutil.copyfile(full_file_path, new_file_path)
                    
                    # Update the progress bar
                    copied_count += 1
                    if self.progress_callback:
                        self.progress_callback(copied_count, file_count)

                except Exception as e:
                    # If an error occurs (like permission denied), log the file path
                    self.copy_errors.append(f"Error copying {full_file_path}: {e}")

        # Save the lookup table in both the original and new project directories
        self.save_lookup_table()
        return copied_count  # Return total copied files count


# Tkinter UI for selecting project and target folders
class PathShortenerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Project Path Shortener")
        
        # Set up UI components
        self.create_widgets()

    def create_widgets(self):
        # Show Details button (moved to top)
        self.button_details = tk.Button(self.root, text="Show Details", command=self.show_details)
        self.button_details.grid(row=0, column=1, pady=10)

        # Labels and textboxes for project folder (using Text widget for wrapping)
        self.label_project_folder = tk.Label(self.root, text="Select Project Folder:")
        self.label_project_folder.grid(row=1, column=0, padx=10, pady=10)

        self.text_project_folder = tk.Text(self.root, wrap=tk.WORD, width=50, height=2)
        self.text_project_folder.grid(row=1, column=1, padx=10, pady=10)

        self.button_project_folder = tk.Button(self.root, text="Browse", command=self.select_project_folder)
        self.button_project_folder.grid(row=1, column=2, padx=10, pady=10)

        # Labels and textboxes for target folder (using Text widget for wrapping)
        self.label_target_folder = tk.Label(self.root, text="Select Target Folder:")
        self.label_target_folder.grid(row=2, column=0, padx=10, pady=10)

        self.text_target_folder = tk.Text(self.root, wrap=tk.WORD, width=50, height=2)
        self.text_target_folder.grid(row=2, column=1, padx=10, pady=10)

        self.button_target_folder = tk.Button(self.root, text="Browse", command=self.select_target_folder)
        self.button_target_folder.grid(row=2, column=2, padx=10, pady=10)

        # Run button
        self.button_run = tk.Button(self.root, text="Start Copying", command=self.run_shortener)
        self.button_run.grid(row=3, column=1, pady=10)

        # Progress bar
        self.progress = ttk.Progressbar(self.root, orient="horizontal", length=400, mode="determinate")
        self.progress.grid(row=4, column=0, columnspan=3, padx=10, pady=10)

        # Progress label for displaying copied file count
        self.label_progress = tk.Label(self.root, text="0/0 Files Copied")
        self.label_progress.grid(row=5, column=0, columnspan=3, padx=10, pady=10)

    def select_project_folder(self):
        # Open a dialog to select the original project folder
        project_folder = filedialog.askdirectory(title="Select Project Folder")
        self.text_project_folder.delete(1.0, tk.END)
        self.text_project_folder.insert(tk.END, project_folder)

    def select_target_folder(self):
        # Open a dialog to select the target folder
        target_folder = filedialog.askdirectory(title="Select Target Folder")
        self.text_target_folder.delete(1.0, tk.END)
        self.text_target_folder.insert(tk.END, target_folder)

    def update_progress(self, copied_count, total_count):
        # Update the progress bar based on the number of files copied
        progress_value = (copied_count / total_count) * 100
        self.progress['value'] = progress_value
        self.label_progress.config(text=f"{copied_count}/{total_count} Files Copied")
        self.root.update_idletasks()

    def show_final_report(self, total_copied, total_affected, shortened_paths, lookup_file, time_elapsed, copy_errors):
        # Create a Toplevel window for the final report
        report_window = tk.Toplevel(self.root)
        report_window.title("Final Report")

        report_text = f"Total Files Copied: {total_copied}\n"
        report_text += f"Total Files Affected (Shortened): {total_affected}\n"
        report_text += f"Lookup Table Location: {lookup_file}\n"
        report_text += f"Total Time Used: {time_elapsed:.2f} seconds\n\n"
        report_text += "Shortened File Paths:\n" + "\n".join(shortened_paths)

        report_label = tk.Text(report_window, wrap=tk.WORD, width=80, height=25)
        report_label.insert(tk.END, report_text)

        if copy_errors:
            report_label.insert(tk.END, "\n\nErrors:\n", "error")
            for error in copy_errors:
                report_label.insert(tk.END, f"{error}\n", "error")

        report_label.tag_config("error", foreground="red")
        report_label.config(state=tk.DISABLED)
        report_label.pack(padx=10, pady=10)

    def show_details(self):
        # Display a pop-up window with detailed features
        details_window = tk.Toplevel(self.root)
        details_window.title("Detailed Features")

        details_text = (
            "This program copies files from a project folder to a target folder, while:\n"
            "- Shortening file paths for files deeper than two levels.\n"
            "- Storing a lookup table with mappings of original to shortened paths.\n"
            "- Tracking progress with a visual progress bar.\n"
            "- Providing a detailed final report with total files copied, affected, and time taken."
        )

        label_details = tk.Text(details_window, wrap=tk.WORD, width=80, height=10)
        label_details.insert(tk.END, details_text)
        label_details.config(state=tk.DISABLED)
        label_details.pack(padx=10, pady=10)

    def run_shortener(self):
        # Get the project and target folder paths from the entries
        project_folder = self.text_project_folder.get(1.0, tk.END).strip()
        target_folder = self.text_target_folder.get(1.0, tk.END).strip()

        if not project_folder or not target_folder:
            messagebox.showerror("Error", "Please select both the project and target folders.")
            return

        # Initialize the PathShortener
        path_shortener = PathShortener(project_folder, target_folder, progress_callback=self.update_progress)

        # Copy files and shorten paths
        try:
            self.progress['value'] = 0  # Reset the progress bar
            start_time = time.time()  # Start the timer
            total_copied = path_shortener.copy_project_files()
            end_time = time.time()  # End the timer
            time_elapsed = end_time - start_time

            # Show final report
            self.show_final_report(
                total_copied=total_copied,
                total_affected=path_shortener.total_affected_files,
                shortened_paths=path_shortener.shortened_paths,
                lookup_file=path_shortener.target_lookup_file,
                time_elapsed=time_elapsed,
                copy_errors=path_shortener.copy_errors
            )

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {str(e)}")


# Run the Tkinter application
if __name__ == "__main__":
    root = tk.Tk()
    app = PathShortenerApp(root)
    root.mainloop()
