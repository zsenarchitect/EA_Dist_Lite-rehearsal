
import os
from EnneadTab import NOTIFICATION
from EnneadTab.DEPOT import ASSET
from Autodesk.Revit import DB # pyright: ignore
from EnneadTab.REVIT import REVIT_PARAMETER


def find_definition_by_name(doc, name):
    shared_para_file = doc.Application.OpenSharedParameterFile()
    if shared_para_file is None:
        return None
    for definition_group in shared_para_file.Groups:
        for definition in definition_group.Definitions:
            if definition.Name == name:
                return definition
    return None

def create_color_setting_to_sheet(doc):
    sample_sheet = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Sheets).WhereElementIsNotElementType().FirstElement()
    if sample_sheet is None:
        # No sheets in the document yet -- there's nothing to bind the
        # parameter to. Bail out cleanly instead of crashing the button
        # with AttributeError on the next .LookupParameter() call.
        NOTIFICATION.messenger("This document has no sheets. Add at least one sheet before configuring [Print_In_Color].")
        return
    para = sample_sheet.LookupParameter("Print_In_Color")
    if para:
        NOTIFICATION.messenger('[Print_In_Color] parameter already exist in current file.')
        return
    

    shared_para_file = doc.Application.OpenSharedParameterFile()
    if not shared_para_file:
        NOTIFICATION.messenger('[{}]\nneed to have a valid shared parameter file'.format(doc.Title))
        filepath = ASSET.get_asset_path('revit/library/EA_SharedParam.txt')
        if not filepath or not os.path.exists(filepath):
            NOTIFICATION.messenger('Cannot locate the shared parameter file from the depot.')
            return
        doc.Application.SharedParametersFilename = filepath

    definition = find_definition_by_name(doc, "Print_In_Color")


    if definition is None:
        # EA_SharedParam.txt is a read-only depot asset (server-managed). A
        # missing definition is not something this tool creates locally --
        # request it through the admin process instead.
        NOTIFICATION.messenger('[Print_In_Color] is not defined in the shared parameter file yet. '
                                'Request it be added via the EnneadTab admin process, then try again.')
        return
    
  
    
    t = DB.Transaction(doc, "add print_in_color parameter to sheet")
    t.Start()
   
    


    # define category set, should be  OST_Sheets
    cate_sets = DB.CategorySet()
    cate = DB.Category.GetCategory(doc, DB.BuiltInCategory.OST_Sheets)
    cate_sets.Insert(cate)


    #instance binding
    binding = DB.InstanceBinding()
    binding.Categories = cate_sets

    doc.ParameterBindings.Insert(definition, binding, REVIT_PARAMETER.get_para_group())

    
    for sheet in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Sheets).WhereElementIsNotElementType().ToElements():
        sheet.LookupParameter(definition.Name).Set(False)
    t.Commit()
    
    
    NOTIFICATION.messenger('[Print_In_Color] parameter added to the current document.')
    



def create_issue_para_to_sheet(doc, issue_name):

    sample_sheet = DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Sheets).WhereElementIsNotElementType().FirstElement()
    if sample_sheet is None:
        # No sheets in the document yet -- there's nothing to bind the
        # issue parameter to. Bail out cleanly.
        NOTIFICATION.messenger("This document has no sheets. Add at least one sheet before adding issue parameters.")
        return
    para = sample_sheet.LookupParameter(issue_name)
    if para:
        NOTIFICATION.messenger('[{}] parameter already exist in current file.'.format(issue_name))
        return
    

    shared_para_file = doc.Application.OpenSharedParameterFile()
    if not shared_para_file:
        NOTIFICATION.messenger('[{}]\nneed to have a valid shared parameter file'.format(doc.Title))
        filepath = ASSET.get_asset_path('revit/library/EA_SharedParam.txt')
        if not filepath or not os.path.exists(filepath):
            NOTIFICATION.messenger('Cannot locate the shared parameter file from the depot.')
            return
        doc.Application.SharedParametersFilename = filepath

    definition = find_definition_by_name(doc, issue_name)


    if definition is None:
        # EA_SharedParam.txt is a read-only depot asset (server-managed). A
        # missing definition is not something this tool creates locally --
        # request it through the admin process instead.
        NOTIFICATION.messenger('[{}] is not defined in the shared parameter file yet. '
                                'Request it be added via the EnneadTab admin process, then try again.'.format(issue_name))
        return
    
  
    
    t = DB.Transaction(doc, "add [{}] parameter to sheet".format(issue_name))
    t.Start()
   
    


    # define category set, should be  OST_Sheets
    cate_sets = DB.CategorySet()
    cate = DB.Category.GetCategory(doc, DB.BuiltInCategory.OST_Sheets)
    cate_sets.Insert(cate)


    #instance binding
    binding = DB.InstanceBinding()
    binding.Categories = cate_sets

    doc.ParameterBindings.Insert(definition, binding, REVIT_PARAMETER.get_para_group())

    
    for sheet in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_Sheets).WhereElementIsNotElementType().ToElements():
        sheet.LookupParameter(definition.Name).Set(False)
    t.Commit()
    
    
    NOTIFICATION.messenger('[{}] parameter added to the current document.'.format(issue_name))
    


if __name__ == "__main__":
    pass