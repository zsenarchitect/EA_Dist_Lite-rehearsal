"""
EnneadTab Python Engine Manager

This module provides a portable Python runtime for EnneadTab Apps.
It handles Python installation, module management, and script execution
in a consistent, user-friendly way. No more Python headaches—just run your code!

Features:
- Automatic download and setup of embeddable Python
- Module installation with pip
- Script execution in a controlled environment

Usage:
    from GetEngine import PythonEngine
    engine = PythonEngine()
    engine.ensure_installed()
    engine.ensure_module('requests')
    engine.run_script('path/to/script.py')
"""

import os
import time
import subprocess
import urllib.request
import zipfile
import sys
import traceback

WINDOW_TEMP_FOLDER = os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Temp')

class PythonEngine:
    """
    Manages a portable Python environment for EnneadTab Apps.
    Handles Python installation, module management, and script execution.
    """
    def __init__(self, engine_folder=None):
        self.engine_folder = engine_folder or os.path.join(WINDOW_TEMP_FOLDER, '_engine')
        self.site_packages = os.path.join(self.engine_folder, 'Lib', 'site-packages')
        self.python_exe = os.path.join(self.engine_folder, 'python.exe')
        self.python_version = '3.10.11'
        self._ensure_dirs()

    def _ensure_dirs(self):
        os.makedirs(self.engine_folder, exist_ok=True)
        os.makedirs(self.site_packages, exist_ok=True)

    def ensure_installed(self):
        """
        Ensure the Python engine is installed and ready to use.
        Downloads and extracts the embeddable Python if needed.
        """
        if os.path.exists(self.python_exe):
            return True
        zip_url = 'https://www.python.org/ftp/python/{0}/python-{0}-embed-amd64.zip'.format(self.python_version)
        zip_path = os.path.join(WINDOW_TEMP_FOLDER, 'python-{}-embed-amd64.zip'.format(self.python_version))
        if not os.path.exists(zip_path):
            print('Downloading Python...')
            urllib.request.urlretrieve(zip_url, zip_path)
        print('Extracting Python...')
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(self.engine_folder)
        self._configure_python()
        return os.path.exists(self.python_exe)

    def _configure_python(self):
        """
        Enable site-packages and configure the embeddable Python.
        """
        py_version = '.'.join(self.python_version.split('.')[:2])
        pth_file = os.path.join(self.engine_folder, 'python{}.pth'.format(py_version))
        alt_pth_file = os.path.join(self.engine_folder, 'python{}_._pth'.format(py_version))
        if os.path.exists(alt_pth_file):
            with open(alt_pth_file, 'r') as f:
                content = f.read()
            content = content.replace('#import site', 'import site')
            if 'Lib' not in content:
                content = 'Lib\n' + content
            if 'Lib\\site-packages' not in content:
                content = 'Lib\\site-packages\n' + content
            with open(alt_pth_file, 'w') as f:
                f.write(content)
        # Touch site-packages
        os.makedirs(self.site_packages, exist_ok=True)

    def ensure_module(self, module_name):
        """
        Ensure a Python module is installed in the engine.
        Installs with pip if missing.
        """
        if self._has_module(module_name):
            return True
        if not self._ensure_pip():
            print('Could not ensure pip is available.')
            return False
        print('Installing module: {}'.format(module_name))
        result = subprocess.call([
            self.python_exe, '-m', 'pip', 'install', module_name,
            '--target', self.site_packages,
            '--no-warn-script-location', '--upgrade'
        ])
        return result == 0 and self._has_module(module_name)

    def _has_module(self, module_name):
        """
        Check if a module can be imported in the engine.
        """
        test_code = (
            'import sys; sys.path.append(r"{}")\n'.format(self.site_packages) +
            'import {0}'.format(module_name)
        )
        try:
            result = subprocess.run([
                self.python_exe, '-c', test_code
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return result.returncode == 0
        except Exception:
            return False

    def _ensure_pip(self):
        """
        Ensure pip is available in the engine.
        """
        get_pip_url = 'https://bootstrap.pypa.io/get-pip.py'
        get_pip_path = os.path.join(self.engine_folder, 'get-pip.py')
        if not self._has_module('pip'):
            print('Installing pip...')
            urllib.request.urlretrieve(get_pip_url, get_pip_path)
            result = subprocess.call([
                self.python_exe, get_pip_path,
                '--no-warn-script-location',
                '--disable-pip-version-check'
            ])
            return result == 0 and self._has_module('pip')
        return True

    def run_script(self, script_path, args=None):
        """
        Run a Python script using the managed engine.
        Args:
            script_path (str): Path to the script to run
            args (list): Optional list of arguments
        Returns:
            (success, stdout, stderr)
        """
        if not os.path.exists(self.python_exe):
            raise RuntimeError('Python engine is not installed.')
        if not os.path.exists(script_path):
            raise FileNotFoundError('Script not found: {}'.format(script_path))
        cmd = [self.python_exe, script_path]
        if args:
            cmd.extend(args)
        env = os.environ.copy()
        env['PYTHONPATH'] = self.site_packages + os.pathsep + env.get('PYTHONPATH', '')
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, universal_newlines=True)
            stdout, stderr = proc.communicate()
            return proc.returncode == 0, stdout, stderr
        except Exception as e:
            return False, '', str(e)

if __name__ == '__main__':
    print('--- EnneadTab Python Engine Self-Test ---')
    engine = PythonEngine()
    print('Ensuring engine is installed...')
    if engine.ensure_installed():
        print('Engine installed!')
        print('Python executable: {}'.format(engine.python_exe))
        print('Testing module installation (requests)...')
        if engine.ensure_module('requests'):
            print('Module requests installed!')
        else:
            print('Failed to install requests.')
    else:
        print('Engine installation failed.')

