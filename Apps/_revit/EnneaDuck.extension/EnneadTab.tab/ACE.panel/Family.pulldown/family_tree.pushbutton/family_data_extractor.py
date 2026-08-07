#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Family Data Extractor Module
Collects family, parameter, and association data from Revit family documents.

Revit API References:
- FamilyParameter: https://www.revitapidocs.com/2015/6175e974-870e-7fbc-3df7-46105f937a6e.htm
- FamilyManager: https://www.revitapidocs.com/2015/1cc4fe6c-0e9f-7439-0021-32d2e06f4c33.htm

Built-in parameters: BuiltInParameter.ToString() returns valid enum.
User-created parameters: BuiltInParameter.ToString() returns "INVALID".
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from Autodesk.Revit import DB # pyright: ignore
from EnneadTab.REVIT import REVIT_APPLICATION


class FamilyDataExtractor:
    """Extracts family hierarchy, parameters, and associations."""
    
    def __init__(self, progress_callback=None):
        self.nodes = []
        self.links = []
        self.docs_to_close = []
        self.node_id_counter = 0
        self.node_map = {}  # Maps family doc title to node id
        self.progress_callback = progress_callback  # Callback to report progress
        
    def extract_family_tree(self, root_doc):
        """Main entry point - traverse family tree recursively.
        
        Args:
            root_doc: Root Revit family document
            
        Returns:
            dict: Tree data with nodes and links
        """
        self._extract_family_node(root_doc, parent_id=None, depth=0)
        
        return {
            "rootFamily": root_doc.Title,
            "nodes": self.nodes,
            "links": self.links
        }
    
    def _extract_family_node(self, family_doc, parent_id=None, depth=0, parent_doc=None, nested_family_obj=None):
        """Extract single family node with all its data.
        
        Args:
            family_doc: Revit family document
            parent_id: Parent node ID (None for root)
            depth: Nesting depth
            parent_doc: Parent family document (for instance counting)
            nested_family_obj: The Family object in parent (for instance counting)
            
        Returns:
            str: Node ID
        """
        # Check depth limit to prevent infinite recursion
        if depth > 20:
            return None
            
        node_id = "node_{}".format(self.node_id_counter)
        self.node_id_counter += 1
        
        # Get family category
        try:
            category_name = family_doc.OwnerFamily.FamilyCategory.Name if family_doc.OwnerFamily else "Unknown"
        except:
            category_name = "Unknown"
        
        # Check if CURRENT family is shared (can be scheduled/tagged)
        # Uses FAMILY_SHARED built-in parameter (pattern from REVIT_FAMILY.py)
        is_shared = False
        try:
            # For family document: check OwnerFamily (represents the family being edited)
            if family_doc.OwnerFamily:
                shared_param = family_doc.OwnerFamily.get_Parameter(DB.BuiltInParameter.FAMILY_SHARED)
                if shared_param:
                    is_shared = shared_param.AsInteger() == 1
            
            # Alternative: If opened from parent, also check from parent's Family object
            # This ensures we get the shared status from the actual Family element
            if not is_shared and parent_doc and nested_family_obj:
                shared_param = nested_family_obj.get_Parameter(DB.BuiltInParameter.FAMILY_SHARED)
                if shared_param:
                    is_shared = shared_param.AsInteger() == 1
        except:
            # Fallback: try to get from FamilySymbol
            try:
                symbols = list(DB.FilteredElementCollector(family_doc).OfClass(DB.FamilySymbol).ToElements())
                if symbols:
                    # Check the family that owns this symbol
                    symbol = symbols[0]
                    if symbol.Family:
                        shared_param = symbol.Family.get_Parameter(DB.BuiltInParameter.FAMILY_SHARED)
                        if shared_param:
                            is_shared = shared_param.AsInteger() == 1
            except:
                pass
        
        # Extract subcategories/object styles
        subcategories = self._extract_subcategories(family_doc)
        
        # Extract preview images for ALL family types
        preview_images_dict = self._extract_preview_image(family_doc)
        
        # Extract document units
        unit_info = self._extract_document_units(family_doc)
        
        # Extract creator and last editor info (if in workshared project context)
        ownership_info = self._extract_ownership_info(parent_doc, nested_family_obj) if parent_doc and nested_family_obj else None
        
        # Check if family is purgeable (no instances) using proper Revit API method
        instance_count = 0
        is_purgeable = False
        
        if parent_doc is not None and nested_family_obj is not None:
            try:
                # Get all family instances in parent document
                all_instances = DB.FilteredElementCollector(parent_doc).OfClass(DB.FamilyInstance).ToElements()
                
                # Count instances of this specific nested family (use shared helper for ElementId)
                nested_family_id = REVIT_APPLICATION.get_element_id_value(nested_family_obj.Id)
                instance_count = 0
                
                for inst in all_instances:
                    try:
                        if inst.Symbol and inst.Symbol.Family:
                            if REVIT_APPLICATION.get_element_id_value(inst.Symbol.Family.Id) == nested_family_id:
                                instance_count += 1
                    except:
                        continue
                
                # Family is purgeable if it has 0 instances and is not a system family
                is_purgeable = (instance_count == 0 and 
                               not nested_family_obj.IsInPlace and 
                               not getattr(nested_family_obj, 'IsSystemFamily', False))
            except:
                instance_count = 0
                is_purgeable = False
        
        # Extract all parameters
        parameters = self._extract_all_parameters(family_doc)
        
        # Analyze parameter usage
        self._analyze_parameter_usage(family_doc, parameters)
        
        # Create node
        node = {
            "id": node_id,
            "name": family_doc.Title,
            "category": category_name,
            "isEditable": True,
            "isShared": is_shared,
            "subcategories": subcategories,
            "previewImages": preview_images_dict,
            "instanceCount": instance_count,
            "isPurgeable": is_purgeable,
            "depth": depth,
            "typeCount": family_doc.FamilyManager.Types.Size,
            "units": unit_info,
            "ownership": ownership_info,
            "parameters": parameters
        }
        
        self.nodes.append(node)
        self.node_map[family_doc.Title] = node_id
        
        # Create link from parent
        if parent_id is not None:
            link = {
                "source": parent_id,
                "target": node_id,
                "parameterCount": 0,
                "associatedParameters": []
            }
            self.links.append(link)
        
        # Process nested families
        nested_families = list(DB.FilteredElementCollector(family_doc).OfClass(DB.Family).ToElements())
        nested_families.sort(key=lambda x: x.FamilyCategory.Name + "_" + x.Name)
        
        for nested_family in nested_families:
            # Skip system families
            if nested_family.FamilyCategory.Name in ["Section Marks", "Level Heads"]:
                continue
                
            if not nested_family.IsEditable:
                continue
                
            try:
                nested_family_doc = family_doc.EditFamily(nested_family)
                self.docs_to_close.append(nested_family_doc)
                
                # Extract parameter associations before recursing
                associations = self._extract_parameter_associations(family_doc, nested_family, nested_family_doc)
                
                # Recurse into nested family (pass parent_doc and nested_family for instance counting)
                nested_node_id = self._extract_family_node(
                    nested_family_doc, 
                    parent_id=node_id, 
                    depth=depth + 1,
                    parent_doc=family_doc,
                    nested_family_obj=nested_family
                )
                
                # Update link with association info
                if nested_node_id:
                    for link in self.links:
                        if link["source"] == node_id and link["target"] == nested_node_id:
                            link["parameterCount"] = len(associations)
                            link["associatedParameters"] = [assoc["parentParameter"] for assoc in associations]
                            break
                    
                    # Add associations to parent parameters
                    for param in node["parameters"]:
                        param_associations = [assoc for assoc in associations if assoc["parentParameter"] == param["name"]]
                        if param_associations:
                            if "associations" not in param:
                                param["associations"] = []
                            for assoc in param_associations:
                                param["associations"].append({
                                    "targetNodeId": nested_node_id,
                                    "targetFamilyName": nested_family_doc.Title,
                                    "targetParameter": assoc["nestedParameter"]
                                })
            except Exception:
                # Skip families that cannot be opened
                pass
        
        return node_id
    
    def _extract_all_parameters(self, family_doc):
        """Get ALL parameters (built-in, shared, project) from family.
        
        Args:
            family_doc: Revit family document
            
        Returns:
            list: List of parameter dictionaries
        """
        parameters = []
        param_names_seen = set()
        
        # Get parameters from FamilyManager
        for family_param in family_doc.FamilyManager.Parameters:
            param_name = family_param.Definition.Name
            
            # Skip duplicates
            if param_name in param_names_seen:
                continue
            param_names_seen.add(param_name)
            
            # Extract parameter info
            # Get storage type from the parameter's definition
            storage_type_str = self._get_storage_type_from_family_param(family_param)
            
            # Get parameter group
            param_group = self._get_parameter_group_name(family_param)
            
            # Check if this is a material parameter
            is_material_param = self._is_material_parameter(family_param)
            
            # Check if this is a built-in parameter
            # FamilyManager parameters CAN be built-in (like Width, Height, etc.)
            built_in_param = None
            try:
                # Try to get BuiltInParameter from the definition
                bip_value = family_param.Definition.BuiltInParameter.ToString()
                # "INVALID" means it's NOT a built-in parameter - it's user-created
                if bip_value and bip_value != "INVALID":
                    built_in_param = bip_value
            except:
                # Not a built-in parameter - it's user-created
                pass
            
            param_info = {
                "name": param_name,
                "isInstance": family_param.IsInstance,
                "isReadOnly": family_param.IsReadOnly,
                "storageType": storage_type_str,
                "builtInParameter": built_in_param,
                "parameterGroup": param_group,
                "isMaterial": is_material_param,
                "formula": family_param.Formula if family_param.Formula else None,
                "values": self._extract_parameter_values_across_types(family_doc, family_param),
                "associations": []
            }
            
            parameters.append(param_info)
        
        # Also get built-in parameters from element instances
        try:
            elements = list(DB.FilteredElementCollector(family_doc).WhereElementIsNotElementType().ToElements())
            if elements:
                sample_element = elements[0]
                for param in sample_element.Parameters:
                    param_name = param.Definition.Name
                    
                    # Skip if already seen
                    if param_name in param_names_seen:
                        continue
                    param_names_seen.add(param_name)
                    
                    # Get built-in parameter enum
                    built_in_param = None
                    try:
                        bip_value = param.Definition.BuiltInParameter.ToString()
                        # "INVALID" means it's NOT a built-in parameter - it's user-created
                        if bip_value and bip_value != "INVALID":
                            built_in_param = bip_value
                    except:
                        pass
                    
                    # Get parameter group for built-in parameters
                    param_group = self._get_builtin_parameter_group_name(param)
                    
                    # Get storage type with proper Boolean/YesNo detection
                    storage_type_str = self._get_builtin_storage_type_with_bool_detection(param)
                    
                    param_info = {
                        "name": param_name,
                        "isInstance": True,  # Most built-in params are instance
                        "isReadOnly": param.IsReadOnly,
                        "storageType": storage_type_str,
                        "builtInParameter": built_in_param,
                        "parameterGroup": param_group,
                        "formula": None,
                        "values": self._get_parameter_value_string(param),
                        "associations": []
                    }
                    
                    parameters.append(param_info)
        except:
            pass
        
        return parameters
    
    def _extract_parameter_values_across_types(self, family_doc, family_param):
        """Get parameter values for all family types.
        
        For material parameters, extracts the material name if available.
        
        Args:
            family_doc: Revit family document
            family_param: FamilyParameter object
            
        Returns:
            dict: Dictionary mapping type name to value string
        """
        values = {}
        is_material = self._is_material_parameter(family_param)
        
        for family_type in family_doc.FamilyManager.Types:
            type_name = family_type.Name
            
            # Get value for this type
            try:
                family_doc.FamilyManager.CurrentType = family_type
                value = family_doc.FamilyManager.Get(family_param)
                
                # For material parameters, get the material name
                if is_material and isinstance(value, DB.ElementId) and REVIT_APPLICATION.get_element_id_value(value) > 0:
                    try:
                        material = family_doc.GetElement(value)
                        if material:
                            value_string = "{} (Material)".format(material.Name)
                        else:
                            value_string = "Element ID: {}".format(REVIT_APPLICATION.get_element_id_value(value))
                    except:
                        value_string = "Element ID: {}".format(REVIT_APPLICATION.get_element_id_value(value))
                else:
                    value_string = self._format_parameter_value(value, family_param)
                
                values[type_name] = value_string
            except:
                values[type_name] = "N/A"
        
        return values
    
    def _extract_parameter_associations(self, parent_doc, nested_family, nested_family_doc):
        """Extract parameter mappings between parent and nested family.
        
        Args:
            parent_doc: Parent family document
            nested_family: Nested Family object
            nested_family_doc: Nested family document
            
        Returns:
            list: List of association dictionaries
        """
        associations = []
        
        # Find instances of the nested family in parent document
        nested_instances = list(
            DB.FilteredElementCollector(parent_doc)
            .OfClass(DB.FamilyInstance)
            .ToElements()
        )
        
        # Filter to instances of this specific nested family
        nested_instances = [inst for inst in nested_instances if inst.Symbol.Family.Id == nested_family.Id]
        
        if not nested_instances:
            return associations
        
        # Use first instance to check associations
        nested_instance = nested_instances[0]
        
        # Check each parent parameter for associations
        for parent_param in parent_doc.FamilyManager.Parameters:
            try:
                # Get associated parameter in nested family
                associated_param = parent_doc.FamilyManager.GetAssociatedFamilyParameter(
                    nested_instance,
                    parent_param
                )
                
                if associated_param is not None:
                    assoc = {
                        "parentParameter": parent_param.Definition.Name,
                        "nestedParameter": associated_param.Definition.Name
                    }
                    associations.append(assoc)
            except Exception:
                # No association or error
                pass
        
        return associations
    
    def _get_storage_type_from_family_param(self, family_param):
        """Get storage type from FamilyParameter with fallback handling.
        
        Uses try/except pattern similar to batch_family_para_creation for robustness.
        Boolean parameters are properly identified as YesNo, with Integer fallback.
        
        Args:
            family_param: FamilyParameter object
            
        Returns:
            str: Storage type string (e.g., "String", "Double", "Integer", "Boolean", "ElementId")
        """
        try:
            # Get the SpecTypeId (newer API)
            spec_type_id = family_param.Definition.GetDataType()
            
            # Check against known SpecTypeId values
            # Boolean types (YesNo) - prioritized
            try:
                if spec_type_id == DB.SpecTypeId.Boolean.YesNo:
                    return "Boolean (Yes/No)"
            except:
                pass
            
            # Text types
            try:
                if spec_type_id == DB.SpecTypeId.String.Text:
                    return "String (Text)"
                elif spec_type_id == DB.SpecTypeId.String.MultilineText:
                    return "String (Multiline)"
            except:
                pass
            
            # Integer types
            try:
                if spec_type_id == DB.SpecTypeId.Int.Integer:
                    return "Integer"
            except:
                pass
            
            # Numeric types
            try:
                if spec_type_id == DB.SpecTypeId.Number:
                    return "Double (Number)"
            except:
                pass
            
            # Length and dimensional types
            try:
                if spec_type_id == DB.SpecTypeId.Length:
                    return "Double (Length)"
                elif spec_type_id == DB.SpecTypeId.Area:
                    return "Double (Area)"
                elif spec_type_id == DB.SpecTypeId.Volume:
                    return "Double (Volume)"
                elif spec_type_id == DB.SpecTypeId.Angle:
                    return "Double (Angle)"
            except:
                pass
            
            # Material type (Reference.Material)
            try:
                if spec_type_id == DB.SpecTypeId.Reference.Material:
                    return "ElementId (Material)"
            except:
                pass
            
            # Fallback: Parse from string representation
            type_str = str(spec_type_id)
            
            # Common patterns with priority for Boolean/YesNo
            if "Boolean" in type_str or "YesNo" in type_str:
                return "Boolean (Yes/No)"
            elif "Material" in type_str:
                return "ElementId (Material)"
            elif "String" in type_str or "Text" in type_str:
                return "String"
            elif "Integer" in type_str or "Int." in type_str:
                return "Integer"
            elif "Length" in type_str:
                return "Double (Length)"
            elif "Area" in type_str:
                return "Double (Area)"
            elif "Volume" in type_str:
                return "Double (Volume)"
            elif "Angle" in type_str:
                return "Double (Angle)"
            elif "Number" in type_str or "Currency" in type_str:
                return "Double"
            elif "Image" in type_str:
                return "ElementId"
            else:
                # Return the actual SpecTypeId for debugging
                parts = type_str.split(".")
                if len(parts) > 1:
                    return parts[-1]
                return type_str if len(type_str) < 40 else "Unknown"
                
        except Exception:
            # Final fallback: try to infer from old API
            try:
                # Older API fallback (DB.ParameterType)
                if hasattr(family_param.Definition, 'ParameterType'):
                    param_type = family_param.Definition.ParameterType
                    if param_type == DB.ParameterType.YesNo:
                        return "Boolean (Yes/No)"
                    elif param_type == DB.ParameterType.Integer:
                        return "Integer"
                    elif param_type == DB.ParameterType.Text:
                        return "String"
                    elif param_type == DB.ParameterType.Length:
                        return "Double (Length)"
            except:
                pass
            
            return "Unknown"
    
    def _get_storage_type_string(self, spec_type_id):
        """Convert SpecTypeId to readable string.
        
        Args:
            spec_type_id: Revit SpecTypeId
            
        Returns:
            str: Storage type string
        """
        try:
            type_str = str(spec_type_id)
            
            # Parse common types
            if "Boolean" in type_str or "YesNo" in type_str:
                return "Boolean"
            elif "String" in type_str or "Text" in type_str:
                return "String"
            elif "Integer" in type_str:
                return "Integer"
            elif "Length" in type_str or "Double" in type_str or "Number" in type_str:
                return "Double"
            elif "ElementId" in type_str:
                return "ElementId"
            else:
                return "Unknown"
        except:
            return "Unknown"
    
    def _get_storage_type_string_from_storage_type(self, storage_type):
        """Convert DB.StorageType to readable string with boolean detection.
        
        Note: Boolean/YesNo parameters are stored as Integer (0 or 1) in Revit.
        This method returns "Integer" which may represent either true Integer 
        parameters or Boolean parameters. Use parameter type checking for accuracy.
        
        Args:
            storage_type: DB.StorageType enum
            
        Returns:
            str: Storage type string
        """
        if storage_type == DB.StorageType.String:
            return "String"
        elif storage_type == DB.StorageType.Integer:
            # Note: Boolean/YesNo parameters are stored as Integer
            return "Integer"
        elif storage_type == DB.StorageType.Double:
            return "Double"
        elif storage_type == DB.StorageType.ElementId:
            return "ElementId"
        else:
            return "None"
    
    def _get_builtin_storage_type_with_bool_detection(self, param):
        """Get storage type for built-in parameter with proper Boolean/YesNo detection.
        
        YesNo parameters are stored as Integer in Revit, but we detect and label them properly.
        Follows codebase pattern from template_data_collector.py
        
        Args:
            param: Parameter object
            
        Returns:
            str: Storage type string with proper Boolean identification
        """
        # First check if it's a YesNo parameter (stored as Integer but actually Boolean)
        try:
            # Try newer API first
            if hasattr(param.Definition, 'GetDataType'):
                spec_type_id = param.Definition.GetDataType()
                if spec_type_id == DB.SpecTypeId.Boolean.YesNo:
                    return "Boolean (Yes/No)"
        except:
            pass
        
        # Try older API
        try:
            if hasattr(param.Definition, 'ParameterType'):
                if param.Definition.ParameterType == DB.ParameterType.YesNo:
                    return "Boolean (Yes/No)"
        except:
            pass
        
        # If not Boolean, return standard storage type
        return self._get_storage_type_string_from_storage_type(param.StorageType)
    
    def _format_parameter_value(self, value, family_param):
        """Format parameter value as string.
        
        Args:
            value: Parameter value
            family_param: FamilyParameter object
            
        Returns:
            str: Formatted value string
        """
        if value is None:
            return "None"
        
        try:
            # Check if it's a length parameter that should be formatted
            if isinstance(value, float):
                # Try to format as length if it's a length parameter
                try:
                    return "{:.3f}".format(value)
                except:
                    return str(value)
            else:
                return str(value)
        except:
            return "N/A"
    
    def _get_parameter_value_string(self, param):
        """Get parameter value as string.
        
        Args:
            param: Parameter object
            
        Returns:
            dict or str: Single value or dict of values
        """
        try:
            if param.StorageType == DB.StorageType.String:
                return {"Current": param.AsString() or ""}
            elif param.StorageType == DB.StorageType.Integer:
                return {"Current": str(param.AsInteger())}
            elif param.StorageType == DB.StorageType.Double:
                return {"Current": "{:.3f}".format(param.AsDouble())}
            elif param.StorageType == DB.StorageType.ElementId:
                return {"Current": str(param.AsElementId())}
            else:
                return {"Current": param.AsValueString() or "N/A"}
        except:
            return {"Current": "N/A"}
    
    def _analyze_parameter_usage(self, family_doc, parameters):
        """Analyze how each parameter is being used in the family.
        
        Checks:
        - If used in formulas (by other parameters)
        - If used in labels
        - If used in associations (already tracked)
        
        NOTE: Only analyzes user-created parameters. Built-in parameters are excluded
        from "unused" warnings as they are managed by Revit.
        
        Args:
            family_doc: Revit family document
            parameters: List of parameter dictionaries
        """
        # Build a set of all parameter names for quick lookup
        param_names = set(p["name"] for p in parameters)
        
        # Track which parameters are used
        used_in_formulas = set()
        used_in_labels = set()
        
        # Check formulas - see which parameters are referenced
        for param in parameters:
            if param["formula"]:
                formula = param["formula"]
                # Check if any other parameter names appear in this formula
                for other_param_name in param_names:
                    if other_param_name != param["name"]:
                        # Simple check: is parameter name mentioned in formula?
                        # This catches most cases like "Width / 2" referencing "Width"
                        if other_param_name in formula:
                            used_in_formulas.add(other_param_name)
        
        # Check labels
        try:
            labels = list(DB.FilteredElementCollector(family_doc).OfClass(DB.TextNote).ToElements())
            for label in labels:
                label_text = label.Text if hasattr(label, 'Text') else ""
                # Check if parameter is used in label (format: <Parameter Name>)
                for param_name in param_names:
                    if "<{}>".format(param_name) in label_text or "{{{0}}}".format(param_name) in label_text:
                        used_in_labels.add(param_name)
        except:
            pass
        
        # Update parameters with usage info
        for param in parameters:
            # Check if this is a built-in parameter (managed by Revit)
            is_builtin = param.get("builtInParameter") is not None
            
            usage = []
            
            # Treat a parameter that HAS its own formula as "used"
            # even if nothing else references it.
            if param.get("formula"):
                usage.append("HasFormula")

            if param["name"] in used_in_formulas:
                usage.append("Formula")
            
            if param["name"] in used_in_labels:
                usage.append("Label")
            
            if param.get("associations") and len(param["associations"]) > 0:
                usage.append("Associated")
            
            # Only mark USER-CREATED parameters as unused
            # Built-in parameters are excluded from usage monitoring
            if is_builtin:
                param["isUsed"] = True  # Always mark built-in as "used"
                param["usedIn"] = ["Built-In"]  # Special marker for built-in params
            else:
                # User-created parameter - check if actually used
                param["isUsed"] = len(usage) > 0
                param["usedIn"] = usage if usage else ["Unused"]
    
    def _is_material_parameter(self, family_param):
        """Check if a family parameter is a material parameter.
        
        Material parameters have SpecTypeId.Reference.Material as their data type.
        
        Args:
            family_param: FamilyParameter object
            
        Returns:
            bool: True if this is a material parameter
        """
        try:
            # Try newer API first
            try:
                spec_type_id = family_param.Definition.GetDataType()
                if spec_type_id == DB.SpecTypeId.Reference.Material:
                    return True
            except:
                pass
            
            # Try older API
            try:
                if hasattr(family_param.Definition, 'ParameterType'):
                    if family_param.Definition.ParameterType == DB.ParameterType.Material:
                        return True
            except:
                pass
            
            return False
        except:
            return False
    
    def _get_parameter_group_name(self, family_param):
        """Get readable parameter group name from FamilyParameter.
        
        Args:
            family_param: FamilyParameter object
            
        Returns:
            str: Parameter group name (e.g., "Dimensions", "Identity Data")
        """
        try:
            # Try to get ParameterGroup (older API)
            try:
                param_group = family_param.Definition.ParameterGroup
                group_str = str(param_group)
                
                # Clean up the group name
                # Remove "PG_" prefix if present
                if group_str.startswith("PG_"):
                    group_str = group_str[3:]
                
                # Convert UPPER_CASE_WITH_UNDERSCORES to Title Case
                group_str = group_str.replace("_", " ").title()
                
                return group_str
            except:
                # Try newer API with GroupTypeId
                try:
                    param_group_id = family_param.Definition.GetGroupTypeId()
                    group_str = DB.LabelUtils.GetLabelForGroup(param_group_id)
                    return group_str
                except:
                    pass
            
            return "General"
        except:
            return "General"
    
    def _get_builtin_parameter_group_name(self, param):
        """Get readable parameter group name from built-in Parameter.
        
        Args:
            param: Parameter object
            
        Returns:
            str: Parameter group name (e.g., "Dimensions", "Identity Data")
        """
        try:
            # Try to get ParameterGroup
            try:
                param_group = param.Definition.ParameterGroup
                group_str = str(param_group)
                
                # Clean up the group name
                if group_str.startswith("PG_"):
                    group_str = group_str[3:]
                
                # Convert UPPER_CASE_WITH_UNDERSCORES to Title Case
                group_str = group_str.replace("_", " ").title()
                
                return group_str
            except:
                # Try newer API
                try:
                    param_group_id = param.Definition.GetGroupTypeId()
                    group_str = DB.LabelUtils.GetLabelForGroup(param_group_id)
                    return group_str
                except:
                    pass
            
            return "General"
        except:
            return "General"
    
    def _extract_subcategories(self, family_doc):
        """Extract subcategories/object styles from family document.
        
        Args:
            family_doc: Revit family document
            
        Returns:
            list: List of subcategory names
        """
        subcategories = []
        
        try:
            # Get main category
            if family_doc.OwnerFamily and family_doc.OwnerFamily.FamilyCategory:
                main_category = family_doc.OwnerFamily.FamilyCategory
                
                # Get all subcategories
                for subcat in main_category.SubCategories:
                    subcategories.append(subcat.Name)
        except:
            pass
        
        return subcategories
    
    def _extract_preview_image(self, family_doc):
        """Extract preview images for ALL family types/symbols.
        
        Uses FamilySymbol (ElementType) to get preview image, not FamilyType.
        FamilyType (from FamilyManager) doesn't have GetPreviewImage method.
        
        Args:
            family_doc: Revit family document
            
        Returns:
            dict: Dictionary mapping type name to base64 image string, or empty dict if fails
        """
        try:
            import System # pyright: ignore
            from System.IO import MemoryStream # pyright: ignore
            from System.Drawing.Imaging import ImageFormat # pyright: ignore
            
            # Get ALL FamilySymbols from the document
            family_symbols = list(
                DB.FilteredElementCollector(family_doc)
                .OfClass(DB.FamilySymbol)
                .ToElements()
            )
            
            if not family_symbols:
                return {}
            
            # Extract preview for EACH symbol/type
            preview_images = {}
            
            for family_symbol in family_symbols:
                try:
                    type_name = family_symbol.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
                    if not type_name:
                        type_name = family_symbol.Name
                    
                    # Get preview image using correct API
                    preview_image = None
                    try:
                        # Try with ImageSize object
                        image_size = DB.ImageSize(256, 256)
                        preview_image = family_symbol.GetPreviewImage(image_size)
                    except:
                        # Fallback: try with System.Drawing.Size
                        try:
                            from System.Drawing import Size # pyright: ignore
                            image_size = Size(256, 256)
                            preview_image = family_symbol.GetPreviewImage(image_size)
                        except:
                            pass
                    
                    if preview_image is not None:
                        # Convert System.Drawing.Bitmap to base64
                        ms = MemoryStream()
                        preview_image.Save(ms, ImageFormat.Png)
                        image_bytes = ms.ToArray()
                        ms.Dispose()
                        
                        # Encode to base64
                        base64_string = System.Convert.ToBase64String(image_bytes)
                        preview_images[type_name] = "data:image/png;base64," + base64_string
                        
                except Exception:
                    # Skip this symbol if extraction fails
                    continue
            
            return preview_images
            
        except Exception:
            # If preview extraction fails, return empty dict
            return {}
    
    def _extract_ownership_info(self, parent_doc, family_obj):
        """Extract creator and last editor information from worksharing data.
        
        Uses WorksharingUtils.GetWorksharingTooltipInfo to get creator and last editor.
        Based on pattern from health_metric/families_checks.py
        
        Args:
            parent_doc: Parent document (must be workshared)
            family_obj: Family object to get info for
            
        Returns:
            dict: Ownership info with creator and lastEditedBy, or None if not available
        """
        try:
            # Check if document is workshared
            if not parent_doc or not hasattr(parent_doc, 'IsWorkshared') or not parent_doc.IsWorkshared:
                return None
            
            # Get worksharing tooltip info
            info = DB.WorksharingUtils.GetWorksharingTooltipInfo(parent_doc, family_obj.Id)
            
            if info:
                creator = info.Creator if info.Creator else "Unknown"
                last_editor = info.LastChangedBy if info.LastChangedBy else "Unknown"
                
                return {
                    "creator": creator,
                    "lastEditedBy": last_editor
                }
            
            return None
            
        except Exception:
            # Worksharing info not available
            return None
    
    def _extract_document_units(self, family_doc):
        """Extract document unit information from family document.
        
        Returns length unit (feet, inches, millimeters, meters, etc.)
        
        Args:
            family_doc: Revit family document
            
        Returns:
            dict: Unit information with length unit name and display format
        """
        try:
            # Get document units
            units = family_doc.GetUnits()
            
            # Get length format options
            try:
                # Try newer API (Revit 2021+)
                format_options = units.GetFormatOptions(DB.SpecTypeId.Length)
                unit_type_id = format_options.GetUnitTypeId()
                
                # Parse unit name from TypeId
                type_id_str = str(unit_type_id.TypeId)
                parts = type_id_str.split("-")
                if len(parts) > 0:
                    first_part = parts[0]
                    unit_parts = first_part.split("unit:")
                    if len(unit_parts) > 1:
                        unit_name = unit_parts[1]
                        
                        # Clean up unit name for display
                        unit_display = unit_name.replace("_", " ").title()
                        
                        # Get accuracy (decimal places)
                        try:
                            accuracy = format_options.Accuracy
                        except:
                            accuracy = 0.01
                        
                        return {
                            "lengthUnit": unit_name,
                            "lengthUnitDisplay": unit_display,
                            "accuracy": str(accuracy)
                        }
            except:
                # Try older API (pre-2021)
                try:
                    format_options = units.GetFormatOptions(DB.UnitType.UT_Length)
                    display_unit = format_options.DisplayUnits
                    unit_str = str(display_unit).replace("DUT_", "").lower()
                    
                    # Clean up unit name
                    unit_display = unit_str.replace("_", " ").title()
                    
                    return {
                        "lengthUnit": unit_str,
                        "lengthUnitDisplay": unit_display,
                        "accuracy": "N/A"
                    }
                except:
                    pass
            
            # Fallback
            return {
                "lengthUnit": "unknown",
                "lengthUnitDisplay": "Unknown",
                "accuracy": "N/A"
            }
            
        except Exception:
            return {
                "lengthUnit": "unknown",
                "lengthUnitDisplay": "Unknown",
                "accuracy": "N/A"
            }
    
    def cleanup_documents(self):
        """Close all opened family documents."""
        for family_doc in self.docs_to_close:
            try:
                family_doc.Close(False)
            except:
                pass
        self.docs_to_close = []


if __name__ == "__main__":
    pass