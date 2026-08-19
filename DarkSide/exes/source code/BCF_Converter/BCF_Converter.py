# Import necessary libraries
import tkinter as tk
from tkinter import filedialog, messagebox
import pandas as pd
import xml.etree.ElementTree as ET
from pathlib import Path
import logging
import zipfile
import tempfile
import os
import subprocess
import openpyxl.styles
import openpyxl


# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BCFTempDir:
    """Context manager for handling temporary BCF directory"""
    def __init__(self, bcf_path):
        self.bcf_path = bcf_path
        self.temp_dir = None
        self._cleanup = True  # Add flag to control cleanup

    def __enter__(self):
        logger.info(f"Creating temporary directory for BCF extraction")
        self.temp_dir = tempfile.mkdtemp()
        logger.info(f"Extracting BCF file to: {self.temp_dir}")
        with zipfile.ZipFile(self.bcf_path, 'r') as zip_ref:
            zip_ref.extractall(self.temp_dir)
        logger.info("BCF extraction completed")
        
        return self.temp_dir

    def disable_cleanup(self):
        """Disable automatic cleanup of temp directory"""
        self._cleanup = False

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._cleanup and self.temp_dir and os.path.exists(self.temp_dir):
            logger.info(f"Cleaning up temporary directory: {self.temp_dir}")
            import shutil
            shutil.rmtree(self.temp_dir)

class BCFConverter:
    """
    Class to handle the conversion of BCF files to Excel format.
    """
    @staticmethod
    def extract_issue_data(issue):
        """
        Extract data from a single issue element.

        :param issue: XML issue element.
        :return: Dictionary containing the extracted data.
        """
        fields = ['ID', 'Title', 'Description', 'Status', 'Priority', 'AssignedTo', 'CreatedDate']
        return {field: issue.find(field).text if issue.find(field) is not None else None 
                for field in fields}

    def convert_bcf_to_excel(self, bcf_path: Path, excel_path: Path) -> None:
        """
        Convert BCF file to Excel format.

        :param bcf_path: Path to the BCF file.
        :param excel_path: Path where the Excel file will be saved.
        """
        try:
            logger.info(f"Starting conversion of {bcf_path} to Excel format")
            
            with BCFTempDir(bcf_path) as temp_dir:
                logger.info("Reading BCF file contents")
                df = self._read_bcf_file(bcf_path, temp_dir)
                
                logger.info("Processing Excel file creation")
                # Define column order
                columns = [
                    'Index', 'Title',  'TopicStatus','Description', 'CreationDate', 'CreationAuthor',
                    'ModifiedDate', 'AssignedTo', 'TopicType'
                ]
                
                # Reorder columns
                df = df[columns]
                
                # Create Excel writer object
                with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                    logger.info("Creating worksheet")
                    df.to_excel(writer, index=False, sheet_name='BCF Issues')
                    
                    logger.info("Formatting Excel worksheet")
                    workbook = writer.book
                    worksheet = writer.sheets['BCF Issues']
                    
                    # Add auto-filter to enable sorting
                    worksheet.auto_filter.ref = worksheet.dimensions
                    
                    # Auto-fit column widths and set text wrap
                    for idx, column in enumerate(worksheet.columns):
                        max_length = 0
                        column_letter = column[0].column_letter
                        
                        for cell in column:
                            try:
                                if len(str(cell.value)) > max_length:
                                    max_length = len(str(cell.value))
                            except:
                                pass
                        
                        adjusted_width = min(max_length + 2, 50)
                        worksheet.column_dimensions[column_letter].width = adjusted_width
                        
                        # Set text wrap for cells in this column
                        for cell in column:
                            cell.alignment = openpyxl.styles.Alignment(wrap_text=True, vertical='top')
                    
                    # Freeze the header row
                    worksheet.freeze_panes = 'A2'

                logger.info(f"Successfully converted {bcf_path} to {excel_path}")
        except Exception as e:
            logger.error(f"Conversion failed: {str(e)}")
            raise

    def _read_bcf_file(self, bcf_path: Path, temp_dir: str) -> pd.DataFrame:
        """
        Read and parse BCF file by extracting the ZIP content first.
        
        :param bcf_path: Path to the BCF file.
        :param temp_dir: Temporary directory containing the extracted files.
        :return: DataFrame containing the extracted data.
        """
        try:
            data = []
            markup_found = False
            
            # Log the contents of temp directory for debugging
            logger.info(f"Contents of temp directory {temp_dir}:")
            for root, dirs, files in os.walk(temp_dir):
                logger.info(f"Directory: {root}")
                logger.info(f"Files: {files}")
                
                for file in files:
                    if file.lower() == 'markup.bcf':
                        markup_found = True
                        file_path = os.path.join(root, file)
                        logger.info(f"Found markup file: {file_path}")
                        
                        tree = ET.parse(file_path)
                        xml_root = tree.getroot()
                        
                        # Log the XML structure for debugging
                        logger.info(f"XML root tag: {xml_root.tag}")
                        logger.info(f"XML root children: {[child.tag for child in xml_root]}")
                        
                        # Try both direct Topic elements and nested ones
                        topics = xml_root.findall('.//Topic')
                        if not topics:
                            topics = xml_root.findall('Topic')
                        
                        logger.info(f"Number of topics found: {len(topics)}")
                        
                        for topic in topics:
                            logger.info(f"Processing topic with ID: {topic.get('Guid')}")
                            
                            issue_data = {
                                'Index': topic.find('Index').text if topic.find('Index') is not None else None,
                                'Title': topic.find('Title').text if topic.find('Title') is not None else None,
                                'Description': topic.find('Description').text if topic.find('Description') is not None else None,
                                'CreationDate': topic.find('CreationDate').text if topic.find('CreationDate') is not None else None,
                                'CreationAuthor': topic.find('CreationAuthor').text if topic.find('CreationAuthor') is not None else None,
                                'ModifiedDate': topic.find('ModifiedDate').text if topic.find('ModifiedDate') is not None else None,
                                'AssignedTo': topic.find('AssignedTo').text if topic.find('AssignedTo') is not None else None,
                                'TopicType': topic.get('TopicType', None),
                                'TopicStatus': topic.get('TopicStatus', None)
                            }
                            data.append(issue_data)
                            logger.info(f"Extracted issue data: {issue_data}")
            
            if not markup_found:
                raise ValueError("No markup.bcf file found in the BCF archive")
                
            if not data:
                raise ValueError("No issues found in the BCF file")
            
            # Create DataFrame and sort by Index
            df = pd.DataFrame(data)
            
            # Convert and format date columns
            date_columns = ['CreationDate', 'ModifiedDate']
            for col in date_columns:
                df[col] = pd.to_datetime(df[col], utc=True)
                df[col] = df[col].dt.tz_convert('US/Eastern').dt.strftime('%Y-%m-%d %H:%M:%S EST')
            
            # Sort by Index
            df['Index'] = pd.to_numeric(df['Index'], errors='coerce')
            df = df.sort_values('Index')
            
            logger.info(f"Successfully created DataFrame with {len(df)} rows")
            return df
                
        except Exception as e:
            logger.error(f"Failed to process BCF file: {str(e)}")
            # Log the full exception traceback for debugging
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

class BCFConverterGUI:
    """
    Class to create a GUI for the BCF to Excel conversion process.
    """
    def __init__(self, root):
        self.root = root
        self.root.title("EnneadTab BCF2Excel Converter")
        self.root.geometry("600x300")
        
        # Add dark theme configuration
        self.root.configure(bg='#2b2b2b')
        
        self.bcf_file_path = None
        self.excel_file_path = None
        self.converter = BCFConverter()
        
        self._create_widgets()
        self._center_window()

    def _center_window(self):
        """
        Center the window on the screen.
        """
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def _create_widgets(self):
        """
        Create and arrange GUI elements.
        """
        # Create main frame with padding and dark background
        main_frame = tk.Frame(self.root, padx=20, pady=20, bg='#2b2b2b')
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Update button styling
        button_style = {
            'bg': '#404040',
            'fg': 'white',
            'activebackground': '#505050',
            'activeforeground': 'white',
            'width': 20
        }

        self.select_bcf_button = tk.Button(
            main_frame, 
            text="Select BCF File", 
            command=self._handle_file_selection,
            **button_style
        )
        self.select_bcf_button.pack(pady=5)

        # Update label styling
        label_style = {
            'bg': '#2b2b2b',
            'fg': 'white',
            'wraplength': 500,
            'font': ('TkDefaultFont', 10, 'bold')
        }

        self.bcf_file_label = tk.Label(
            main_frame, 
            text="No BCF file selected",
            **label_style
        )
        self.bcf_file_label.pack(pady=5)

        self.excel_file_label = tk.Label(
            main_frame, 
            text="No save location selected",
            **label_style
        )
        self.excel_file_label.pack(pady=5)

        # Update checkbox styling with default value=True
        self.open_excel_var = tk.BooleanVar(value=True)
        self.open_excel_checkbox = tk.Checkbutton(
            main_frame,
            text="Open Excel after conversion",
            variable=self.open_excel_var,
            bg='#2b2b2b',
            fg='white',
            selectcolor='#404040',
            activebackground='#2b2b2b',
            activeforeground='white'
        )
        self.open_excel_checkbox.pack(pady=5)

        # Update convert button
        self.convert_button = tk.Button(
            main_frame,
            text="Convert to Excel",
            command=self._handle_conversion,
            state=tk.DISABLED,
            **button_style
        )
        self.convert_button.pack(pady=10)

    def _handle_file_selection(self):
        """
        Handle BCF file selection and prompt for save location.
        """
        try:
            self.bcf_file_path = Path(filedialog.askopenfilename(
                title="Select BCF File",
                filetypes=[("BCF Files", "*.bcf")]
            ))
            
            if not self.bcf_file_path.name:  # User cancelled
                return
                
            self.bcf_file_label.config(text=f"BCF File: {self.bcf_file_path}")
            self._prompt_save_location()
            
        except Exception as e:
            logger.error(f"File selection error: {str(e)}")
            messagebox.showerror("Error", "Failed to select BCF file")

    def _prompt_save_location(self):
        """
        Prompt for Excel file save location.
        """
        try:
            default_name = f"converted_{self.bcf_file_path.stem}.xlsx"
            
            self.excel_file_path = Path(filedialog.asksaveasfilename(
                title="Save Excel File",
                initialfile=default_name,
                defaultextension=".xlsx",
                filetypes=[("Excel Files", "*.xlsx")]
            ))
            
            if not self.excel_file_path.name:  # User cancelled
                return
                
            self.excel_file_label.config(text=f"Excel File: {self.excel_file_path}")
            self.convert_button.config(state=tk.NORMAL)
            
        except Exception as e:
            logger.error(f"Save location error: {str(e)}")
            messagebox.showerror("Error", "Failed to set save location")

    def _handle_conversion(self):
        """
        Handle the conversion process.
        """
        try:
            self.convert_button.config(state=tk.DISABLED)
            self.root.config(cursor="wait")
            self.root.update()
            
            self.converter.convert_bcf_to_excel(
                self.bcf_file_path, 
                self.excel_file_path
            )
            messagebox.showinfo("Success", "BCF file has been converted to Excel successfully!")
            
            # Open Excel if checkbox is checked
            if self.open_excel_var.get():
                self._open_excel_file()
            
        except Exception as e:
            logger.error(f"Conversion error: {str(e)}")
            messagebox.showerror("Error", f"Conversion failed: {str(e)}")
            
        finally:
            self.convert_button.config(state=tk.NORMAL)
            self.root.config(cursor="")

    def _open_excel_file(self):
        """
        Open the Excel file using the default system application.
        """
        try:
            if os.name == 'nt':  # Windows
                os.startfile(self.excel_file_path)
            else:  # macOS and Linux
                subprocess.run(['open' if os.name == 'darwin' else 'xdg-open', self.excel_file_path])
        except Exception as e:
            logger.error(f"Failed to open Excel file: {str(e)}")
            messagebox.showwarning("Warning", "Could not open Excel file automatically")

def main():
    """
    Main entry point of the application.
    """
    try:
        root = tk.Tk()
        app = BCFConverterGUI(root)
        root.mainloop()
    except Exception as e:
        logger.critical(f"Application failed to start: {str(e)}")
        messagebox.showerror("Critical Error", "Application failed to start")

if __name__ == "__main__":
    main()
