import ENVIRONMENT
import FOLDER
import os
import time
import random

if ENVIRONMENT.IS_RHINO_ENVIRONMENT:
    import rhinoscriptsyntax as rs
    import Rhino # pyright: ignore


def update_rui_v7():
    

    for tool_bar_name in rs.ToolbarCollectionNames():
        if ENVIRONMENT.PLUGIN_NAME.lower() in tool_bar_name.lower():
            rs.CloseToolbarCollection(tool_bar_name, prompt=False)


    my_local_version = FOLDER.copy_file_to_local_dump_folder(ENVIRONMENT.DIST_RUI_CLASSIC)
    rs.OpenToolbarCollection(my_local_version)

def update_rhino8_containers_xml(rui_path=None, is_installing=True):
    """Register or unregister EnneadTab Modern RUI in Rhino 8 containers.xml.

    Rhino 8 changed toolbar persistence: rs.OpenToolbarCollection only affects the
    live session, and does not persist across restarts unless registered in
    %APPDATA%/McNeel/Rhinoceros/8.0/settings/Scheme__*/containers.xml under <files>.
    """
    import re
    import shutil

    if rui_path is None:
        rui_path = os.path.join(ENVIRONMENT.DUMP_FOLDER, "{}_For_Rhino_Modern.rui".format(ENVIRONMENT.PLUGIN_NAME))

    appdata = os.environ.get("APPDATA")
    if not appdata:
        return False

    rhino8_settings_dir = os.path.join(appdata, "McNeel", "Rhinoceros", "8.0", "settings")
    if not os.path.isdir(rhino8_settings_dir):
        return False

    rui_guid = "9d3c8a78-27a1-4c03-b74d-508554dcef36"
    plugin_guid = "02bf604d-799c-4cc2-830e-8d72f21b14b7"
    entry_line = '    <file_name guid="{}" plug_in_guid="{}" source="File">{}</file_name>'.format(
        rui_guid, plugin_guid, rui_path
    )

    success = False
    for item in os.listdir(rhino8_settings_dir):
        scheme_dir = os.path.join(rhino8_settings_dir, item)
        if not os.path.isdir(scheme_dir) or not item.startswith("Scheme__"):
            continue
        xml_path = os.path.join(scheme_dir, "containers.xml")
        if not os.path.isfile(xml_path):
            continue

        try:
            with open(xml_path, "r", encoding="utf-8-sig") as f:
                content = f.read()
        except Exception:
            try:
                with open(xml_path, "r") as f:
                    content = f.read()
            except Exception:
                continue

        has_entry = (rui_path.lower() in content.lower()) or (rui_guid.lower() in content.lower())

        if is_installing:
            if has_entry:
                success = True
                continue
            if "<files>" in content and "</files>" in content:
                content = content.replace("  <files>\n", "  <files>\n{}\n".format(entry_line), 1)
            elif "<files/>" in content:
                content = content.replace("<files/>", "<files>\n{}\n  </files>".format(entry_line), 1)
            else:
                files_block = "  <!--Open RUI files-->\n  <files>\n{}\n  </files>\n".format(entry_line)
                if "<!--Plug-in associated files-->" in content:
                    content = content.replace("  <!--Plug-in associated files-->", files_block + "  <!--Plug-in associated files-->", 1)
                elif "<plug_in_files>" in content:
                    content = content.replace("  <plug_in_files>", files_block + "  <plug_in_files>", 1)
                elif "<dock_bars" in content:
                    content = content.replace("  <dock_bars", files_block + "  <dock_bars", 1)
                else:
                    idx = content.find("</name>")
                    if idx != -1:
                        insert_pos = idx + len("</name>\n")
                        content = content[:insert_pos] + files_block + content[insert_pos:]
                    else:
                        continue
        else:
            if not has_entry:
                success = True
                continue
            lines = content.splitlines(True)
            new_lines = [l for l in lines if (rui_guid.lower() not in l.lower()) and (rui_path.lower() not in l.lower())]
            content = "".join(new_lines)
            content = re.sub(r"[ \t]*<!--Open RUI files-->\s*<files>\s*</files>\s*", "", content)
            content = re.sub(r"[ \t]*<files>\s*</files>\s*", "", content)

        try:
            bak_path = xml_path + ".bak"
            shutil.copy2(xml_path, bak_path)
            with open(xml_path, "w", encoding="utf-8-sig") as f:
                f.write(content)
            success = True
        except Exception:
            pass

    return success


def update_rui_v8():
    good_rui_toolbar_name = os.path.basename(ENVIRONMENT.DIST_RUI_MODERN).replace(".rui", "")

    for tool_bar_name in rs.ToolbarCollectionNames():
        # do not close current opened modern rui so it will not deactivate and disappear after restart
        if good_rui_toolbar_name == tool_bar_name:
            continue

        if ENVIRONMENT.PLUGIN_NAME.lower() in tool_bar_name.lower():
            rs.CloseToolbarCollection(tool_bar_name, prompt=False)


    my_local_version = FOLDER.copy_file_to_local_dump_folder(ENVIRONMENT.DIST_RUI_MODERN)
    rs.OpenToolbarCollection(my_local_version)
    update_rhino8_containers_xml(my_local_version, is_installing=True)




def update_my_rui():
    if rs.ExeVersion() >= 8:
        update_rui_v8()
    else:
        update_rui_v7()


def close_rui():
    """Uninstall counterpart to update_my_rui: close every EnneadTab
    toolbar collection without reopening one.
    """
    for tool_bar_name in rs.ToolbarCollectionNames():
        if ENVIRONMENT.PLUGIN_NAME.lower() in tool_bar_name.lower():
            rs.CloseToolbarCollection(tool_bar_name, prompt=False)
    update_rhino8_containers_xml(is_installing=False)




def add_startup_script():
    
    """hear me out here:
    python cannot add startup script directly
   
    i use this python script C to call rhino script B to call rhino script A, which is the command alias
    This will not run the startup command, it just add to the start sequence.
    """
    max_attempts = 3
    
    rvb_caller_script_path = "{}\\{}_StartupCaller.rvb".format(ENVIRONMENT.WINDOW_TEMP_FOLDER, ENVIRONMENT.PLUGIN_NAME)

    rvb_caller_content = """
Option Explicit

Sub StartupCaller()
    Dim commandName
    commandName = "{}_{}_Startup"
    Call Rhino.Command(commandName)
End Sub

Call StartupCaller()
""".format(ENVIRONMENT.PLUGIN_ABBR, ENVIRONMENT.PLUGIN_NAME)

    # Use retry logic for the first file
    for attempt in range(max_attempts):
        try:
            with open(rvb_caller_script_path, "w") as f:
                f.write(rvb_caller_content)
            break
        except IOError as e:
            if attempt < max_attempts - 1:
                # Add a small random delay to avoid race conditions
                time.sleep(0.5 + random.random())
                continue
            else:
                print("Failed to write caller script after {} attempts: {}".format(max_attempts, e))
                raise

    rvb_startup_modifier_script_path = "{}\\{}_StartupEnable.rvb".format(ENVIRONMENT.WINDOW_TEMP_FOLDER, ENVIRONMENT.PLUGIN_NAME)

    rvb_startup_modifier_content = """
Option Explicit

Sub StartupEnable()
    On Error Resume Next
    
    Dim filePath
    Dim intCount
    Dim arrPaths
    Dim strPath
    Dim temp_folder
    
    temp_folder = "C:\\temp\\{}_Dump"

    ' Get count of startup scripts
    intCount = Rhino.StartupScriptCount
    
    ' If there are scripts, check for ones containing "menu" and remove them
    If intCount > 0 Then
        arrPaths = Rhino.StartupScriptList
        For Each strPath in arrPaths
            If InStr(strPath, "menu") > 0 Then
                Call Rhino.DeleteStartupScript (strPath)
            End If
        Next
    End If
    
    filePath = temp_folder & "\\{}_StartupCaller.rvb"
    
    ' Ensure path with spaces is handled correctly by enclosing in quotes
    filePath = Chr(34) & filePath & Chr(34)
    
    Call Rhino.AddStartupScript(filePath)
    
    If Err.Number <> 0 Then
        Call Rhino.Print("Error in StartupEnable: " & Err.Description)
    End If
End Sub

Call StartupEnable()
""".format(ENVIRONMENT.PLUGIN_NAME, ENVIRONMENT.PLUGIN_NAME)

    # Use retry logic for the second file
    for attempt in range(max_attempts):
        try:
            with open(rvb_startup_modifier_script_path, "w") as f:
                f.write(rvb_startup_modifier_content)
            break
        except IOError as e:
            if attempt < max_attempts - 1:
                # Add a small random delay to avoid race conditions
                time.sleep(0.5 + random.random())
                continue
            else:
                print("Failed to write startup modifier script after {} attempts: {}".format(max_attempts, e))
                raise
                
    Rhino.RhinoApp.RunScript("-LoadScript " + rvb_startup_modifier_script_path, True)


def remove_startup_script():
    """Uninstall counterpart to add_startup_script: clears any EnneadTab
    startup script registration without adding a new one.

    Filters on PLUGIN_NAME ("EnneadTab"), not "menu" -- confirmed live
    (2026-09-08) that add_startup_script actually registers
    "<WINDOW_TEMP_FOLDER>\\EnneadTab_StartupCaller.rvb", which contains no
    "menu" substring at all. An earlier version of this function copied the
    "menu" filter from add_startup_script's own internal self-cleanup loop
    (which targets a DIFFERENT, older startup-script mechanism) without
    checking it actually matched the current registration -- so it deleted
    nothing, and EnneadTab kept auto-loading after "uninstall" (reproduced:
    user ran the uninstaller, then reopened Rhino and EnneadTab was still
    there).
    """
    rvb_path = "{}\\{}_StartupDisable.rvb".format(ENVIRONMENT.WINDOW_TEMP_FOLDER, ENVIRONMENT.PLUGIN_NAME)

    rvb_content = """
Option Explicit

Sub StartupDisable()
    On Error Resume Next

    Dim intCount
    Dim arrPaths
    Dim strPath

    intCount = Rhino.StartupScriptCount
    If intCount > 0 Then
        arrPaths = Rhino.StartupScriptList
        For Each strPath in arrPaths
            If InStr(strPath, "{}") > 0 Then
                Call Rhino.DeleteStartupScript (strPath)
            End If
        Next
    End If
End Sub

Call StartupDisable()
""".format(ENVIRONMENT.PLUGIN_NAME)

    with open(rvb_path, "w") as f:
        f.write(rvb_content)

    Rhino.RhinoApp.RunScript("-LoadScript " + rvb_path, True)


def unit_test():
    pass

    
if __name__ == "__main__":

    update_my_rui()