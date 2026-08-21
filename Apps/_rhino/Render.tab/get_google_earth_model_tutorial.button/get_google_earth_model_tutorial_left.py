
__title__ = "GoogleEarthTutorial"
__doc__ = """MANUAL route to site context: opens the Blender video tutorial.

This is the OLD, hand-driven way. It opens a YouTube walkthrough for capturing a
city in Blender and bringing it across into Rhino, plus a companion Blender
script in this button's folder that tidies up the imported materials.

There is now an AUTOMATIC one: GetEarth, in the Create tab. Paste a Google Maps
link, give it a size, and the site model arrives georeferenced and textured with
no Blender step at all. Try that first.

This button stays for two reasons, and will be retired when neither holds:
1. GetEarth's server-side model builder is not finished yet, so this is still
   the only route that works end to end today.
2. The Blender path gives you manual control over exactly what gets captured,
   which the automatic one deliberately does not.
"""


from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION
import webbrowser


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def get_google_earth_model_tutorial():
    # Say this BEFORE opening the browser. Once the video is up the designer is
    # already committed to the manual route; the point is to offer the automatic
    # one while the choice is still open.
    NOTIFICATION.messenger(
        main_text=("Opening the MANUAL Blender tutorial.\n\n"
                   "There is now an automatic version: GetEarth, in the Create "
                   "tab. Paste a Google Maps link, give it a size, done."))

    webbrowser.open("https://www.youtube.com/watch?v=YtlK4046VRQ")

    print("Also check script folder for the python script used in blender.")
    print("Automatic alternative: GetEarth button in Create.tab.")


if __name__ == "__main__":
    get_google_earth_model_tutorial()
