
import os
import sys
import subprocess


import ENVIRONMENT
import NOTIFICATION
import OUTPUT
import TEXT
import ERROR_HANDLE

def print_boolean_in_color(bool):
    if not ENVIRONMENT.is_terminal_environment():
        return bool

    import TEXT

    if bool:
        return TEXT.colored_text("True", TEXT.TextColorEnum.Green)
    else:
        return TEXT.colored_text("False", TEXT.TextColorEnum.Red)


def print_text_in_highlight_color(text, ok=True):
    if not ENVIRONMENT.is_terminal_environment():
        return text

    return TEXT.colored_text(
        text, TEXT.TextColorEnum.Blue if ok else TEXT.TextColorEnum.Red
    )


IGNORE_LIST = ["__pycache__", "RHINO", "scripts", "RIR"]


def module_call_test(module_call):
    module = module_call.split(".")[0]
    eval("import {}".format(module))
    results = eval(repr(module_call))
    return results


def pretty_test(test_dict, filename):
    """Test function for a module with a dictionary of test cases.
    Only intended to run in terminal, using Python 3.
    Rhino and Revit in-envionment testing will be supported
    with future updates.

    Args:
        test_dict (dict): Dictionary of test cases.
        filename (str): Filename of the module to test.

    Use the following formats for test_dict:
    test_dict = {
        "function_name_1": {
            "'string_arg_1'": expected_result,
            "'string_arg_2'": expected_result,
            ...
        },
        "function_name_2": {
            "num1, num2": expected_result,
            "num3, num4": expected_result,
            ...
        },
        "function_name_3": {
            "[list_arg_1]": expected_result,
            ...
        },
        "function_name_4": {
            "{'string_arg', num_arg}": expected_result,
            ...
        ...
    }

    Returns:
        bool: True if all tests pass, False if any test fails.

    """
    from importlib import import_module

    from COLOR import TextColorEnum as T
    from TEXT import colored_text as C

    # Import the module by filename
    module = import_module(filename.split("/")[-1].split(".")[0])

    for func_template, test_cases in test_dict.items():
        func_name = func_template.split("(")[0]
        display_func = C(func_name, T.Magenta)
        print("Testing {}".format(display_func))

        # if display_func == "module_test":
        #     func_to_call = getattr()
        # else:
        #     func_to_call = getattr(module, func_name)
        func_to_call = getattr(module, func_name)

        all_passed = True

        for test_case, expected in test_cases.items():
            display_test_case = C(test_case, T.Yellow)
            print("    args: {}".format(display_test_case))
            result = None


            switch = False
            for char in ["[", "{"]:
                if char in test_case:
                    switch = True
                    break
            if switch:
                args = (eval(test_case),)
            else:
                args = tuple(eval(arg.strip()) for arg in test_case.split(","))

            failure_message = "    expected {}, got {} - {}".format(C(expected, T.Blue),C(result, T.Blue),C('Passed', T.Green))
            success_message = "    expected {}, got {} - {}".format(C(expected, T.Blue),C(result, T.Red),C('Failed', T.Red))
            try:
                result = func_to_call(*args)
                if result == expected:
                    print(
                        failure_message
                    )
                else:
                    print(
                        success_message
                    )
            except Exception as e:
                print(
                    failure_message
                )
                if e:
                    print("    {}".format(C(str(e), T.Red)))
            if all_passed:
                if not result == expected:
                    all_passed = False



class UnitTest:
    def __init__(self):
        self.failed_module = []
        self.count = 0

    def try_run_unit_test(self, module):
        print(
            "\n--{}:\nImport module [{}] Successfully".format(
                self.count + 1, print_text_in_highlight_color(module.__name__)
            )
        )
        self.count += 1
        if not hasattr(module, "unit_test"):
            print("This module has no tester.")
            return True
        test_func = getattr(module, "unit_test")
        if not callable(test_func):
            return True

        print(
            print_text_in_highlight_color(
                "Running unit test for module <{}>".format(module.__name__)
            )
        )
        
        # Always run with default engine first
        try:
            test_func()
            print("OK!")
            result = True
        except AssertionError as e:
            print("Assertion Error! There is some unexpected results in the test")
            ERROR_HANDLE.print_note(ERROR_HANDLE.get_alternative_traceback())
            NOTIFICATION.messenger("[{}] has failed the unit test".format(module))
            result = False
        
        # If in terminal/IDE environment, also try IronPython
        if ENVIRONMENT.is_terminal_environment():
            self._try_ironpython_unit_test(module)
        
        return result

    def _try_ironpython_unit_test(self, module):
        """Try to run the same unit test using IronPython if available."""
        # Try to find IronPython executable
        possible_ipy = [
            'ipy', 'ipy.exe', 'ipy64', 'ipy64.exe',
            r'C:\Program Files\IronPython 2.7\ipy.exe',
            r'C:\Program Files (x86)\IronPython 2.7\ipy.exe',
        ]
        
        ipy_found = None
        for ipy in possible_ipy:
            try:
                # Try to get version to check if exists
                subprocess.check_output([ipy, '-V'], stderr=subprocess.STDOUT)
                ipy_found = ipy
                break
            except Exception:
                continue
        
        if not ipy_found:
            return
        
        # Get the module file path
        try:
            module_file = module.__file__
        except AttributeError:
            return
        
        print("  Also testing with IronPython: {}".format(ipy_found))
        try:
            # Try with timeout first (Python 3)
            try:
                result = subprocess.check_output([ipy_found, module_file], 
                                               stderr=subprocess.STDOUT, 
                                               universal_newlines=True,
                                               timeout=30)  # 30 second timeout
            except (TypeError, AttributeError):
                # Fallback for IronPython 2.7 which doesn't support timeout parameter
                result = subprocess.check_output([ipy_found, module_file], 
                                               stderr=subprocess.STDOUT, 
                                               universal_newlines=True)
            print("  IronPython test completed successfully")
        except subprocess.TimeoutExpired:
            print("  IronPython test timed out")
        except Exception as e:
            print("  IronPython test failed: {}".format(e))

    def process_folder(self, folder):
        if not os.path.isdir(folder):
            return

        for module_file in os.listdir(folder):
            # this so in terminal run not trying to test REVIT_x and RHINO_x file
            if module_file in IGNORE_LIST:
                continue

            if module_file.endswith(".pyc"):
                continue
            module_path = os.path.join(folder, module_file)

            if os.path.isdir(module_path):
                self.process_folder(module_path)
                continue

            if not module_file.endswith(".py"):
                continue
            module_name = module_file.split(".")[0]
            if module_name in IGNORE_LIST:
                continue
            try:
                # Use importlib.util instead of deprecated imp module
                try:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location(module_name, module_path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                except ImportError:
                    # Fallback to imp for IronPython 2.7 compatibility
                    try:
                        import imp
                        module = imp.load_source(module_name, module_path)
                    except ImportError:
                        # Final fallback for environments without imp
                        import types
                        import io
                        with io.open(module_path, 'r', encoding='utf-8') as f:
                            code = f.read()
                        module = types.ModuleType(module_name)
                        exec(code, module.__dict__)
                self.try_run_unit_test(module)
            except Exception as e:
                print("Failed to import or test module {}: {}".format(module_file, e))


def test_core_module():
    tester = UnitTest()

    tester.process_folder(ENVIRONMENT.CORE_FOLDER)
    if len(tester.failed_module) > 0:
        print("\n\n\nbelow modules are failed.")
        print("\n--".join(tester.failed_module))
        raise TooManyFailedModuleException

    OUTPUT.display_output_on_browser()


class TooManyFailedModuleException(BaseException):
    def __init__(self):
        super(TooManyFailedModuleException, self).__init__(
            "There are too many failed module during unit-test for the core module."
        )


# Example integration: always run dual engine test for IMAGE.py when running this module directly
if __name__ == "__main__":
    test_core_module()
