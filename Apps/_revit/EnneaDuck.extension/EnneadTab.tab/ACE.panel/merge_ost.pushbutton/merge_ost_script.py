#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Merge duplicate object styles (subcategories) into a single target.

Solves the 'boomerang' problem where deleted subcategories reappear because
families still carry them internally.

Workflow:
  1. Pick the bad subcategory to remove and the target to keep.
  2. Dry-delete the bad subcategory (rolled back) to discover every
     family and project element that references it.
  3. Open each affected family (loadable and in-place), reassign
     geometry from bad to target subcategory, delete the bad one,
     and load the family back.
  4. Reassign project-level elements (detail lines, filled regions, etc.)
     and delete the bad subcategory from the project.

Note: Category.Name is read-only in the Revit API so subcategories
cannot be renamed directly; elements must be reassigned instead.
"""
__title__ = "Merge\nObject Style"
__tip__ = True

import proDUCKtion  # pyright: ignore
proDUCKtion.validify()

import traceback
from pyrevit import forms, script  # pyright: ignore
from pyrevit.revit import ErrorSwallower  # pyright: ignore
from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_FAMILY
from Autodesk.Revit import DB  # pyright: ignore
from System import EventHandler  # pyright: ignore
from Autodesk.Revit.DB.Events import DocumentChangedEventArgs  # pyright: ignore

DOC = REVIT_APPLICATION.get_doc()


class SubCategoryItem(forms.TemplateListItem):
    @property
    def name(self):
        return "{}: {}".format(self.item.Parent.Name, self.item.Name)


class DocumentChangeTracker:
    def __init__(self):
        self.modified_ids = []
        self.deleted_ids = []

    def on_doc_changed(self, sender, args):
        for element_id in args.GetModifiedElementIds():
            self.modified_ids.append(element_id)
        for element_id in args.GetDeletedElementIds():
            self.deleted_ids.append(element_id)

    def clear(self):
        self.modified_ids = []
        self.deleted_ids = []


def select_sub_category(task, limited_category=None):
    sub_categories = []
    all_categories = DOC.Settings.Categories
    for category in sorted(all_categories, key=lambda x: x.Name):
        if limited_category and category.Name != limited_category:
            continue
        for sub_category in category.SubCategories:
            sub_categories.append(SubCategoryItem(sub_category))

    sub_categories.sort(key=lambda x: x.name)
    res = forms.SelectFromList.show(
        sub_categories,
        button_name="Select {} SubCategory".format(task),
        title="Select {} SubCategory".format(task),
    )
    return res


def dry_delete_and_classify(doc, bad_sub_category):
    """Dry-delete the bad subcategory and classify the modified elements.

    Returns:
        loadable_families: list of DB.Family (IsInPlace == False)
        inplace_families:  list of DB.Family (IsInPlace == True)
        project_element_ids: list of ElementId for non-family project elements
        total_affected: int total modified + deleted count
    """
    tracker = DocumentChangeTracker()
    handler = EventHandler[DocumentChangedEventArgs](tracker.on_doc_changed)
    doc.Application.DocumentChanged += handler

    loadable_families = []
    inplace_families = []
    project_element_ids = []

    try:
        t = DB.Transaction(doc, "Dry Delete for Merge OST")
        t.Start()
        try:
            doc.Delete(bad_sub_category.Id)
        except Exception as e:
            t.RollBack()
            print("Cannot delete subcategory '{}': {}".format(
                bad_sub_category.Name, e))
            return [], [], [], 0

        seen_family_ids = set()
        for element_id in tracker.modified_ids:
            try:
                element = doc.GetElement(element_id)
                if element is None:
                    continue
                if isinstance(element, DB.Family):
                    eid_val = REVIT_APPLICATION.get_element_id_value(element.Id)
                    if eid_val not in seen_family_ids:
                        seen_family_ids.add(eid_val)
                        if element.IsInPlace:
                            inplace_families.append(element)
                        else:
                            loadable_families.append(element)
                elif isinstance(element, DB.GraphicsStyle):
                    pass
                else:
                    project_element_ids.append(element_id)
            except Exception:
                pass

        total = len(tracker.modified_ids) + len(tracker.deleted_ids)
        t.RollBack()
    finally:
        doc.Application.DocumentChanged -= handler

    return loadable_families, inplace_families, project_element_ids, total


def get_or_create_subcategory_in_family(family_doc, subc_name, copy_visuals_from=None):
    """Return existing subcategory or create a new one under the family's main category."""
    parent_category = family_doc.OwnerFamily.FamilyCategory
    for subc in parent_category.SubCategories:
        if subc.Name == subc_name:
            return subc

    new_subc = family_doc.Settings.Categories.NewSubcategory(
        parent_category, subc_name)

    if copy_visuals_from:
        try:
            new_subc.LineColor = copy_visuals_from.LineColor
        except Exception:
            pass
        try:
            new_subc.Material = copy_visuals_from.Material
        except Exception:
            pass
        for gs_type in [DB.GraphicsStyleType.Projection, DB.GraphicsStyleType.Cut]:
            try:
                new_subc.SetLineWeight(
                    copy_visuals_from.GetLineWeight(gs_type), gs_type)
            except Exception:
                pass
            try:
                new_subc.SetLinePatternId(
                    copy_visuals_from.GetLinePatternId(gs_type), gs_type)
            except Exception:
                pass

    return new_subc


def reassign_elements_in_family(family_doc, bad_subc, target_subc):
    """Reassign every element in the family doc from bad_subc to target_subc.
    Returns the number of elements reassigned.
    """
    count = 0
    bad_gs_proj = None
    target_gs_proj = None
    try:
        bad_gs_proj = bad_subc.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
    except Exception:
        pass
    try:
        target_gs_proj = target_subc.GetGraphicsStyle(
            DB.GraphicsStyleType.Projection)
    except Exception:
        pass

    all_elements = (
        DB.FilteredElementCollector(family_doc)
        .WhereElementIsNotElementType()
        .ToElements()
    )

    for element in all_elements:
        reassigned = False

        # GenericForm (extrusions, blends, sweeps, etc.)
        try:
            if isinstance(element, DB.GenericForm):
                if element.Subcategory and element.Subcategory.Id == bad_subc.Id:
                    element.Subcategory = target_subc
                    reassigned = True
        except Exception:
            pass

        # CurveElement (model / symbolic / detail lines)
        if not reassigned:
            try:
                if isinstance(element, DB.CurveElement) and bad_gs_proj and target_gs_proj:
                    if element.LineStyle and element.LineStyle.Id == bad_gs_proj.Id:
                        element.LineStyle = target_gs_proj
                        reassigned = True
            except Exception:
                pass

        # FAMILY_ELEM_SUBCATEGORY built-in parameter
        if not reassigned:
            try:
                param = element.get_Parameter(
                    DB.BuiltInParameter.FAMILY_ELEM_SUBCATEGORY)
                if param and not param.IsReadOnly:
                    if param.AsElementId() == bad_subc.Id:
                        param.Set(target_subc.Id)
                        reassigned = True
            except Exception:
                pass

        # Last resort: match by Category Id
        if not reassigned:
            try:
                if (hasattr(element, "Category")
                        and element.Category
                        and element.Category.Id == bad_subc.Id):
                    param = element.get_Parameter(
                        DB.BuiltInParameter.FAMILY_ELEM_SUBCATEGORY)
                    if param and not param.IsReadOnly:
                        param.Set(target_subc.Id)
                        reassigned = True
            except Exception:
                pass

        if reassigned:
            count += 1

    return count


def _load_family_back(family_doc, project_doc, is_in_place):
    """Load a family document back into the project.
    For in-place families we use a direct LoadFamily call to avoid the
    save-to-temp-file fallback in REVIT_FAMILY.load_family which does not
    apply to in-place families.
    """
    loading_opt = REVIT_FAMILY.EnneadTabFamilyLoadingOption()

    if is_in_place:
        try:
            family_doc.LoadFamily.Overloads[
                DB.Document, DB.IFamilyLoadOptions
            ](project_doc, loading_opt)
            return
        except Exception:
            pass
        family_doc.LoadFamily(project_doc, loading_opt)
    else:
        REVIT_FAMILY.load_family(family_doc, project_doc)


def process_single_family(doc, family, bad_name, target_name):
    """Open family doc, reassign elements, load back.
    Works for both loadable and in-place families.
    Returns (success_bool, status_string).
    """
    family_name = family.Name
    family_doc = None
    is_in_place = family.IsInPlace

    try:
        if not family.IsEditable:
            return False, "Not editable"

        family_doc = doc.EditFamily(family)
        if not family_doc:
            return False, "Could not open family document"

        parent_category = family_doc.OwnerFamily.FamilyCategory
        bad_subc = None
        target_subc = None
        for subc in parent_category.SubCategories:
            if subc.Name == bad_name:
                bad_subc = subc
            elif subc.Name == target_name:
                target_subc = subc

        if not bad_subc:
            family_doc.Close(False)
            family_doc = None
            return False, "Subcategory '{}' not found in family".format(bad_name)

        t = DB.Transaction(family_doc, "Merge Object Style")
        t.Start()
        try:
            if not target_subc:
                target_subc = get_or_create_subcategory_in_family(
                    family_doc, target_name, copy_visuals_from=bad_subc)
                print("    Created subcategory '{}' in family".format(target_name))

            reassigned = reassign_elements_in_family(
                family_doc, bad_subc, target_subc)
            print("    Reassigned {} elements".format(reassigned))

            try:
                family_doc.Delete(bad_subc.Id)
            except Exception as del_err:
                print("    Warning: could not delete old subcategory: {}".format(
                    del_err))

            t.Commit()
        except Exception:
            t.RollBack()
            raise

        _load_family_back(family_doc, doc, is_in_place)
        tag = " (in-place)" if is_in_place else ""
        print("    Loaded family back into project{}".format(tag))

        family_doc.Close(False)
        family_doc = None

        return True, "{} elements reassigned".format(reassigned)

    except Exception as e:
        if family_doc:
            try:
                family_doc.Close(False)
            except Exception:
                pass
        ERROR_HANDLE.print_note(traceback.format_exc())
        return False, str(e)


def reassign_project_elements(doc, project_element_ids,
                               bad_sub_category, target_sub_category):
    """Reassign project-level elements that were modified during the dry-delete.

    Handles:
      - CurveElement  (detail / model lines) via LineStyle property
      - FilledRegion  (border line style) via SetLineStyleId
        NOTE: The Revit API exposes no GetLineStyleId() on FilledRegion, so
        we rely on the dry-delete having identified these elements as affected
        and set them to the target unconditionally.
      - Any element with a matching FAMILY_ELEM_SUBCATEGORY parameter
      - Any element whose Category matches the bad subcategory

    Returns (reassigned_count, skipped_elements_info).
    """
    bad_gs = None
    target_gs = None
    try:
        bad_gs = bad_sub_category.GetGraphicsStyle(
            DB.GraphicsStyleType.Projection)
    except Exception:
        pass
    try:
        target_gs = target_sub_category.GetGraphicsStyle(
            DB.GraphicsStyleType.Projection)
    except Exception:
        pass

    count = 0
    skipped_info = []

    for element_id in project_element_ids:
        element = doc.GetElement(element_id)
        if element is None:
            continue

        reassigned = False

        # -- CurveElement (detail / model lines) --
        if isinstance(element, DB.CurveElement):
            try:
                if bad_gs and target_gs:
                    if element.LineStyle and element.LineStyle.Id == bad_gs.Id:
                        element.LineStyle = target_gs
                        reassigned = True
            except Exception:
                pass

        # -- FilledRegion (border line style) --
        if not reassigned:
            try:
                if isinstance(element, DB.FilledRegion) and target_gs:
                    element.SetLineStyleId(target_gs.Id)
                    reassigned = True
            except Exception:
                pass

        # -- FAMILY_ELEM_SUBCATEGORY parameter --
        if not reassigned:
            try:
                param = element.get_Parameter(
                    DB.BuiltInParameter.FAMILY_ELEM_SUBCATEGORY)
                if param and not param.IsReadOnly:
                    if param.AsElementId() == bad_sub_category.Id:
                        param.Set(target_sub_category.Id)
                        reassigned = True
            except Exception:
                pass

        # -- Match by Category directly --
        if not reassigned:
            try:
                if (hasattr(element, "Category")
                        and element.Category
                        and element.Category.Id == bad_sub_category.Id):
                    param = element.get_Parameter(
                        DB.BuiltInParameter.FAMILY_ELEM_SUBCATEGORY)
                    if param and not param.IsReadOnly:
                        param.Set(target_sub_category.Id)
                        reassigned = True
            except Exception:
                pass

        if reassigned:
            count += 1
        else:
            try:
                type_name = element.GetType().Name
                cat_name = element.Category.Name if element.Category else "?"
                skipped_info.append("{} ({}) ID:{}".format(
                    type_name, cat_name, element_id))
            except Exception:
                skipped_info.append("ID:{}".format(element_id))

    return count, skipped_info


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def merge_ost(doc):
    output = script.get_output()
    output.close_others()

    print("=" * 60)
    print("MERGE OBJECT STYLE")
    print("=" * 60)

    # --- Pick subcategories ---------------------------------------------------
    bad_sub_category = select_sub_category("Bad (to remove)")
    if not bad_sub_category:
        return

    target_sub_category = select_sub_category(
        "Target (to keep)", bad_sub_category.Parent.Name)
    if not target_sub_category:
        return

    if bad_sub_category.Id == target_sub_category.Id:
        NOTIFICATION.messenger("Bad and Target subcategories are the same!")
        return

    bad_name = bad_sub_category.Name
    target_name = target_sub_category.Name
    parent_name = bad_sub_category.Parent.Name

    print("\nMerge:  '{}: {}'  -->  '{}: {}'".format(
        parent_name, bad_name, parent_name, target_name))

    # --- Dry delete to discover affected elements -----------------------------
    print("\n" + "-" * 60)
    print("Step 1/3  Scanning for affected elements (dry delete)...")
    print("-" * 60)

    (loadable_families,
     inplace_families,
     project_element_ids,
     total_affected) = dry_delete_and_classify(doc, bad_sub_category)

    all_families = loadable_families + inplace_families

    for fam in loadable_families:
        print("  Loadable family: {}".format(fam.Name))
    for fam in inplace_families:
        print("  In-place family: {}".format(fam.Name))
    if project_element_ids:
        print("  {} project-level elements also reference this subcategory".format(
            len(project_element_ids)))

    if not all_families and not project_element_ids:
        t = DB.Transaction(doc, "Delete unused subcategory")
        t.Start()
        try:
            doc.Delete(bad_sub_category.Id)
            t.Commit()
            print("\nSubcategory '{}' deleted (nothing referenced it).".format(
                bad_name))
            NOTIFICATION.messenger("Subcategory deleted (no references found).")
        except Exception:
            t.RollBack()
            print("\nCould not delete subcategory. It may be protected.")
        return

    # --- Confirm with user ----------------------------------------------------
    msg_lines = [
        "Merge '{}: {}' into '{}: {}'".format(
            parent_name, bad_name, parent_name, target_name),
        "",
    ]
    if loadable_families:
        msg_lines.append(
            "{} loadable families will be edited and reloaded:".format(
                len(loadable_families)))
        for f in sorted(loadable_families, key=lambda x: x.Name):
            msg_lines.append("  - {}".format(f.Name))
    if inplace_families:
        msg_lines.append(
            "{} in-place families will be edited:".format(
                len(inplace_families)))
        for f in sorted(inplace_families, key=lambda x: x.Name):
            msg_lines.append("  - {} (in-place)".format(f.Name))
    if project_element_ids:
        msg_lines.append("")
        msg_lines.append(
            "{} project-level elements will be reassigned.".format(
                len(project_element_ids)))

    if not forms.alert(
            "\n".join(msg_lines), title="Confirm Merge", yes=True, no=True):
        print("\nCancelled by user.")
        return

    # --- Process families (loadable + in-place) -------------------------------
    print("\n" + "-" * 60)
    print("Step 2/3  Processing {} families...".format(len(all_families)))
    print("-" * 60)

    results = []
    success_count = 0

    with ErrorSwallower():
        for i, family in enumerate(all_families, 1):
            tag = " (in-place)" if family.IsInPlace else ""
            print("\n[{}/{}] {}{}".format(
                i, len(all_families), family.Name, tag))
            ok, status = process_single_family(
                doc, family, bad_name, target_name)
            results.append((family.Name, tag, ok, status))
            if ok:
                success_count += 1

    # --- Reassign project-level elements and delete subcategory ---------------
    print("\n" + "-" * 60)
    print("Step 3/3  Cleaning up project...")
    print("-" * 60)

    t = DB.Transaction(doc, "Merge Object Style Cleanup")
    t.Start()
    try:
        proj_count, skipped = reassign_project_elements(
            doc, project_element_ids, bad_sub_category, target_sub_category)
        if proj_count:
            print("Reassigned {} project-level elements".format(proj_count))
        if skipped:
            print("Could not reassign {} elements:".format(len(skipped)))
            for info in skipped[:20]:
                print("  - {}".format(info))
            if len(skipped) > 20:
                print("  ... and {} more".format(len(skipped) - 20))

        try:
            doc.Delete(bad_sub_category.Id)
            print("Deleted subcategory '{}: {}' from project".format(
                parent_name, bad_name))
        except Exception as e:
            print(
                "Warning: could not delete subcategory from project: {}".format(e))

        t.Commit()
    except Exception as e:
        t.RollBack()
        print("Cleanup transaction failed: {}".format(e))

    # --- Summary --------------------------------------------------------------
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("Merged: '{}: {}' --> '{}: {}'".format(
        parent_name, bad_name, parent_name, target_name))
    print("Families: {}/{} succeeded".format(success_count, len(all_families)))
    if proj_count:
        print("Project elements reassigned: {}".format(proj_count))

    table_data = []
    for name, tag, ok, status in results:
        table_data.append(
            [name + tag, "OK" if ok else "FAIL", status])

    if table_data:
        output.print_table(
            table_data=table_data,
            title="Merge Results",
            columns=["Family", "Result", "Details"],
            formats=["", "", ""],
        )

    total_ok = success_count
    total_all = len(all_families)
    if total_ok == total_all:
        NOTIFICATION.messenger(
            "Merge complete!\n{} families updated, {} project elements reassigned.".format(
                total_ok, proj_count))
    else:
        failed = total_all - total_ok
        NOTIFICATION.messenger(
            "Merge finished with {} failure(s).\n{}/{} families, {} project elements.".format(
                failed, total_ok, total_all, proj_count),
            sticky=True)


################## main code below #####################
if __name__ == "__main__":
    merge_ost(DOC)
