#! python 2
# -*- coding: utf-8 -*-
"""Step 2: does a textured glTF survive import into Rhino 8 with its texture?

WHY THIS DECIDES THE SERVER CONTRACT: Google Photorealistic 3D Tiles are served
as glTF/GLB. If Rhino 8 ingests GLB with materials and texture maps intact, the
EnneadTab-EarthModel service can hand back what it already has, with no
conversion step and no conversion loss. If it does not, the service must
transcode to OBJ+MTL and we pay for that in fidelity and complexity.

Target render engines (Sen Zhang, 2026-08-05): Enscape, Rhino Render, and
EnneadTab's own AI render service. The first two consume Rhino materials, so the
material/texture assertions below are what matter for them. AI render consumes a
VIEWPORT CAPTURE rather than the mesh, so for that leg the rendered PNG at the
end is the actual acceptance artifact -- same pipeline as this harness's L4.

Uses no _-Export: export option dialogs are modal and would block the script
server. The OBJ leg is deliberately NOT tested here (see UNTESTED note below).

Run:  RhinoCode.exe script DarkSide/tests/get_earth/rhino_l3_texture_format.py
Poll for the JSON; do NOT trust the CLI exit code.
"""

import os
import json
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, "l3_texture_format_result.json")
PNG_PATH = os.path.join(HERE, "l3_texture_format_capture.png")

SAMPLE_GLB = (r"C:\Users\szhang\AppData\Local\Temp\claude"
              r"\C--Users-szhang-github\6d42bbbb-ee1d-4b50-a710-12ddc58bc516"
              r"\scratchpad\BoxTextured.glb")

result = {"ok": True, "checks": [], "untested": [
    "OBJ+MTL leg -- _-Export opens a modal options dialog which would block the "
    "script server. Needs a separate approach (scripted export options or a "
    "server-side produced OBJ fixture)."
]}


def check(name, fn):
    try:
        result["checks"].append({"name": name, "ok": True, "value": fn()})
    except Exception as e:
        result["checks"].append({"name": name, "ok": False, "error": str(e)})
        result["ok"] = False


def main():
    import rhinoscriptsyntax as rs
    import Rhino
    import scriptcontext as sc

    doc = Rhino.RhinoDoc.ActiveDoc

    check("sample_exists", lambda: {"path": SAMPLE_GLB,
                                    "exists": os.path.exists(SAMPLE_GLB),
                                    "bytes": os.path.getsize(SAMPLE_GLB)})

    # Clear the scratch document. Deliberately not _-New: that can raise a
    # save-changes dialog, and a modal dialog deadlocks the script server.
    def _clear():
        rs.Command("_-SelAll _Delete", False)
        return {"objects_after_clear": doc.Objects.Count}

    check("clear_document", _clear)

    def _import():
        before = doc.Objects.Count
        ok = rs.Command('_-Import "%s" _Enter' % SAMPLE_GLB, False)
        return {"command_ok": bool(ok),
                "objects_before": before,
                "objects_after": doc.Objects.Count,
                "created": doc.Objects.Count - before}

    check("import_glb", _import)

    # --- the real question: did materials and texture maps come across? ------

    def _materials():
        found = []
        for m in doc.Materials:
            if m is None or m.IsDeleted:
                continue
            entry = {"name": m.Name, "textures": []}
            try:
                for t in m.GetTextures():
                    if t is None:
                        continue
                    entry["textures"].append({
                        "type": str(t.TextureType),
                        "file": os.path.basename(t.FileName or ""),
                        "enabled": bool(t.Enabled),
                    })
            except Exception as e:
                entry["texture_error"] = str(e)
            found.append(entry)
        return {"material_count": len(found), "materials": found}

    check("doc_materials", _materials)

    def _render_materials():
        # Rhino 8 routes imported PBR through RenderMaterials; doc.Materials can
        # look empty even when the render material is fully populated.
        out = []
        try:
            table = doc.RenderMaterials
            for rm in table:
                out.append({"name": rm.Name, "type": str(rm.TypeName)})
        except Exception as e:
            return {"error": str(e)}
        return {"render_material_count": len(out), "render_materials": out}

    check("render_materials", _render_materials)

    def _object_material_binding():
        bound = []
        for o in doc.Objects:
            if o is None:
                continue
            att = o.Attributes
            rec = {"id": str(o.Id)[:8],
                   "source": str(att.MaterialSource),
                   "material_index": att.MaterialIndex}
            try:
                rm = o.RenderMaterial
                rec["render_material"] = rm.Name if rm else None
            except Exception:
                rec["render_material"] = "n/a"
            bound.append(rec)
        return {"object_count": len(bound), "objects": bound[:10]}

    check("object_material_binding", _object_material_binding)

    def _has_texture_bitmap():
        """The single pass/fail the server contract turns on."""
        for m in doc.Materials:
            if m is None or m.IsDeleted:
                continue
            try:
                for t in m.GetTextures():
                    if t is not None and t.FileName:
                        return {"textured": True, "via": "Material.GetTextures",
                                "file": os.path.basename(t.FileName)}
            except Exception:
                pass
        try:
            if doc.RenderMaterials.Count > 0:
                return {"textured": "maybe", "via": "RenderMaterials present",
                        "count": doc.RenderMaterials.Count}
        except Exception:
            pass
        return {"textured": False}

    check("VERDICT_texture_survived", _has_texture_bitmap)

    # --- L4 capture: the AI-render leg's actual acceptance artifact ----------

    def _capture():
        rs.Command("_-SelNone", False)
        rs.Command("_-Zoom _All _Extents", False)
        rs.Command("_-SetDisplayMode _Mode=_Rendered _Enter", False)
        view = doc.Views.ActiveView
        cap = Rhino.Display.ViewCapture()
        cap.Width = 900
        cap.Height = 600
        cap.ScaleScreenItems = False
        cap.DrawAxes = False
        cap.DrawGrid = False
        cap.TransparentBackground = False
        bmp = cap.CaptureToBitmap(view)
        if bmp is None:
            raise Exception("CaptureToBitmap returned None")
        bmp.Save(PNG_PATH)
        return {"path": PNG_PATH,
                "bytes": os.path.getsize(PNG_PATH),
                "mode": str(view.ActiveViewport.DisplayMode.EnglishName)}

    check("rendered_capture", _capture)


try:
    main()
except Exception:
    result["ok"] = False
    result["fatal"] = traceback.format_exc()
finally:
    with open(JSON_PATH, "w") as f:
        json.dump(result, f, indent=2, default=str)
