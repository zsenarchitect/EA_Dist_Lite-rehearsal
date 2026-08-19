import tkinter as tk
from tkinter import ttk, filedialog
import os
from md_converter import MarkdownConverter
import traceback
from datetime import datetime
IS_TESTING = True
class MarkdownToIndesignGUI:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Markdown to InDesign Converter 📚")
        self.window.geometry("800x300") 
        
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.default_md_dir = os.path.join(script_dir, "test.md")
        timestamp = datetime.now().strftime("_%Y%m%d-%H%M%S")  # Example: _20240321-023030
        self.default_indd_dir = os.path.join(script_dir, f"output{timestamp}.indd")
        
        self.converter = MarkdownConverter()
        self.setup_gui()
        
    def setup_gui(self):
        # Source file section
        source_frame = ttk.LabelFrame(self.window, text="Source Markdown File", padding=10)
        source_frame.pack(fill="x", padx=10, pady=5)
        
        self.source_path = tk.StringVar(value=self.default_md_dir)
        source_entry = ttk.Entry(source_frame, textvariable=self.source_path)
        source_entry.pack(side="left", padx=5, fill="x", expand=True)
        ttk.Button(source_frame, text="Browse", command=self.browse_source).pack(side="left")
        
        # Destination file section
        dest_frame = ttk.LabelFrame(self.window, text="Destination InDesign File", padding=10)
        dest_frame.pack(fill="x", padx=10, pady=5)
        
        self.dest_path = tk.StringVar(value=self.default_indd_dir)
        dest_entry = ttk.Entry(dest_frame, textvariable=self.dest_path)
        dest_entry.pack(side="left", padx=5, fill="x", expand=True)
        ttk.Button(dest_frame, text="Browse", command=self.browse_dest).pack(side="left")
        
        # Convert button and status
        ttk.Button(self.window, text="Convert to InDesign! 🚀", 
                  command=self.convert).pack(pady=20)
        self.status_label = ttk.Label(self.window, text="Ready to convert! 🎯")
        self.status_label.pack(pady=10)
        
    def browse_source(self):
        filename = filedialog.askopenfilename(
            initialdir=os.path.dirname(self.default_md_dir),
            title="Select Markdown File",
            filetypes=(("Markdown files", "*.md"), ("All files", "*.*"))
        )
        if filename:
            self.source_path.set(filename)
            
    def browse_dest(self):
        filename = filedialog.asksaveasfilename(
            initialdir=os.path.dirname(self.default_indd_dir),
            title="Save InDesign File",
            filetypes=(("InDesign files", "*.indd"), ("All files", "*.*")),
            defaultextension=".indd"
        )
        if filename:
            self.dest_path.set(filename)
            
    def convert(self):
        try:
            self.status_label.config(text="🔄 Converting...")
            self.window.update()


            result = self.converter.convert(
                        self.source_path.get(),
                        self.dest_path.get()
                    )
            
            self.status_label.config(text="✨ Conversion complete! InDesign file opened! 🎉")
            if result:
                self.window.destroy()
        except Exception as e:
            self.status_label.config(text=f"❌ Error: {str(e)}")
            print (traceback.format_exc())
    
    def run(self):
        self.window.mainloop()

if __name__ == "__main__":
    app = MarkdownToIndesignGUI()
    app.run()
