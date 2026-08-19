import shutil
import os
import time


def _source_bases():
    """Local / env sources only. The office L: drive is retired."""
    bases = []
    env = (os.environ.get("EA_REVIT_INI_SOURCE") or "").strip()
    if env:
        bases.append(env)
    userprofile = os.environ.get("USERPROFILE", "")
    eco = os.path.join(userprofile, "Documents", "EnneadTab Ecosystem")
    bases.append(os.path.join(eco, "Dump", "RevitInitialization"))
    bases.append(os.path.join(eco, "EA_Dist", "Apps", "lib", "EnneadTab", "revit_initialization"))
    here = os.path.dirname(os.path.abspath(__file__))
    bases.append(os.path.join(here, "RevitInitialization"))
    return bases


def copy_revit_ini_files():
    filename = "Revit.ini"
    target_base = "C:\\ProgramData\\Autodesk\\RVT "
    found_any = False

    for source_base in _source_bases():
        if not source_base or not os.path.isdir(source_base):
            continue
        for year in range(2000, 2099):
            source_path = os.path.join(source_base, str(year), filename)
            target_path = os.path.join(target_base + str(year), "UserDataCache", filename)
            if not os.path.exists(source_path):
                continue
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copyfile(source_path, target_path)
            found_any = True
            print("Copied {} to {}".format(source_path, target_path))

    if not found_any:
        print("No Revit.ini sources found. The office L: drive is retired.")
        print("Put year folders under:")
        print("  Documents\\EnneadTab Ecosystem\\Dump\\RevitInitialization\\<year>\\Revit.ini")
        print("or set EA_REVIT_INI_SOURCE to that parent folder.")

    print("\n\nRestart Revit to see updates.")
    print("You can close this window")
    time.sleep(30)

if __name__ == "__main__":
    copy_revit_ini_files()
