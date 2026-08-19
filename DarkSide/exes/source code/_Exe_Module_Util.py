import os
import sys
import subprocess
import importlib
import _Exe_Util

class ModuleLoader:
    def __init__(self, requirements_file=None):
        """Initialize ModuleLoader with optional requirements file
        Args:
            requirements_file (str, optional): Path to requirements file. 
                                            If None, will look for 'requirements.txt' in same directory
        """
        self.modules_dir = os.path.join(_Exe_Util.ECO_SYS_FOLDER, "Exe_Modules")
        
        # If no requirements file specified, look for default requirements.txt
        if requirements_file is None:
            self.requirements_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
        else:
            # If relative path, make it absolute relative to current script
            if not os.path.isabs(requirements_file):
                requirements_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), requirements_file)
            self.requirements_file = requirements_file
        
        # Create modules directory if it doesn't exist
        if not os.path.exists(self.modules_dir):
            os.makedirs(self.modules_dir)
            
        # Add modules directory to Python path
        if self.modules_dir not in sys.path:
            sys.path.append(self.modules_dir)

    def install_requirements(self):
        """Install requirements from requirements file if it exists"""
        if os.path.exists(self.requirements_file):
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", self.requirements_file])
            except subprocess.CalledProcessError:
                print("Failed to install requirements. Trying with user installation...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "-r", self.requirements_file])

    def load_module(self, module_name):
        """Dynamically load a module, installing it if necessary"""
        try:
            return importlib.import_module(module_name)
        except ImportError:
            print("Module {} not found. Installing...".format(module_name))
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", module_name])
            except subprocess.CalledProcessError:
                print("Failed to install module. Trying with user installation...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", module_name])
            return importlib.import_module(module_name)

    def get_required_modules(self):
        """Get list of required modules from requirements file"""
        if not os.path.exists(self.requirements_file):
            return []
            
        with open(self.requirements_file, 'r') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]

    def ensure_modules(self):
        """Ensure all required modules are installed"""
        required_modules = self.get_required_modules()
        for module in required_modules:
            self.load_module(module.split('==')[0])  # Handle version specifiers 