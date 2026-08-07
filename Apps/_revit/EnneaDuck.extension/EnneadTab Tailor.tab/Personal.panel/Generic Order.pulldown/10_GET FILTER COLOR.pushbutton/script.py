__title__ = "10_GET FILTER COLOR"
__doc__ = """List the surface override color of every filter in the active view.

Prints each view filter by name with its surface foreground pattern
RGB values, so you can copy exact colors when matching or rebuilding
filter overrides in another view or project."""


from pyrevit import forms, DB, revit, script


################## main code below #####################
output = script.get_output()
output.close_others()
#ideas:

print(revit.active_view)
view = revit.active_view
filters = list(view.GetFilters())
filters.sort(key = lambda f: revit.doc.GetElement(f).Name)
for f in filters:
    filter_obj = view.GetFilterOverrides(f)
    print("********")
    print(revit.doc.GetElement(f).Name)
    try:
        color = filter_obj.SurfaceForegroundPatternColor
        print(color.Red, color.Green, color.Blue)
    except:
        continue
