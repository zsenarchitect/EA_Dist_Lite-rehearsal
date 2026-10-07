__title__ = "PlaceAsset"
__doc__ = "Place Asset from asset library"

import os
import sys
import Rhino # pyright: ignore
import rhinoscriptsyntax as rs

from EnneadTab import AUTH, LOG, ERROR_HANDLE, NOTIFICATION
from EnneadTab.DEPOT import ASSET, LIBRARY_CATALOG
import asset_UI as ui

# senzhang-todo #5773 decided uploads/tagging happen on Library's own website
# only -- Rhino stays a pure read consumer of GET /api/v1/assets, same
# contract #5449's Revit family browser already depends on. "rhino_block" is
# Library's own AssetFormat value (EnneadTab-Library/lib/types.ts) -- not the
# literal file extension.
RHINO_BLOCK_ASSET_FORMAT = "rhino_block"


def insert_ref_block(asset_row, is_ref_block_method):
    block_name = asset_row.block_name
    if rs.IsBlock(block_name):
        rs.InsertBlock(block_name, (0,0,0))
        return

    external_block_filepath = _download_asset_file(asset_row)
    if not external_block_filepath:
        return

    dummyInitialObjects = [Rhino.Geometry.Point(Rhino.Geometry.Plane.WorldXY.Origin)]
    dummyInitialAttributes = [Rhino.DocObjects.ObjectAttributes()]
    indexOfAddedBlock = Rhino.RhinoDoc.ActiveDoc.InstanceDefinitions.Add(block_name,
                                                                        "",
                                                                        Rhino.Geometry.Plane.WorldXY.Origin,
                                                                        dummyInitialObjects ,
                                                                        dummyInitialAttributes)


    if is_ref_block_method:
        block_method = Rhino.DocObjects.InstanceDefinitionUpdateType.Linked

    else:
        block_method = Rhino.DocObjects.InstanceDefinitionUpdateType.LinkedAndEmbedded
        #block_method = Rhino.DocObjects.InstanceDefinitionUpdateType.Static
        #block_method = Rhino.DocObjects.InstanceDefinitionUpdateType.Embedded

    modified = Rhino.RhinoDoc.ActiveDoc.InstanceDefinitions.ModifySourceArchive(indexOfAddedBlock,
                                                                                Rhino.FileIO.FileReference.CreateFromFullPath(external_block_filepath),
                                                                                block_method,
                                                                                True)# bool for quite mode, no error msg shown
    obj = Rhino.RhinoDoc.ActiveDoc.Objects.AddInstanceObject(indexOfAddedBlock,Rhino.Geometry.Transform.Identity)

    if not is_ref_block_method:
        # NOTE: this is the block-packaging TOOL SCRIPT (a Depot asset key
        # unrelated to the EnneadTab-Library catalog cutover above) -- keep
        # resolving it through ASSET, not LIBRARY_CATALOG.
        blocks_folder = ASSET.get_asset_folder('rhino/scripts/blocks')
        if not blocks_folder:
            return
        sys.path.append(blocks_folder)
        import block_layer_packaging
        block_layer_packaging.pack_block_layers(blocks = [obj], flatten_layer = True)



        import imp
        MAKE_BLOCK_UNIQUE = imp.load_source('make block unique',
                                            os.path.join(blocks_folder, "make block unique.py"))

        MAKE_BLOCK_UNIQUE.make_block_unique(add_name_tag = False, original_blocks = [obj], treat_nesting = True)
        rs.DeleteBlock(block_name)
        rs.RenameBlock( "{}_new".format(block_name), block_name )


def _download_asset_file(asset_row):
    if not asset_row.download_url:
        NOTIFICATION.messenger(main_text = "'{0}' has no downloadable file published yet.".format(asset_row.name))
        return None

    local_path = LIBRARY_CATALOG.download_asset(asset_row.download_url, token = AUTH.get_token())
    if not local_path:
        NOTIFICATION.messenger(main_text = "Could not download '{0}' from EnneadTab-Library right now. Check your connection or try again later.".format(asset_row.name))
        return None
    return local_path



@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def place_asset():
    token = AUTH.get_token()
    assets, _categories = LIBRARY_CATALOG.list_assets(asset_format = RHINO_BLOCK_ASSET_FORMAT, token = token)
    if assets is None:
        if not token:
            # Lazy sign-in, same pattern as AI Render: open the browser now,
            # non-blocking, and tell the user to retry once it completes.
            AUTH.request_auth()
            NOTIFICATION.messenger(main_text = "Sign in to EnneadTab in the browser window that just opened, then click this button again.")
        else:
            NOTIFICATION.messenger(main_text = "EnneadTab-Library is unreachable right now. Check your connection or try again later.")
        return
    if not assets:
        NOTIFICATION.messenger(main_text = "No Rhino block assets are published on EnneadTab-Library yet.")
        return

    selected_rows, is_ref_block_method = ui.ShowImageSelectionDialog(assets)

    if not selected_rows or is_ref_block_method is None:
        return
    insert_ref_block(selected_rows[0], is_ref_block_method)



if __name__ == "__main__":
    place_asset()
