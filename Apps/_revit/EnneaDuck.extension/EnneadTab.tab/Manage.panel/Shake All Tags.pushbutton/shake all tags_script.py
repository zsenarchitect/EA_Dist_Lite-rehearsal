#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Force every tag on the sheets you pick to redraw itself with current text.

Fixes blank or stale tag text without leaving any permanent change behind: each
tag is nudged, the view refreshes, and the tag is put straight back where it was.
The whole run is one undo step.

Features:
- Pinned tags are temporarily unpinned, then re-pinned
- Tags owned by another user in a workshared model are skipped
- Summary of shaken, refreshed, failed, and skipped tags when it finishes"""
__title__ = "Shake\nAll Tags"
__tip__ = True

import proDUCKtion # pyright: ignore 
proDUCKtion.validify()

from EnneadTab import ERROR_HANDLE, LOG
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_SELECTION, REVIT_TAG
from Autodesk.Revit import DB # pyright: ignore 

try:
    from pyrevit import script, forms # pyright: ignore
    OUTPUT = script.get_output()
except: # pylint: disable=bare-except
    OUTPUT = None
    forms = None

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()


# =============================================================================
# CONSTANTS
# =============================================================================

SHAKE_OFFSET = DB.XYZ(0.1, 0.1, 0.1)


# =============================================================================
# CLASSES
# =============================================================================

class TagShakeStats:
    """Track statistics for tag shaking operation."""
    
    def __init__(self):
        self.total_tags = 0
        self.shaken_tags = 0
        self.refreshed_tags = 0
        self.failed_tags = 0
        self.skipped_tags = 0
        
    def add_result(self, was_shaken, was_refreshed, failed=False, skipped=False):
        """Record result of shaking a tag."""
        self.total_tags += 1
        if skipped:
            self.skipped_tags += 1
        elif failed:
            self.failed_tags += 1
        else:
            if was_shaken:
                self.shaken_tags += 1
            if was_refreshed:
                self.refreshed_tags += 1
    
    def get_summary(self):
        """Get summary string of statistics."""
        parts = []
        if self.shaken_tags > 0:
            parts.append("{} shaken".format(self.shaken_tags))
        if self.refreshed_tags > 0:
            parts.append("{} refreshed".format(self.refreshed_tags))
        if self.failed_tags > 0:
            parts.append("{} failed".format(self.failed_tags))
        if self.skipped_tags > 0:
            parts.append("{} skipped".format(self.skipped_tags))
        
        if parts:
            return " | ".join(parts)
        return "No tags processed"


# =============================================================================
# FUNCTIONS
# =============================================================================

def get_views_from_sheet(sheet, doc):
    """Get all view elements from a sheet.
    
    Args:
        sheet: ViewSheet element
        doc: Document object
        
    Returns:
        list: List of view elements
    """
    views = []
    for view_id in sheet.GetAllViewports():
        view = doc.GetElement(view_id)
        if view:
            views.append(view)
    return views


def collect_tags_from_view(view, doc):
    """Collect all tags from a view.
    
    Args:
        view: View element
        doc: Document object
        
    Returns:
        list: List of tag elements (IndependentTag and SpatialElementTag)
    """
    independent_tags = DB.FilteredElementCollector(doc, view.ViewId)\
        .OfClass(DB.IndependentTag)\
        .WhereElementIsNotElementType()\
        .ToElements()

    spatial_el_tags = DB.FilteredElementCollector(doc, view.ViewId)\
        .OfClass(DB.SpatialElementTag)\
        .WhereElementIsNotElementType()\
        .ToElements()

    return list(independent_tags) + list(spatial_el_tags)


def shake_single_tag(tag, view_element, doc):
    """Shake a single tag to force refresh.
    
    Args:
        tag: Tag element to shake
        view_element: View element containing the tag
        doc: Document object
        
    Returns:
        tuple: (was_shaken: bool, was_refreshed: bool, error: str or None, skipped: bool)
    """
    if not tag or not view_element:
        return False, False, "Invalid tag or view", True
    
    # Check if tag is changeable (user has ownership)
    if not REVIT_SELECTION.is_changable(tag):
        return False, False, "Tag is not changeable (no ownership)", True
    
    try:
        pin_condition = tag.Pinned
        old_text = tag.TagText if hasattr(tag, 'TagText') else None
        up_direction = view_element.UpDirection
        
        # Check if tag has a leader - tags without leaders have restrictions on TagHeadPosition
        has_leader = hasattr(tag, 'HasLeader') and tag.HasLeader
        
        # Combined transaction for forward and back movement
        t = DB.Transaction(doc, "Shake Tag")
        t.Start()
        
        try:
            # Unpin if needed
            if pin_condition:
                tag.Pinned = False
            
            # Move tag forward using Location (works for all tags)
            if hasattr(tag, 'Location') and tag.Location:
                tag.Location.Move(up_direction)
                tag.Location.Move(SHAKE_OFFSET)
            
            # Only move TagHeadPosition if tag has a leader
            # Tags without leaders cannot have head position outside host element
            if has_leader and hasattr(tag, 'TagHeadPosition'):
                try:
                    current_head = tag.TagHeadPosition
                    tag.TagHeadPosition = current_head + up_direction + SHAKE_OFFSET
                except:
                    # If TagHeadPosition fails, continue with Location movement only
                    pass
            
            # Move leader end if tag has a leader
            if has_leader:
                try:
                    current_leader_end = REVIT_TAG.get_leader_end(tag)
                    REVIT_TAG.set_leader_end(tag, current_leader_end + up_direction)
                except:
                    pass
            
            doc.Regenerate()
            
            # Move tag back
            if hasattr(tag, 'Location') and tag.Location:
                tag.Location.Move(-1 * up_direction)
                tag.Location.Move(-1 * SHAKE_OFFSET)
            
            # Only move TagHeadPosition back if tag has a leader
            if has_leader and hasattr(tag, 'TagHeadPosition'):
                try:
                    current_head = tag.TagHeadPosition
                    tag.TagHeadPosition = current_head - up_direction - SHAKE_OFFSET
                except:
                    pass
            
            # Move leader end back if tag has a leader
            if has_leader:
                try:
                    current_leader_end = REVIT_TAG.get_leader_end(tag)
                    REVIT_TAG.set_leader_end(tag, current_leader_end - up_direction)
                except:
                    pass
            
            # Restore pin state
            if pin_condition:
                tag.Pinned = True
            
            t.Commit()
            
            # Check if tag text was refreshed
            new_text = tag.TagText if hasattr(tag, 'TagText') else None
            was_refreshed = (old_text is not None and new_text is not None and 
                           old_text != new_text)
            
            return True, was_refreshed, None, False
            
        except Exception as e:
            t.RollBack()
            error_msg = "Error shaking tag: {}".format(str(e))
            return False, False, error_msg, False
            
    except Exception as e:
        error_msg = "Failed to process tag: {}".format(str(e))
        return False, False, error_msg, False


def shake_tags_in_view(view, doc, stats, output=None):
    """Shake all tags in a view to force refresh.
    
    Args:
        view: View element containing tags to shake
        doc: Document object
        stats: TagShakeStats object to track statistics
        output: Optional output object for progress updates
        
    Returns:
        int: Number of tags processed
    """
    tags = collect_tags_from_view(view, doc)
    
    if not tags:
        return 0
    
    view_name = view.Parameter[DB.BuiltInParameter.VIEW_NAME].AsString()
    view_element = doc.GetElement(view.ViewId)
    
    if not view_element:
        print("Warning: Could not get view element for view: {}".format(view_name))
        return 0
    
    print('Processing {} tags in view: {}'.format(len(tags), view_name))
    
    for idx, tag in enumerate(tags):
        was_shaken, was_refreshed, error, skipped = shake_single_tag(tag, view_element, doc)
        
        if skipped:
            stats.add_result(was_shaken=False, was_refreshed=False, skipped=True)
            # Don't print skipped tags to avoid clutter - they're expected in worksharing
        elif error:
            stats.add_result(was_shaken=False, was_refreshed=False, failed=True)
            if OUTPUT:
                OUTPUT.print_md("**Error**: {} | View: {}".format(error, view_name))
        else:
            stats.add_result(was_shaken=was_shaken, was_refreshed=was_refreshed)
            if was_refreshed and hasattr(tag, 'TagText'):
                print("  Tag refreshed: {}".format(tag.TagText))
        
        # Update progress for tag-level processing
        if output and len(tags) > 10:  # Only show progress for views with many tags
            output.update_progress(idx + 1, len(tags))
    
    return len(tags)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main():
    """Main function to shake all tags on selected sheets."""
    if not DOC:
        print("No active document.")
        return
    
    if not forms:
        print("pyrevit.forms not available.")
        return
    
    sel_sheets = forms.select_sheets(
        title='Select Sheets That Have The Tags You Want To ~~Shake~~'
    )

    if not sel_sheets:
        return

    # Collect all views from selected sheets
    target_views = []
    for sheet in sel_sheets:
        views = get_views_from_sheet(sheet, DOC)
        target_views.extend(views)
        print("Sheet '{}' has {} view(s)".format(
            sheet.Parameter[DB.BuiltInParameter.SHEET_NUMBER].AsString() + " - " +
            sheet.Parameter[DB.BuiltInParameter.SHEET_NAME].AsString(),
            len(views)
        ))

    if not target_views:
        print("No views found on selected sheets.")
        return

    # Count total tags before processing
    total_tags = 0
    for view in target_views:
        tags = collect_tags_from_view(view, DOC)
        total_tags += len(tags)
    
    if total_tags == 0:
        print("No tags found in selected views.")
        return

    print('\n' + '='*60)
    print('Shaking tags in {} view(s) | Total tags: {}'.format(len(target_views), total_tags))
    print('='*60 + '\n')
    
    stats = TagShakeStats()
    tg = DB.TransactionGroup(DOC, 'Shake All Tags')
    tg.Start()
    
    try:
        for idx, view in enumerate(target_views):
            if OUTPUT:
                OUTPUT.print_md("**Processing view {}/{}**".format(idx + 1, len(target_views)))
            
            shake_tags_in_view(view, DOC, stats, OUTPUT)
            
            if OUTPUT:
                OUTPUT.update_progress(idx + 1, len(target_views))
    finally:
        tg.Assimilate()
    
    # Print summary
    print('\n' + '='*60)
    print('Shake Complete!')
    print('='*60)
    print('Total tags: {}'.format(stats.total_tags))
    print('Summary: {}'.format(stats.get_summary()))
    print('='*60)
    
    if OUTPUT:
        OUTPUT.print_md("## Shake Complete!")
        OUTPUT.print_md("**Total tags**: {}".format(stats.total_tags))
        OUTPUT.print_md("**Summary**: {}".format(stats.get_summary()))


################## main code below #####################
if __name__ == '__main__':
    main()
