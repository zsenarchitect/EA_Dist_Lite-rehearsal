#!/usr/bin/python
# -*- coding: utf-8 -*-

__title__ = "EnneadCity GUI"
__doc__ = "EnneadCity - Work on your plot with GUI interface"

import rhinoscriptsyntax as rs
import scriptcontext as sc
import os
import sys

# Import ETO forms
import Rhino.UI
import Eto.Forms as forms
import Eto.Drawing as drawing

# Import EnneadTab modules
from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION

# Get current script file directory
my_directory = os.path.dirname(os.path.realpath(__file__))
sys.path.append(my_directory)
import city_utility # pyright: ignore


class EnneadCityForm(forms.Dialog[bool]):
    """Main EnneadCity GUI form"""
    
    def __init__(self):
        self.InitializeComponent()
        
    def InitializeComponent(self):
        """Initialize the form components"""
        # Form properties
        self.Title = "EnneadCity - Plot Management"
        self.Size = drawing.Size(400, 300)
        self.Resizable = False
        
        # Main layout
        self.main_layout = forms.TableLayout()
        self.main_layout.Padding = drawing.Padding(10)
        self.main_layout.Spacing = drawing.Size(5, 5)
        
        # Title label
        self.title_label = forms.Label()
        self.title_label.Text = "EnneadCity Plot Management"
        self.title_label.Font = drawing.Font("Arial", 14, drawing.FontStyle.Bold)
        self.title_label.HorizontalAlign = forms.HorizontalAlign.Center
        
        # Current user info
        self.user_info_label = forms.Label()
        self.user_info_label.Text = "Current User: {}".format(city_utility.USER.USER_NAME)
        self.user_info_label.Font = drawing.Font("Arial", 10)
        
        # Current plot info
        self.current_plot_label = forms.Label()
        current_plot = city_utility.get_current_user_plot_file()
        if current_plot and os.path.exists(current_plot):
            self.current_plot_label.Text = "Current Plot: {}".format(os.path.basename(current_plot))
            self.current_plot_label.TextColor = drawing.Color.FromArgb(0, 128, 0)  # Green
        else:
            self.current_plot_label.Text = "No plot assigned"
            self.current_plot_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
        
        # Buttons section
        self.buttons_layout = forms.TableLayout()
        self.buttons_layout.Rows.Add(forms.TableRow())
        
        # Open current plot button
        self.open_current_btn = forms.Button()
        self.open_current_btn.Text = "Open My Current Plot"
        self.open_current_btn.Size = drawing.Size(150, 30)
        self.open_current_btn.Click += self.OnOpenCurrentPlot
        
        # Select new plot button
        self.select_plot_btn = forms.Button()
        self.select_plot_btn.Text = "Select New Plot"
        self.select_plot_btn.Size = drawing.Size(150, 30)
        self.select_plot_btn.Click += self.OnSelectNewPlot

        # Release current plot button
        self.release_current_btn = forms.Button()
        self.release_current_btn.Text = "Release My Plot"
        self.release_current_btn.Size = drawing.Size(150, 30)
        self.release_current_btn.Click += self.OnReleaseCurrentPlot

        # Load all plots button
        self.load_all_btn = forms.Button()
        self.load_all_btn.Text = "Load All Plots (Session)"
        self.load_all_btn.Size = drawing.Size(150, 30)
        self.load_all_btn.Click += self.OnLoadAllPlots

        # Admin: split masterplan button (infrequent admin action, visually
        # separated from the main claim/release/load flow)
        self.admin_split_btn = forms.Button()
        self.admin_split_btn.Text = "Admin: Split Masterplan"
        self.admin_split_btn.Size = drawing.Size(150, 30)
        self.admin_split_btn.Click += self.OnAdminSplitMasterplan
        
        # Available plots info
        self.available_plots_label = forms.Label()
        self.available_plots_label.Text = "Available Plots:"
        self.available_plots_label.Font = drawing.Font("Arial", 10, drawing.FontStyle.Bold)
        
        # Plots list
        self.plots_list = forms.ListBox()
        self.plots_list.Height = 100
        self.plots_list.SelectionMode = forms.ListBoxSelectionMode.Single
        self.UpdatePlotsList()
        
        # Status label
        self.status_label = forms.Label()
        self.status_label.Text = "Ready"
        self.status_label.Font = drawing.Font("Arial", 9)
        self.status_label.TextColor = drawing.Color.FromArgb(0, 0, 255)  # Blue
        
        # Bottom buttons
        self.bottom_layout = forms.TableLayout()
        self.bottom_layout.Rows.Add(forms.TableRow())
        
        self.refresh_btn = forms.Button()
        self.refresh_btn.Text = "Refresh"
        self.refresh_btn.Click += self.OnRefresh
        
        self.close_btn = forms.Button()
        self.close_btn.Text = "Close"
        self.close_btn.Click += self.OnClose
        
        # Assemble layout
        self.main_layout.Rows.Add(forms.TableRow(self.title_label))
        self.main_layout.Rows.Add(forms.TableRow(self.user_info_label))
        self.main_layout.Rows.Add(forms.TableRow(self.current_plot_label))
        self.main_layout.Rows.Add(forms.TableRow())  # Spacer
        
        # Buttons row
        button_row = forms.TableRow()
        button_row.Cells.Add(self.open_current_btn)
        button_row.Cells.Add(self.select_plot_btn)
        button_row.Cells.Add(self.release_current_btn)
        self.main_layout.Rows.Add(button_row)

        self.main_layout.Rows.Add(forms.TableRow(self.load_all_btn))
        self.main_layout.Rows.Add(forms.TableRow(self.admin_split_btn))
        self.main_layout.Rows.Add(forms.TableRow())  # Spacer
        
        self.main_layout.Rows.Add(forms.TableRow(self.available_plots_label))
        self.main_layout.Rows.Add(forms.TableRow(self.plots_list))
        self.main_layout.Rows.Add(forms.TableRow(self.status_label))
        
        # Bottom buttons row
        bottom_row = forms.TableRow()
        bottom_row.Cells.Add(self.refresh_btn)
        bottom_row.Cells.Add(self.close_btn)
        self.main_layout.Rows.Add(bottom_row)
        
        self.Content = self.main_layout
        
    def UpdatePlotsList(self):
        """Update the list of available plots"""
        try:
            empty_plots = city_utility.get_empty_plot_files()
            occupied_plots = city_utility.get_occupied_plot_files()
            
            self.plots_list.Items.Clear()
            
            # Add empty plots
            for plot in empty_plots:
                plot_name = os.path.basename(plot).replace(".3dm", "")
                self.plots_list.Items.Add("{} (Available)".format(plot_name))
            
            # Add occupied plots
            for plot in occupied_plots:
                plot_name = os.path.basename(plot).replace(".3dm", "")
                self.plots_list.Items.Add("{} (Occupied)".format(plot_name))
                
        except Exception as e:
            self.status_label.Text = "Error loading plots: {}".format(str(e))
            self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
            try:
                ERROR_HANDLE.send_error_to_error_dump(str(e), "UpdatePlotsList", city_utility.USER.USER_NAME)
            except Exception:
                pass

    def OnOpenCurrentPlot(self, sender, e):
        """Handle opening current user's plot"""
        try:
            plot_file = city_utility.get_current_user_plot_file()
            if plot_file and os.path.exists(plot_file):
                import clr # pyright: ignore
                is_open = clr.StrongBox[bool](False)
                sc.doc.Open(plot_file, is_open)
                self.status_label.Text = "Opened current plot: {}".format(os.path.basename(plot_file))
                self.status_label.TextColor = drawing.Color.FromArgb(0, 128, 0)  # Green
            else:
                self.status_label.Text = "No current plot assigned or file not found"
                self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
        except Exception as ex:
            self.status_label.Text = "Error opening plot: {}".format(str(ex))
            self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
            try:
                ERROR_HANDLE.send_error_to_error_dump(str(ex), "OnOpenCurrentPlot", city_utility.USER.USER_NAME)
            except Exception:
                pass

    def OnReleaseCurrentPlot(self, sender, e):
        """Handle releasing current user's claimed plot"""
        try:
            plot_file = city_utility.get_current_user_plot_file()
            if not plot_file:
                self.status_label.Text = "No current plot assigned to release"
                self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
                return

            plot_id = os.path.splitext(os.path.basename(plot_file))[0]
            success = city_utility.release_current_user_plot_file(plot_id)

            if success:
                self.status_label.Text = "Released plot: {}".format(plot_id)
                self.status_label.TextColor = drawing.Color.FromArgb(0, 128, 0)  # Green

                self.current_plot_label.Text = "No plot assigned"
                self.current_plot_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red

                self.UpdatePlotsList()
            else:
                self.status_label.Text = "Failed to release plot: {}".format(plot_id)
                self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
        except Exception as ex:
            self.status_label.Text = "Error releasing plot: {}".format(str(ex))
            self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
            try:
                ERROR_HANDLE.send_error_to_error_dump(str(ex), "OnReleaseCurrentPlot", city_utility.USER.USER_NAME)
            except Exception:
                pass

    def OnSelectNewPlot(self, sender, e):
        """Handle selecting a new plot"""
        try:
            empty_plots = city_utility.get_empty_plot_files()
            if not empty_plots:
                self.status_label.Text = "No available plots found"
                self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
                return
            
            # Create plot selection dialog
            plot_names = [os.path.basename(plot).replace(".3dm", "") for plot in empty_plots]
            plot_number = rs.ListBox(plot_names, 
                                   message="Select a plot number from those available plots", 
                                   title="EnneadCity - Select Plot")
            
            if not plot_number:
                self.status_label.Text = "No plot selected"
                return
            
            # Set the selected plot
            plot_file = os.path.join(city_utility.PLOT_FILES_FOLDER, "{}.3dm".format(plot_number))
            claimed = city_utility.set_current_user_plot_file(plot_file)
            if not claimed:
                # Claim failed (already claimed by someone else / network /
                # auth failure) -- city_utility already reported the real
                # cause via ErrorDump + NOTIFICATION. Do NOT proceed to open a
                # file that was never actually claimed/downloaded, and do NOT
                # report false success.
                self.status_label.Text = "Could not claim plot {}. See notification for details.".format(plot_number)
                self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
                self.UpdatePlotsList()
                return

            # Open the plot
            import clr # pyright: ignore
            is_open = clr.StrongBox[bool](False)
            sc.doc.Open(plot_file, is_open)
            rs.Command("_SetLinetypeScale 500 _Enter")
            
            self.status_label.Text = "Selected and opened plot: {}".format(plot_number)
            self.status_label.TextColor = drawing.Color.FromArgb(0, 128, 0)  # Green
            
            # Update current plot label
            self.current_plot_label.Text = "Current Plot: {}".format(plot_number)
            self.current_plot_label.TextColor = drawing.Color.FromArgb(0, 128, 0)  # Green
            
            # Refresh plots list
            self.UpdatePlotsList()
            
        except Exception as ex:
            self.status_label.Text = "Error selecting plot: {}".format(str(ex))
            self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
            try:
                ERROR_HANDLE.send_error_to_error_dump(str(ex), "OnSelectNewPlot", city_utility.USER.USER_NAME)
            except Exception:
                pass

    def OnLoadAllPlots(self, sender, e):
        """Handle loading all plots into a session.

        Strict all-or-nothing per docs/plans/cloud-to-local-bridge.md and
        MENTAL-MODEL.md's Invariants: attempt to download EVERY required file
        first (every plot with an uploaded .3dm, plus every background file).
        If ANY of them fails, abort the whole action -- never build or run
        -WorkSession with a partial set, and never silently skip a missing
        file. Only on 100% success is the Attach command string built and run.
        """
        try:
            plot_paths, background_paths, failures = city_utility.download_all_required_files()

            if failures:
                detail = "; ".join("{}: {}".format(name, reason) for name, reason in failures)
                message = "Cannot load all plots -- {} file(s) failed to download ({}). No WorkSession was opened.".format(
                    len(failures), detail)
                self.status_label.Text = message
                self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
                try:
                    ERROR_HANDLE.send_error_to_error_dump(message, "OnLoadAllPlots", city_utility.USER.USER_NAME)
                except Exception:
                    pass
                try:
                    NOTIFICATION.messenger(main_text=message)
                except Exception:
                    pass
                return

            all_files = plot_paths + background_paths
            if not all_files:
                self.status_label.Text = "No plot files or background files found to attach"
                self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
                return

            file_string_link = ""
            for file in all_files:
                file_string_link += " Attach \"{}\"".format(file)

            rs.Command("-WorkSession  {}  Enter".format(file_string_link))
            rs.ZoomExtents(view=None, all=True)
            rs.Command("_SetLinetypeScale 500 _Enter")
            self.status_label.Text = "Loaded all plots into session"
            self.status_label.TextColor = drawing.Color.FromArgb(0, 128, 0)  # Green

        except Exception as ex:
            self.status_label.Text = "Error loading all plots: {}".format(str(ex))
            self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
            try:
                ERROR_HANDLE.send_error_to_error_dump(str(ex), "OnLoadAllPlots", city_utility.USER.USER_NAME)
            except Exception:
                pass

    def OnAdminSplitMasterplan(self, sender, e):
        """Admin action: split the currently OPEN master-plan Rhino document
        into per-plot files and upload each to the cloud API. Needs an open
        Rhino document with the master plan visible -- this is a desktop-side,
        infrequent admin action, not part of the main claim/release flow."""
        try:
            import export_from_masterplan # pyright: ignore
            export_from_masterplan.export_from_masterplan()

            self.status_label.Text = "Masterplan split complete (see ErrorDump for any per-plot upload failures)"
            self.status_label.TextColor = drawing.Color.FromArgb(0, 128, 0)  # Green

            self.UpdatePlotsList()
        except Exception as ex:
            self.status_label.Text = "Error splitting masterplan: {}".format(str(ex))
            self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
            try:
                ERROR_HANDLE.send_error_to_error_dump(str(ex), "OnAdminSplitMasterplan", city_utility.USER.USER_NAME)
            except Exception:
                pass

    def OnRefresh(self, sender, e):
        """Handle refresh button click"""
        try:
            # Update current plot info
            current_plot = city_utility.get_current_user_plot_file()
            if current_plot and os.path.exists(current_plot):
                self.current_plot_label.Text = "Current Plot: {}".format(os.path.basename(current_plot))
                self.current_plot_label.TextColor = drawing.Color.FromArgb(0, 128, 0)  # Green
            else:
                self.current_plot_label.Text = "No plot assigned"
                self.current_plot_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
            
            # Update plots list
            self.UpdatePlotsList()
            
            self.status_label.Text = "Refreshed"
            self.status_label.TextColor = drawing.Color.FromArgb(0, 0, 255)  # Blue
            
        except Exception as ex:
            self.status_label.Text = "Error refreshing: {}".format(str(ex))
            self.status_label.TextColor = drawing.Color.FromArgb(255, 0, 0)  # Red
            try:
                ERROR_HANDLE.send_error_to_error_dump(str(ex), "OnRefresh", city_utility.USER.USER_NAME)
            except Exception:
                pass

    def OnClose(self, sender, e):
        """Handle close button click"""
        self.Close(True)


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def ennead_city_gui():
    """Main function to show the EnneadCity GUI"""
    try:
        # Cached files are scratch -- sweep anything older than 7 days on each
        # GUI launch (best-effort, never raises).
        try:
            city_utility.cleanup_stale_cache()
        except Exception:
            pass

        # Create and show the form
        form = EnneadCityForm()
        form.ShowModal(Rhino.UI.RhinoEtoApp.MainWindow)
        return True
    except Exception as e:
        print("Error showing EnneadCity GUI: {}".format(str(e)))
        try:
            ERROR_HANDLE.send_error_to_error_dump(str(e), "ennead_city_gui", city_utility.USER.USER_NAME)
        except Exception:
            pass
        return False


if __name__ == "__main__":
    ennead_city_gui()
