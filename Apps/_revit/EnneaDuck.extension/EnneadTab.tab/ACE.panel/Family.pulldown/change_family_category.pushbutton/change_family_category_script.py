#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = "Batch change family categories with user-friendly interface and comprehensive reporting."
__title__ = "Change\nFamily Category"

import proDUCKtion # pyright: ignore 
proDUCKtion.validify()

from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_FAMILY, REVIT_SELECTION, REVIT_FORMS
from Autodesk.Revit import DB # pyright: ignore 
from pyrevit import forms

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()


class FamilyCategoryChanger:
    """Handles batch family category changes with comprehensive error handling and reporting."""
    
    def __init__(self, doc):
        self.doc = doc
        self.success_count = 0
        self.failure_count = 0
        self.failed_families = []
        self.success_families = []
        
    def get_all_families(self):
        """Get all families from the document."""
        families = DB.FilteredElementCollector(self.doc).OfClass(DB.Family).ToElements()
        return [f for f in families if f.FamilyCategory is not None]
    
    def get_all_family_categories(self):
        """Get all unique family categories from the document (Model categories only)."""
        # Use category ID for uniqueness since Revit Category objects might not hash properly
        category_dict = {}
        for family in self.get_all_families():
            if family.FamilyCategory and family.FamilyCategory.CategoryType == DB.CategoryType.Model:
                category_id = family.FamilyCategory.Id
                if category_id not in category_dict:
                    category_dict[category_id] = family.FamilyCategory
        
        # Convert to sorted list by name
        categories = sorted(category_dict.values(), key=lambda x: x.Name)
        return categories
    
    def select_source_category(self):
        """Let user select source family category."""
        categories = self.get_all_family_categories()
        if not categories:
            NOTIFICATION.messenger("No family categories found in the document.")
            return None
            
        class CategoryOption(forms.TemplateListItem):
            @property
            def name(self):
                return self.item.Name
                
        selected = forms.SelectFromList.show(
            [CategoryOption(cat) for cat in categories],
            title="Select Source Family Category",
            multiselect=False,
            button_name="Select Category"
        )
        return selected
    
    def select_families_in_category(self, source_category):
        """Let user select families within the source category."""
        families = [f for f in self.get_all_families() 
                   if f.FamilyCategory and f.FamilyCategory.Id == source_category.Id]
        
        if not families:
            NOTIFICATION.messenger("No families found in category: {}".format(source_category.Name))
            return []
            
        class FamilyOption(forms.TemplateListItem):
            @property
            def name(self):
                return "[{}] {}".format(self.item.FamilyCategory.Name, self.item.Name)
                
        selected = forms.SelectFromList.show(
            [FamilyOption(f) for f in families],
            title="Select Families to Change Category",
            multiselect=True,
            button_name="Select Families"
        )
        return selected if selected else []
    
    def get_all_available_family_categories(self):
        """Get all available Revit family categories from the document settings (Model categories only)."""
        categories = []
        for category in self.doc.Settings.Categories:
            # Only include Model categories (exclude annotation categories)
            # Remove AllowsBoundParameters filter as it might be too restrictive
            if category.CategoryType == DB.CategoryType.Model:
                categories.append(category)
        return sorted(categories, key=lambda x: x.Name)
    
    def select_target_category(self):
        """Let user select target family category from all available Revit categories."""
        categories = self.get_all_available_family_categories()

        
        if not categories:
            NOTIFICATION.messenger("No other family categories available.")
            return None
            
        class CategoryOption(forms.TemplateListItem):
            @property
            def name(self):
                return self.item.Name
                
        selected = forms.SelectFromList.show(
            [CategoryOption(cat) for cat in categories],
            title="Select Target Family Category (All Available Categories)",
            multiselect=False,
            button_name="Select Target Category"
        )
        return selected
    
    @ERROR_HANDLE.try_catch_error()
    def change_family_category(self, family, target_category):
        """Change a single family's category with proper transaction handling."""
        family_doc = None
        
        # Refresh family reference to avoid "referenced object is not valid" error
        try:
            family = self.doc.GetElement(family.Id)
            if not family:
                raise Exception("Family no longer exists in document")
        except:
            raise Exception("Family reference is invalid")
        
        # Check if family is editable
        if not REVIT_FAMILY.is_family_editable(family, self.doc):
            raise Exception("Family is not editable")
        
        # Open family document
        family_doc = self.doc.EditFamily(family)
        if not family_doc:
            raise Exception("Could not open family document")
        
        # Start transaction in family document
        t = DB.Transaction(family_doc, "Change Family Category")
        t.Start()
        
        # Change the family category
        family_doc.OwnerFamily.FamilyCategory = target_category
        t.Commit()
        
        # Load family back to project
        family_doc.LoadFamily(self.doc, REVIT_FAMILY.EnneadTabFamilyLoadingOption())
        family_doc.Close(False)
        family_doc = None  # Mark as closed to avoid double close
        
        return True
    
    @ERROR_HANDLE.try_catch_error()
    def process_families(self, families, target_category):
        """Process all selected families with progress reporting."""
        total_families = len(families)
        
        for i, family in enumerate(families, 1):
            # Store family name before processing to avoid stale reference issues
            family_name = family.Name
            NOTIFICATION.messenger("Processing family {}/{}: {}".format(i, total_families, family_name))
            
            if self.change_family_category(family, target_category):
                self.success_count += 1
                self.success_families.append(family_name)
            else:
                self.failure_count += 1
                self.failed_families.append(family_name)
    
    def generate_report(self):
        """Generate and display success/failure report."""
        report_lines = []
        report_lines.append("=== FAMILY CATEGORY CHANGE REPORT ===")
        report_lines.append("Total families processed: {}".format(self.success_count + self.failure_count))
        report_lines.append("Successful changes: {}".format(self.success_count))
        report_lines.append("Unsuccessful changes: {}".format(self.failure_count))
        
        if self.success_families:
            report_lines.append("\nSUCCESSFUL CHANGES:")
            for family_name in self.success_families:
                report_lines.append("  ✓ {}".format(family_name))
        
        if self.failed_families:
            report_lines.append("\nUNSUCCESSFUL CHANGES:")
            for family_name in self.failed_families:
                report_lines.append("  ✗ {}".format(family_name))
        
        report_text = "\n".join(report_lines)
        
        # Add suggestion for fixing family name prefixes
        if self.success_count > 0:
            report_text += "\n\n=== NEXT STEPS ==="
            report_text += "\n💡 SUGGESTION: After changing family categories, you may want to update family name prefixes to match the new categories."
            report_text += "\n   Use the 'Batch Fix Family Name' tool → 'Fix Category Prefix Only' to automatically update prefixes."
        
        # Display report in output
        from EnneadTab import OUTPUT
        output = OUTPUT.get_output()
        output.insert_divider()
        output.write("Family Category Change Report", OUTPUT.Style.Subtitle)
        output.write(report_text, OUTPUT.Style.MainBody)
        output.plot()
        
        # Also show notification
        if self.failure_count == 0:
            NOTIFICATION.messenger("All {} families processed successfully!".format(self.success_count))
        else:
            NOTIFICATION.messenger("Processed {} families. {} successful, {} failed.".format(
                self.success_count + self.failure_count, self.success_count, self.failure_count))
    
    def select_processing_mode(self):
        """Let user choose between processing selected families or selecting from category."""
        options = [
            "Process Selected Families",
            "Select from Family Category List"
        ]
        
        selected = REVIT_FORMS.dialogue(
            title="Choose Processing Mode",
            main_text="How would you like to select families to process?",
            sub_text="Choose your preferred method for selecting families to change category.",
            options=options
        )
        
        if selected == "Process Selected Families":
            return "selected"
        elif selected == "Select from Family Category List":
            return "category"
        else:
            return None
    
    def get_selected_families(self):
        """Get unique families from current selection (including family instances)."""
        from EnneadTab.REVIT import REVIT_SELECTION
        selected_elements = REVIT_SELECTION.get_selected_elements(self.doc)
        
        # Use set to ensure uniqueness by family ID
        family_dict = {}
        
        for element in selected_elements:
            family = None
            
            # Check if element is a family instance
            if isinstance(element, DB.FamilyInstance):
                family = element.Symbol.Family
            # Check if element is a family directly
            elif isinstance(element, DB.Family):
                family = element
            
            # Add to dict if it's a valid model family
            if family and family.FamilyCategory and family.FamilyCategory.CategoryType == DB.CategoryType.Model:
                family_id = family.Id
                if family_id not in family_dict:
                    family_dict[family_id] = family
        
        families = list(family_dict.values())
        
        if not families:
            NOTIFICATION.messenger("No families found in selection. Please select family instances or families and try again.")
            return []
        
        return families
    
    @ERROR_HANDLE.try_catch_error()
    def run(self):
        """Main execution method."""
        # Step 1: Choose processing mode
        mode = self.select_processing_mode()
        if not mode:
            return
        
        families = []
        source_category = None
        
        if mode == "selected":
            # Mode 1: Process selected families
            families = self.get_selected_families()
            if not families:
                return
            
            # Get the category of the first selected family (assuming all are from same category)
            source_category = families[0].FamilyCategory
            
        elif mode == "category":
            # Mode 2: Select from family category list
            # Step 2: Let user pick source family category
            source_category = self.select_source_category()
            if not source_category:
                return
            
            # Step 3: Let user pick families within that category
            families = self.select_families_in_category(source_category)
            if not families:
                return
        
        # Step 4: Let user pick target family category
        target_category = self.select_target_category()
        if not target_category:
            return
        
        # Step 5: Batch process families
        self.process_families(families, target_category)
        
        # Generate report
        self.generate_report()


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def change_family_category(doc):
    """Main function to change family categories."""
    changer = FamilyCategoryChanger(doc)
    changer.run()


################## main code below #####################
if __name__ == "__main__":
    change_family_category(DOC)







