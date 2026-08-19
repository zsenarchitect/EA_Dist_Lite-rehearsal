"""Retired. The Shanghai BackupRepo copy path is gone.

Do not copy from BackupRepo. Do not probe L:. The only update path is
EnneadTab_OS_Installer.
"""
import sys
import tkinter as tk
from tkinter import messagebox

root = tk.Tk()
root.withdraw()
messagebox.showerror(
    "ShanghaiRepoAssist retired",
    "The Shanghai BackupRepo copy is retired.\nRun EnneadTab_OS_Installer instead.")
sys.exit(1)
