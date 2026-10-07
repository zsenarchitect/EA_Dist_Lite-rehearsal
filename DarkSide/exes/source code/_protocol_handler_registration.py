"""Windows registry registration for the enneadtab-depot:// custom URI
protocol (senzhang-todo #5513). Called from EnneadTab_OS_Installer.py on
install and EnneadTab_OS_UnInstaller.py on uninstall.

Registering a custom URI protocol is the standard documented Windows shell
mechanism (HKEY_CLASSES_ROOT\\<scheme> with a 'URL Protocol' marker and a
\\shell\\open\\command default value) -- the same shape browsers already use
for e.g. mailto: or vscode:. Written under HKEY_CURRENT_USER\\Software\\
Classes (not HKEY_CLASSES_ROOT directly) so it needs no elevation, matching
every other EnneadTab-OS installer step -- EA_Dist installs entirely under
the user's own Documents folder, never Program Files.
https://learn.microsoft.com/windows/win32/shell/app-registration

The registry-key VALUES this would write are pure and unit-tested
(protocol_registry_entries); the actual winreg calls that WRITE them cannot
even be IMPORTED outside Windows and are exercised only by a live install --
host-verification-pending, same caveat as every other change in this session
that touches a real Revit/Rhino/Windows surface this environment cannot run.
"""

PROTOCOL_NAME = "enneadtab-depot"


def handler_command(handler_exe_path):
    """The exact command string HKCU\\Software\\Classes\\<scheme>\\shell\\
    open\\command's default value gets set to. Windows appends the activated
    URI as one argument -- '%1' is the literal placeholder it substitutes."""
    return '"{0}" "%1"'.format(handler_exe_path)


def protocol_registry_entries(handler_exe_path):
    """Every (key_path, value_name, value) triple registration needs to set,
    as plain data -- register_protocol_handler() below just walks this and
    calls winreg. Kept separate so the DECISION of what to write is testable
    without Windows or elevated permissions."""
    root = PROTOCOL_NAME
    return [
        (root, None, "URL:EnneadTab-Library Asset Install"),
        (root, "URL Protocol", ""),
        (root + "\\shell\\open\\command", None, handler_command(handler_exe_path)),
    ]


def register_protocol_handler(handler_exe_path):
    """Write the entries from protocol_registry_entries()."""
    import winreg

    for key_path, value_name, value in protocol_registry_entries(handler_exe_path):
        full_path = "Software\\Classes\\{0}".format(key_path)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, full_path) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, value)


def unregister_protocol_handler():
    """Best-effort cleanup -- deleting a registry key tree needs a recursive
    walk (winreg has no rmtree), and a missing key is not an error (the user
    may never have installed the version that registered it)."""
    import winreg

    def _delete_tree(root, path):
        try:
            with winreg.OpenKey(root, path) as key:
                while True:
                    try:
                        sub = winreg.EnumKey(key, 0)
                    except OSError:
                        break
                    _delete_tree(root, path + "\\" + sub)
            winreg.DeleteKey(root, path)
        except FileNotFoundError:
            pass

    _delete_tree(winreg.HKEY_CURRENT_USER, "Software\\Classes\\{0}".format(PROTOCOL_NAME))
