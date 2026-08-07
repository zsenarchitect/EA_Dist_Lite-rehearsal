#!/usr/bin/python
# -*- coding: utf-8 -*-

__doc__ = "Find elements with invalid phase references that cause crashes during regeneration."
__title__ = "Invalid Phase Element"

import os
import json
import time

import proDUCKtion # pyright: ignore
proDUCKtion.validify()

from EnneadTab import ERROR_HANDLE, LOG, NOTIFICATION
from EnneadTab.REVIT import REVIT_APPLICATION
from Autodesk.Revit import DB # pyright: ignore
from System.Collections.Generic import List # pyright: ignore

UIDOC = REVIT_APPLICATION.get_uidoc()
DOC = REVIT_APPLICATION.get_doc()

# Revit 2024+ uses .Value, older uses .IntegerValue
get_id_value = REVIT_APPLICATION.get_element_id_value

REPORT_PATH = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")),
    "github",
    "invalid_phase_report.json"
)


def get_valid_phase_ids(doc):
    """Get set of all valid phase ElementIds in the document."""
    valid_ids = set()
    for phase in doc.Phases:
        valid_ids.add(get_id_value(phase.Id))
    return valid_ids


def get_phase_info(doc):
    """Get list of phase dicts for reporting."""
    phases = []
    for phase in doc.Phases:
        phases.append({
            "name": phase.Name,
            "id": get_id_value(phase.Id)
        })
    return phases


def check_phase_param(element, param_name, builtin_param, valid_phase_ids):
    """Check if a phase parameter points to a valid phase."""
    param = element.get_Parameter(builtin_param)
    if param is None:
        return False, None
    if param.StorageType != DB.StorageType.ElementId:
        return False, None

    phase_id = param.AsElementId()
    if phase_id == DB.ElementId.InvalidElementId:
        return False, None

    id_val = get_id_value(phase_id)
    if id_val not in valid_phase_ids:
        return True, "{} = ElementId({}) [NOT FOUND]".format(param_name, id_val)

    return False, None


def check_element_phase_status(element, phases):
    """Try calling GetPhaseStatus for each phase, catch if it throws."""
    bad_phases = []
    for phase in phases:
        try:
            element.GetPhaseStatus(phase.Id)
        except Exception as e:
            bad_phases.append("GetPhaseStatus(Phase '{}') threw: {}".format(phase.Name, str(e)))
    return bad_phases


def scan_document(doc, label):
    """Scan a single document for invalid phase references."""
    valid_phase_ids = get_valid_phase_ids(doc)
    phases = doc.Phases
    phase_info = get_phase_info(doc)

    print("\n{}".format("=" * 60))
    print("Scanning: {}".format(label))
    print("Valid phases: {}".format(
        ", ".join(["{} (id={})".format(p["name"], p["id"]) for p in phase_info])))
    print("-" * 60)

    collector = DB.FilteredElementCollector(doc).WhereElementIsNotElementType()
    bad_elements = []

    count = 0
    for element in collector:
        count += 1
        issues = []

        is_bad, detail = check_phase_param(
            element, "PHASE_CREATED",
            DB.BuiltInParameter.PHASE_CREATED, valid_phase_ids)
        if is_bad:
            issues.append(detail)

        is_bad, detail = check_phase_param(
            element, "PHASE_DEMOLISHED",
            DB.BuiltInParameter.PHASE_DEMOLISHED, valid_phase_ids)
        if is_bad:
            issues.append(detail)

        phase_errors = check_element_phase_status(element, phases)
        if phase_errors:
            issues.extend(phase_errors)

        if issues:
            try:
                cat_name = element.Category.Name if element.Category else "<No Category>"
            except Exception:
                cat_name = "<Error reading category>"

            bad_elements.append({
                "id": get_id_value(element.Id),
                "element_id": element.Id,
                "doc_title": label,
                "category": cat_name,
                "name": element.Name if hasattr(element, "Name") else "<unnamed>",
                "issues": issues
            })

    print("Scanned {} elements, found {} bad.".format(count, len(bad_elements)))

    return {
        "label": label,
        "title": doc.Title,
        "path": doc.PathName if doc.PathName else "<not saved>",
        "phases": phase_info,
        "element_count": count,
        "bad_elements": bad_elements
    }


def get_linked_documents(doc):
    """Get all loaded linked Revit documents."""
    linked_docs = []
    link_instances = DB.FilteredElementCollector(doc)\
        .OfClass(DB.RevitLinkInstance)\
        .ToElements()
    seen = set()
    for link in link_instances:
        link_doc = link.GetLinkDocument()
        if link_doc is None:
            print("WARNING: Link '{}' is not loaded, skipping.".format(link.Name))
            continue
        doc_title = link_doc.Title
        if doc_title in seen:
            continue
        seen.add(doc_title)
        linked_docs.append((doc_title, link_doc))
    return linked_docs


def cross_check_phases(host_phases, linked_results):
    """Compare phase tables across host and linked docs to find mismatches."""
    host_ids = set(p["id"] for p in host_phases)
    host_names = set(p["name"] for p in host_phases)
    mismatches = []

    for result in linked_results:
        link_ids = set(p["id"] for p in result["phases"])
        link_names = set(p["name"] for p in result["phases"])

        ids_only_in_host = host_ids - link_ids
        ids_only_in_link = link_ids - host_ids
        names_only_in_host = host_names - link_names
        names_only_in_link = link_names - host_names

        if ids_only_in_host or ids_only_in_link or names_only_in_host or names_only_in_link:
            mismatches.append({
                "link_title": result["title"],
                "host_phases": [p["name"] for p in host_phases],
                "link_phases": [p["name"] for p in result["phases"]],
                "names_only_in_host": list(names_only_in_host),
                "names_only_in_link": list(names_only_in_link),
                "ids_only_in_host": list(ids_only_in_host),
                "ids_only_in_link": list(ids_only_in_link)
            })
    return mismatches


class SafeEncoder(json.JSONEncoder):
    """Handle IronPython long and other non-standard types."""
    def default(self, obj):
        try:
            return int(obj)
        except Exception:
            return str(obj)


def save_report(report):
    """Save JSON report to disk for Claude to read."""
    # Strip non-serializable ElementId objects before saving
    for doc_result in report.get("documents", []):
        for bad in doc_result.get("bad_elements", []):
            bad.pop("element_id", None)

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, cls=SafeEncoder)
    print("\nReport saved to: {}".format(REPORT_PATH))


@LOG.log(__file__, __title__)
@ERROR_HANDLE.try_catch_error()
def invalid_phase_element(doc):
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "revit_version": doc.Application.VersionNumber,
        "host_document": doc.Title,
        "host_path": doc.PathName if doc.PathName else "<not saved>",
        "documents": [],
        "phase_mismatches": [],
        "total_bad_elements": 0
    }

    # Scan host document
    host_result = scan_document(doc, "HOST: {}".format(doc.Title))
    report["documents"].append(host_result)

    # Scan all linked documents
    linked_docs = get_linked_documents(doc)
    print("\nFound {} linked documents.".format(len(linked_docs)))

    linked_results = []
    for title, link_doc in linked_docs:
        result = scan_document(link_doc, "LINK: {}".format(title))
        report["documents"].append(result)
        linked_results.append(result)

    # Cross-check phase tables between host and links
    host_phases = host_result["phases"]
    mismatches = cross_check_phases(host_phases, linked_results)
    report["phase_mismatches"] = mismatches

    if mismatches:
        print("\n{}".format("=" * 60))
        print("PHASE TABLE MISMATCHES:")
        for mm in mismatches:
            print("\n  Link: {}".format(mm["link_title"]))
            print("    Host phases: {}".format(", ".join(mm["host_phases"])))
            print("    Link phases: {}".format(", ".join(mm["link_phases"])))
            if mm["names_only_in_host"]:
                print("    Phases ONLY in host: {}".format(", ".join(mm["names_only_in_host"])))
            if mm["names_only_in_link"]:
                print("    Phases ONLY in link: {}".format(", ".join(mm["names_only_in_link"])))

    # Collect all bad elements
    all_bad = []
    for doc_result in report["documents"]:
        all_bad.extend(doc_result["bad_elements"])
    report["total_bad_elements"] = len(all_bad)

    print("\n{}".format("=" * 60))
    if not all_bad and not mismatches:
        print("No invalid phase elements or mismatches found.")
    elif all_bad:
        print("FOUND {} ELEMENTS WITH INVALID PHASE REFERENCES:".format(len(all_bad)))
        for item in all_bad:
            print("\n  [{}] Element ID: {}".format(item["doc_title"], item["id"]))
            print("    Category: {}".format(item["category"]))
            print("    Name: {}".format(item["name"]))
            for issue in item["issues"]:
                print("    >> {}".format(issue))

    # Select bad elements in the host doc
    host_bad_ids = [item["element_id"] for item in all_bad
                    if item["doc_title"].startswith("HOST:")]
    if host_bad_ids and UIDOC:
        id_list = List[DB.ElementId](host_bad_ids)
        UIDOC.Selection.SetElementIds(id_list)

    save_report(report)

    summary = "{} bad elements, {} phase mismatches across {} docs.".format(
        len(all_bad), len(mismatches), len(report["documents"]))
    summary += "\nReport: {}".format(REPORT_PATH)
    NOTIFICATION.messenger(summary)



################## main code below #####################
if __name__ == "__main__":
    invalid_phase_element(DOC)
