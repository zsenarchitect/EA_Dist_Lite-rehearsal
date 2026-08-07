#!/usr/bin/python
# -*- coding: utf-8 -*-

import os
from EnneadTab import EXE, FOLDER, ERROR_HANDLE

@ERROR_HANDLE.try_catch_error()
def open_sample_excel():
    excel_path = os.path.join(os.path.dirname(__file__), "Make Sheet With Excel.xls")
    copy = FOLDER.copy_file_to_local_dump_folder(excel_path,
                                                           "Sample Sheet Creation Data.xls")
    EXE.try_open_app(copy)
    


if __name__== "__main__":
    pass

