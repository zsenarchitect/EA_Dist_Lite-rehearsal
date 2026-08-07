__doc__ = """Open e.AI rendering website for enhancing and refining your renders!

This tool opens the e.AI web application (https://enneadtab.com/rendering/home) that helps you:
- Polish and enhance render outputs
- Apply post-processing effects
- Refine render quality and appearance
- Streamline your rendering workflow

Perfect for visualization specialists looking to take their renders to the next level.
"""

__title__ = "GetInspired"



import proDUCKtion # pyright: ignore 
proDUCKtion.validify()
from EnneadTab import LOG, ERROR_HANDLE
import webbrowser

@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def get_inspired():
    url = "https://enneadtab.com/rendering/home"
    webbrowser.open(url)
    print("Opening {} in browser...".format(url))

if __name__ == "__main__":
    get_inspired()

