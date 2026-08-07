 # -*- coding: utf-8 -*-
__title__ = "RandomDeselectByDist"
__doc__ = """Randomly deselects blocks based on their distance from a curve.

The probability of keeping a block is proportional to its distance from the curve.
Blocks closer to the curve have higher chance of being kept.
Distance clamping is available to control the influence range.

Usage:
1. Pre-select blocks or select when prompted
2. Select a base curve as attractor
3. Adjust distance clamps in the dialog
4. Click "Select" to apply random deselection
5. Keep clicking "Select" to get different random results
6. Adjust clamp values and click "Select" again to refine results
7. Click "Close" when satisfied with the selection

Features:
- Interactive Eto form with dedicated pick buttons
- Real-time distance range calculation
- Persistent settings (remembers last clamp values)
- Dynamic visualization (circles/pipes) that updates with each selection
- Iterative workflow - keep trying until you get the desired result
"""

import rhinoscriptsyntax as rs
import random
import os
import Eto.Forms as Forms
import Eto.Drawing as Drawing
import Rhino
import Rhino.UI
from EnneadTab import ERROR_HANDLE, LOG, DATA_FILE, NOTIFICATION
from EnneadTab.RHINO import RHINO_UI

FORM_KEY = 'random_deselect_by_dist_form'
TEMP_OBJ_NAME = 'TEMP_SELECTION_SIZE'


class RandomDeselectByDistDialog(Forms.Dialog[bool]):
    """Dialog for random deselection by distance with interactive controls."""
    
    def __init__(self):
        self.initial_blocks = []  # Store original selection
        self.current_blocks = []  # Current working selection
        self.base_crv = None
        self.min_dist = 0.0
        self.max_dist = 1.0
        self.Closed += self.OnFormClosed
        
        self.InitializeComponent()
        
    def InitializeComponent(self):
        """Initialize the form components."""
        self.Title = "Random De-Select by Distance"
        self.Size = Drawing.Size(420, 450)
        self.Resizable = False
        self.Padding = Drawing.Padding(10)
        
        # Main layout
        layout = Forms.DynamicLayout()
        layout.Padding = Drawing.Padding(10)
        layout.Spacing = Drawing.Size(5, 5)
        
        # Title
        title_label = Forms.Label()
        title_label.Text = "Random De-Select by Distance"
        title_label.Font = Drawing.Font("Arial", 12, Drawing.FontStyle.Bold)
        title_label.HorizontalAlign = Forms.HorizontalAlign.Center
        
        # Pick blocks button
        self.pick_blocks_btn = Forms.Button()
        self.pick_blocks_btn.Text = "Pick Blocks"
        self.pick_blocks_btn.Click += self.OnPickBlocks
        self.blocks_info_label = Forms.Label()
        # Use long placeholder text to reserve width so form size is stable
        self.blocks_info_label.Text = "No blocks selected"
        
        # Pick curve button  
        self.pick_crv_btn = Forms.Button()
        self.pick_crv_btn.Text = "Pick Curve"
        self.pick_crv_btn.Click += self.OnPickCurve
        self.crv_info_label = Forms.Label()
        # Use long placeholder text to reserve width so form size is stable
        self.crv_info_label.Text = "No curve selected"
        
        # Distance range button
        self.calc_range_btn = Forms.Button()
        self.calc_range_btn.Text = "Calculate Distance Range"
        self.calc_range_btn.Click += self.OnCalculateRange
        self.calc_range_btn.Enabled = False
        
        # Invert selection button
        self.invert_btn = Forms.Button()
        self.invert_btn.Text = "Invert Selection"
        self.invert_btn.Click += self.OnInvertSelection
        self.invert_btn.Enabled = False
        
        # Clamp inputs
        clamp0_layout = Forms.DynamicLayout()
        clamp0_layout.AddRow(Forms.Label(Text="Near Clamp:"), self.CreateClamp0Input())
        
        clamp1_layout = Forms.DynamicLayout()
        clamp1_layout.AddRow(Forms.Label(Text="Far Clamp:"), self.CreateClamp1Input())
        
        # Buttons
        self.select_btn = Forms.Button()
        self.select_btn.Text = "Select"
        self.select_btn.Click += self.OnSelect
        self.select_btn.Enabled = False
        
        close_btn = Forms.Button()
        close_btn.Text = "Close"
        close_btn.Click += self.OnClose
        
        # Assemble layout (single-column stacked layout)
        layout.AddSeparateRow(None, self.CreateLogoImage())
        layout.AddRow(title_label)
        layout.AddRow(None)  # spacer
        
        # Stack: button then its info label
        layout.AddRow(self.pick_blocks_btn)
        layout.AddRow(self.blocks_info_label)
        layout.AddRow(self.pick_crv_btn)
        layout.AddRow(self.crv_info_label)
        layout.AddRow(None)  # spacer
        
        layout.AddRow(self.calc_range_btn)
        layout.AddRow(self.invert_btn)
        layout.AddRow(None)  # spacer
        
        layout.AddRow(clamp0_layout)
        layout.AddRow(clamp1_layout)
        layout.AddRow(None)  # spacer
        
        layout.AddRow(self.select_btn)
        layout.AddRow(close_btn)
        
        self.Content = layout
        self.LoadSettings()
        RHINO_UI.apply_dark_style(self)
        
    def CreateLogoImage(self):
        """Create and return the logo image view widget."""
        self.logo = Forms.ImageView()
        
        # Use the same logo path pattern as other forms
        from EnneadTab import IMAGE
        logo_path = IMAGE.get_image_path_by_name("icon_logo_dark_background.png")
        if logo_path and os.path.exists(logo_path):
            temp_bitmap = Drawing.Bitmap(logo_path)
            self.logo.Image = temp_bitmap.WithSize(200, 30)
        else:
            # Fallback to a simple text label if logo not found
            self.logo = Forms.Label(Text="Random De-Select by Distance", Font=Drawing.Font("Arial", 12, Drawing.FontStyle.Bold))
        
        return self.logo
        
    def CreateClamp0Input(self):
        """Create clamp0 text input."""
        self.clamp0_text = Forms.TextBox()
        self.clamp0_text.Width = 100
        self.clamp0_text.Text = "0"
        return self.clamp0_text
        
    def CreateClamp1Input(self):
        """Create clamp1 text input."""
        self.clamp1_text = Forms.TextBox()
        self.clamp1_text.Width = 100
        self.clamp1_text.Text = "1"
        return self.clamp1_text
        
    def LoadSettings(self):
        """Load saved clamp settings."""
        saved_clamp0 = DATA_FILE.get_sticky("RandomDeselectByDist_clamp0", 0.0)
        saved_clamp1 = DATA_FILE.get_sticky("RandomDeselectByDist_clamp1", 1.0)
        self.clamp0_text.Text = str(saved_clamp0)
        self.clamp1_text.Text = str(saved_clamp1)
        
    @ERROR_HANDLE.try_catch_error()
    def SaveSettings(self):
        """Save clamp settings."""
        clamp0 = float(self.clamp0_text.Text)
        clamp1 = float(self.clamp1_text.Text)
        DATA_FILE.set_sticky("RandomDeselectByDist_clamp0", clamp0)
        DATA_FILE.set_sticky("RandomDeselectByDist_clamp1", clamp1)
            
    @ERROR_HANDLE.try_catch_error()
    def OnPickBlocks(self, sender, e):
        """Handle pick blocks button click."""
        self.initial_blocks = rs.GetObjects(message="Pick blocks pool", filter=4096, preselect=True)
        if self.initial_blocks:
            # Start with all blocks selected (no sub-selection yet)
            self.current_blocks = self.initial_blocks[:]  # Copy the list
            self.blocks_info_label.Text = "{} blocks selected".format(len(self.initial_blocks))
            self.UpdateSelectButton()
        else:
            self.current_blocks = []
            self.blocks_info_label.Text = "No blocks selected"
            
    @ERROR_HANDLE.try_catch_error()
    def OnPickCurve(self, sender, e):
        """Handle pick curve button click."""
        self.base_crv = rs.GetObject(message="Pick base curve as attractor", 
                                   filter=rs.filter.curve, preselect=True)
        if self.base_crv:
            self.crv_info_label.Text = "Curve selected"
            self.UpdateSelectButton()
        else:
            self.crv_info_label.Text = "No curve selected"
            
    @ERROR_HANDLE.try_catch_error()
    def OnCalculateRange(self, sender, e):
        """Calculate and update distance range."""
        if not self.current_blocks or not self.base_crv:
            NOTIFICATION.messenger("Please select blocks and curve first")
            return
            
        # Calculate distance range
        dist_map = []
        for x in self.current_blocks:
            dist = get_block_dist_to_crv(x, self.base_crv)
            if dist is not None:
                dist_map.append(float(dist))  # type: ignore
        
        if not dist_map:
            NOTIFICATION.messenger("No valid distances calculated")
            return
            
        sorted_map = sorted(dist_map)
        self.min_dist = sorted_map[0]
        self.max_dist = sorted_map[-1]
        
        # Update text boxes
        self.clamp0_text.Text = str(self.min_dist)
        self.clamp1_text.Text = str(self.max_dist)
        
        NOTIFICATION.messenger("Distance range: {:.3f} to {:.3f}".format(self.min_dist, self.max_dist))
        
    @ERROR_HANDLE.try_catch_error()
    def OnInvertSelection(self, sender, e):
        """Handle Invert Selection button click."""
        if not self.initial_blocks:
            NOTIFICATION.messenger("No initial blocks selected to invert")
            return
            
        # Invert selection: Current blocks = Initial blocks - Current blocks
        # Find blocks from initial selection that are NOT in current blocks
        inverted_blocks = []
        for obj in self.initial_blocks:
            if obj not in self.current_blocks:
                inverted_blocks.append(obj)
        
        # Update the current working selection to the inverted selection
        self.current_blocks = inverted_blocks[:]
        rs.UnselectAllObjects()
        rs.SelectObjects(self.current_blocks)
        self.blocks_info_label.Text = "{} blocks selected".format(len(self.current_blocks))
        
        # Update button states
        self.UpdateSelectButton()
        
        NOTIFICATION.messenger("Selection inverted: {} blocks from {} initial".format(
            len(self.current_blocks), len(self.initial_blocks)))
        
        
    def UpdateSelectButton(self):
        """Update Select button enabled state."""
        self.select_btn.Enabled = bool(self.current_blocks and self.base_crv)
        self.calc_range_btn.Enabled = bool(self.current_blocks and self.base_crv)
        
        # Invert button enabled when we have initial blocks (can always invert within initial set)
        self.invert_btn.Enabled = bool(self.initial_blocks and len(self.initial_blocks) > 0)
        
        
    @ERROR_HANDLE.try_catch_error()
    def OnSelect(self, sender, e):
        """Handle Select button click."""
        clamp0 = float(self.clamp0_text.Text)
        clamp1 = float(self.clamp1_text.Text)
        
        # Validate inputs
        if clamp0 < 0 or clamp1 < 0:
            NOTIFICATION.messenger("Clamp values must be positive")
            return
            
        if clamp0 >= clamp1:
            NOTIFICATION.messenger("Near clamp must be less than far clamp")
            return
            
        # Save settings
        self.SaveSettings()
        
        # Execute the deselection (form stays open)
        self.execute_random_deselect(clamp0, clamp1)
            
    def OnClose(self, sender, e):
        """Handle Close button click."""
        self.Close(True)
        
    def OnFormClosed(self, sender, e):
        """Handle form closed event and clean up visualization objects."""
        # Clean up all temporary visualization objects
        purge_old_visualization()
        
    @ERROR_HANDLE.try_catch_error()
    def execute_random_deselect(self, clamp0, clamp1):
        """Execute the random deselection logic."""
        # Calculate distance range
        dist_map = []
        for x in self.initial_blocks:
            dist = get_block_dist_to_crv(x, self.base_crv)
            if dist is not None:
                dist_map.append(float(dist))  # type: ignore
        
        if not dist_map:
            NOTIFICATION.messenger("No valid distances calculated")
            return

        sorted_map = sorted(dist_map)
        min_dist = sorted_map[0]
        max_dist = sorted_map[-1]

        # Create visual guides
        create_visualization(self.base_crv, clamp0, clamp1)

        # Calculate keep probability for each block
        factor_map = [map_num_with_clamp(x, min_dist, max_dist, 1.0, 0.0, clamp0, clamp1) for x in dist_map]
        keep_map = [random.random() < x for x in factor_map]
        kept_blocks = filter_by_mask(self.initial_blocks, keep_map)

        # Update selection
        rs.UnselectAllObjects()
        rs.SelectObjects(kept_blocks)
        self.current_blocks = kept_blocks[:]
        
        NOTIFICATION.messenger("Kept {} out of {} blocks".format(len(kept_blocks), len(self.initial_blocks)))
        
        # Update button states
        self.UpdateSelectButton()


def map_num_linear(X, x0, x1, y0, y1):
    """Maps a number from one range to another linearly.
    
    Args:
        X (float): Input value to map
        x0 (float): Input range start
        x1 (float): Input range end
        y0 (float): Output range start
        y1 (float): Output range end
    
    Returns:
        float: Mapped value in output range
    """
    k = (y1 - y0) / (x1 - x0)
    b = y0 - k * x0
    return k * float(X) + b


def map_num_with_clamp(X, x0, x1, y0, y1, clamp0, clamp1):
    """Maps a number with clamping at boundaries.
    
    Args:
        X (float): Input value to map
        x0, x1 (float): Input range
        y0, y1 (float): Output range
        clamp0 (float): Lower clamp threshold
        clamp1 (float): Upper clamp threshold
    
    Returns:
        float: Mapped and clamped value
    """
    if X < clamp0:
        return y0
    if X > clamp1:
        return y1
    return map_num_linear(X, clamp0, clamp1, y0, y1)


def get_block_dist_to_crv(block, crv):
    """Calculates distance from block insertion point to closest point on curve.
    
    Args:
        block: Block instance ID
        crv: Curve ID
    
    Returns:
        float: Distance between block and curve
    """
    pt = rs.BlockInstanceInsertPoint(block)
    param = rs.CurveClosestPoint(crv, pt, segment_index=-1)
    closest_pt = rs.EvaluateCurve(crv, param, segment_index=-1)
    return rs.Distance(closest_pt, pt)


def filter_by_mask(obj_list, bool_mask):
    """Filters a list of objects using a boolean mask.
    
    Args:
        obj_list (list): Objects to filter
        bool_mask (list): Boolean values determining which objects to keep
    
    Returns:
        list: Filtered objects where mask is True
    """
    return [obj for obj, keep in zip(obj_list, bool_mask) if keep]


def is_valid_guid(obj_id):
    """Check if a GUID is valid for Rhino operations."""
    if not obj_id:
        return False
    guid_str = str(obj_id)
    if guid_str == "00000000-0000-0000-0000-000000000000":
        return False
    try:
        # Try to get object properties to validate it exists
        rs.ObjectName(obj_id)
        return True
    except:
        return False


def purge_old_visualization():
    """Purge old visualization objects with TEMP_SELECTION_SIZE name."""
    old_objects = rs.ObjectsByName(TEMP_OBJ_NAME)
    if old_objects:
        rs.DeleteObjects(old_objects)


def create_visualization(base_crv, clamp0, clamp1):
    """Creates visual guides showing the clamping distances.
    
    Args:
        base_crv: Curve ID
        clamp0 (float): Near clamp distance
        clamp1 (float): Far clamp distance
    """
    # Purge old visualization objects first
    purge_old_visualization()
    
    # Create circles if curve is short/point-like (skip if radius is 0)
    circles = []
    center = rs.CurveEndPoint(base_crv)
    if center and clamp0 > 0:
        circle_id = rs.AddCircle(center, clamp0)
        if is_valid_guid(circle_id):
            rs.ObjectName(circle_id, TEMP_OBJ_NAME)
            circles.append(circle_id)
    if center and clamp1 > 0:
        circle_id = rs.AddCircle(center, clamp1)
        if is_valid_guid(circle_id):
            rs.ObjectName(circle_id, TEMP_OBJ_NAME)
            circles.append(circle_id)
    
    if circles:  # Only create group if there are circles
        group_id = rs.AddGroup()
        if is_valid_guid(group_id):
            rs.AddObjectsToGroup(circles, group_id)

    # Try creating pipes for longer curves (skip if radius is 0)
        pipes = []
    if clamp0 > 0:
        pipe_result = rs.AddPipe(base_crv, parameters=0, radii=clamp0, blend_type=0, cap=2, fit=False)
        if pipe_result:
            # AddPipe might return a list of objects or a single object
            if isinstance(pipe_result, list):
                for pipe_id in pipe_result:
                    if is_valid_guid(pipe_id):
                        rs.ObjectName(pipe_id, TEMP_OBJ_NAME)
                        pipes.append(pipe_id)
            else:
                if is_valid_guid(pipe_result):
                    rs.ObjectName(pipe_result, TEMP_OBJ_NAME)
                    pipes.append(pipe_result)
    if clamp1 > 0:
        pipe_result = rs.AddPipe(base_crv, parameters=0, radii=clamp1, blend_type=0, cap=2, fit=False)
        if pipe_result:
            # AddPipe might return a list of objects or a single object
            if isinstance(pipe_result, list):
                for pipe_id in pipe_result:
                    if is_valid_guid(pipe_id):
                        rs.ObjectName(pipe_id, TEMP_OBJ_NAME)
                        pipes.append(pipe_id)
            else:
                if is_valid_guid(pipe_result):
                    rs.ObjectName(pipe_result, TEMP_OBJ_NAME)
                    pipes.append(pipe_result)
    
    if pipes:  # Only create group if there are pipes
        group_id = rs.AddGroup()
        if is_valid_guid(group_id):
            rs.AddObjectsToGroup(pipes, group_id)




@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def random_deselect_by_dist():
    """Main function to show the Eto form dialog."""
    dialog = RandomDeselectByDistDialog()
    result = Rhino.UI.EtoExtensions.ShowSemiModal(dialog, Rhino.RhinoDoc.ActiveDoc, Rhino.UI.RhinoEtoApp.MainWindow)
    
    if result:
        NOTIFICATION.messenger("Random deselection tool closed")
    else:
        NOTIFICATION.messenger("Tool cancelled")


if __name__ == "__main__":
    random_deselect_by_dist()
