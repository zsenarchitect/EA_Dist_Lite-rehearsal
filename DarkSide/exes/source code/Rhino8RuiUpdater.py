import os
import shutil
import time

import _Exe_Util

import time

def main():
    message = "Wait slightly so Rhino app is fully closed!"
    for char in message:
        print(char, end="", flush=True)  # flush=True makes it print immediately
        time.sleep(0.1)

    print ()

    wait_time = 30
        
    print("🦏 Rhino is getting ready to charge...")
    
    for remaining in range(wait_time, 0, -1):
        print(f"\r🕒 T-minus {remaining} seconds until stampede!", end="")
        time.sleep(1)
    
    print("\n🎯 Release the Rhino!")

    ruis = [
        "{}_For_Rhino_Modern.rui".format(_Exe_Util.PLUGIN_NAME),
        "{}_For_Rhino_Classic.rui".format(_Exe_Util.PLUGIN_NAME)
    ]
    
    for rui in ruis:
        source_rui_path = os.path.join(_Exe_Util.DIST_FOLDER, "Apps", "_rhino", rui)
        target_rui_path = os.path.join(_Exe_Util.DUMP_FOLDER, rui)
        try:
            shutil.copy(source_rui_path, target_rui_path)
        except Exception as e:
            print(f"Error copying {source_rui_path} to {target_rui_path}: {e}")


if __name__ == "__main__":
    main()


