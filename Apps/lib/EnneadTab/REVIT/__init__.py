#!/usr/bin/python
# -*- coding: utf-8 -*-


import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ENVIRONMENT
if ENVIRONMENT.IS_REVIT_ENVIRONMENT:
    imported_modules = {}
    for module in os.listdir(os.path.dirname(__file__)):
        #print (module)
        if module == '__init__.py':
            continue

        if module[-3:] != '.py':
            continue
        try:
            module_name = module[:-3]
            imported_module = __import__(module_name, locals(), globals())
            imported_modules[module_name] = imported_module
        except Exception as e:
            pass
            #print (e)
            # print ("Cannot import {}".format(module))

    # Expose all imported modules in the package namespace
    globals().update(imported_modules)

    del module# delete this varible becaue it is refering to last item on the for loop



