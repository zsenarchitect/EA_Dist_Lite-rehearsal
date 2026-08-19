import ast



import os


from BaseHandler import BaseHandler
from IconHandler import IconHandler
from GuidHandler import GuidHandler
from KnowledgeHandler import KnowledgeHandler

from constants import PLUGIN_ABBR, PLUGIN_NAME, ECO_SYS_FOLDER


class MacroHandler(BaseHandler):
    """Note to self:
    Macro is the foundation of all toolbar layout, that link scattered information to UI
    there can be multiple UI items(button left right click, or menu item) call for same macro. In rhino manual edit you can recycle macro usage, but there is little benefit doing that if I am building rui dhnamically, 
    So let each macro be unique is the best/simplest way.."""

    
    """THis is what need to be filled for a typical macro item.
    need to have those attrs:
    - guid -----> created when init instance
    - bitmap_id -----> only retrieve that at this stage by looking for icon file in same folder. 
                        Still use IconHandler but Dont pass a big dict around
    - text ----> parse from script
    - tooltip ----> parse from script
    - help_text ----> parse from script
    - button_text ----> parse from script
    - menu_text ----> parse from script
    - script ----> firgure out here

    Example:    
        <macro_item guid="f15302e0-b388-452e-aa50-791a080ae744" bitmap_id="329c4ab7-6a9e-4e1e-acd7-0a57500af57a">
      <text>
        <locale_1033>macro_name_test</locale_1033>
      </text>
      <tooltip>
        <locale_1033>tooltip text test</locale_1033>
      </tooltip>
      <help_text>
        <locale_1033>help text test</locale_1033>
      </help_text>
      <button_text>
        <locale_1033>button_text_test</locale_1033>
      </button_text>
      <menu_text>
        <locale_1033>menu_text_test</locale_1033>
      </menu_text>
      <script>_show</script>
    </macro_item>


    """
    def __init__(self, script_path):
        self.script_path = script_path
        self.script_name = os.path.basename(script_path).replace(".py", "")
        # create unique guid that looks like this d58ceae7-fdb0-4104-80da-274b94ad44a9
        self.guid = GuidHandler(script_path).guid
        # print (self.guid)
        self.icon = self.get_icon()
        
        # parse this python by load it to extract gloabl vars by path
        self.script_gloabl_vars_dict = extract_global_variables(self.script_path)

        
        KnowledgeHandler(self.script_path, self.icon, self.script_gloabl_vars_dict)

        # find a template to write script, tooltip, and other default info.
        self.assign_basic_info()

        for searcher in [".tab", ".menu"]:
            if searcher in script_path:
                search_folder = script_path.split(searcher)[0].rsplit("\\", 1)[0]
                break
        # print (search_folder)
        self.script = self.get_script(search_folder)



    def __repr__(self) -> str:
        return f"MacroHandler({self.script_name})"

    def print_detail(self):
        print ("\n\n")
        print ("MacroHandler Details: [{}]".format(self.script_name))
        for attr in sorted(dir(self)):
            if not attr.startswith("_") and not callable(getattr(self, attr)):
                print (attr, getattr(self, attr), sep=": ")

 


    def assign_basic_info(self):
        
        
        attr_dict = {"text":"__title__", # become the macro name, not visible to user, can have duplicate
                     "tooltip":"__doc__", # become text during mouse hovering, visible to user
                     "help_text":"__doc__", # detailed description, not visible to user
                     "button_text":"__title__", # become the button text when used as left click macro. Visible to user.
                     "menu_text":"__title__"} # become the menu text. Visible to user.
        for key, attr in attr_dict.items():

            value = self.script_gloabl_vars_dict.get(attr, "N/A")

            if attr == "__title__" and value == "N/A":
                value = self.script_name
            if attr == "__doc__" and value == "N/A":
                value = "Documentation Pending for <" + self.script_name + ">"
  

            # allow some script to have multiple alias to create with different shorthand
            if isinstance(value, list):
                value = value[0]

            # 2026-04-08: __title__ is used for both display AND command alias (EA_{title}).
            # Spaces/newlines in __title__ break Rhino command aliases silently.
            # Warn at build time so the author can fix it.
            if attr == "__title__" and isinstance(value, str):
                if " " in value or "\n" in value:
                    print("\033[93mWARNING: __title__ contains spaces or newlines in {}: '{}'\n"
                          "  This will produce a broken Rhino command alias. Use PascalCase instead.\033[0m"
                          .format(self.script_path, value))

            setattr(self, key, value)
            
        
    def get_icon(self):
        current_folder = os.path.dirname(self.script_path)
        for f in os.listdir(current_folder):
            if 'icon' in f:
                # make sure the file extension is either .png or .svg
                if f.endswith('.png') or f.endswith('.svg'):
                    icon_path = os.path.join(current_folder, f)
                    
                    return IconHandler(icon_path, caller = self.script_name)
     

        return IconHandler(None, caller = self.script_name)

    def get_script(self, search_folder):
        """used to just use a template format to fill in info. 
        Now create alias automatically and call that.

        (Prefer second for long term effort. It is cleaner to read, BUT do require USER to register all alias dynamically.)
        """
        must_full_converter = self.script_gloabl_vars_dict.get("__FONDATION__")
        if not must_full_converter:
            alias = self.script_gloabl_vars_dict.get("__title__")
            script_name = generate_alias_script_name(alias)
            if script_name:
                return script_name
        locator = self.script_path.split("{}\\".format(search_folder))[1]
        locator = locator.replace("\\", "\\\\")

        #This macro is auto-generated, manual modification will be discarded;
        # note to self: using ; at the end of the line to simulate a one-liner python
        # Priority search for the EnneadTab lib folder:
        # 1. Dev repos under common developer parent folders, including nested org subfolders
        #    (e.g., github/ennead-llp/EnneadTab-OS) so developers get their live source first.
        # 2. Fallback to the Ecosystem (EA_Dist) copy that every end-user machine has.
        # Non-dev users skip step 1 in microseconds (paths simply don't exist); developers
        # get their uncommitted/unpublished changes applied instantly without waiting on AutoDist.
        script = """! _-RunPythonScript (
import os
import sys
common_folders = ["github","dev-repo","duck-repo","design-repo"]
org_folders = ["", "ennead-llp", "Personal", "LakeHouse-LLP", "Toni-LLP", "TimeBank-llp", "zsenarchitect"]
lib_folders = []
for parent in common_folders:
    for org in org_folders:
        parts = [os.environ['USERPROFILE'], parent]
        if org:
            parts.append(org)
        parts += ["EnneadTab-OS", "Apps", "lib", "EnneadTab"]
        lib_folders.append(os.path.join(*parts))
lib_folders.append(os.path.join(os.environ['USERPROFILE'], 'Documents','EnneadTab Ecosystem','EA_Dist','Apps','lib','EnneadTab'))
lib_folders.append(os.path.join(os.environ['USERPROFILE'], 'Documents','EnneadTab-Ecosystem','EA_Dist','Apps','lib','EnneadTab'))
for lib_folder in lib_folders:
    if os.path.exists(lib_folder):
        sys.path.append(lib_folder)
        break
import MODULE_HELPER
MODULE_HELPER.run_Rhino_button('{}')
)
""".format(locator)
        return script

    
    def as_json(self):
        data =  {
            "@guid": self.guid,
            "@bitmap_id": self.icon.guid,
            "text": {"locale_1033": self.text},
            "tooltip": {"locale_1033": self.tooltip},
            "help_text": {"locale_1033": self.help_text},
            "button_text": {"locale_1033": self.button_text},
            "menu_text": {"locale_1033": self.menu_text},
            "script": self.script
        }

        return {"macro_item": data}
        




class ClickBehavior:
    Left = "_left.py"
    Right = "_right.py"

def get_macro(button_folder, click):

    for folder, _, files in os.walk(button_folder):
        for f in files:
            # dont want to process the helper scripts.
            if click in f:
                script_path = os.path.join(folder, f)
                # macros.append(MacroHandler(script_path))
                return MacroHandler(script_path)

    return None

def extract_global_variables(script_path):
    # Scripts are saved as UTF-8; default locale encoding (cp1252 on the
    # publisher machine) mojibakes any non-ASCII doc text into the RUI tooltip.
    with open(script_path, 'r', encoding="utf-8") as file:
        script_content = file.read()
    
    tree = ast.parse(script_content)
    global_vars = {}
    
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id
                    # Initialize default value
                    var_value = None
                    
                    # Handle different node value types
                    if isinstance(node.value, ast.Constant):
                        var_value = node.value.value  # Direct constant value
                    elif isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
                        # Handle string formatting cases like "abc {}".format(var)
                        if node.value.func.attr == 'format':
                            try:
                                # Get the base string
                                if isinstance(node.value.func.value, ast.Constant):
                                    base_string = node.value.func.value.value
                                else:
                                    base_string = ast.literal_eval(node.value.func.value)
                                
                                # For format args, keep them as placeholders
                                format_args = []
                                for arg in node.value.args:
                                    if isinstance(arg, ast.Name):
                                        format_args.append(f"{{{arg.id}}}")
                                    elif isinstance(arg, ast.Constant):
                                        format_args.append(str(arg.value))
                                    else:
                                        format_args.append("{...}")
                                
                                var_value = base_string.format(*format_args)
                            except:
                                var_value = "Template string with dynamic values"
                    else:
                        try:
                            # Fallback for other types using literal_eval
                            var_value = ast.literal_eval(node.value)
                        except ValueError:
                            var_value = "Unsupported value for safe evaluation, ask Sen Z to fix this."
                    
                    # Only add to global_vars if we got a value
                    if var_value is not None:
                        global_vars[var_name] = var_value
    
    return global_vars
    
def generate_alias_script_name(alias):
    prefunction_name = """{}_Activate{}
""".format(PLUGIN_ABBR, PLUGIN_NAME)
    if isinstance(alias, list):
        alias = alias[0]
    if alias is not None:
        if alias == alias.upper():
            return "{}{}".format(prefunction_name, alias)
        else:
            return "{}{}_{}".format(prefunction_name, PLUGIN_ABBR,alias)
    return None

if __name__ == "__main__":
    pass
