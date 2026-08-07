"""Utilities for data conversions and comparisons."""

import ENVIRONMENT


class DataType:
    ElementId = "ElementId"
    Curve = "Curve"
    CurveLoop = "CurveLoop"
    Point3d = "Point3d"
    TableCellCombinedParameterData = "TableCellCombinedParameterData"
    XYZ = "XYZ"
    Double = "Double"


def list_to_system_list(list, type=DataType.ElementId, use_IList=False):
    """Convert a python list to a System collection List.
    In many occasions it is necessary to cast a python list to a .NET List object

    Args:
        list (python list): _description_
        type (str, optional): the description for target data type. Defaults to "ElementId".
        use_IList (bool, optional): Whether to use IList interface instead of list instance. Defaults to False.

    Returns:
        System.Collections.Generic.List: The converted list object.
    """

    import System  # pyright: ignore

    if ENVIRONMENT.is_Revit_environment():
        from Autodesk.Revit import DB  # pyright: ignore
    if ENVIRONMENT.is_Rhino_environment():
        import Rhino  # pyright: ignore

    if use_IList:
        if type == DataType.CurveLoop:
            return System.Collections.Generic.IList[DB.CurveLoop](list)

        if type == DataType.Curve:
            return System.Collections.Generic.IList[DB.Curve](list)
        
        if type == DataType.TableCellCombinedParameterData:
            return System.Collections.Generic.IList[DB.TableCellCombinedParameterData](
                list
            )

        if type == DataType.ElementId:
            return System.Collections.Generic.IList[DB.ElementId](list)

        return System.Collections.Generic.IList[type](list)

    if type == DataType.Point3d:
        return System.Collections.Generic.List[Rhino.Geometry.Point3d](list)
    if type == DataType.ElementId:
        return System.Collections.Generic.List[DB.ElementId](list)
    if type == DataType.CurveLoop:
        return System.Collections.Generic.List[DB.CurveLoop](list)
    if type == DataType.Curve:
        return System.Collections.Generic.List[DB.Curve](list)
    if type == DataType.TableCellCombinedParameterData:
        return System.Collections.Generic.List[DB.TableCellCombinedParameterData](list)

    if type == DataType.XYZ:
        pts = System.Collections.Generic.List[DB.XYZ]()
        for pt in list:
            pts.Add(pt)
        return pts

    if type == DataType.Double:
        values = System.Collections.Generic.List[System.Double]()
        for value in list:
            values.Add(value)

        return values

    return System.Collections.Generic.List[type](list)
    # print_note("Things are not right here...type = {}".format(type))

    return False


def compare_list(A, B):
    """Compare two lists and return the unique elements in each list and the shared elements.

    Args:
        A (list): The first list.
        B (list): The second list.

    Returns:
        tuple: A tuple containing three lists: unique elements in A, unique elements in B, and shared elements.
    """
    unique_A = [x for x in A if x not in B]
    unique_B = [x for x in B if x not in A]
    shared = [x for x in A if x in B]

    return unique_A, unique_B, shared


def safe_convert_net_array_to_list(net_array):
    """
    Safely convert .NET Array objects (like those returned by forms.pick_file) to Python lists.
    
    This function handles the common issue where pyrevit's forms.pick_file() returns
    a .NET Array[str] object instead of a Python list, which can cause AttributeError
    when trying to call .replace() or other string methods on it.
    
    Args:
        net_array: The object to convert, could be a .NET Array, Python list, tuple, or other iterable
        
    Returns:
        list: A Python list containing the converted items as strings
        
    Example:
        >>> files_raw = forms.pick_file(multi_file=True)
        >>> files = safe_convert_net_array_to_list(files_raw)
        >>> # Now files is a proper Python list that can be safely used
    """
    if not net_array:
        return []
        
    try:
        # Handle .NET Array objects that don't have .replace() method
        if hasattr(net_array, '__iter__') and not isinstance(net_array, (list, tuple, str, bytes)):
            # Convert each item to string to handle any .NET string objects
            return [str(item) for item in net_array]
        else:
            # Handle regular Python iterables
            return list(net_array) if isinstance(net_array, (list, tuple)) else [net_array]
    except Exception as e:
        # Fallback: try to convert to string and handle as single item
        try:
            array_str = str(net_array)
            if array_str and array_str != 'None':
                return [array_str]
            else:
                return []
        except:
            # Last resort: return empty list
            return []


def safe_convert_to_string(obj):
    """
    Safely convert any object to a string, handling .NET objects that don't have .replace().
    
    Args:
        obj: The object to convert to string
        
    Returns:
        str: String representation of the object
        
    Example:
        >>> net_array = some_net_array_object
        >>> result = safe_convert_to_string(net_array)
        >>> # Now result is a safe string that can be used with .replace() etc.
    """
    try:
        return str(obj)
    except:
        # Handle .NET Array objects that don't have .replace()
        if hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
            return "[" + ", ".join(str(item) for item in obj) + "]"
        else:
            return "Unable to convert to string"
def unit_test():
    # print all the enumerations of DataType
    print("All DataType in class:")
    for i, type in enumerate(dir(DataType)):
        if type.startswith("__"):
            continue
        print("{}: {}".format(type, getattr(DataType, type)))
    pass


if __name__ == "__main__":
    unit_test()
    pass
