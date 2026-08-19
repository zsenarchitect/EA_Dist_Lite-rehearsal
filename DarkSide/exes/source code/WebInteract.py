import _Exe_Util
import tkinter as tk
from tkinter import ttk, messagebox

DEBUG = True

class DraggableFrame(ttk.Frame):
    def __init__(self, container, value, **kwargs):
        super().__init__(container, **kwargs)
        self.pack(fill=tk.X, expand=True)
        
        # Create a frame to act as a draggable card (only this part is draggable)
        self.card = ttk.Frame(self, style='Card.TFrame', padding=5)
        self.card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=2)
        
        # Add a handle for dragging
        self.handle = ttk.Label(self.card, text="≡", cursor="hand2")  # Triple bar as drag handle
        self.handle.pack(side=tk.LEFT, padx=(0,5))
        
        # Create an entry widget for the target sheet number
        self.entry = ttk.Entry(self.card)
        self.entry.insert(0, value)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Bind drag events to the handle and card
        for widget in [self.handle, self.card]:
            widget.bind('<Button-1>', self.start_drag)
            widget.bind('<B1-Motion>', self.drag)
            widget.bind('<ButtonRelease-1>', self.stop_drag)
        
        self.drag_start_y = 0
        self.is_dragging = False
        self.placeholder = None  # Placeholder for visual feedback during drag
        
    def start_drag(self, event):
        # Record the starting y-coordinate of the drag
        self.drag_start_y = event.y_root
        self.is_dragging = True
        
        # Change the style to indicate dragging
        self.card.configure(style='DragCard.TFrame')
        self.lift()  # Bring the frame to the top of the stacking order
        
        # Create a placeholder that looks like the original frame but slightly offset
        self.placeholder = ttk.Frame(self.master.master)  # Use the grandparent to access the entire column
        placeholder_card = ttk.Frame(self.placeholder, style='Card.TFrame', padding=5)
        placeholder_card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(15,5), pady=2)  # Extra padding
        
        placeholder_handle = ttk.Label(placeholder_card, text="≡")
        placeholder_handle.pack(side=tk.LEFT, padx=(0,5))
        
        placeholder_entry = ttk.Entry(placeholder_card)
        placeholder_entry.insert(0, self.entry.get())
        placeholder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        placeholder_entry.configure(state='disabled')  # Make it look inactive
        
        # Pack the placeholder initially
        self.placeholder.pack(fill=tk.X, expand=True)
            
    def drag(self, event):
        if not self.is_dragging:
            return
            
        y = event.y_root
        
        # Get all DraggableFrames in the entire column
        frames = [
            f.winfo_children()[1] for f in self.master.master.winfo_children()
            if len(f.winfo_children()) > 1 and isinstance(f.winfo_children()[1], DraggableFrame) and f.winfo_children()[1] != self
        ]
        
        # Determine where to insert the placeholder
        insert_before = None
        for frame in frames:
            frame_middle_y = frame.winfo_y() + frame.winfo_height() / 2
            if y - self.master.master.winfo_rooty() < frame_middle_y:
                insert_before = frame
                break
        
        # Move the placeholder to the new position
        if self.placeholder:
            self.placeholder.pack_forget()
            if insert_before:
                self.placeholder.pack(before=insert_before.master, fill=tk.X, expand=True)
            else:
                self.placeholder.pack(fill=tk.X, expand=True)
        
        # Print the current order of items during dragging
        self.print_order()
        
    def stop_drag(self, event):
        if not self.is_dragging:
            return
            
        self.is_dragging = False
        
        # Move the actual frame to the placeholder's position
        if self.placeholder:
            self.pack_forget()
            # Determine the correct position using the placeholder's position
            next_widget = self.placeholder.pack_info().get('before')
            self.placeholder.destroy()
            self.placeholder = None
            
            # Correctly place the dragged item at the placeholder's position
            if next_widget:
                self.pack(before=next_widget, fill=tk.X, expand=True)
            else:
                self.pack(fill=tk.X, expand=True)
        
        # Reset the style to indicate the end of dragging
        self.card.configure(style='Card.TFrame')
        
        # Print the final order of items after dragging
        self.print_order()
    
    def print_order(self):
        # Print the order of items based on their current position
        order = [
            frame.entry.get() for row_frame in self.master.master.winfo_children()
            for frame in row_frame.winfo_children() if isinstance(frame, DraggableFrame)
        ]
        print("Current order:", order)

class FormGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Sheet Number Editor")
        self.root.geometry("500x600")
        
        # Define styles for normal and dragging states
        style = ttk.Style()
        style.configure('Card.TFrame', 
                       background='white',
                       relief='raised',
                       borderwidth=1)
        style.configure('DragCard.TFrame',
                       background='#e1e1e1',
                       relief='raised',
                       borderwidth=2)
        style.configure('Placeholder.TFrame', 
                       background='#e0e0e0',
                       relief='solid',
                       borderwidth=1)
        
        # Data storage
        if DEBUG:
            self.data = {
                "Sheet-A101": "A101",
                "Sheet-A102": "A102",
                "Sheet-A103": "A103",
                "Sheet-A201": "A201",
                "Sheet-A202": "A202",
            }
        else:
            self.data = _Exe_Util.get_data("web_form_data") or {}
            
        # Create main frame with scrollbar
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Add canvas and scrollbar
        self.canvas = tk.Canvas(self.main_frame)
        self.scrollbar = ttk.Scrollbar(self.main_frame, orient=tk.VERTICAL, 
                                     command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Add header labels
        header_frame = ttk.Frame(self.scrollable_frame)
        header_frame.pack(fill=tk.X, expand=True, pady=(0, 10))
        
        ttk.Label(header_frame, text="Current Sheet", width=15).pack(side=tk.LEFT, padx=(5,0))
        ttk.Label(header_frame, text="Target Sheet").pack(side=tk.LEFT, padx=5)
        
        # Create form fields
        self.create_form()
        
        # Add save button
        save_btn = ttk.Button(self.root, text="Save Changes", command=self.save_changes)
        save_btn.pack(pady=10)
        
        # Enable mousewheel scrolling
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        
    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
    def create_form(self):
        """Create form with fixed labels and draggable value cards"""
        for current_value, target_value in self.data.items():
            # Create a container frame for each row
            row_frame = ttk.Frame(self.scrollable_frame)
            row_frame.pack(fill=tk.X, expand=True)
            
            # Create label for current sheet number on column position 1
            ttk.Label(row_frame, text=current_value, width=15).pack(side=tk.LEFT, padx=(5,0))
            # Create draggable frame for target value on column position 2 
            DraggableFrame(row_frame, target_value)
    
    def save_changes(self):
        """Save changes back to file"""
        new_data = {}
        for row_frame in self.scrollable_frame.winfo_children():
            current_label = row_frame.winfo_children()[0]
            current_value = current_label.cget("text")
            draggable_frame = row_frame.winfo_children()[1]
            if isinstance(draggable_frame, DraggableFrame):
                target_value = draggable_frame.entry.get()
                new_data[current_value] = target_value
        
        self.data = new_data
        
        if not DEBUG:
            _Exe_Util.set_data("web_form_data", self.data)
        messagebox.showinfo("Success", "Changes saved successfully!")
        
        if DEBUG:
            print("Saved Data:")
            for k, v in self.data.items():
                print(f"{k}: {v}")
    
    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = FormGUI()
    app.run()