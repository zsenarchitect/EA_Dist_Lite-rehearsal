__title__ = "ExtractPreviewImages"
__doc__ = """Extract preview images from Rhino files.

Key Features:
- Batch image extraction
- Multiple file support
- Automatic naming convention
- Progress tracking"""

import rhinoscriptsyntax as rs
import scriptcontext as sc
import os.path as op
import os
import System # pyright: ignore

from EnneadTab import LOG, ERROR_HANDLE
from EnneadTab.DEPOT import ASSET


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def extract_preview_images():
    main_folder = ASSET.get_asset_folder('rhino/asset-library')
    if not main_folder:
        return
    file_paths = ["{}\{}".format(main_folder, x) for x in os.listdir(main_folder) if ".3dm" in x[-4:].lower()]

    # NOTE: this writes generated .png previews back into the local depot
    # cache folder, not to the server -- "asset" is a read-only, cacheable
    # namespace (plan 5.1). Previews saved here are local-only and will not
    # be visible to other users; that is an open design question this
    # migration does not resolve (unlike EA_SharedParam.txt/D1), flagged for
    # a follow-up decision.
    target_folder = os.path.join(main_folder, "Database", "data")

    total_count = len(file_paths)
    LOG_TEXT = ""
    for i, file_path in enumerate(file_paths):
        i += 1
        try:
            head, tail = op.split(file_path)
            jpg_name = tail.replace(".3dm", ".png")
            jpg_name = "{}\{}".format(target_folder, jpg_name)

            image = sc.doc.ExtractPreviewImage(file_path)

            image.Save(jpg_name, System.Drawing.Imaging.ImageFormat.Png)
            print("Getting {}/{} png as {}".format(i + 1, total_count, jpg_name))
        except Exception as e:
            note = "Failed {}/{} png as {} becasue {}".format(i + 1, total_count, file_path, e)
            print(note)
            LOG_TEXT += "\n{}".format(note)

    if len(LOG_TEXT) != 0:
        rs.TextOut(LOG_TEXT)


if __name__ == "__main__":
    extract_preview_images()
