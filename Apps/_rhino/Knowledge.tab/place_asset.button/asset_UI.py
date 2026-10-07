import Rhino # pyright: ignore
import Eto # pyright: ignore



import textwrap



from EnneadTab import NOTIFICATION, SOUND
from EnneadTab.RHINO import RHINO_UI
from EnneadTab.DEPOT import ASSET, LIBRARY_CATALOG

# senzhang-todo #5511/#5773: this dialog used to browse a LOCAL folder
# (ASSET.get_asset_folder('rhino/asset-library')), with per-asset .meta
# sidecar files for tags/download-count, plus a "Manager Mode" UI that wrote
# those sidecars. Upload/tag now happens on EnneadTab-Library's own website
# (crowdsourced -- any office user, not one curator), so this dialog is a
# pure READ consumer of Library's REST catalog: no local writes, no Manager
# Mode, tags/download-count come straight from Library's JSON. The button's
# own UI chrome (logo, icons, default preview placeholders) still lives in
# the local Depot asset folder below -- that part is unrelated to the
# catalog cutover and is unchanged.


class LibraryAssetRow(object):
    """One row = one EnneadTab-Library catalog asset, read-only. Mirrors
    library_family_browser.pushbutton's LibraryAssetRow (senzhang-todo #5449)
    -- holds only plain JSON data, never a Rhino API object, since this is
    what a WPF/Eto grid selects and Eto's selection machinery can call
    ToString/property-enumeration on a row outside any API context."""

    def __init__(self, asset_dict):
        self.data = asset_dict
        self.asset_id = asset_dict.get("id", "N/A")
        self.name = asset_dict.get("name") or "N/A"
        self.category = asset_dict.get("category", "N/A")
        self.tags = [t.lower() for t in (asset_dict.get("tags") or [])]
        self.download_count = asset_dict.get("downloadCount", 0)

        version_history = asset_dict.get("versionHistory") or []
        latest = version_history[0] if version_history else {}
        self.download_url = latest.get("downloadUrl")

        self.preview_url = LIBRARY_CATALOG.resolve_media_url(asset_dict.get("previewUrl"))

        self.block_name = _block_name_for_asset(self.download_url, self.name)

    def matches_text(self, text):
        haystack = "_".join([self.name, self.category] + self.tags).lower()
        return text.lower() in haystack


def _block_name_for_asset(download_url, fallback_name):
    """The name used both as the Rhino InstanceDefinition name and as the
    dedup key against blocks already in the doc (rs.IsBlock) -- keep it
    stable and derived from the actual file, matching the old convention of
    using the real filename (e.g. "Chair01.3dm"), not an opaque asset id."""
    if download_url:
        candidate = download_url.rstrip("/").split("/")[-1]
        if candidate:
            return candidate
    return "{0}.3dm".format(fallback_name)


# make modal dialog
class ImageSelectionDialog(Eto.Forms.Dialog[bool]):
    """
    Eto.Forms.ImageViewCell good,
    Eto.Forms.ImageTextCell bad

    Eto.Forms.DrawableCell ---
    """
    # Initializer
    def __init__(self, options):
        # Eto initials
        self.Title = "V11"
        self.Resizable = True
        self.Padding = Eto.Drawing.Padding(5)
        self.Spacing = Eto.Drawing.Size(5, 5)

        #self.Bounds = Eto.Drawing.Rectangle()
        self.listbox_height = 600
        self.left_layout_width = 400
        self.multi_select = False

        self.Button_Names = ["Place Asset!"]
        # Still a local Depot asset folder -- this is the button's OWN UI
        # chrome (logo/icons/placeholders), unrelated to the Library catalog
        # cutover. There is no REST equivalent for "give me this button's
        # icons", so this stays exactly as it was.
        self.FOLDER_PRIMARY = ASSET.get_asset_folder('rhino/asset-library') or ""
        self.FOLDER_APP_IMAGES = "{}\Database\\app images".format(self.FOLDER_PRIMARY)
        self.DEFAULT_IMAGE_NOTHING_SELECTED = "{}\\DEFAULT PREVIEW_NOTHING SELECTED.png".format(self.FOLDER_APP_IMAGES)
        self.DEFAULT_IMAGE_CANNOT_FIND_PREVIEW_IMAGE = "{}\\DEFAULT PREVIEW_CANNOT FIND PREVIEW IMAGE.png".format(self.FOLDER_APP_IMAGES)
        self.LOGO_IMAGE = "{}\\Ennead_Architects_Logo.png".format(self.FOLDER_APP_IMAGES)
        self.SOUND_MUTE = False
        self.IMAGE_MAX_SIZE = 800

        # fields -- options is a list of LibraryAssetRow, one per Library
        # catalog asset (see ShowImageSelectionDialog below).
        self.ScriptList = options
        self.SearchedScriptList = self.ScriptList[::]
        self.ROWS_BY_NAME = dict((row.name, row) for row in self.ScriptList)
        # tags are whatever Library's own curators/uploaders set per asset --
        # no more hardcoded TAG_DEFAULT_LIST; the filter list is exactly the
        # union of tags actually present in this fetch.
        self.TAG_DEFAULT_LIST = sorted(set(tag for row in self.ScriptList for tag in row.tags))


        # initialize layout
        layout = Eto.Forms.DynamicLayout()
        layout.Padding = Eto.Drawing.Padding(5)
        layout.Spacing = Eto.Drawing.Size(5, 5)


        left_layout = Eto.Forms.DynamicLayout()
        left_layout.Padding = Eto.Drawing.Padding(5)
        left_layout.Spacing = Eto.Drawing.Size(5, 5)

        # add message
        left_layout.BeginVertical()
        left_layout.AddRow(self.CreateMessageBar())
        left_layout.EndVertical()

        # add search
        left_layout.BeginVertical()
        left_layout.AddRow(*self.CreateSearchBar())
        left_layout.EndVertical()

        # add listBox
        left_layout.BeginVertical()
        left_layout.AddRow(self.CreateScriptListBox(), None, self.CreateVerticalTagCheckBoxGroupBox())
        left_layout.EndVertical()


        # add tag box
        left_layout.BeginVertical()
        left_layout.AddSeparateRow(self.CreateOccupancyGroup())
        left_layout.EndVertical()


        # add option box
        left_layout.BeginVertical()
        left_layout.AddSeparateRow(self.CreateInsertMethodGroupBox())
        left_layout.EndVertical()

        left_layout.AddSpace()#this will make strectchable empty space, make sure it IS BETWEEN LAYOUT BUNDLES

        # add buttons
        left_layout.BeginVertical()
        left_layout.AddRow(*self.CreateButtons())
        left_layout.EndVertical()

        # add previews
        preview_image_layout = Eto.Forms.DynamicLayout()
        preview_image_layout.Padding = Eto.Drawing.Padding(5)
        preview_image_layout.Spacing = Eto.Drawing.Size(5, 5)
        #preview_image_layout.BeginHorizontal()
        preview_image_layout.AddSeparateRow(None, self.CreateLogoImage())
        preview_image_layout.AddRow(None)
        preview_image_layout.AddSeparateRow(None, self.CreateCredit())
        preview_image_layout.AddSeparateRow(self.CreatePreviewImage())

        #preview_image_layout.EndHorizontal()



        layout.AddRow(left_layout,preview_image_layout)

        # set content
        self.Content = layout

        RHINO_UI.apply_dark_style(self)

    """
    ##  create content ############################################################################################################################

    """



    # create message bar function
    def CreateMessageBar(self):
        self.msg = Eto.Forms.Label()
        self.msg.Text = "EnneadTab's Asset Search Tool. Browses EnneadTab-Library -- to add or tag an asset, use Library's website (crowdsourced: any office user can upload)."
        self.msg.Font = Eto.Drawing.Font("Arial", 5)#, TextColor = Eto.Drawing.Color(0,0,240))
        return self.msg
        #self.msg.HorizontalAlignment = Eto.Forms.HorizontalAlignment.Left


    # create search bar function
    def CreateSearchBar(self):
        """
        Creates two controls for the search bar
        self.lbl_Search as a simple label
        self.tB_Search as a textBox to input search strings to
        """


        self.lbl_Search = Eto.Forms.Label()
        self.lbl_Search.Text = "Search: "
        self.lbl_Search.VerticalAlignment = Eto.Forms.VerticalAlignment.Center
        self.lbl_Search.Font = Eto.Drawing.Font("Arial", 10, Eto.Drawing.FontStyle.Italic, Eto.Drawing.FontDecoration.Underline)

        self.tB_Search = Eto.Forms.TextBox()
        self.tB_Search.Width = 300
        self.tB_Search.TextChanged += self.EVENT_SearchBarTextbox_TextChanged

        self.button_clear_text = Eto.Forms.Button()
        self.button_clear_text.Text = "Clear Search Bar"
        self.button_clear_text.Height = 5
        self.button_clear_text.Image = Eto.Drawing.Bitmap(r"{}\clear_text.png".format(self.FOLDER_APP_IMAGES))
        self.button_clear_text.ImagePosition = Eto.Forms.ButtonImagePosition.Left
        self.button_clear_text.Click += self.EVENT_ClearSearchBarButton_Clicked
        return [self.lbl_Search, self.tB_Search,   self.button_clear_text]


    def CreateScriptListBox(self):
        # Create a multi selection box with grid view - this is similar to Rhino MultipleListBox
        self.lb = Eto.Forms.GridView()
        self.lb.ShowHeader = True
        self.lb.AllowMultipleSelection = self.multi_select
        self.lb.Height = self.listbox_height
        self.lb.Width = self.left_layout_width
        self.lb.AllowColumnReordering = True


        self.update_ListBox_DataStore(source_list = self.SearchedScriptList)


        self.lb.SelectedRowsChanged += self.EVENT_Listbox_SelectedRowChanged


        # Create Gridview Column
        column1 = Eto.Forms.GridColumn()
        column1.Editable = False
        column1.HeaderText = "Asset File"
        column1.Width = self.left_layout_width - 100

        column1.DataCell = Eto.Forms.TextBoxCell(0)
        self.lb.Columns.Add(column1)


        column2 = Eto.Forms.GridColumn()
        column2.Editable = False
        column2.HeaderText = "Downloads"
        column2.Width = 100
        column2.DataCell = Eto.Forms.TextBoxCell(1)
        column2.Sortable = True
        self.lb.Columns.Add(column2)


        return self.lb


    def CreateVerticalTagCheckBoxGroupBox(self):
        self.tag_option_groupbox_vertical = Eto.Forms.GroupBox()
        self.tag_option_groupbox_vertical.Text = "Tags:"
        self.tag_option_groupbox_vertical.Padding = Eto.Drawing.Padding (10)

        group_layout = Eto.Forms.DynamicLayout()
        group_layout.Spacing = Eto.Drawing.Size(6,6)
        group_layout.Width = 100


        self.checkbox_list_tag_filter = Eto.Forms.CheckBoxList()
        self.checkbox_list_tag_filter.DataStore = self.TAG_DEFAULT_LIST
        self.checkbox_list_tag_filter.Orientation = Eto.Forms.Orientation.Vertical
        self.checkbox_list_tag_filter.SelectedValues  = []
        self.checkbox_list_tag_filter.Spacing = Eto.Drawing.Size(5,5)
        self.checkbox_list_tag_filter.Padding = Eto.Drawing.Padding(10,5, 5, 5)
        self.checkbox_list_tag_filter.SelectedValuesChanged += self.EVENT_TagFilterCheckboxList_CheckedValueChanged
        self.IS_TAG_LIST_CHANGING = False



        self.tag_vertical_clear_button = Eto.Forms.Button()
        self.tag_vertical_clear_button.Height = 20
        self.tag_vertical_clear_button.Width = 100
        self.tag_vertical_clear_button.Text = "Clear Filter"
        self.tag_vertical_clear_button.Click += self.EVENT_ClearTagFilterButton_Clicked



        #group_layout.AddRow(self.tag_filter_chairs,self.tag_filter_desks,self.tag_filter_socials )
        group_layout.AddColumn(self.checkbox_list_tag_filter, None, self.tag_vertical_clear_button )



        self.tag_option_groupbox_vertical.Content = group_layout

        return self.tag_option_groupbox_vertical


    def CreateOccupancyGroup(self):
        self.tag_option_groupbox = Eto.Forms.GroupBox()
        self.tag_option_groupbox.Text = "How many poeple can this asset accomendate?(Future function)"
        self.tag_option_groupbox.Padding = Eto.Drawing.Padding (5)
        group_layout = Eto.Forms.DynamicLayout()
        group_layout.Spacing = Eto.Drawing.Size(6,6)


        self.radiobutton_list_occupancy_filter = Eto.Forms.RadioButtonList()
        self.OCCUPANCY_DEFAULT_LIST = ["Any", "0", "1", "2", "3 ", "4", "5+"]
        self.radiobutton_list_occupancy_filter.DataStore = self.OCCUPANCY_DEFAULT_LIST
        self.radiobutton_list_occupancy_filter.Orientation = Eto.Forms.Orientation.Horizontal
        self.radiobutton_list_occupancy_filter.SelectedValue = self.OCCUPANCY_DEFAULT_LIST[0]
        self.radiobutton_list_occupancy_filter.Spacing = Eto.Drawing.Size(5,5)
        self.radiobutton_list_occupancy_filter.Padding = Eto.Drawing.Padding(3,3, 3, 3)
        self.radiobutton_list_occupancy_filter.SelectedValueChanged += self.EVENT_OccupancyFilterRadioButtonList_CheckedValueChanged


        #group_layout.AddRow(self.tag_filter_chairs,self.tag_filter_desks,self.tag_filter_socials )

        group_layout.AddRow(self.radiobutton_list_occupancy_filter )

        self.tag_option_groupbox.Content = group_layout

        return self.tag_option_groupbox


    def CreateInsertMethodGroupBox(self):
        self.block_insert_method_groupbox = Eto.Forms.GroupBox()
        self.block_insert_method_groupbox.Text = "How to insert block?"
        self.block_insert_method_groupbox.Padding = Eto.Drawing.Padding (5)
        group_layout = Eto.Forms.DynamicLayout()
        group_layout.Spacing = Eto.Drawing.Size(6,6)

        self.radio_button_list_ref_block_method = Eto.Forms.RadioButtonList()
        self.radio_button_list_ref_block_method.DataStore = ["As Ref Link", "Embed In Current File"]
        self.radio_button_list_ref_block_method.Orientation = Eto.Forms.Orientation.Vertical
        self.radio_button_list_ref_block_method.SelectedIndex = 1
        self.radio_button_list_ref_block_method.Spacing = Eto.Drawing.Size(5,5)
        self.radio_button_list_ref_block_method.Padding = Eto.Drawing.Padding(3,3, 3,3)



        group_layout.AddRow(self.radio_button_list_ref_block_method )

        lines = ["Notes:", "-Using ref link will keep file light and layer clear, but you don't have ability to modify geomtry, material or use MakeBlockUnique.", "-Using embed block will make it a local block and lose connection to the shared network folder."]
        for line in lines:
            self.ref_block_method_label = Eto.Forms.Label()
            self.ref_block_method_label.Text = textwrap.fill(line, 100)
            group_layout.AddRow(self.ref_block_method_label )
        self.block_insert_method_groupbox.Content = group_layout

        return self.block_insert_method_groupbox
        #self.msg.HorizontalAlignment = Eto.Forms.HorizontalAlignment.Left


    def CreateButtons(self):
        """
        Creates buttons for either print the selection result
        or exiting the dialog
        """
        user_buttons = []
        max_height = 50
        for b_name in self.Button_Names:
            self.btn_Run = Eto.Forms.Button()
            self.btn_Run.Height = max_height
            self.btn_Run.Text = b_name
            self.btn_Run.Image = Eto.Drawing.Bitmap(r"{}\download.png".format(self.FOLDER_APP_IMAGES))
            self.btn_Run.ImagePosition = Eto.Forms.ButtonImagePosition.Right
            self.btn_Run.Click += self.EVENT_PlaceAssetButton_Clicked
            user_buttons.append(self.btn_Run)

        self.btn_Cancel = Eto.Forms.Button()
        self.btn_Cancel.Text = "Close"
        self.btn_Cancel.Click += self.EVENT_CloseButton_Clicked
        self.btn_Cancel.Height = max_height

        user_buttons.extend([ None, self.btn_Cancel])


        return user_buttons


    # create logo image bar function
    def CreateLogoImage(self):
        self.logo = Eto.Forms.ImageView()
        temp_bitmap = Eto.Drawing.Bitmap(self.LOGO_IMAGE)
        self.logo.Image = temp_bitmap.WithSize(200,50)
        return self.logo


    def CreateCredit(self):
        self.credit = Eto.Forms.Label()
        self.credit.Text = "Created by Sen Zhang. V11"
        self.credit.Font = Eto.Drawing.Font("Arial", 7, Eto.Drawing.FontStyle.Italic, Eto.Drawing.FontDecoration.Underline)
        return self.credit


    # create preview image bar function
    def CreatePreviewImage(self):
        self.preview_image = Eto.Forms.ImageView()
        temp_bitmap = Eto.Drawing.Bitmap(self.DEFAULT_IMAGE_NOTHING_SELECTED)
        self.preview_image.Image = temp_bitmap.WithSize(self.IMAGE_MAX_SIZE,self.IMAGE_MAX_SIZE)
        return self.preview_image


    # create a search function
    def Search(self):#################

        """
        Searches self.ScriptList with a given string.
        Tag filter is include-all (an asset must carry every checked tag, or
        have the tag as a substring of its name, same as before); text search
        is now a plain case-insensitive substring match against name/category/
        tags (get_item_tags never applied case-folding for tags either, so
        this is at least as permissive as the old fnmatch("*text*") glob).
        """
        text = self.tB_Search.Text
        include_list = list(self.checkbox_list_tag_filter.SelectedValues)

        def include_real_tag(row):
            if not include_list:
                return True
            for tag in include_list:
                if tag.lower() not in row.tags and tag.lower() not in row.name.lower():
                    return False
            return True

        reduced_pool = list(filter(include_real_tag, self.ScriptList))

        if text == "":
            self.SearchedScriptList = reduced_pool
        else:
            self.SearchedScriptList = [row for row in reduced_pool if row.matches_text(text)]

        self.update_ListBox_DataStore(source_list = self.SearchedScriptList)
        self.update_available_tags_in_tag_filter()


    def update_available_tags_in_tag_filter(self):
        """
        dynamically find out what other tags can stay and update:
        ex. if a tag is shown in any item in current list, it should stay, else gone.

        record the value that is currently check, make a new tag list, set select as record.
        """
        checked_tags = list(self.checkbox_list_tag_filter.SelectedValues)
        possible_tags_pool = set()
        for row in self.SearchedScriptList:
            for tag in self.TAG_DEFAULT_LIST:
                if tag in checked_tags or tag.lower() in row.name.lower() or tag.lower() in row.tags:
                    possible_tags_pool.add(tag)

        possible_tags = [tag for tag in self.TAG_DEFAULT_LIST if tag in possible_tags_pool]

        self.IS_TAG_LIST_CHANGING = True
        self.checkbox_list_tag_filter.DataStore = possible_tags
        self.checkbox_list_tag_filter.SelectedValues = checked_tags
        self.IS_TAG_LIST_CHANGING = False


    def update_preview_image(self):
        if self.is_nothing_selected():
            image_path = self.DEFAULT_IMAGE_NOTHING_SELECTED
        else:
            row = self.get_selected_asset_row()
            image_path = None
            if row is not None and row.preview_url:
                # Lazily downloaded on selection -- Library's REST API has no
                # local-file preview to read anymore, so this is a real
                # network round trip per row click (see PR notes: a known,
                # accepted latency tradeoff, not solved in this pass).
                image_path = LIBRARY_CATALOG.download_asset(row.preview_url)
            if not image_path:
                image_path = self.DEFAULT_IMAGE_CANNOT_FIND_PREVIEW_IMAGE

        try:
            temp_bitmap = Eto.Drawing.Bitmap(image_path)
        except Exception as e:
            print(str(e))
            temp_bitmap = Eto.Drawing.Bitmap(self.DEFAULT_IMAGE_CANNOT_FIND_PREVIEW_IMAGE)

        self.preview_image.Image = temp_bitmap.WithSize(self.IMAGE_MAX_SIZE,self.IMAGE_MAX_SIZE)
        self.Title  = image_path
        #print self.preview_image


    def get_listbox_selected_items(self):
        # return selected items
        return list(self.lb.SelectedItems)


    def get_listbox_selected_items_column0(self):
        """do not check for nothing slected, otherwise it will cause self refer loop"""
        if self.get_listbox_selected_items() == []:
            return
        return list(self.lb.SelectedItems)[0][0]


    def get_listbox_selected_items_column1(self):
         #activate after adding second column
        if self.get_listbox_selected_items() == []:
            return
        return list(self.lb.SelectedItems)[0][1]


    def get_selected_asset_row(self):
        name = self.get_listbox_selected_items_column0()
        if name is None:
            return None
        return self.ROWS_BY_NAME.get(name)


    def is_nothing_selected(self):
        if self.lb.SelectedItems is None:
            return True
        if self.get_listbox_selected_items() == []:
            return True
        if self.get_listbox_selected_items_column0() is None:
            return True
        return False


    def update_ListBox_DataStore(self, source_list):
        self.lb.DataStore = [[row.name, row.download_count] for row in sorted(source_list, key = lambda r: r.name)]

    def set_new_listitem(self, increment = 1):
        current_rhino = self.get_listbox_selected_items_column0()
        #print "EEEEEEEEEE"
        #print self.lb.DataStore[0:10]
        for i, entry in enumerate(self.lb.DataStore):
            if entry[0] == current_rhino:
                break
        #print i
        try:
            next_item = self.lb.DataStore[i + increment]
            print(next_item)
            self.lb.SelectedRow = i + increment
        except IndexError:
            NOTIFICATION.messenger(main_text = "End of list.")
            self.lb.SelectedRow = 0
    """
    ####  event call ##############################################################################################################################
    ###############################################################################################################################################
    ###############################################################################################################################################
    ###############################################################################################################################################
    ###############################################################################################################################################
    ###############################################################################################################################################
    ###############################################################################################################################################
    """
    # Gridview SelectedRows Changed Event
    def EVENT_Listbox_SelectedRowChanged (self,sender,e):

        self.update_preview_image()
        self.sound_selected_item_changed()
        return self.lb.SelectedRows


    # event handler handling text input in ther search bar
    def EVENT_SearchBarTextbox_TextChanged(self, sender, e):
        self.Search()


    def EVENT_ClearSearchBarButton_Clicked(self, sender, e):
        self.tB_Search.Text = ""


    # event handler handling clicking on the 'clear tag filter' button
    def EVENT_ClearTagFilterButton_Clicked(self, sender, e):
        # set checkbox list to None
        self.checkbox_list_tag_filter.SelectedValues  = []

        # call search() to update list
        self.Search()
        pass


    # event handler handling clicking on the tag any checkbox item
    def EVENT_TagFilterCheckboxList_CheckedValueChanged(self, sender, e):

        # call search() to update list
        if self.IS_TAG_LIST_CHANGING:
            return
        self.Search()
        pass


    # event handler handling clicking on the occupancy radio change item
    def EVENT_OccupancyFilterRadioButtonList_CheckedValueChanged(self, sender, e):

        # call search() to update list
        self.Search()
        pass

    def EVENT_NextListboxItemButton_Clicked(self, sender, e):
        self.set_new_listitem(increment = 1)
        self.sound_page_next()

    def EVENT_PrevListboxItemButton_Clicked(self, sender, e):
        self.set_new_listitem(increment = -1)
        self.sound_page_prev()


    # event handler handling clicking on the 'run' button
    def EVENT_PlaceAssetButton_Clicked(self, sender, e):
        # close window after double click action. Otherwise, run with error
        self.Close(True)
        self.get_listbox_selected_items()


    # event handler handling clicking on the 'cancel' button
    def EVENT_CloseButton_Clicked(self, sender, e):
        self.Close(False)

############################################ Sound ######################

    def sound_page_prev(self):
        if self.SOUND_MUTE:
            return
        file = "sound_effect_menu_page_trun_backward.wav"
        SOUND.play_sound(file)

    def sound_page_next(self):
        if self.SOUND_MUTE:
            return
        file = "sound_effect_menu_page_trun_forward.wav"
        SOUND.play_sound(file)

    def sound_selected_item_changed(self):
        if self.SOUND_MUTE:
            return
        file = "sound_effect_menu_flip.wav"
        SOUND.play_sound(file)
"""
####  outside dialog ################################################################################################################################
#####################################################################################################################################################
#####################################################################################################################################################
#####################################################################################################################################################
#####################################################################################################################################################
#####################################################################################################################################################
#####################################################################################################################################################
#####################################################################################################################################################
"""
def ShowImageSelectionDialog(assets):
    """assets: raw list of EnneadTab-Library catalog asset dicts, straight off
    LIBRARY_CATALOG.list_assets(). Returns ([selected LibraryAssetRow, ...],
    is_ref_block_method) on Place, or (None, None) if the dialog was closed
    without placing."""

    rows = [LibraryAssetRow(asset) for asset in assets]

    dlg = ImageSelectionDialog(rows)
    rc = Rhino.UI.EtoExtensions.ShowSemiModal(dlg, Rhino.RhinoDoc.ActiveDoc, Rhino.UI.RhinoEtoApp.MainWindow)

    if (rc):

        selected_names = [x[0] for x in dlg.get_listbox_selected_items()]
        selected_rows = [dlg.ROWS_BY_NAME[name] for name in selected_names if name in dlg.ROWS_BY_NAME]

        is_ref_block_method = False if "Embed" in dlg.radio_button_list_ref_block_method.SelectedValue else True
        return selected_rows, is_ref_block_method

    else:
        print("Dialog did not run")
        return None, None
