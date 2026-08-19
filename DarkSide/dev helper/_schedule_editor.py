import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union, Any, Callable
from DarkSide.exes.source_code._Exe_Util import get_openai_api_key, list_api_keys
import openai
from openai import OpenAI
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import statistics
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

class DocstringUpdater:
    """A class for updating Python docstrings using OpenAI's API.
    
    This class provides functionality to analyze Python scripts and generate
    appropriate docstrings following the Rhino script style.
    """
    
    # Class-level configuration
    LOG_FILE: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docstring_changes.log")
    PROGRESS_LOG_FILE: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docstring_progress.log")
    DEFAULT_CONFIG: Dict[str, Any] = {
        "model": "gpt-4-turbo-preview",
        "temperature": 0.7,
        "max_tokens": 1000,
        "system_prompt": "You are a Python documentation expert. Generate clear, concise docstrings following the Rhino script style with Features and Usage sections. Avoid using f-strings in docstrings for Python 2 compatibility.",
        "max_workers": 4  # For parallel processing
    }

    def __init__(self, file_path: Optional[str] = None, progress_callback: Optional[Callable[[str], None]] = None) -> None:
        """Initialize the DocstringUpdater.
        
        Args:
            file_path: Optional path to the Python file to update
            progress_callback: Optional callback function to report progress
        """
        self.file_path: Optional[str] = file_path
        self.content: Optional[str] = None
        self.api_key: Optional[str] = None
        self.client: Optional[OpenAI] = None
        self.suggested_docstring: Optional[str] = None
        self.lines: Optional[List[str]] = None
        self.title_start: int = -1
        self.docstring_start: int = -1
        self.docstring_end: int = -1
        self.original_docstring: Optional[str] = None
        self.config: Dict[str, Any] = self.DEFAULT_CONFIG.copy()
        self.progress_callback: Optional[Callable[[str], None]] = progress_callback
        self.setup_logging()

    def setup_logging(self) -> None:
        """Set up logging configuration."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.PROGRESS_LOG_FILE),
                logging.StreamHandler()
            ]
        )

    def log_progress(self, message: str) -> None:
        """Log progress message.
        
        Args:
            message: Progress message to log
        """
        logging.info(message)
        if self.progress_callback:
            self.progress_callback(message)

    def read_file_content(self) -> None:
        """Read the file content and split into lines."""
        if not self.file_path:
            raise ValueError("File path not set")
            
        with open(self.file_path, 'r', encoding='utf-8') as f:
            self.content = f.read()
        self.lines = self.content.split('\n')

    def get_openai_api_key(self) -> Optional[str]:
        """Get OpenAI API key from helper.
        
        Returns:
            Optional[str]: Error message if API key not found, None if successful
        """
        self.api_key = get_openai_api_key("EnneadTabAPI")
        if not self.api_key:
            api_keys = list_api_keys()
            return "Error: Could not get OpenAI API key. Available keys: {}".format(api_keys)
        return None

    def setup_openai_client(self) -> None:
        """Set up OpenAI client with the API key."""
        if not self.api_key:
            raise ValueError("API key not set")
        self.client = OpenAI(api_key=self.api_key)

    def prepare_prompt(self) -> str:
        """Prepare the prompt for OpenAI.
        
        Returns:
            str: Formatted prompt for OpenAI
        """
        if not self.content:
            raise ValueError("File content not loaded")
            
        return """Analyze this Python script and generate a docstring in the following format:

```python
__title__ = "[Script Title]"
__doc__ = \"\"\"[Brief description of what the script does]

Features:
- Feature 1
- Feature 2
...

Usage:
1. Step 1
2. Step 2
...\"\"\"

Here is the script to analyze:
{}
""".format(self.content)

    def get_openai_response(self) -> None:
        """Get response from OpenAI and store the suggested docstring."""
        if not self.client:
            raise ValueError("OpenAI client not initialized")
            
        response = self.client.chat.completions.create(
            model=self.config["model"],
            messages=[
                {"role": "system", "content": self.config["system_prompt"]},
                {"role": "user", "content": self.prepare_prompt()}
            ],
            temperature=self.config["temperature"],
            max_tokens=self.config["max_tokens"]
        )
        self.suggested_docstring = response.choices[0].message.content.strip()

    def validate_docstring(self) -> Optional[str]:
        """Validate the docstring format.
        
        Returns:
            Optional[str]: Error message if validation fails, None if successful
        """
        if not self.suggested_docstring:
            return "Error: No docstring generated"
            
        if '__title__' not in self.suggested_docstring or '__doc__' not in self.suggested_docstring:
            return "Error: Invalid docstring format from OpenAI"
        return None

    def find_existing_docstring(self) -> None:
        """Find the existing docstring in the file."""
        if not self.lines:
            raise ValueError("File lines not loaded")
            
        for i, line in enumerate(self.lines):
            if '__title__' in line:
                self.title_start = i
            if '__doc__' in line and '"""' in line:
                self.docstring_start = i
                # Find the end of the docstring
                for j in range(i + 1, len(self.lines)):
                    if '"""' in self.lines[j]:
                        self.docstring_end = j
                        break
                # Store original docstring for logging
                self.original_docstring = '\n'.join(self.lines[self.docstring_start:self.docstring_end + 1])
                break

    def replace_or_insert_docstring(self) -> List[str]:
        """Replace or insert the docstring in the file content.
        
        Returns:
            List[str]: Updated file lines with new docstring
        """
        if not self.lines or not self.suggested_docstring:
            raise ValueError("File content or docstring not loaded")
            
        if self.title_start != -1 and self.docstring_start != -1 and self.docstring_end != -1:
            # Replace existing title and docstring
            return (self.lines[:self.title_start] + 
                   [self.suggested_docstring.split('\n')[0]] + 
                   [''] + 
                   [self.suggested_docstring.split('\n')[1]] + 
                   self.lines[self.docstring_end + 1:])
        else:
            # Insert new title and docstring after imports
            import_end = 0
            for i, line in enumerate(self.lines):
                if line.startswith('import ') or line.startswith('from '):
                    import_end = i
            return (self.lines[:import_end + 1] + 
                   [''] + 
                   [self.suggested_docstring.split('\n')[0]] + 
                   [''] + 
                   [self.suggested_docstring.split('\n')[1]] + 
                   self.lines[import_end + 1:])

    def write_to_file(self, new_lines: List[str]) -> None:
        """Write the updated content back to the file.
        
        Args:
            new_lines: List of lines to write to the file
        """
        if not self.file_path:
            raise ValueError("File path not set")
            
        with open(self.file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(new_lines))

    def log_change(self, status: str = "approved") -> None:
        """Log the docstring change to a JSON file.
        
        Args:
            status: Status of the change (approved/rejected)
        """
        if not self.original_docstring or not self.suggested_docstring:
            raise ValueError("Original or new docstring not set")
            
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "file": self.file_path,
            "original": self.original_docstring,
            "new": self.suggested_docstring,
            "status": status
        }
        
        # Create log file if it doesn't exist
        if not os.path.exists(self.LOG_FILE):
            with open(self.LOG_FILE, 'w') as f:
                json.dump([], f)
        
        # Read existing log entries
        with open(self.LOG_FILE, 'r') as f:
            log_entries = json.load(f)
        
        # Add new entry
        log_entries.append(log_entry)
        
        # Write back to log file
        with open(self.LOG_FILE, 'w') as f:
            json.dump(log_entries, f, indent=4)

    def analyze_docstring(self) -> Dict[str, Any]:
        """Analyze the quality of the docstring.
        
        Returns:
            Dict[str, Any]: Analysis results
        """
        if not self.suggested_docstring:
            raise ValueError("Suggested docstring not set")
            
        analysis = {
            "has_title": bool(self.suggested_docstring and '__title__' in self.suggested_docstring),
            "has_doc": bool(self.suggested_docstring and '__doc__' in self.suggested_docstring),
            "has_features": bool(self.suggested_docstring and 'Features:' in self.suggested_docstring),
            "has_usage": bool(self.suggested_docstring and 'Usage:' in self.suggested_docstring),
            "length": len(self.suggested_docstring) if self.suggested_docstring else 0
        }
        return analysis

    def update_docstring(self) -> str:
        """Main method to update docstring.
        
        Returns:
            str: Status message indicating success or failure
        """
        try:
            # Execute steps in sequence
            self.read_file_content()
            
            error = self.get_openai_api_key()
            if error:
                return error
                
            self.setup_openai_client()
            self.get_openai_response()
            
            error = self.validate_docstring()
            if error:
                return error
                
            self.find_existing_docstring()
            new_lines = self.replace_or_insert_docstring()
            self.write_to_file(new_lines)
            
            # Log the change if there was an original docstring
            if self.original_docstring:
                self.log_change()
            
            return "Successfully updated docstring using OpenAI analysis"
        except Exception as e:
            return "Error: {}".format(str(e))

    @classmethod
    def process_directory(cls, directory_path: str, progress_callback: Optional[Callable[[str], None]] = None) -> List[Tuple[str, str]]:
        """Process all Python files in a directory.
        
        Args:
            directory_path: Path to the directory to process
            progress_callback: Optional callback function to report progress
            
        Returns:
            List[Tuple[str, str]]: List of (file_path, result) tuples
        """
        results = []
        python_files = []
        
        # First, collect all Python files
        for root, _, files in os.walk(directory_path):
            for file in files:
                if file.endswith('.py'):
                    python_files.append(os.path.join(root, file))
        
        total_files = len(python_files)
        if progress_callback:
            progress_callback("Found {} Python files to process".format(total_files))
        
        # Process files in parallel
        with ThreadPoolExecutor(max_workers=cls.DEFAULT_CONFIG["max_workers"]) as executor:
            futures = []
            for i, file_path in enumerate(python_files, 1):
                if progress_callback:
                    progress_callback("Processing file {}/{}: {}".format(i, total_files, file_path))
                updater = cls(file_path, progress_callback)
                futures.append(executor.submit(updater.update_docstring))
            
            # Collect results as they complete
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append((file_path, result))
                except Exception as e:
                    if progress_callback:
                        progress_callback("Error processing file: {}".format(str(e)))
                    results.append((file_path, "Error: {}".format(str(e))))
        
        return results

    @classmethod
    def generate_statistics(cls) -> Union[Dict[str, Any], str]:
        """Generate statistics from the log file.
        
        Returns:
            Union[Dict[str, Any], str]: Statistics or error message
        """
        if not os.path.exists(cls.LOG_FILE):
            return "No log file found"

        with open(cls.LOG_FILE, 'r') as f:
            log_entries = json.load(f)

        if not log_entries:
            return "No changes logged"

        stats = {
            "total_changes": len(log_entries),
            "approved_changes": len([e for e in log_entries if e.get("status") == "approved"]),
            "rejected_changes": len([e for e in log_entries if e.get("status") == "rejected"]),
            "files_modified": len(set(e["file"] for e in log_entries)),
            "average_docstring_length": statistics.mean(len(e["new"]) for e in log_entries if "new" in e),
            "success_rate": len([e for e in log_entries if e.get("status") == "approved"]) / len(log_entries) * 100
        }

        return stats

class DocstringUpdaterGUI:
    """GUI for the DocstringUpdater application."""
    
    def __init__(self) -> None:
        """Initialize the GUI."""
        self.root = tk.Tk()
        self.root.title("Docstring Updater")
        self.updater = DocstringUpdater()
        self.setup_gui()

    def setup_gui(self) -> None:
        """Set up the GUI components."""
        # Configuration frame
        config_frame = ttk.LabelFrame(self.root, text="OpenAI Configuration", padding=10)
        config_frame.pack(fill=tk.X, padx=5, pady=5)

        # Model selection
        ttk.Label(config_frame, text="Model:").grid(row=0, column=0, sticky=tk.W)
        self.model_var = tk.StringVar(value=self.updater.config["model"])
        model_combo = ttk.Combobox(config_frame, textvariable=self.model_var, 
                                 values=["gpt-4-turbo-preview", "gpt-4", "gpt-3.5-turbo"])
        model_combo.grid(row=0, column=1, sticky=tk.W)
        ttk.Label(config_frame, text="Select the OpenAI model to use").grid(row=0, column=2, sticky=tk.W)

        # Temperature
        ttk.Label(config_frame, text="Temperature:").grid(row=1, column=0, sticky=tk.W)
        self.temp_var = tk.DoubleVar(value=self.updater.config["temperature"])
        temp_scale = ttk.Scale(config_frame, from_=0, to=1, variable=self.temp_var, orient=tk.HORIZONTAL)
        temp_scale.grid(row=1, column=1, sticky=tk.W)
        ttk.Label(config_frame, text="Controls randomness (0 = deterministic, 1 = creative)").grid(row=1, column=2, sticky=tk.W)

        # Max tokens
        ttk.Label(config_frame, text="Max Tokens:").grid(row=2, column=0, sticky=tk.W)
        self.tokens_var = tk.IntVar(value=self.updater.config["max_tokens"])
        tokens_entry = ttk.Entry(config_frame, textvariable=self.tokens_var)
        tokens_entry.grid(row=2, column=1, sticky=tk.W)
        ttk.Label(config_frame, text="Maximum length of the generated docstring").grid(row=2, column=2, sticky=tk.W)

        # Max workers
        ttk.Label(config_frame, text="Max Workers:").grid(row=3, column=0, sticky=tk.W)
        self.workers_var = tk.IntVar(value=self.updater.config["max_workers"])
        workers_entry = ttk.Entry(config_frame, textvariable=self.workers_var)
        workers_entry.grid(row=3, column=1, sticky=tk.W)
        ttk.Label(config_frame, text="Number of parallel processes").grid(row=3, column=2, sticky=tk.W)

        # Progress log
        log_frame = ttk.LabelFrame(self.root, text="Progress Log", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Action buttons
        button_frame = ttk.Frame(self.root)
        button_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Button(button_frame, text="Process File", command=self.process_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Process Directory", command=self.process_directory).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Show Statistics", command=self.show_statistics).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Clear Log", command=self.clear_log).pack(side=tk.LEFT, padx=5)

    def update_progress(self, message: str) -> None:
        """Update the progress log.
        
        Args:
            message: Progress message to display
        """
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()

    def clear_log(self) -> None:
        """Clear the progress log."""
        self.log_text.delete(1.0, tk.END)

    def process_file(self) -> None:
        """Process a single file."""
        file_path = filedialog.askopenfilename(filetypes=[("Python files", "*.py")])
        if file_path:
            self.updater.file_path = file_path
            self.updater.config.update({
                "model": self.model_var.get(),
                "temperature": self.temp_var.get(),
                "max_tokens": self.tokens_var.get(),
                "max_workers": self.workers_var.get()
            })
            self.update_progress("Processing file: {}".format(file_path))
            result = self.updater.update_docstring()
            self.update_progress("Result: {}".format(result))
            messagebox.showinfo("Result", result)

    def process_directory(self) -> None:
        """Process a directory of files."""
        directory_path = filedialog.askdirectory()
        if directory_path:
            self.updater.config.update({
                "model": self.model_var.get(),
                "temperature": self.temp_var.get(),
                "max_tokens": self.tokens_var.get(),
                "max_workers": self.workers_var.get()
            })
            self.update_progress("Processing directory: {}".format(directory_path))
            results = DocstringUpdater.process_directory(directory_path, self.update_progress)
            self.update_progress("Processed {} files".format(len(results)))
            messagebox.showinfo("Results", "Processed {} files".format(len(results)))

    def show_statistics(self) -> None:
        """Show statistics about docstring changes."""
        stats = DocstringUpdater.generate_statistics()
        if isinstance(stats, dict):
            stats_text = "\n".join("{}: {}".format(k, v) for k, v in stats.items())
        else:
            stats_text = stats
        self.update_progress("Statistics:\n{}".format(stats_text))
        messagebox.showinfo("Statistics", stats_text)

    def run(self) -> None:
        """Run the GUI application."""
        self.root.mainloop()

if __name__ == "__main__":
    # Launch GUI
    gui = DocstringUpdaterGUI()
    gui.run()
