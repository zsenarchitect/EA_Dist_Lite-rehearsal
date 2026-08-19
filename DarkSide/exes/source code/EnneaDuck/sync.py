import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import _Exe_Util


class Sync:
    def __init__(self, parent):
        self.parent = parent

    def is_sync_queue_turn(self):
        docs = ""
        records = ""
        is_my_turn = False
        folder = "{}\\Sync_Queue".format(_Exe_Util.DB_FOLDER)

        data = _Exe_Util.get_data("last_sync_record_data")

        for doc in data.keys():
            filepath = "{}\\Sync Queue_{}.queue".format(folder, doc)
            if not os.path.exists(filepath):
                continue

            content = list(_Exe_Util.get_list(filepath))

            for i, line_record in enumerate(content):
                if self.parent.user_name in line_record:  # Use parent to access user_name
                    records += "\n{}\n{}".format(docs, content)
                    docs += "\n{}".format(doc)
                    if i == 0:
                        is_my_turn = True
                    break

        return is_my_turn, docs, records
