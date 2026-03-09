"""
Sidecar JSON (and optional FBX) export for level entities.
"""

import json
import os

from pymxs import runtime as rt

from .scene_ops import EntityOps
from .texture_ops import TextureOps


def _safe_name(obj) -> str:
    """Escape a node name for MaxScript $'name' selectors."""
    return str(obj.name).replace("'", "\\'")


def _is_visible(obj) -> bool:
    """Return True if the object's eye icon is on (not hidden)."""
    try:
        return not obj.isHidden
    except Exception:
        return True


def _is_exportable(obj) -> bool:
    """Return True if object is visible and not a proxy visual child.

    Excludes proxy VIS models created by the place tool, which have
    le_visual_child user property set to 'true'.
    """
    try:
        if not _is_visible(obj):
            return False
        prop = rt.getUserProp(obj, "le_visual_child")
        if prop is not None and str(prop).strip().lower() == "true":
            return False
        return True
    except Exception:
        return True


class SidecarExporter:
    @staticmethod
    def _scan_collision_metadata() -> dict:
        result = {}
        for obj in rt.objects:
            try:
                if not rt.isKindOf(obj, rt.GeometryClass):
                    continue
                if not _is_visible(obj):
                    continue
            except Exception:
                continue
            name = str(obj.name)
            if name.endswith("-col"):
                continue
            try:
                prop = rt.getUserProp(obj, "le_visual_child")
                if prop is not None and str(prop).strip().lower() == "true":
                    continue
            except Exception:
                pass
            safe = _safe_name(obj)

            pos = obj.transform.position
            try:
                euler = rt.execute(f"($'{safe}').transform.rotation as eulerAngles")
                rotation = [float(euler.x), float(euler.y), float(euler.z)]
            except Exception:
                rotation = [0.0, 0.0, 0.0]
            scl = obj.transform.scale

            col_child = None
            try:
                col_name = rt.execute(f"""(
                    local result = ""
                    for c in $'{safe}'.children where (matchPattern c.name pattern:"*-col") do (
                        result = c.name
                        exit
                    )
                    result
                )""")
                if col_name and str(col_name).strip():
                    col_child = str(col_name).strip()
            except Exception:
                pass

            entry = {
                "position": [float(pos.x), float(pos.y), float(pos.z)],
                "rotation": rotation,
                "scale": [float(scl.x), float(scl.y), float(scl.z)],
            }
            if col_child:
                entry["collision_type"] = "convex"
                entry["collision_mesh"] = col_child
            else:
                entry["collision_type"] = "trimesh"
            result[name] = entry
        return result

    @staticmethod
    def _scan_lights() -> dict:
        """Collect light properties for the sidecar."""
        result = {}
        for obj in rt.objects:
            try:
                if str(rt.superClassOf(obj)).lower() != "light":
                    continue
                if not _is_visible(obj):
                    continue
            except Exception:
                continue

            try:
                name = str(obj.name)
                cls = str(rt.classOf(obj))

                cls_lower = cls.lower()
                if "spot" in cls_lower:
                    light_type = "spot"
                elif "direct" in cls_lower:
                    light_type = "directional"
                else:
                    light_type = "omni"

                try:
                    color = obj.color
                    r = round(float(color.r) / 255.0, 4)
                    g = round(float(color.g) / 255.0, 4)
                    b = round(float(color.b) / 255.0, 4)
                except Exception:
                    r, g, b = 1.0, 1.0, 1.0

                try:
                    multiplier = float(obj.multiplier)
                except Exception:
                    multiplier = 1.0

                range_val = 0.0
                try:
                    if bool(obj.useFarAtten):
                        range_val = float(obj.farAttenEnd)
                except Exception:
                    pass
                if range_val == 0.0:
                    try:
                        range_val = float(obj.decayRadius)
                    except Exception:
                        pass
                if range_val <= 0.0:
                    range_val = 40.0

                pos = obj.transform.position
                position = [float(pos.x), float(pos.y), float(pos.z)]

                safe = _safe_name(obj)
                try:
                    euler = rt.execute(f"($'{safe}').transform.rotation as eulerAngles")
                    rotation = [float(euler.x), float(euler.y), float(euler.z)]
                except Exception:
                    rotation = [0.0, 0.0, 0.0]

                entry = {
                    "type": light_type,
                    "position": position,
                    "rotation": rotation,
                    "color": [r, g, b],
                    "multiplier": multiplier,
                    "range": range_val,
                }

                if light_type == "spot":
                    try:
                        entry["hotspot"] = float(obj.hotspot)
                        entry["falloff"] = float(obj.falloff)
                    except Exception:
                        pass

                result[name] = entry
            except Exception:
                continue
        return result

    @staticmethod
    def export(filepath: str) -> int:
        entities = EntityOps.get_all_entities() or []

        data = {"entities": {}}
        for obj in entities:
            if not _is_visible(obj):
                continue
            entity_type = EntityOps.get_prop(obj, "le_entity_type")
            if entity_type is None:
                continue

            pos = obj.transform.position
            safe_name = _safe_name(obj)
            euler = rt.execute(f"($'{safe_name}').transform.rotation as eulerAngles")
            scl = obj.transform.scale

            entry = {
                "entity_type": entity_type,
                "transform": {
                    "position": [float(pos.x), float(pos.y), float(pos.z)],
                    "rotation": [float(euler.x), float(euler.y), float(euler.z)],
                    "scale": [float(scl.x), float(scl.y), float(scl.z)],
                },
                "metadata": {},
            }

            if EntityOps.get_prop(obj, "le_is_trigger") == "true":
                entry["is_trigger"] = True

            refs = EntityOps.get_trigger_refs(obj)
            if refs:
                entry["trigger_refs"] = refs

            trigger_id_keys = EntityOps.get_trigger_id_keys(obj)
            if trigger_id_keys:
                entry["trigger_id_keys"] = trigger_id_keys

            trigger_ref_keys = EntityOps.get_trigger_ref_keys(obj)
            if trigger_ref_keys:
                entry["trigger_ref_keys"] = trigger_ref_keys

            for key in EntityOps.get_meta_keys(obj):
                entry["metadata"][key] = EntityOps.get_meta(obj, key)

            data["entities"][str(obj.name)] = entry

        meshes = SidecarExporter._scan_collision_metadata()
        if meshes:
            data["meshes"] = meshes

        lights = SidecarExporter._scan_lights()
        if lights:
            data["lights"] = lights

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        return len(entities)

    @staticmethod
    def _configure_fbx_for_unreal():
        """Set FBX exporter settings for Unreal Engine compatibility."""
        settings = [
            ('"SmoothingGroups"', "true"),
            ('"SmoothMeshExport"', "false"),
            ('"Triangulate"', "true"),
            ('"PreserveEdgeOrientation"', "true"),
            ('"TangentSpaceExport"', "true"),
            ('"Animation"', "false"),
            ('"Cameras"', "false"),
            ('"Lights"', "false"),
            ('"EmbedTextures"', "true"),
            ('"ASCII"', "false"),
            ('"FileVersion"', '"FBX202000"'),
            ('"ConvertUnit"', '"cm"'),
            ('"ScaleFactor"', "1.0"),
        ]
        for param, value in settings:
            try:
                rt.execute(f"FBXExporterSetParam {param} {value}")
            except Exception:
                pass

    @staticmethod
    def _ensure_smoothing_groups():
        """Assign smoothing groups to poly objects that lack them.

        Uses auto-smooth at 45 degrees so flat-shaded faces get distinct
        groups while curved surfaces share them.  Unreal relies on
        smoothing groups to split mesh sections per material — without
        them all faces may collapse into material slot 0.
        """
        for obj in rt.objects:
            try:
                if not rt.isKindOf(obj, rt.Editable_Poly):
                    continue
                if not _is_visible(obj):
                    continue
                safe = _safe_name(obj)
                has_sg = rt.execute(f"""
                    local hasSG = false
                    for f = 1 to (polyop.getNumFaces $'{safe}') while not hasSG do (
                        if (polyop.getFaceSmoothGroup $'{safe}' f) != 0 do hasSG = true
                    )
                    hasSG
                """)
                if has_sg:
                    continue
                rt.execute(f"polyop.autoSmooth $'{safe}' #all 45.0")
            except Exception:
                continue

    @staticmethod
    def _ensure_unique_multimaterials():
        """Clone shared Multi/Sub-Object materials so each object has its own.

        When meshes are copied in 3ds Max, the copy often shares the same
        material instance.  Subsequent per-object operations (compaction,
        consolidation) would mutate the shared instance and corrupt the
        sibling.  This step isolates every object first.
        """
        seen: dict[int, object] = {}
        for obj in rt.objects:
            try:
                if not _is_visible(obj):
                    continue
                mat = obj.material
                if mat is None:
                    continue
                if str(rt.classOf(mat)) != "Multimaterial":
                    continue
                mat_handle = int(rt.getHandleByAnim(mat))
                if mat_handle not in seen:
                    seen[mat_handle] = obj
                else:
                    safe = _safe_name(obj)
                    rt.execute(f"$'{safe}'.material = copy $'{safe}'.material")
            except Exception:
                continue

    @staticmethod
    def _compact_material_ids():
        """Remove unused Multi/Sub-Object slots and remap face material IDs.

        Unreal expects contiguous material IDs (1..N) matching exactly N
        sub-material slots.  Gaps or empty slots cause faces to be
        assigned to the wrong material or all collapse to slot 0.
        """
        for obj in rt.objects:
            try:
                if not _is_visible(obj):
                    continue
                mat = obj.material
                if mat is None:
                    continue
                if str(rt.classOf(mat)) != "Multimaterial":
                    continue
                if not rt.isKindOf(obj, rt.Editable_Poly):
                    continue

                safe = _safe_name(obj)
                num_faces = int(rt.execute(f"polyop.getNumFaces $'{safe}'"))
                num_subs = int(mat.numsubs)

                if num_faces == 0 or num_subs == 0:
                    continue

                used_ids = set()
                for fi in range(1, num_faces + 1):
                    mid = int(rt.execute(f"polyop.getFaceMatID $'{safe}' {fi}"))
                    used_ids.add(mid)

                sorted_ids = sorted(used_ids)
                if not sorted_ids:
                    continue

                already_compact = sorted_ids == list(
                    range(1, len(sorted_ids) + 1)
                ) and num_subs == len(sorted_ids)
                if already_compact:
                    continue

                id_map = {old: new for new, old in enumerate(sorted_ids, 1)}

                new_subs = []
                for old_id in sorted_ids:
                    if 1 <= old_id <= num_subs:
                        sub = mat[old_id]
                        new_subs.append(sub)
                    else:
                        new_subs.append(
                            rt.StandardMaterial(name=f"LE_Placeholder_{old_id}")
                        )

                mat.numsubs = len(new_subs)
                for i, sub in enumerate(new_subs, 1):
                    mat[i] = sub

                for fi in range(1, num_faces + 1):
                    old_mid = int(rt.execute(f"polyop.getFaceMatID $'{safe}' {fi}"))
                    new_mid = id_map.get(old_mid, 1)
                    if new_mid != old_mid:
                        rt.execute(f"polyop.setFaceMatID $'{safe}' {fi} {new_mid}")
            except Exception:
                continue

    @staticmethod
    def export_with_fbx(directory: str, scene_name: str = "") -> int:
        if not scene_name:
            scene_name = str(rt.getFilenameFile(rt.maxFileName))
            if not scene_name:
                scene_name = "level"

        SidecarExporter._ensure_unique_multimaterials()
        TextureOps.consolidate_materials_for_export()
        SidecarExporter._compact_material_ids()
        SidecarExporter._ensure_smoothing_groups()
        SidecarExporter._configure_fbx_for_unreal()

        fbx_path = os.path.join(directory, f"{scene_name}.fbx")
        json_path = os.path.join(directory, f"{scene_name}_entities.json")

        old_sel = list(rt.getCurrentSelection())
        exportable = [obj for obj in rt.objects if _is_exportable(obj)]
        if exportable:
            rt.select(exportable)
        else:
            rt.clearSelection()
        rt.exportFile(fbx_path, rt.Name("noPrompt"), selectedOnly=True, using=rt.FBXEXP)
        if old_sel:
            rt.select(old_sel)
        else:
            rt.clearSelection()

        return SidecarExporter.export(json_path)
