import os
import shutil
import _Exe_Util
ACC_PREFIX = "C:\\Users\\{}\\DC\\ACCDocs\\Ennead Architects LLP\\2412_SPARC\\Project Files".format(_Exe_Util.USER_NAME)
J_PREFIX = "J:\\2412"
FILES_TO_FETCH = {
    "j_address1.txt":"j_address1.txt",
    "j_address2.txt":"j_address2.txt",
    "j_address3.txt":"j_address3.txt",
}


BIM_LINK_FOLDER_ACC = os.path.join(ACC_PREFIX, "3_BIM", "01_ARCHITECTURE_Coordination", "0_BIM", "Schedules_BIMLink")
BIM_LINK_FOLDER_J = os.path.join(J_PREFIX, "0_BIM", "10_BIM Management", "03_BIMLinks")

def main():
    if not os.path.exists(ACC_PREFIX):
        print (f"{ACC_PREFIX} not valid folder path")
        return
    for key, value in FILES_TO_FETCH.items():
        full_key = os.path.join(ACC_PREFIX, key)
        full_value = os.path.join(J_PREFIX, value)
        if os.path.exists(full_key):
            try:
                shutil.copy(full_key, full_value)
            except Exception as e:
                print(f"Error copying {full_key} to {full_value}: {e}")
        else:
            print (f"{full_key} not valid file path")

    for file in os.listdir(BIM_LINK_FOLDER_ACC):
        full_acc_path = os.path.join(BIM_LINK_FOLDER_ACC, file)
        full_j_path = os.path.join(BIM_LINK_FOLDER_J, file)
       
        try:
            shutil.copy(full_acc_path, full_j_path)
           
        except Exception as e:
            _Exe_Util.messenger(f"Error copying {full_acc_path} to {full_j_path}:\n{e}")




if __name__ == "__main__":
    main()


