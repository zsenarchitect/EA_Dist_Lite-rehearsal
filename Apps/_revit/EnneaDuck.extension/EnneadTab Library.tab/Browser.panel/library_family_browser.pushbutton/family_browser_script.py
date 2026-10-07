#!/usr/bin/python
# -*- coding: utf-8 -*-



__doc__ = "Browse and place digital assets from EnneadTab-Library directly into the active document.\n\nDisclaimer: EnneadTab only helps you find and load the asset, but is not participating in the creation and maintenance of the library content."
__title__ = "Family\nBrowser"


from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent # pyright: ignore
from Autodesk.Revit.Exceptions import InvalidOperationException # pyright: ignore
from pyrevit.forms import WPFWindow # pyright: ignore
# from pyrevit import forms #
from pyrevit import script #
# from pyrevit import revit #
import os

import System # pyright: ignore
import proDUCKtion # pyright: ignore
proDUCKtion.validify()
from EnneadTab import AUTH, ENVIRONMENT, ERROR_HANDLE, NOTIFICATION
from EnneadTab.DEPOT import LIBRARY_CATALOG
import traceback
from Autodesk.Revit import DB # pyright: ignore

from Autodesk.Revit import UI # pyright: ignore
uidoc = __revit__.ActiveUIDocument # pyright: ignore
doc = __revit__.ActiveUIDocument.Document # pyright: ignore
__persistentengine__ = True


def _find_loaded_family(target_doc, family_name):
    """Post-LoadFamily lookup by name -- the established idiom in this repo
    (content_transfer_script.py, cleanup_family_script.py) since IronPython's
    out-param LoadFamily overload is fragile; a name match on the freshly
    loaded family is simpler and already proven here."""
    for family in DB.FilteredElementCollector(target_doc).OfClass(DB.Family):
        if family.Name == family_name:
            return family
    return None


def _activate_default_symbol(target_doc, family):
    """Return an active FamilySymbol for `family`, or None if it has none."""
    symbol_ids = family.GetFamilySymbolIds()
    if not symbol_ids or symbol_ids.Count == 0:
        return None
    symbol = target_doc.GetElement(list(symbol_ids)[0])
    if symbol is None:
        return None
    if not symbol.IsActive:
        t = DB.Transaction(target_doc, "Activate Family Symbol")
        t.Start()
        symbol.Activate()
        target_doc.Regenerate()
        t.Commit()
    return symbol


@ERROR_HANDLE.try_catch_error()
def load_family(family_path):
    """Load `family_path` into the active document, then prompt the user to
    place an instance (#5449: "Direct Family Load/Placement"). Placement is
    best-effort: a family with no symbols (rare, but not impossible for an
    arbitrary library asset) still loads, it just is not placed."""
    app = doc.Application
    family_doc = app.OpenDocumentFile(family_path)

    family_doc.LoadFamily(doc, FamilyOption())

    family_name = family_doc.OwnerFamily.Name
    family = _find_loaded_family(doc, family_name)
    if family is None:
        NOTIFICATION.messenger(main_text="'{0}' loaded, but could not be found in the document to place an instance.".format(family_name))
        return

    symbol = _activate_default_symbol(doc, family)
    if symbol is None:
        NOTIFICATION.messenger(main_text="'{0}' loaded, but has no placeable type.".format(family_name))
        return

    uidoc.PromptForFamilyInstancePlacement(symbol)


class FamilyOption(DB.IFamilyLoadOptions):
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        #update_log( "#Normal Family Load option")
        #update_log( "is family in use?: {}".format(familyInUse))
        overwriteParameterValues = True# true means use project value
        #update_log( "is overwriteParameterValues?: {}".format(overwriteParameterValues))
        #update_log( "should load")
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        #update_log( "#Shared Family Load option")
        #update_log( "is family in use?: {}".format(familyInUse))
        overwriteParameterValues = True
        #update_log( "is overwriteParameterValues?: {}".format(overwriteParameterValues))


        source = DB.FamilySource.Family
        #source = DB.FamilySource.Family
        #update_log( "is shared component using family or project definition?: {}".format(str(source)))
        #update_log( "should load")
        return True

# Create a subclass of IExternalEventHandler
class SimpleEventHandler(IExternalEventHandler):
    """
    Simple IExternalEventHandler sample
    """

    # __init__ is used to make function from outside of the class to be executed by the handler. \
    # Instructions could be simply written under Execute method only
    def __init__(self, do_this):
        self.do_this = do_this
        self.kwargs = None
        self.OUT = None


    # Execute method run in Revit API environment.
    def Execute(self,  uiapp):
        try:
            try:
                #print "try to do event handler func"
                self.OUT = self.do_this(*self.kwargs)
            except:
                print ("failed")
                print (traceback.format_exc())
        except InvalidOperationException:
            # If you don't catch this exeption Revit may crash.
            print ("InvalidOperationException catched")

    def GetName(self):
        return "simple function executed by an IExternalEventHandler in a Form"



class LibraryAssetRow(object):
    """One row = one EnneadTab-Library catalog asset. Unlike the old
    shared-network-library metadata index (one row per family TYPE, indexed
    locally by meta_data_exporter.pushbutton), Library's REST API already
    returns one entry per asset with its own parameters/versions embedded --
    no local re-indexing needed.

    Holds only plain data from the JSON response (never a Revit API element --
    see this repo's CLAUDE.md "Modeless WPF DataGrid forms" checklist: WPF's
    selection machinery calls GetHashCode/ToString on a selected row OUTSIDE
    the API context, and a held element throws there, uncatchably)."""

    def __init__(self, asset_dict):
        self.data = asset_dict
        self.asset_id = asset_dict.get("id", "N/A")
        self.family_name = asset_dict.get("name", "N/A")           # DataGrid "Asset" column
        self.type_name = asset_dict.get("category", "N/A")         # DataGrid "Category" column
        self.format = asset_dict.get("format", "N/A")
        self.tags = asset_dict.get("tags", []) or []
        self.author = asset_dict.get("author", "N/A")
        self.current_version = asset_dict.get("currentVersion", "N/A")

        version_history = asset_dict.get("versionHistory", []) or []
        latest = version_history[0] if version_history else {}
        self.download_url = latest.get("downloadUrl")
        self.released_at = latest.get("releasedAt", "N/A")

        preview_url = asset_dict.get("previewUrl")
        resolved_preview = LIBRARY_CATALOG.resolve_media_url(preview_url)
        self.preview_images = [resolved_preview] if resolved_preview else []

    @property
    def searcher_name(self):
        return "_".join([self.family_name, self.type_name, self.format] + list(self.tags))




# A simple WPF form used to call the ExternalEvent
class family_browser_ModelessForm(WPFWindow):
    """
    Simple modeless form sample
    """

    def pre_actions(self):
        

        self.load_family_event_handler = SimpleEventHandler(load_family)
        self.ext_event_load_family = ExternalEvent.Create(self.load_family_event_handler)

        pass

    def __init__(self):
        self.pre_actions()

        xaml_file_name = "family_browser_ModelessForm.xaml" ###>>>>>> if change from window to dockpane, the top level <Window></Window> need to change to <Page></Page>
        WPFWindow.__init__(self, xaml_file_name)

        self.title_text.Text = "EnneadTab Family Browser"

        self.sub_text.Text = "Browse EnneadTab-Library with a search bar. Results are ranked by direct name match, then partial word match."


        self.Title = self.title_text.Text

        self.set_image_source(self.logo_img, os.path.join(ENVIRONMENT.IMAGE_FOLDER, "logo_vertical_light.png"))
        self.set_image_source(self.monitor_icon, "monitor_icon.png")
        self.set_image_source(self.preview_image, "DEFAULT PREVIEW_CANNOT FIND PREVIEW IMAGE.png")
        self.set_image_source(self.status_icon, "update_icon.png")

        self.data_pool = self._load_catalog()
        self.data_grid.ItemsSource = self.data_pool[:]

        self.Show()

    def _load_catalog(self):
        """Fetch the catalog from EnneadTab-Library. Degrades to an empty pool
        (same shape as ASSET.py's offline degradation -- a dead network never
        raises out of this button) when Library is unreachable."""
        token = AUTH.get_token()
        assets, _categories = LIBRARY_CATALOG.list_assets(token=token)
        if assets is None:
            if not token:
                # Lazy sign-in, same pattern as AI Render: open the browser
                # now, non-blocking, and tell the user to retry once done.
                AUTH.request_auth()
                NOTIFICATION.messenger(main_text="Sign in to EnneadTab in the browser window that just opened, then reopen this dialog.")
            else:
                NOTIFICATION.messenger(main_text="EnneadTab-Library is unreachable right now. Check your connection or try again later.")
            return []
        return [LibraryAssetRow(x) for x in assets]

    @ERROR_HANDLE.try_catch_error()
    def preview_selection_changed(self, sender, e):
        if len(self.data_grid.ItemsSource) == 0:
            return

        obj = self.data_grid.SelectedItem
        
        if not obj:
            
            return

        try:
            #preview_image = "{}\{}.jpg".format(self.output_folder, obj.view.UniqueId)
            preview_images = self.get_true_preview_images(obj)
            
            # create many WPF image objects, the same count as the count of preview_images
            
            self.img_viewer_panel.Children.Clear()
            
            for preview_image in preview_images:

                image = System.Windows.Controls.Image()
                bitmap = System.Windows.Media.Imaging.BitmapImage()
                bitmap.BeginInit()
                bitmap.UriSource = System.Uri(preview_image)  # already an absolute Library URL, see LIBRARY_CATALOG.resolve_media_url
                bitmap.EndInit()

                # Set max width for image
                
                image.MaxWidth  = 600
                image.Source = bitmap
                image.Stretch = System.Windows.Media.Stretch.Uniform
                image.Margin = System.Windows.Thickness(10)

                self.img_viewer_panel.Children.Add(image)
      
                #self.set_image_source(self.preview_image, preview_image)
                
                # hide self.preview_image, set visibility as collapese
                self.preview_image.Visibility = System.Windows.Visibility.Collapsed
                

            note = "Asset = {0}\nCategory = {1}\nAuthor = {2}\nVersion {3} (released {4})".format(obj.family_name, obj.type_name, obj.author, obj.current_version, obj.released_at)
            self.textblock_export_status.Text = note
        except:
            #self.update_preview_grid()
            print (traceback.format_exc())
            self.preview_image.Visibility = System.Windows.Visibility.Visible
            self.set_image_source(self.preview_image, "DEFAULT PREVIEW_CANNOT FIND PREVIEW IMAGE.png")
            self.textblock_export_status.Text = ""

    @ERROR_HANDLE.try_catch_error()
    def UI_changed(self, sender, e):
        self.update_preview_grid()

    @ERROR_HANDLE.try_catch_error()
    def refresh_table_Click(self, sender, e):
        self.update_preview_grid()
        self.debug_textbox.Text = "Currently showing {} views.".format(len(self.data_grid.ItemsSource))

    @ERROR_HANDLE.try_catch_error()
    def update_preview_grid(self):
        if not hasattr(self, "_search_results"):
            self._search_results = []
        if len(self._search_results) != 0:
            self.data_grid.ItemsSource = self._search_results
        else:
            self.data_grid.ItemsSource = self.data_pool
        

    @ERROR_HANDLE.try_catch_error()
    def open_view_click(self, sender, e):
        obj = self.data_grid.SelectedItem
        if not obj:
            return
        if not obj.view:
            self.update_preview_grid()
            return
        uidoc.ActiveView = obj.view
        pass

  

    def get_true_preview_images(self, preview_obj):
        # Already-resolved absolute Library URLs (LIBRARY_CATALOG.resolve_media_url) -- no local folder join needed.
        return preview_obj.preview_images

   
    
    def set_search_results(self, *collections):
        """Set search results for returning."""
        self._result_index = 0
        self._search_results = []


        for resultset in collections:
            self._search_results.extend(sorted(resultset))

        temp = []
        for x in self._search_results:
            if x not in temp:
                temp.append(x)
        self._search_results = temp
        

    
    def find_direct_match(self, input_text):
        """Find direct text matches in search term."""
        results = []
        if input_text:
            for preview_obj in self.data_pool:
                if preview_obj.searcher_name.lower().startswith(input_text):
                    results.append(preview_obj)

        return results

    
    def find_word_match(self, input_text):
        """Find direct word matches in search term."""
        results = []
        if input_text:
            cur_words = input_text.split(' ')
            for preview_obj in self.data_pool:
                if all([x in preview_obj.searcher_name.lower() for x in cur_words]):
                    results.append(preview_obj)

        return results

    
    def NOT_IN_USE_find_in_doc_match(self, input_text):
        """Find direct word matches in search term."""
        def has_keyword_in_doc(command_name, keywords):
            doc_string = self.search_datas[command_name][0]

            if not doc_string:
                return False

            for keyword in keywords:

                if keyword.lower() in doc_string.lower():
                    #print keyword
                    #print doc_string
                    return True
            return False

        results = []
        if input_text:
            cur_words = input_text.split(' ')
            for command_name in self._search_data_keys:
                if has_keyword_in_doc(command_name, cur_words):
                    results.append(command_name)

        return results


    def clear_search_click(self, sender, e):
        self.search_textbox.Text = ""

    @ERROR_HANDLE.try_catch_error()
    def search_box_value_changed(self, sender, args):
        """Handle text changed event."""



        #import System
        if len(self.search_textbox.Text) == 0:
            self._search_results = []
        else:
            


            direct_match_results = self.find_direct_match(self.search_textbox.Text)
            word_results = self.find_word_match(self.search_textbox.Text)
            self.set_search_results(direct_match_results, word_results)
            #in_doc_results = self.find_in_doc_match(self.search_textbox.Text)
            #self.set_search_results(direct_match_results, word_results, in_doc_results)

            #print self._search_results


        self.update_preview_grid()


    @ERROR_HANDLE.try_catch_error()
    def load_family_click(self, sender, e):
        if len(self.data_grid.ItemsSource) == 0:
            return

        obj = self.data_grid.SelectedItem

        if not obj:
            return

        if not obj.download_url:
            NOTIFICATION.messenger(main_text="'{0}' has no downloadable file published yet.".format(obj.family_name))
            return

        family_path = LIBRARY_CATALOG.download_asset(obj.download_url, token=AUTH.get_token())
        if not family_path:
            NOTIFICATION.messenger(main_text="Could not download '{0}' from EnneadTab-Library right now. Check your connection or try again later.".format(obj.family_name))
            return

        self.load_family_event_handler.kwargs = family_path,
        self.ext_event_load_family.Raise()

    def close_Click(self, sender, e):
        # This Raise() method launch a signal to Revit to tell him you want to do something in the API context
        self.Close()

    def mouse_down_main_panel(self, sender, args):
        #print "mouse down"
        sender.DragMove()




################## main code below #####################
output = script.get_output()
output.close_others()


if __name__ == "__main__":
    
    family_browser_ModelessForm()
       

