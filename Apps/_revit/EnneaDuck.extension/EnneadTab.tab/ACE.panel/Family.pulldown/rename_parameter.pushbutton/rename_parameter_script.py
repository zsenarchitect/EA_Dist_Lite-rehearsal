#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = """Rename family parameters without losing the values already set in the project.

Renaming a parameter by hand normally wipes whatever every instance had in it. This
carries the values across, so schedules, tags, and filters keep reading the same
numbers under the new name.

Features:
- Rename several parameters in one pass from a single dialog
- The dialog stays open so you can keep working in the model beside it
- Values are read back and re-applied after the rename

Usage:
1. Run the button and pick the family to work on
2. Type the new name beside each parameter you want changed
3. Apply, and check the values survived in a schedule"""
__title__ = "Rename\nParameters"
__persistentengine__ = True

import os
import traceback

from Autodesk.Revit import DB, UI  # pyright: ignore
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent  # pyright: ignore
from Autodesk.Revit.Exceptions import InvalidOperationException  # pyright: ignore
from pyrevit import script
from pyrevit.forms import WPFWindow
import proDUCKtion  # pyright: ignore

proDUCKtion.validify()

from EnneadTab import ENVIRONMENT, ERROR_HANDLE, LOG, NOTIFICATION
from EnneadTab.REVIT import REVIT_APPLICATION, REVIT_FAMILY, REVIT_SELECTION, REVIT_PARAMETER, REVIT_UNIT

DOC = REVIT_APPLICATION.get_doc()
UIDOC = REVIT_APPLICATION.get_uidoc()

class SimpleEventHandler(IExternalEventHandler):
    """Generic external event handler wrapper."""

    def __init__(self, do_this):
        self.do_this = do_this
        self.kwargs = tuple()
        self.OUT = None

    def Execute(self, uiapp):
        try:
            try:
                self.OUT = self.do_this(*self.kwargs)
            except Exception:
                pass
        except InvalidOperationException:
            pass

    def GetName(self):
        return "EnneadTab Family Parameter Rename Handler"


class ParameterRenameItem(object):
    """Stores metadata required for renaming a parameter."""

    def __init__(self, name, is_instance, can_rename, reason, group_enum, group_type_id, data_type, spec_type, storage_type, data_type_id):
        self.original_name = name
        self.is_instance = is_instance
        self.can_rename = can_rename
        self.reason = reason
        self.group_enum = group_enum
        self.group_type_id = group_type_id
        self.data_type = data_type
        self.spec_type = spec_type
        self.storage_type = storage_type
        self.data_type_id = data_type_id
        self.new_name = ""
        self.metadata_text = ""


class RenameParameterForm(WPFWindow):
    """Modeless window for collecting rename instructions."""

    def __init__(self, controller, parameter_items):
        self.controller = controller
        self.parameter_items = parameter_items
        self.row_controls = []

        xaml_path = os.path.join(os.path.dirname(__file__), "rename_parameter_ModelessForm.xaml")
        WPFWindow.__init__(self, xaml_path)

        self.Title = "{} - {}".format(ENVIRONMENT.PLUGIN_NAME, controller.target_title)
        self.header_text.Text = "Rename parameters for [{}]".format(controller.target_title)
        self.sub_text.Text = "Leave a field blank to skip renaming. Locked parameters explain why they are disabled."
        editable_count = len([x for x in parameter_items if x.can_rename])
        locked_count = len(parameter_items) - editable_count
        self.set_image_source(self.logo_img, os.path.join(ENVIRONMENT.IMAGE_FOLDER, "logo_vertical_light.png"))
        self.status_text.Text = "Ready to rename {} parameter(s). Locked: {}. Values are preserved via duplicate/load workflow.".format(editable_count, locked_count)

        self.populate_table()
        self.Show()

    def populate_table(self):
        table_panel = self.table_panel
        table_panel.Children.Clear()

        System = __import__("System")  # late import to avoid IronPython issues
        Thickness = System.Windows.Thickness
        Grid = System.Windows.Controls.Grid
        TextBlock = System.Windows.Controls.TextBlock
        TextBox = System.Windows.Controls.TextBox
        ColumnDefinition = System.Windows.Controls.ColumnDefinition
        Brushes = System.Windows.Media.Brushes

        header_row = Grid()
        header_row.ColumnDefinitions.Add(ColumnDefinition())
        header_row.ColumnDefinitions.Add(ColumnDefinition())
        header_row.ColumnDefinitions.Add(ColumnDefinition())

        name_header = TextBlock()
        name_header.Text = "Current Name"
        name_header.FontWeight = System.Windows.FontWeights.Bold
        name_header.Margin = Thickness(4, 2, 4, 2)
        header_row.Children.Add(name_header)

        info_header = TextBlock()
        info_header.Text = "Type Info"
        info_header.FontWeight = System.Windows.FontWeights.Bold
        info_header.Margin = Thickness(4, 2, 4, 2)
        Grid.SetColumn(info_header, 1)
        header_row.Children.Add(info_header)

        new_header = TextBlock()
        new_header.Text = "New Name"
        new_header.FontWeight = System.Windows.FontWeights.Bold
        new_header.Margin = Thickness(4, 2, 4, 2)
        Grid.SetColumn(new_header, 2)
        header_row.Children.Add(new_header)

        table_panel.Children.Add(header_row)

        for item in self.parameter_items:
            row_grid = Grid()
            row_grid.ColumnDefinitions.Add(ColumnDefinition())
            row_grid.ColumnDefinitions.Add(ColumnDefinition())
            row_grid.ColumnDefinitions.Add(ColumnDefinition())

            name_block = TextBlock()
            name_block.Text = item.original_name
            name_block.Margin = Thickness(4, 2, 4, 2)
            name_block.FontSize = 14
            name_block.FontWeight = System.Windows.FontWeights.SemiBold
            name_block.Foreground = Brushes.White
            if item.reason:
                name_block.ToolTip = item.reason
            row_grid.Children.Add(name_block)

            info_block = TextBlock()
            info_block.Text = item.metadata_text or ""
            info_block.Margin = Thickness(4, 2, 4, 2)
            info_block.TextWrapping = System.Windows.TextWrapping.Wrap
            info_block.FontSize = 12
            info_block.Opacity = 0.85
            info_block.Foreground = Brushes.White
            Grid.SetColumn(info_block, 1)
            row_grid.Children.Add(info_block)

            name_box = TextBox()
            name_box.Margin = Thickness(4, 2, 4, 2)
            if item.can_rename:
                name_box.Text = ""
            else:
                name_box.Text = "Locked"
                name_box.IsEnabled = False
                if item.reason:
                    name_box.ToolTip = item.reason
            Grid.SetColumn(name_box, 2)
            row_grid.Children.Add(name_box)

            table_panel.Children.Add(row_grid)
            self.row_controls.append((item, name_box))

    def close_click(self, sender, args):
        self.Close()

    def ok_click(self, sender, args):
        rename_requests = []
        for item, textbox in self.row_controls:
            if not item.can_rename:
                continue
            proposed = textbox.Text or ""
            proposed = proposed.strip()
            if proposed:
                if proposed == item.original_name:
                    continue
                item.new_name = proposed
                rename_requests.append(item)
        self.controller.queue_rename(rename_requests)
        self.Close()

    def mouse_down_main_panel(self, sender, args):
        try:
            self.DragMove()
        except Exception:
            pass


class RenameParameterController(object):
    """Coordinates UI and Revit-side work."""

    def __init__(self):
        self.entry_doc = DOC
        self.target_family = None
        self.target_title = ""
        self.target_family_name = ""
        self.is_family_doc = self.entry_doc.IsFamilyDocument
        self.use_entry_family_doc = False
        self.parameter_items = []
        self.pending_requests = []

        self.event_handler = SimpleEventHandler(self.perform_rename)
        self.ext_event = ExternalEvent.Create(self.event_handler)

        self.output = script.get_output()
        self.output.close_others()

        self._parameter_type_enum = getattr(DB, "ParameterType", None)
        self._built_in_group_enum = getattr(DB, "BuiltInParameterGroup", None)
        self._parameter_type_to_spec = self._build_parameter_type_map()
        self._default_group_type_id = self._resolve_group_type_id("Data")
        self._default_group_enum = self._resolve_builtin_group("PG_DATA")

    def run(self):
        if not self._resolve_target_family():
            return

        if not self._collect_parameters():
            NOTIFICATION.messenger("No parameters available for renaming.")
            return

        RenameParameterForm(self, self.parameter_items)

    def queue_rename(self, rename_requests):
        if not rename_requests:
            NOTIFICATION.messenger("No rename changes were provided.")
            return

        if not self._validate_requests(rename_requests):
            return

        self.pending_requests = rename_requests
        self.event_handler.kwargs = tuple()
        self.ext_event.Raise()

    def _resolve_target_family(self):
        if self.is_family_doc:
            family = self._pick_family_in_family_doc()
            if not family:
                return False
            self.target_family = family
            self.target_title = self.entry_doc.Title if family == getattr(self.entry_doc, "OwnerFamily", None) else family.Name
            self.target_family_name = family.Name
            self.use_entry_family_doc = family == getattr(self.entry_doc, "OwnerFamily", None)
            return True

        selected = REVIT_SELECTION.pick_family(self.entry_doc, multi_select=False)
        if not selected:
            return False

        family = getattr(selected, "item", selected)
        if family.IsInPlace or not family.IsEditable:
            NOTIFICATION.messenger("Selected family is not editable. Please choose another family.")
            return False

        self.target_family = family
        self.target_title = family.Name
        self.target_family_name = family.Name
        self.use_entry_family_doc = False
        return True

    def _pick_family_in_family_doc(self):
        families = self._collect_families_from_doc(self.entry_doc)
        if not families:
            NOTIFICATION.messenger("No families are available in the current family document.")
            return None

        from pyrevit import forms

        class FamilyOption(forms.TemplateListItem):
            def __init__(self, fam):
                self.item = fam

            @property
            def name(self):
                family = self.item
                try:
                    category = family.FamilyCategory
                    if category:
                        return "[{}] {}".format(category.Name, family.Name)
                except Exception:
                    pass
                return family.Name

        options = [FamilyOption(fam) for fam in families]
        options = sorted(options, key=lambda opt: opt.name.lower())
        selected = forms.SelectFromList.show(
            options,
            multiselect=False,
            title="Select family within {}".format(self.entry_doc.Title),
            button_name="Select Family",
            width=800
        )
        if not selected:
            return None
        return getattr(selected, "item", selected)

    def _collect_families_from_doc(self, doc):
        families = []
        owner_family = getattr(doc, "OwnerFamily", None)
        if owner_family is not None:
            families.append(owner_family)
        try:
            collector = DB.FilteredElementCollector(doc).OfClass(DB.Family)
            for fam in collector:
                if owner_family is not None and fam.Id == owner_family.Id:
                    continue
                families.append(fam)
        except Exception:
            pass

        seen_ids = set()
        unique_families = []
        for fam in families:
            try:
                fam_id = REVIT_APPLICATION.get_element_id_value(fam.Id)
            except Exception:
                fam_id = id(fam)
            if fam_id in seen_ids:
                continue
            seen_ids.add(fam_id)
            unique_families.append(fam)
        return unique_families

    def _collect_parameters(self):
        self.parameter_items = []
        self._all_parameter_names = set()

        if self.is_family_doc and self.use_entry_family_doc:
            family_doc = self.entry_doc
            should_close = False
        else:
            try:
                family_doc = self.entry_doc.EditFamily(self.target_family)
            except Exception as err:
                NOTIFICATION.messenger("Unable to open family '{}'.\n{}".format(self.target_title, err))
                self._log_exception("Unable to open family '{}'".format(self.target_title), err)
                return False
            should_close = True

        try:
            fam_manager = family_doc.FamilyManager
            for family_param in fam_manager.Parameters:
                name = family_param.Definition.Name
                self._all_parameter_names.add(name)

                can_rename = True
                reasons = []

                if family_param.IsReadOnly:
                    can_rename = False
                    reasons.append("Read-only parameter")

                built_in = DB.BuiltInParameter.INVALID
                try:
                    built_in = family_param.Definition.BuiltInParameter
                except Exception:
                    pass
                if built_in != DB.BuiltInParameter.INVALID:
                    can_rename = False
                    reasons.append("Built-in parameter")

                if getattr(family_param, "IsShared", False):
                    can_rename = False
                    reasons.append("Shared parameter")

                group_enum = None
                try:
                    group_enum = family_param.Definition.ParameterGroup
                except Exception:
                    group_enum = None

                group_type_id = None
                try:
                    group_type_id = family_param.Definition.GetGroupTypeId()
                except Exception:
                    group_type_id = None

                if group_type_id is None and self._is_valid_group(self._default_group_type_id):
                    group_type_id = self._default_group_type_id
                if group_enum is None and self._default_group_enum is not None:
                    group_enum = self._default_group_enum

                data_type = None
                spec_type = None
                try:
                    data_type = family_param.Definition.ParameterType
                except Exception:
                    data_type = None
                try:
                    temp_spec = family_param.Definition.GetSpecTypeId()
                    if self._is_valid_spec(temp_spec):
                        spec_type = temp_spec
                except Exception:
                    spec_type = None
                data_type_id = None
                try:
                    data_type_id = family_param.Definition.GetDataType()
                except Exception:
                    data_type_id = None

                storage_type = None
                try:
                    storage_type = family_param.StorageType
                except Exception:
                    storage_type = None

                item = ParameterRenameItem(
                    name=name,
                    is_instance=family_param.IsInstance,
                    can_rename=can_rename,
                    reason=", ".join(reasons),
                    group_enum=group_enum,
                    group_type_id=group_type_id,
                    data_type=data_type,
                    spec_type=spec_type,
                    storage_type=storage_type,
                    data_type_id=data_type_id
                )
                item.metadata_text = self._format_parameter_metadata(item)
                self.parameter_items.append(item)
                pass
        finally:
            if not self.is_family_doc and should_close and family_doc:
                try:
                    family_doc.Close(False)
                except Exception:
                    pass

        try:
            self.parameter_items.sort(key=lambda item: (item.original_name or "").lower())
        except Exception:
            pass
        return len(self.parameter_items) > 0

    def _validate_requests(self, rename_requests):
        errors = []
        seen = set()
        invalid_chars = ["\\", "[", "]", "{", "}", "<", ">", "|", "?", ";"]

        existing_names = set(self._all_parameter_names)
        originals = set([item.original_name for item in rename_requests])
        conflicting_targets = existing_names.difference(originals)

        for item in rename_requests:
            new_lower = item.new_name.lower()
            if new_lower in seen:
                errors.append("Duplicate target name '{}' detected.".format(item.new_name))
            seen.add(new_lower)

            for bad_char in invalid_chars:
                if bad_char in item.new_name:
                    errors.append("Name '{}' contains invalid character '{}'".format(item.new_name, bad_char))
                    break

            if item.new_name in conflicting_targets:
                errors.append("Name '{}' already exists in the family.".format(item.new_name))

        if errors:
            NOTIFICATION.messenger("Cannot proceed:\n- " + "\n- ".join(errors), sticky=True)
            return False
        return True

    def perform_rename(self):
        if not self.pending_requests:
            return

        try:
            if self.is_family_doc and self.use_entry_family_doc:
                self._rename_inside_family_doc()
            else:
                self._rename_with_project_loading()
        except Exception as err:
            NOTIFICATION.messenger("Family rename failed. See console for details.")
            ERROR_HANDLE.print_note("Rename failure: {}".format(err))
            self._log_exception("Rename failure", err)
            pass
        else:
            NOTIFICATION.messenger("Completed parameter rename for [{}].".format(self.target_title))
        finally:
                    self.pending_requests = []

    def _rename_inside_family_doc(self):
        family_doc = self.entry_doc
        fam_manager = family_doc.FamilyManager
        self._add_new_parameters(family_doc, fam_manager)
        self._finalize_rename(family_doc, fam_manager)

    def _rename_with_project_loading(self):
        family_ref = self._get_family_reference()
        if not family_ref:
            NOTIFICATION.messenger("Unable to locate family '{}' before rename.".format(self.target_family_name))
            return

        family_doc = self.entry_doc.EditFamily(family_ref)
        fam_manager = family_doc.FamilyManager
        self._add_new_parameters(family_doc, fam_manager)
        REVIT_FAMILY.load_family(family_doc, self.entry_doc)
        family_doc.Close(False)

        family_ref = self._get_family_reference()
        if not family_ref:
            NOTIFICATION.messenger("Unable to reopen family '{}' after loading.".format(self.target_family_name))
            return

        family_doc = self.entry_doc.EditFamily(family_ref)
        fam_manager = family_doc.FamilyManager
        self._finalize_rename(family_doc, fam_manager)
        REVIT_FAMILY.load_family(family_doc, self.entry_doc)
        family_doc.Close(False)

        self.target_family = family_ref

    def _add_new_parameters(self, family_doc, fam_manager):
        transaction = DB.Transaction(family_doc, "Create temporary parameters")
        transaction.Start()

        try:
            for item in self.pending_requests:
                original_param = self._find_parameter(fam_manager, item.original_name)
                if original_param is None:
                    ERROR_HANDLE.print_note("Cannot find parameter '{}'".format(item.original_name))
                    continue

                existing = self._find_parameter(fam_manager, item.new_name)
                if existing is not None:
                    ERROR_HANDLE.print_note("Temporary parameter '{}' already exists. Skipping.".format(item.new_name))
                    continue

                temp_param = self._create_temp_parameter(fam_manager, item)
                if temp_param is None:
                    ERROR_HANDLE.print_note("Failed to create temporary parameter '{}' for rename.".format(item.new_name))
                    continue
                else:
                    pass

                try:
                    fam_manager.SetFormula(temp_param, item.original_name)
                except Exception as err:
                    message = "Failed to set formula on '{}' referencing '{}'".format(item.new_name, item.original_name)
                    ERROR_HANDLE.print_note(message)
                    self._log_exception(message, err)
                    raise
        except Exception:
            transaction.RollBack()
            raise
        else:
            transaction.Commit()

    def _finalize_rename(self, family_doc, fam_manager):
        transaction = DB.Transaction(family_doc, "Finalize parameter rename")
        transaction.Start()

        try:
            for item in self.pending_requests:
                temp_param = self._find_parameter(fam_manager, item.new_name)
                if temp_param:
                    fam_manager.RemoveParameter(temp_param)

                original_param = self._find_parameter(fam_manager, item.original_name)
                if original_param is None:
                    ERROR_HANDLE.print_note("Original parameter '{}' not found during rename.".format(item.original_name))
                    continue

                fam_manager.RenameParameter(original_param, item.new_name)
        except Exception:
            transaction.RollBack()
            raise
        else:
            transaction.Commit()

    def _copy_type_values(self, fam_manager, source_param, target_param, storage_type):
        for fam_type in fam_manager.Types:
            fam_manager.CurrentType = fam_type
            try:
                value = fam_manager.Get(source_param)
            except Exception:
                value = None

            if value is None and storage_type == DB.StorageType.String:
                value = ""

            try:
                fam_manager.Set(target_param, value)
            except Exception:
                pass

    def _find_parameter(self, fam_manager, name):
        for param in fam_manager.Parameters:
            if param.Definition.Name == name:
                return param
        return None

    def _create_temp_parameter(self, fam_manager, item):
        try:
            group_type_id = self._pick_group_type_id(item)
            group_enum = self._pick_group_enum(item)

            parameter_type = self._pick_parameter_type(item)
            spec_type = self._pick_spec_type(item, parameter_type)
            if not spec_type and item.data_type_id:
                spec_type = item.data_type_id

            if parameter_type is None and item.storage_type is not None:
                parameter_type = self._guess_parameter_type_from_storage(item.storage_type)
                if parameter_type is not None:
                    spec_type = self._pick_spec_type(item, parameter_type)

            if parameter_type is not None and group_enum is not None:
                try:
                    return fam_manager.AddParameter(item.new_name, group_enum, parameter_type, item.is_instance)
                except Exception as err:
                    ERROR_HANDLE.print_note("ParameterType add failed for '{}': {}".format(item.new_name, err))
                    self._log_exception("AddParameter legacy overload failed for {} with ParameterType {}".format(item.new_name, parameter_type), err)

            if group_type_id and spec_type:
                try:
                    return fam_manager.AddParameter(item.new_name, group_type_id, spec_type, item.is_instance)
                except Exception as err:
                    ERROR_HANDLE.print_note("SpecTypeId add failed for '{}': {}".format(item.new_name, err))
                    self._log_exception("AddParameter Forge overload failed for {} with SpecType {}".format(item.new_name, spec_type), err)

            if group_enum is not None and spec_type:
                try:
                    return fam_manager.AddParameter(item.new_name, group_enum, spec_type, item.is_instance)
                except Exception as err:
                    ERROR_HANDLE.print_note("SpecTypeId + BuiltInGroup add failed for '{}': {}".format(item.new_name, err))
                    self._log_exception("AddParameter mixed overload failed for {} with SpecType {}".format(item.new_name, spec_type), err)

            if group_type_id and parameter_type is not None:
                spec_guess = self._guess_spec_from_parameter_type(parameter_type)
                if spec_guess:
                    try:
                        return fam_manager.AddParameter(item.new_name, group_type_id, spec_guess, item.is_instance)
                    except Exception as err:
                        ERROR_HANDLE.print_note("Spec guess add failed for '{}': {}".format(item.new_name, err))
                        self._log_exception("Spec guess overload failed for {} with Spec {}".format(item.new_name, spec_guess), err)

            spec_from_storage = self._guess_spec_from_storage(item.storage_type)
            if spec_from_storage and not self._spec_matches(spec_type, spec_from_storage):
                if group_type_id:
                    try:
                        return fam_manager.AddParameter(item.new_name, group_type_id, spec_from_storage, item.is_instance)
                    except Exception as err:
                        ERROR_HANDLE.print_note("Storage spec add failed for '{}': {}".format(item.new_name, err))
                        self._log_exception("Storage spec overload failed for {} with Spec {}".format(item.new_name, spec_from_storage), err)
                if group_enum is not None:
                    try:
                        return fam_manager.AddParameter(item.new_name, group_enum, spec_from_storage, item.is_instance)
                    except Exception as err:
                        ERROR_HANDLE.print_note("Storage spec + built-in group add failed for '{}': {}".format(item.new_name, err))
                        self._log_exception("Storage spec overload failed for {} with Spec {}".format(item.new_name, spec_from_storage), err)
        except Exception as err:
            ERROR_HANDLE.print_note("Error adding temporary parameter '{}': {}".format(item.new_name, err))
            self._log_exception("Exception while adding temp parameter '{}'".format(item.new_name), err)
        return None

    def _pick_group_type_id(self, item):
        if item.group_type_id and self._is_valid_group(item.group_type_id):
            return item.group_type_id
        if self._is_valid_group(self._default_group_type_id):
            return self._default_group_type_id
        fallback = self._resolve_group_type_id("Data")
        if self._is_valid_group(fallback):
            return fallback
        return None

    def _pick_group_enum(self, item):
        if item.group_enum:
            return item.group_enum
        if self._default_group_enum is not None:
            return self._default_group_enum
        return self._resolve_builtin_group("PG_DATA")

    def _pick_parameter_type(self, item):
        param_type = item.data_type
        if param_type is None:
            return None
        invalid = self._parameter_type_member("Invalid")
        if invalid is not None and param_type == invalid:
            return None
        return param_type

    def _pick_spec_type(self, item, parameter_type):
        if self._is_valid_spec(item.spec_type):
            return item.spec_type
        spec_guess = self._guess_spec_from_parameter_type(parameter_type or item.data_type)
        if spec_guess:
            return spec_guess
        if item.data_type_id:
            return item.data_type_id
        return self._guess_spec_from_storage(item.storage_type)

    def _guess_spec_from_parameter_type(self, parameter_type):
        if parameter_type is None:
            return None

        spec = self._parameter_type_to_spec.get(parameter_type)
        if spec:
            return spec

        name = self._safe_to_string(parameter_type)
        spec = self._infer_spec_from_text(name)
        if spec:
            return spec

        if hasattr(parameter_type, "TypeId"):
            spec = self._infer_spec_from_text(self._safe_to_string(parameter_type.TypeId))
            if spec:
                return spec

        return None

    def _guess_spec_from_storage(self, storage_type):
        if storage_type == DB.StorageType.Integer:
            spec = self._get_spec_type("Int", "Integer")
            if spec:
                return spec
            return self._infer_spec_from_text("Integer")
        if storage_type == DB.StorageType.Double:
            spec = getattr(DB.SpecTypeId, "Number", None)
            if spec:
                return spec
            return self._infer_spec_from_text("Number")
        if storage_type == DB.StorageType.String:
            spec = self._get_spec_type("String", "Text")
            if spec:
                return spec
            return self._infer_spec_from_text("Text")
        if storage_type == DB.StorageType.ElementId:
            spec = self._get_spec_type("Reference", "ElementId")
            if spec:
                return spec
            return self._infer_spec_from_text("ElementId")
        return None

    def _is_valid_spec(self, spec):
        if not spec:
            return False
        try:
            return spec.IsValidId()
        except Exception:
            return True

    def _is_valid_group(self, group_id):
        if not group_id:
            return False
        try:
            return group_id.IsValidId()
        except Exception:
            return True

    def _guess_parameter_type_from_storage(self, storage_type):
        mapping = {
            DB.StorageType.Integer: self._parameter_type_member("Integer"),
            DB.StorageType.Double: self._parameter_type_member("Number"),
            DB.StorageType.String: self._parameter_type_member("Text"),
            DB.StorageType.ElementId: self._parameter_type_member("ElementId"),
        }
        guess = mapping.get(storage_type)
        if guess is None:
            return None
        invalid = self._parameter_type_member("Invalid")
        if invalid is not None and guess == invalid:
            return None
        return guess

    def _get_family_reference(self):
        if not self.target_family_name:
            return None
        if self.is_family_doc:
            families = self._collect_families_from_doc(self.entry_doc)
            for fam in families:
                if fam.Name == self.target_family_name:
                    return fam
            return None
        family = REVIT_FAMILY.get_family_by_name(self.target_family_name, doc=self.entry_doc)
        return getattr(family, "item", family)

    def _log_exception(self, message, err):
        try:
            traceback_text = traceback.format_exc()
        except Exception:
            traceback_text = None
        if traceback_text and traceback_text.strip() and traceback_text.strip() != "None":
            ERROR_HANDLE.print_note(traceback_text)

    def _format_parameter_metadata(self, item):
        lines = []
        storage_name = self._storage_type_to_text(item.storage_type)
        if storage_name:
            lines.append("Storage: {}".format(storage_name))
        spec_source = None
        if item.spec_type:
            spec_source = item.spec_type
        elif item.data_type_id:
            spec_source = item.data_type_id
        spec_name = self._spec_type_to_text(spec_source)
        if spec_name:
            lines.append("Spec: {}".format(spec_name))
        param_name = self._parameter_type_to_text(item.data_type)
        if param_name:
            if not spec_name or param_name.lower() != spec_name.lower():
                lines.append("Param: {}".format(param_name))
        if item.reason:
            if "Shared parameter" in item.reason:
                lines.append("Note: Shared parameter (cannot rename)")
            elif not lines:
                lines.append(item.reason)
        return "\n".join(lines)

    def _describe_spec(self, item):
        spec_text = []
        if item.spec_type:
            spec_text.append("spec={}".format(self._safe_to_string(item.spec_type)))
        if item.data_type:
            spec_text.append("param_type={}".format(self._safe_to_string(item.data_type)))
        if item.storage_type is not None:
            spec_text.append("storage={}".format(item.storage_type))
        if item.data_type_id:
            spec_text.append("data_type_id={}".format(self._safe_to_string(item.data_type_id)))
        if not spec_text:
            spec_text.append("unknown-metadata")
        return ", ".join(spec_text)

    def _describe_created_parameter(self, param):
        definition = param.Definition
        parts = []
        try:
            parts.append("group_type={}".format(self._safe_to_string(definition.GetGroupTypeId())))
        except Exception:
            pass
        try:
            parts.append("group_enum={}".format(getattr(definition, "ParameterGroup", None)))
        except Exception:
            pass
        try:
            parts.append("spec={}".format(self._safe_to_string(definition.GetSpecTypeId())))
        except Exception:
            try:
                parts.append("spec={}".format(self._safe_to_string(definition.GetDataType())))
            except Exception:
                pass
        try:
            parts.append("param_type={}".format(self._safe_to_string(getattr(definition, "ParameterType", None))))
        except Exception:
            pass
        try:
            parts.append("storage={}".format(param.StorageType))
        except Exception:
            pass
        if not parts:
            return "definition={}".format(definition)
        return ", ".join(parts)

    def _storage_type_to_text(self, storage_type):
        if storage_type is None:
            return ""
        try:
            return storage_type.ToString()
        except Exception:
            pass
        mapping = {
            getattr(DB.StorageType, "None", None): "None",
            getattr(DB.StorageType, "Integer", None): "Integer",
            getattr(DB.StorageType, "Double", None): "Double",
            getattr(DB.StorageType, "String", None): "String",
            getattr(DB.StorageType, "ElementId", None): "ElementId",
        }
        for key, value in mapping.items():
            if key is not None and storage_type == key:
                return value
        return str(storage_type)

    def _spec_type_to_text(self, spec):
        if not spec:
            return ""
        try:
            readable = REVIT_UNIT.get_unit_spec_name(spec)
            if readable:
                return readable
        except Exception:
            pass
        text = self._safe_to_string(spec)
        if "aec:" in text:
            text = text.split("aec:")[-1]
        if "unit:" in text:
            text = text.split("unit:")[-1]
        if "::" in text:
            text = text.split("::")[-1]
        if "spec:" in text:
            text = text.split("spec:")[-1]
        if "-" in text:
            text = text.split("-")[0]
        return text

    def _parameter_type_to_text(self, param_type):
        if not param_type:
            return ""
        return self._safe_to_string(param_type)

    def _spec_matches(self, spec_a, spec_b):
        if spec_a is None or spec_b is None:
            return False
        try:
            if spec_a == spec_b:
                return True
        except Exception:
            pass
        try:
            if hasattr(spec_a, "TypeId") and hasattr(spec_b, "TypeId"):
                return spec_a.TypeId == spec_b.TypeId
        except Exception:
            pass
        return False

    def _get_spec_type(self, *names):
        current = getattr(DB, "SpecTypeId", None)
        for name in names:
            if current is None:
                return None
            try:
                current = getattr(current, name)
            except Exception:
                return None
        return current

    def _build_parameter_type_map(self):
        mapping = {}
        parameter_type_enum = getattr(DB, "ParameterType", None)
        if not parameter_type_enum:
            return mapping

        def _assign(name, spec):
            try:
                value = getattr(parameter_type_enum, name)
            except Exception:
                value = None
            if value is not None and spec is not None:
                mapping[value] = spec

        _assign("YesNo", self._get_spec_type("Boolean", "YesNo"))
        _assign("Boolean", self._get_spec_type("Boolean", "YesNo"))
        _assign("Text", self._get_spec_type("String", "Text"))
        _assign("MultilineText", self._get_spec_type("String", "MultilineText"))
        _assign("Integer", self._get_spec_type("Int", "Integer"))
        _assign("Number", getattr(DB.SpecTypeId, "Number", None))
        _assign("Length", getattr(DB.SpecTypeId, "Length", None))
        _assign("Area", getattr(DB.SpecTypeId, "Area", None))
        _assign("Volume", getattr(DB.SpecTypeId, "Volume", None))
        _assign("Angle", getattr(DB.SpecTypeId, "Angle", None))
        _assign("Material", getattr(DB.SpecTypeId, "Material", None))
        _assign("URL", self._get_spec_type("String", "URL"))
        _assign("Image", self._get_spec_type("String", "Image"))
        _assign("FamilyType", self._get_spec_type("Reference", "ElementId"))
        return mapping

    def _resolve_group_type_id(self, name):
        group_type_container = getattr(DB, "GroupTypeId", None)
        if not group_type_container:
            return None
        try:
            return getattr(group_type_container, name)
        except Exception:
            return None

    def _resolve_builtin_group(self, name):
        if not self._built_in_group_enum:
            return None
        try:
            return getattr(self._built_in_group_enum, name)
        except Exception:
            return None

    def _parameter_type_member(self, name):
        if not self._parameter_type_enum:
            return None
        try:
            return getattr(self._parameter_type_enum, name)
        except Exception:
            return None

    def _infer_spec_from_text(self, text):
        if not text:
            return None
        try:
            spec_from_rev_param = REVIT_PARAMETER.get_parameter_type_from_string(text)
        except Exception:
            spec_from_rev_param = None
        if spec_from_rev_param:
            return spec_from_rev_param

        normalized = text.lower().strip()
        if "aec:" in normalized:
            normalized = normalized.split("aec:")[-1]
        if "unit:" in normalized:
            normalized = normalized.split("unit:")[-1]
        if "::" in normalized:
            normalized = normalized.split("::")[-1]
        if "-" in normalized:
            normalized = normalized.split("-")[0]

        try:
            return REVIT_PARAMETER.get_parameter_type_from_string(normalized)
        except Exception:
            pass
        try:
            return REVIT_UNIT.lookup_unit_spec_id(normalized)
        except Exception:
            return None

    def _safe_to_string(self, value):
        if value is None:
            return ""
        try:
            return value.ToString()
        except Exception:
            pass
        try:
            if hasattr(value, "TypeId"):
                return str(value.TypeId)
        except Exception:
            pass
        try:
            return str(value)
        except Exception:
            return ""


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def main():
    controller = RenameParameterController()
    controller.run()


if __name__ == "__main__":
    main()

