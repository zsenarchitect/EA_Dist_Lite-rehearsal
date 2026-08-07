#!/usr/bin/python
# -*- coding: utf-8 -*-


import os
import sys
root_folder = os.path.abspath((os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(root_folder)
import ENVIRONMENT
import COLOR
import IMAGE

if ENVIRONMENT.IS_RHINO_ENVIRONMENT:
    import rhinoscriptsyntax as rs
    import scriptcontext as sc
    import Eto # pyright: ignore






def hex_to_eto_color(hex_str):
    """Eto.Drawing.Color from #RRGGBB or #AARRGGBB hex string.

    Thin Eto wrapper over COLOR.hex_to_rgba. On invalid input, returns
    Colors.White (matches historical helper behavior across the
    EnneadTab Rhino dialogs) - the parse layer in COLOR.py owns
    fallback semantics; this wrapper just adapts the tuple to Eto.

    Args:
        hex_str (str): Hex string with or without leading '#'. 6 or 8 chars.

    Returns:
        Eto.Drawing.Color
    """
    a, r, g, b = COLOR.hex_to_rgba(hex_str)
    # Eto's FromArgb signature is (red, green, blue, alpha=255) --
    # deliberately DIFFERENT from System.Drawing's (alpha, r, g, b).
    # Passing the tuple in System.Drawing order put alpha into the red
    # channel, so every "#1A1A1A"-style dark grey rendered as ~10%-alpha
    # bright red -- the "burgundy bleed" chased across the ai_render
    # viewer's v1-v11 paint iterations (2026-04-28 .. 2026-06-04).
    return Eto.Drawing.Color.FromArgb(r, g, b, a)


def apply_dark_style(UI):
    
    logo_dark_path = IMAGE.get_image_path_by_name("icon_logo_dark_background.png")
    temp_bitmap = Eto.Drawing.Bitmap(logo_dark_path)
    if hasattr(UI, "logo"):
        UI.logo.Image = temp_bitmap.WithSize(200,30)
    
    icon_path = IMAGE.get_image_path_by_name("icon_form.png")
    UI.Icon = Eto.Drawing.Icon(icon_path)
    
    
    apply_styles_to_control(UI.Content)

def apply_styles_to_control(control):

    
    if hasattr(control, "DataStore"):
        if isinstance(control, Eto.Forms.RadioButtonList):
            pass
        elif isinstance(control, Eto.Forms.CheckBoxList):
            pass
        else:
            return


    dark_background_color = COLOR.tuple_to_color(COLOR.DARKER_BACKGROUND)
    primary_background_color = COLOR.tuple_to_color(COLOR.PRIMARY_BACKGROUND)
    text_color = COLOR.tuple_to_color(COLOR.PRIMARY_TEXT)


    # Apply styles to buttons

    if isinstance(control, Eto. Forms.Button):
        control.BackgroundColor = dark_background_color
        control.TextColor = text_color


    # Apply styles to labels
    elif isinstance(control, Eto. Forms.Label):
        control.TextColor = text_color

    elif isinstance(control, Eto.Forms.TextBox):
        control.BackgroundColor = primary_background_color
        control.TextColor = text_color

    elif isinstance(control, Eto.Forms.RadioButtonList):
        control.BackgroundColor = dark_background_color
        control.TextColor = text_color
        
    elif isinstance(control, Eto.Forms.CheckBoxList):
        control.BackgroundColor = dark_background_color
        control.TextColor = text_color
        
    elif isinstance(control, Eto.Forms.CheckBox):
        control.BackgroundColor = dark_background_color
        control.TextColor = text_color
        
    elif isinstance(control, Eto.Forms.GroupBox):
        control.BackgroundColor = dark_background_color
        control.TextColor = text_color
        
    # if isinstance(control, Eto.Forms.GridView):
    # #     print control.BackgroundColor
    #     control.CellFormatting += OnCellFormatting
        
    elif isinstance(control, Eto.Forms.DynamicLayout):
        control.BackgroundColor = dark_background_color
        
    elif isinstance(control, Eto.Forms.TableLayout):
        control.BackgroundColor = dark_background_color
        
    elif isinstance(control, Eto.Forms.StackLayout):
        control.BackgroundColor = dark_background_color

    if hasattr(control, 'BackgroundColor'):
            control.BackgroundColor = dark_background_color
    if hasattr(control, 'TextColor'):
        control.TextColor = text_color

    # Check and replace image path for ImageView
    # elif isinstance(control, Eto.Forms.ImageView):
    #     #  and "Ennead_Architects_Logo" in control.Image.FileName
    #     print control.Image
    #     for x in dir(control.Image):
    #         print x
    #     temp_bitmap = Eto.Drawing.Bitmap(logo_dark_path)
    #     control.Image = temp_bitmap.WithSize(200,30)

    # Recursively apply styles to sub-controls
    if hasattr(control, "Controls"):
        for sub_control in control.Controls:
            apply_styles_to_control(sub_control)
    elif isinstance(control, Eto.Forms.Container):
        for child in control.Children:
            apply_styles_to_control(child)
    elif hasattr(control, "Items"):
        if isinstance(control, Eto.Forms.MenuItem):
            pass
        elif isinstance(control, Eto.Forms.ComboBox):
            pass
        else:
            for item in control.Items:
                apply_styles_to_control(item)


def OnCellFormatting(self, sender, e): 
    e.ForegroundColor = Eto.Drawing.Colors.White 
    dark_background_color = COLOR.tuple_to_color(COLOR.DARKER_BACKGROUND)
    primary_background_color = COLOR.tuple_to_color(COLOR.PRIMARY_BACKGROUND)
    if e.Row % 2 == 0:
        e.Cell.BackgroundColor = dark_background_color
    else:
        e.Cell.BackgroundColor = primary_background_color


def unit_test():
    pass

if __name__ == "__main__":
    unit_test()