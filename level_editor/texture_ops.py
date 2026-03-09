"""
Texture and material operations: materials, per-face UVs, live
reprojection, and texture continuation.  Parallel to EntityOps.
"""

import json
import math
import os
import time

from pymxs import runtime as rt

from level_editor import uv_math

rt.execute("""
global le_layer_ca_def
if le_layer_ca_def == undefined do (
    le_layer_ca_def = attributes "LE_LayerUVs" (
        parameters main ( le_layer_uvs type:#string default:"{}" )
    )
)
""")

WORLD_TILE_SIZE = 100.0


def _safe_name(obj) -> str:
    """Escape a node name for MaxScript $'name' selectors."""
    return str(obj.name).replace("'", "\\'")


class TextureOps:
    SUPPORTED_EXTENSIONS = {
        ".png",
        ".jpg",
        ".jpeg",
        ".tga",
        ".bmp",
        ".tif",
        ".tiff",
        ".dds",
    }

    _face_uv_store: dict = {}
    _tracked_objects: dict = {}
    _reprojecting: bool = False
    _last_reproject_time: float = 0.0
    REPROJECT_THROTTLE: float = 0.05
    _face_map_verts: dict = {}

    @staticmethod
    def _resolve_obj_from_handle(handle: int):
        info = TextureOps._tracked_objects.get(handle)
        if info is not None:
            obj = info["obj"]
            try:
                if rt.isValidNode(obj):
                    return obj
            except Exception:
                pass
        try:
            obj = rt.getAnimByHandle(handle)
            if obj is not None and rt.isValidNode(obj):
                return obj
        except Exception:
            pass
        return None

    @staticmethod
    def load_face_uv_params_from_scene(obj) -> bool:
        handle = TextureOps._obj_handle(obj)
        compiled = TextureOps.compile_stack_uvs(obj)
        if compiled:
            TextureOps._face_uv_store[handle] = compiled
            return True
        return False

    @staticmethod
    def scan_texture_directory(textures_dir: str) -> list[dict]:
        results = []
        if not os.path.isdir(textures_dir):
            return results

        for dirpath, _dirs, filenames in os.walk(textures_dir):
            _dirs[:] = [d for d in _dirs if d.lower() != "normals"]
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in TextureOps.SUPPORTED_EXTENSIONS:
                    continue
                abs_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(abs_path, textures_dir).replace("\\", "/")
                results.append({"name": rel_path, "path": abs_path})

        results.sort(key=lambda t: t["name"].lower())
        return results

    @staticmethod
    def find_normal_map(diffuse_path: str) -> str | None:
        if not diffuse_path:
            return None
        diffuse_dir = os.path.dirname(diffuse_path)
        normals_dir = os.path.join(diffuse_dir, "normals")
        base_name = os.path.splitext(os.path.basename(diffuse_path))[0]
        normal_stem = f"{base_name}_normal"
        diffuse_ext = os.path.splitext(diffuse_path)[1]
        candidate = os.path.join(normals_dir, normal_stem + diffuse_ext)
        if os.path.isfile(candidate):
            return candidate
        for ext in TextureOps.SUPPORTED_EXTENSIONS:
            candidate = os.path.join(normals_dir, normal_stem + ext)
            if os.path.isfile(candidate):
                return candidate
        return None

    @staticmethod
    def _is_base_editable_poly(obj) -> bool:
        try:
            base_cls = str(rt.classOf(obj.baseObject))
            return base_cls == "Editable_Poly"
        except Exception:
            return False

    @staticmethod
    def ensure_editable_poly(obj) -> bool:
        safe = _safe_name(obj)
        try:
            if not TextureOps._is_base_editable_poly(obj):
                rt.execute(f"convertToPoly $'{safe}'")
            return True
        except Exception as e:
            print(f"[LevelEditor] Error in ensure_editable_poly: {e}")
            return False

    @staticmethod
    def is_in_face_subobject_mode(obj) -> bool:
        try:
            return int(rt.subObjectLevel or 0) == 4
        except Exception:
            return False

    @staticmethod
    def _obj_handle(obj) -> int:
        try:
            return int(rt.getHandleByAnim(obj))
        except Exception:
            return id(obj)

    @staticmethod
    def store_face_uv_params(
        obj,
        face_indices: list[int],
        tile_u: float,
        tile_v: float,
        rotation: float,
        offset_u: float,
        offset_v: float,
    ):

        compact_params = [
            round(tile_u, 4),
            round(tile_v, 4),
            round(rotation, 4),
            round(offset_u, 4),
            round(offset_v, 4),
        ]

        active_mod = TextureOps._get_active_edit_poly()

        if active_mod is not None:
            try:
                has_ca = rt.execute(
                    "isProperty (modPanel.getCurrentObject()) #le_layer_uvs"
                )
                if not has_ca:
                    rt.execute("""(
                        local m = modPanel.getCurrentObject()
                        local oldSel = m.GetSelection #Face
                        custAttributes.add m le_layer_ca_def
                        if subObjectLevel != 4 then subObjectLevel = 4
                        m.SetSelection #Face oldSel
                    )""")

                raw = active_mod.le_layer_uvs
                data = json.loads(raw) if raw and str(raw) != "{}" else {}
                for fi in face_indices:
                    data[str(fi)] = compact_params
                active_mod.le_layer_uvs = json.dumps(data, separators=(",", ":"))
            except Exception as e:
                print(f"[LevelEditor] Layer Write Error: {e}")
        else:
            try:
                raw = rt.getUserProp(obj, "le_face_uvs")
                data = (
                    json.loads(str(raw))
                    if raw and str(raw).strip() not in ("", "undefined")
                    else {}
                )
                for fi in face_indices:
                    data[str(fi)] = compact_params
                rt.setUserProp(
                    obj, "le_face_uvs", json.dumps(data, separators=(",", ":"))
                )
            except Exception:
                pass

        handle = TextureOps._obj_handle(obj)
        TextureOps._face_uv_store[handle] = TextureOps.compile_stack_uvs(obj)

    @staticmethod
    def get_face_uv_params(obj, face_index: int) -> dict | None:
        key = TextureOps._obj_handle(obj)
        if key not in TextureOps._face_uv_store:
            TextureOps.load_face_uv_params_from_scene(obj)
        store = TextureOps._face_uv_store.get(key)
        if store is None:
            return None
        return store.get(face_index)

    @staticmethod
    def get_all_face_uv_params(obj) -> dict:
        key = TextureOps._obj_handle(obj)
        if key not in TextureOps._face_uv_store:
            TextureOps.load_face_uv_params_from_scene(obj)
        return dict(TextureOps._face_uv_store.get(key, {}))

    @staticmethod
    def _get_num_faces(obj) -> int:
        safe = _safe_name(obj)
        try:
            return int(rt.execute(f"undo off (polyop.getNumFaces $'{safe}')"))
        except Exception:
            return 0

    @staticmethod
    def _snapshot_verts(obj) -> tuple:
        """Snapshot LOCAL vertex positions (no transform multiply)."""
        safe = _safe_name(obj)
        try:
            arr = rt.execute(f"""undo off (
                local o = $'{safe}'
                local nv = polyop.getNumVerts o
                local result = #()
                result.count = nv * 3
                local idx = 1
                for vi = 1 to nv do (
                    local lp = polyop.getVert o vi
                    result[idx] = lp.x; result[idx+1] = lp.y; result[idx+2] = lp.z
                    idx += 3
                )
                result
            )""")
            if arr is None:
                return ()
            return tuple(round(float(v), 3) for v in arr)
        except Exception:
            return ()

    @staticmethod
    def _snapshot_transform(obj) -> tuple:
        """Snapshot the object's transform matrix as 12 floats."""
        try:
            xf = obj.transform
            r1 = xf.row1
            r2 = xf.row2
            r3 = xf.row3
            r4 = xf.row4
            return (
                round(float(r1.x), 4),
                round(float(r1.y), 4),
                round(float(r1.z), 4),
                round(float(r2.x), 4),
                round(float(r2.y), 4),
                round(float(r2.z), 4),
                round(float(r3.x), 4),
                round(float(r3.y), 4),
                round(float(r3.z), 4),
                round(float(r4.x), 4),
                round(float(r4.y), 4),
                round(float(r4.z), 4),
            )
        except Exception:
            return ()

    @staticmethod
    def track_object(obj):
        if not TextureOps._is_base_editable_poly(obj):
            return
        handle = TextureOps._obj_handle(obj)
        TextureOps._tracked_objects[handle] = {
            "obj": obj,
            "local_verts": TextureOps._snapshot_verts(obj),
            "transform": TextureOps._snapshot_transform(obj),
            "num_faces": TextureOps._get_num_faces(obj),
            "stack_state": TextureOps._snapshot_stack_state(obj),
        }
        TextureOps.load_face_uv_params_from_scene(obj)

    @staticmethod
    def refresh_tracking(obj):
        handle = TextureOps._obj_handle(obj)
        info = TextureOps._tracked_objects.get(handle)
        if info is not None:
            info["local_verts"] = TextureOps._snapshot_verts(obj)
            info["transform"] = TextureOps._snapshot_transform(obj)
            info["num_faces"] = TextureOps._get_num_faces(obj)
            info["stack_state"] = TextureOps._snapshot_stack_state(obj)

    @staticmethod
    def check_tracked_objects() -> list:
        if TextureOps._reprojecting:
            return []
        try:
            if rt.execute("theHold.Holding()"):
                return []
        except Exception:
            return []
        if (
            time.time() - TextureOps._last_reproject_time
            < TextureOps.REPROJECT_THROTTLE
        ):
            return []

        changed = []
        to_remove = []
        for handle, info in list(TextureOps._tracked_objects.items()):
            obj = info["obj"]
            try:
                if not rt.isValidNode(obj):
                    to_remove.append(handle)
                    continue
                current_local_verts = TextureOps._snapshot_verts(obj)
                if not current_local_verts:
                    continue
                current_xform = TextureOps._snapshot_transform(obj)
                current_faces = TextureOps._get_num_faces(obj)
                current_stack = TextureOps._snapshot_stack_state(obj)

                local_verts_changed = current_local_verts != info["local_verts"]
                xform_changed = current_xform != info.get("transform", ())
                topo_changed = current_faces != info.get("num_faces", 0)
                stack_changed = current_stack != info.get("stack_state", "")

                if stack_changed:
                    TextureOps.load_face_uv_params_from_scene(obj)
                    topo_changed = True

                if (
                    local_verts_changed
                    or xform_changed
                    or topo_changed
                    or stack_changed
                ):
                    info["local_verts"] = current_local_verts
                    info["transform"] = current_xform
                    info["num_faces"] = current_faces
                    info["stack_state"] = current_stack
                    changed.append(
                        (obj, topo_changed, xform_changed, local_verts_changed)
                    )
            except Exception:
                pass
        for h in to_remove:
            TextureOps._tracked_objects.pop(h, None)
            TextureOps._face_uv_store.pop(h, None)
            TextureOps._face_map_verts.pop(h, None)
        return changed

    @staticmethod
    def is_tracked(obj) -> bool:
        return TextureOps._obj_handle(obj) in TextureOps._tracked_objects

    @staticmethod
    def untrack_all():
        TextureOps._tracked_objects.clear()
        TextureOps._face_map_verts.clear()

    @staticmethod
    def get_selected_faces(obj) -> list[int]:
        safe = _safe_name(obj)
        try:
            script = f"""(
                local o = $'{safe}'
                local resStr = ""
                if o != undefined do (
                    local sel = #()
                    local ep = undefined
                    for m in o.modifiers where classOf m == Edit_Poly do (
                        ep = m
                        exit
                    )
                    if ep != undefined then (
                        sel = (ep.GetSelection #Face) as array
                    ) else (
                        try (sel = (polyop.getFaceSelection o) as array) catch ()
                    )
                    for i in sel do resStr += (i as string) + ","
                )
                resStr
            )"""
            raw = rt.execute(script)
            if not raw:
                return []
            return [int(x) for x in str(raw).split(",") if x.strip()]
        except Exception as e:
            print(f"[LevelEditor] get_selected_faces error: {e}")
            return []

    @staticmethod
    def create_material_for_texture(texture_path: str, name: str = ""):
        if not name:
            name = "LE_" + os.path.splitext(os.path.basename(texture_path))[0]
        mat = rt.StandardMaterial(name=name)
        tex = rt.BitmapTexture(filename=texture_path)
        mat.diffuseMap = tex
        mat.showInViewport = True
        normal_path = TextureOps.find_normal_map(texture_path)
        if normal_path:
            bump = rt.Normal_Bump()
            bump.normal_map = rt.BitmapTexture(filename=normal_path)
            mat.bumpMap = bump
            mat.bumpMapAmount = 100
        return mat

    @staticmethod
    def get_or_create_multimaterial(obj):
        current = obj.material
        if current is not None:
            if str(rt.classOf(current)) == "Multimaterial":
                return current

        safe = _safe_name(obj)
        if current is None:
            rt.execute(f"""(
                local m = Multimaterial numsubs:2 name:"LE_Multi"
                m[1] = StandardMaterial name:"LE_Reserved1" diffuse:(color 100 100 100)
                m[2] = StandardMaterial name:"LE_Default2" diffuse:(color 150 150 150)
                $'{safe}'.material = m
            )""")
        else:
            rt.execute(f"""(
                local old = $'{safe}'.material
                local m = Multimaterial numsubs:2 name:"LE_Multi"
                m[1] = StandardMaterial name:"LE_Reserved1" diffuse:(color 100 100 100)
                m[2] = old
                $'{safe}'.material = m
            )""")
        return obj.material

    @staticmethod
    def _find_sub_slot_for_texture(obj, texture_path: str) -> int | None:
        norm = os.path.normcase(os.path.abspath(texture_path))
        safe = _safe_name(obj)
        try:
            n = int(rt.execute(f"$'{safe}'.material.numsubs"))
        except Exception:
            return None
        for i in range(1, n + 1):
            try:
                path_str = rt.execute(
                    f"try($'{safe}'.material[{i}].diffuseMap.filename)catch(\"\")"
                )
                if path_str:
                    existing = os.path.normcase(os.path.abspath(str(path_str)))
                    if existing == norm:
                        return i
            except Exception:
                continue
        return None

    @staticmethod
    def apply_texture_to_faces(obj, face_indices: list[int], texture_path: str):
        TextureOps.get_or_create_multimaterial(obj)
        safe = _safe_name(obj)

        slot = TextureOps._find_sub_slot_for_texture(obj, texture_path)
        if slot is None:
            n = int(rt.execute(f"$'{safe}'.material.numsubs"))
            new_n = n + 1
            rt.execute(f"$'{safe}'.material.numsubs = {new_n}")
            tex_escaped = texture_path.replace("\\", "\\\\").replace('"', '\\"')
            mat_name = "LE_" + os.path.splitext(os.path.basename(texture_path))[0]
            mat_name_escaped = mat_name.replace('"', '\\"')
            normal_path = TextureOps.find_normal_map(texture_path)
            normal_lines = ""
            if normal_path:
                norm_escaped = normal_path.replace("\\", "\\\\").replace('"', '\\"')
                normal_lines = (
                    f"\nm.bumpMap = Normal_Bump()"
                    f'\nm.bumpMap.normal_map = BitmapTexture filename:"{norm_escaped}"'
                    f"\nm.bumpMapAmount = 100"
                )
            rt.execute(f"""(
                local m = StandardMaterial name:"{mat_name_escaped}"
                m.diffuseMap = BitmapTexture filename:"{tex_escaped}"
                m.showInViewport = true{normal_lines}
                $'{safe}'.material[{new_n}] = m
            )""")
            slot = new_n

        face_bits = ", ".join(str(fi) for fi in face_indices)
        rt.execute(f"""(try(
            local o = $'{safe}'
            for fi in #({face_bits}) do polyop.setFaceMatID o fi {slot}
        )catch(print (getCurrentException())))""")

    @staticmethod
    def apply_texture_to_object(obj, texture_path: str):
        if not TextureOps.ensure_editable_poly(obj):
            return

        num_faces = TextureOps._get_num_faces(obj)
        if num_faces > 0:
            faces = list(range(1, num_faces + 1))
            TextureOps.apply_texture_to_faces(obj, faces, texture_path)

        rt.redrawViews()

    @staticmethod
    def get_face_texture_path(obj, face_index: int) -> str | None:
        safe = _safe_name(obj)
        try:
            mat = obj.material
            if mat is None:
                return None
            cls = str(rt.classOf(mat))
            if cls == "Multimaterial":
                mat_id = int(rt.execute(f"polyop.getFaceMatID $'{safe}' {face_index}"))
                path = rt.execute(
                    f"try($'{safe}'.material[{mat_id}].diffuseMap.filename)catch(\"\")"
                )
                return str(path) if path else None
            else:
                try:
                    return str(mat.diffuseMap.filename) if mat.diffuseMap else None
                except Exception:
                    return None
        except Exception:
            return None

    @staticmethod
    def get_face_uvs(obj, face_index: int, map_channel: int = 1) -> list[tuple]:
        safe = _safe_name(obj)
        try:
            map_face = rt.execute(
                f"polyop.getMapFace $'{safe}' {map_channel} {face_index}"
            )
            if map_face is None:
                return []
            uvs = []
            for mv_idx in map_face:
                uv = rt.execute(
                    f"polyop.getMapVert $'{safe}' {map_channel} {int(mv_idx)}"
                )
                uvs.append((float(uv.x), float(uv.y)))
            return uvs
        except Exception:
            return []

    @staticmethod
    def set_face_uvs(obj, face_index: int, uvs: list[tuple], map_channel: int = 1):
        safe = _safe_name(obj)
        handle = TextureOps._obj_handle(obj)
        n_new = len(uvs)

        dedicated = TextureOps._face_map_verts.get(handle, {}).get(face_index)
        if dedicated is not None and len(dedicated) == n_new:
            try:
                for i, (u, v) in enumerate(uvs):
                    rt.execute(
                        f"polyop.setMapVert $'{safe}' {map_channel} "
                        f"{dedicated[i]} (point3 {u} {v} 0)"
                    )
                return
            except Exception:
                TextureOps._face_map_verts.get(handle, {}).pop(face_index, None)

        try:
            num = int(rt.execute(f"polyop.getNumMapVerts $'{safe}' {map_channel}"))
            new_start = num + 1

            rt.execute(
                f"polyop.setNumMapVerts $'{safe}' {map_channel} {num + n_new} keep:true"
            )

            new_indices = []
            for i, (u, v) in enumerate(uvs):
                idx = new_start + i
                rt.execute(
                    f"polyop.setMapVert $'{safe}' {map_channel} "
                    f"{idx} (point3 {u} {v} 0)"
                )
                new_indices.append(idx)

            idx_str = ", ".join(str(idx) for idx in new_indices)
            rt.execute(
                f"polyop.setMapFace $'{safe}' {map_channel} {face_index} #({idx_str})"
            )

            TextureOps._face_map_verts.setdefault(handle, {})[face_index] = new_indices
        except Exception:
            pass

    @staticmethod
    def get_face_normal(obj, face_index: int) -> tuple:
        safe = _safe_name(obj)
        try:
            n = rt.execute(f"polyop.getFaceNormal $'{safe}' {face_index}")
            return (float(n.x), float(n.y), float(n.z))
        except Exception:
            return (0.0, 0.0, 1.0)

    @staticmethod
    def get_face_center(obj, face_index: int) -> tuple:
        safe = _safe_name(obj)
        try:
            c = rt.execute(f"polyop.getFaceCenter $'{safe}' {face_index}")
            return (float(c.x), float(c.y), float(c.z))
        except Exception:
            return (0.0, 0.0, 0.0)

    @staticmethod
    def get_face_verts_world(obj, face_index: int) -> list[tuple]:
        safe = _safe_name(obj)
        try:
            vert_indices = rt.execute(f"polyop.getFaceVerts $'{safe}' {face_index}")
            if vert_indices is None:
                return []
            verts = []
            for vi in vert_indices:
                pos = rt.execute(f"polyop.getVert $'{safe}' {int(vi)}")
                wp = pos * obj.transform
                verts.append((float(wp.x), float(wp.y), float(wp.z)))
            return verts
        except Exception:
            return []

    @staticmethod
    def apply_uv_transform(
        obj,
        face_indices: list[int],
        tile_u: float = 1.0,
        tile_v: float = 1.0,
        rotation_deg: float = 0.0,
        offset_u: float = 0.0,
        offset_v: float = 0.0,
        map_channel: int = 1,
        *,
        redraw: bool = True,
        store: bool = True,
    ):
        if not TextureOps._is_base_editable_poly(obj):
            if redraw:
                rt.redrawViews()
            return

        from . import uv_math

        if store:
            TextureOps.store_face_uv_params(
                obj,
                face_indices,
                tile_u,
                tile_v,
                rotation_deg,
                offset_u,
                offset_v,
            )

        inv_tile = 1.0 / WORLD_TILE_SIZE
        rot_rad = math.radians(rotation_deg)
        cos_r = math.cos(rot_rad)
        sin_r = math.sin(rot_rad)

        for fi in face_indices:
            verts = TextureOps.get_face_verts_world(obj, fi)
            if len(verts) < 3:
                continue

            normal = uv_math.compute_polygon_normal(verts)

            u_axis, v_axis = uv_math.quake_axes(normal)

            new_uvs = []
            for vert in verts:
                raw_u = uv_math.vec_dot(vert, u_axis) * inv_tile * tile_u
                raw_v = uv_math.vec_dot(vert, v_axis) * inv_tile * tile_v
                u = raw_u * cos_r - raw_v * sin_r + offset_u
                v = raw_u * sin_r + raw_v * cos_r + offset_v
                new_uvs.append((u, v))
            TextureOps.set_face_uvs(obj, fi, new_uvs, map_channel)

        TextureOps.reselect_faces(obj, face_indices)

        if redraw:
            rt.redrawViews()

    @staticmethod
    def read_face_uv_properties(obj, face_index: int, map_channel: int = 1) -> dict:
        from . import uv_math

        verts = TextureOps.get_face_verts_world(obj, face_index)
        uvs = TextureOps.get_face_uvs(obj, face_index, map_channel)
        if len(verts) < 2 or len(uvs) < 2:
            return {
                "tile_u": 1.0,
                "tile_v": 1.0,
                "rotation": 0.0,
                "offset_u": 0.0,
                "offset_v": 0.0,
            }

        return uv_math.decompose_uv_properties(verts, uvs, WORLD_TILE_SIZE)

    @staticmethod
    def _edge_matched_params(
        source_obj, source_face: int, target_obj, target_face: int, params: dict
    ) -> tuple[float, float, float, float]:
        """Compute corrected tile and offset values for seamless continuation.

        When source and target faces fall into different quake axis groups,
        this method:
        1. Detects if the texture flow direction reverses (e.g. V axis
           switches from Z to Y) and negates the tile to compensate.
        2. Computes offset corrections so UVs match at the shared edge.

        Returns (tile_u, tile_v, offset_u, offset_v).
        """
        from . import uv_math

        orig_tu = params["tile_u"]
        orig_tv = params["tile_v"]
        orig_ou = params["offset_u"]
        orig_ov = params["offset_v"]

        src_verts = TextureOps.get_face_verts_world(source_obj, source_face)
        tgt_verts = TextureOps.get_face_verts_world(target_obj, target_face)

        if len(src_verts) < 3 or len(tgt_verts) < 3:
            return orig_tu, orig_tv, orig_ou, orig_ov

        src_normal = uv_math.compute_polygon_normal(src_verts)
        src_u, src_v = uv_math.quake_axes(src_normal)

        tgt_normal = uv_math.compute_polygon_normal(tgt_verts)
        tgt_u, tgt_v = uv_math.quake_axes(tgt_normal)

        if src_u == tgt_u and src_v == tgt_v:
            return orig_tu, orig_tv, orig_ou, orig_ov

        TOLERANCE = 0.05
        shared = []
        non_shared_tgt = []
        for tv in tgt_verts:
            found = False
            for sv in src_verts:
                if (
                    abs(sv[0] - tv[0]) < TOLERANCE
                    and abs(sv[1] - tv[1]) < TOLERANCE
                    and abs(sv[2] - tv[2]) < TOLERANCE
                ):
                    shared.append(sv)
                    found = True
                    break
            if not found:
                non_shared_tgt.append(tv)

        if not shared:
            return orig_tu, orig_tv, orig_ou, orig_ov

        tile_u = orig_tu
        tile_v = orig_tv

        if non_shared_tgt:
            edge_c = (
                sum(v[0] for v in shared) / len(shared),
                sum(v[1] for v in shared) / len(shared),
                sum(v[2] for v in shared) / len(shared),
            )
            interior = (
                sum(v[0] for v in non_shared_tgt) / len(non_shared_tgt),
                sum(v[1] for v in non_shared_tgt) / len(non_shared_tgt),
                sum(v[2] for v in non_shared_tgt) / len(non_shared_tgt),
            )
            D = uv_math.vec_sub(interior, edge_c)

            su = uv_math.vec_dot(D, src_u)
            tu = uv_math.vec_dot(D, tgt_u)
            if su * tu < -1e-6:
                tile_u = -tile_u

            sv = uv_math.vec_dot(D, src_v)
            tv = uv_math.vec_dot(D, tgt_v)
            if sv * tv < -1e-6:
                tile_v = -tile_v

        inv_tile = 1.0 / WORLD_TILE_SIZE
        rot_rad = math.radians(params["rotation"])
        cos_r = math.cos(rot_rad)
        sin_r = math.sin(rot_rad)

        sum_du = 0.0
        sum_dv = 0.0
        for V in shared:
            ru_s = uv_math.vec_dot(V, src_u) * inv_tile * orig_tu
            rv_s = uv_math.vec_dot(V, src_v) * inv_tile * orig_tv
            u_src = ru_s * cos_r - rv_s * sin_r + orig_ou
            v_src = ru_s * sin_r + rv_s * cos_r + orig_ov

            ru_t = uv_math.vec_dot(V, tgt_u) * inv_tile * tile_u
            rv_t = uv_math.vec_dot(V, tgt_v) * inv_tile * tile_v
            u_tgt0 = ru_t * cos_r - rv_t * sin_r
            v_tgt0 = ru_t * sin_r + rv_t * cos_r

            sum_du += u_src - u_tgt0
            sum_dv += v_src - v_tgt0

        n = len(shared)
        return tile_u, tile_v, sum_du / n, sum_dv / n

    @staticmethod
    def continue_texture(
        obj, source_face: int, target_faces: list[int], map_channel: int = 1
    ):
        safe = _safe_name(obj)
        try:
            src_mat_id = int(rt.execute(f"polyop.getFaceMatID $'{safe}' {source_face}"))
        except Exception:
            src_mat_id = 1
        for tf in target_faces:
            try:
                rt.execute(f"polyop.setFaceMatID $'{safe}' {tf} {src_mat_id}")
            except Exception:
                pass

        params = TextureOps.get_face_uv_params(obj, source_face)
        if params is None:
            params = TextureOps.read_face_uv_properties(obj, source_face, map_channel)

        for tf in target_faces:
            tu, tv, ou, ov = TextureOps._edge_matched_params(
                obj, source_face, obj, tf, params
            )
            TextureOps.apply_uv_transform(
                obj,
                [tf],
                tu,
                tv,
                params["rotation"],
                ou,
                ov,
                map_channel,
                redraw=False,
                store=True,
            )
        rt.redrawViews()

    @staticmethod
    def continue_texture_cross_object(
        source_obj,
        source_face: int,
        target_obj,
        target_faces: list[int],
        map_channel: int = 1,
    ):
        tex_path = TextureOps.get_face_texture_path(source_obj, source_face)
        if tex_path:
            TextureOps.apply_texture_to_faces(target_obj, target_faces, tex_path)

        params = TextureOps.get_face_uv_params(source_obj, source_face)
        if params is None:
            params = TextureOps.read_face_uv_properties(
                source_obj, source_face, map_channel
            )

        for tf in target_faces:
            tu, tv, ou, ov = TextureOps._edge_matched_params(
                source_obj, source_face, target_obj, tf, params
            )
            TextureOps.apply_uv_transform(
                target_obj,
                [tf],
                tu,
                tv,
                params["rotation"],
                ou,
                ov,
                map_channel,
                redraw=False,
                store=True,
            )
        rt.redrawViews()

    @staticmethod
    def raycast_face_under_cursor():
        try:
            result = rt.execute("""(
                local r = mapScreenToWorldRay mouse.pos
                if r == undefined then #(undefined, 0)
                else (
                    local bestObj = undefined
                    local bestFace = 0
                    local bestDist = 1e30

                    for o in geometry do (
                        if not o.isHidden and not o.isFrozen do (
                            local hit = undefined
                            try (hit = intersectRay o r) catch ()
                            if hit != undefined do (
                                local hitPos = hit.pos
                                local d = distance r.pos hitPos
                                if d < bestDist do (
                                    local faceIdx = 0
                                    try (
                                        local localHit = hitPos * (inverse o.transform)
                                        local nf = polyop.getNumFaces o
                                        local closestD = 1e30
                                        for fi = 1 to nf do (
                                            local fc = polyop.getFaceCenter o fi
                                            local dd = distance localHit fc
                                            if dd < closestD do (
                                                closestD = dd
                                                faceIdx = fi
                                            )
                                        )
                                    ) catch (
                                        faceIdx = 0
                                    )
                                    if faceIdx > 0 do (
                                        bestDist = d
                                        bestObj = o
                                        bestFace = faceIdx
                                    )
                                )
                            )
                        )
                    )
                    #(bestObj, bestFace)
                )
            )""")

            if result is None:
                return None, None

            obj = result[0]
            face = int(result[1])
            if obj is None or face <= 0:
                return None, None
            if not rt.isValidNode(obj):
                return None, None
            return obj, face
        except Exception:
            return None, None

    @staticmethod
    def reproject_object(obj, map_channel: int = 1):
        if TextureOps._reprojecting:
            return
        if not TextureOps._is_base_editable_poly(obj):
            return

        stored = TextureOps.get_all_face_uv_params(obj)
        if not stored:
            return

        safe = _safe_name(obj)
        handle = TextureOps._obj_handle(obj)
        obj_map = TextureOps._face_map_verts.get(handle, {})

        from . import uv_math

        inv_tile = 1.0 / WORLD_TILE_SIZE

        TextureOps._reprojecting = True
        try:
            face_list = sorted(stored.keys())
            read_script = f"""undo off (
                local o = $'{safe}'
                local xf = o.transform
                local result = #()
                local faces = #({", ".join(str(f) for f in face_list)})
                for fi in faces do (
                    local vis = polyop.getFaceVerts o fi
                    local faceData = #(fi, vis.count)
                    for vi in vis do (
                        local wp = (polyop.getVert o vi) * xf
                        append faceData wp.x
                        append faceData wp.y
                        append faceData wp.z
                    )
                    append result faceData
                )
                result
            )"""

            try:
                all_face_data = rt.execute(read_script)
            except Exception:
                return

            if all_face_data is None:
                return

            inplace_writes: list[tuple[int, float, float]] = []
            new_alloc_faces: list[tuple[int, list[tuple]]] = []

            for faceData in all_face_data:
                arr = list(faceData)
                fi = int(arr[0])
                nv = int(arr[1])

                verts = []
                for vi in range(nv):
                    base = 2 + vi * 3
                    verts.append(
                        (float(arr[base]), float(arr[base + 1]), float(arr[base + 2]))
                    )

                if len(verts) < 3:
                    continue

                params = stored.get(fi)
                if params is None:
                    continue

                t_u = params["tile_u"]
                t_v = params["tile_v"]
                rot = params["rotation"]
                o_u = params["offset_u"]
                o_v = params["offset_v"]

                normal = uv_math.compute_polygon_normal(verts)
                u_axis, v_axis = uv_math.quake_axes(normal)

                rot_rad = math.radians(rot)
                cos_r = math.cos(rot_rad)
                sin_r = math.sin(rot_rad)

                uvs = []
                for vert in verts:
                    raw_u = uv_math.vec_dot(vert, u_axis) * inv_tile * t_u
                    raw_v = uv_math.vec_dot(vert, v_axis) * inv_tile * t_v
                    u = raw_u * cos_r - raw_v * sin_r + o_u
                    v = raw_u * sin_r + raw_v * cos_r + o_v
                    uvs.append((u, v))

                dedicated = obj_map.get(fi)
                if dedicated is not None and len(dedicated) == len(uvs):
                    for mi, (u, v) in zip(dedicated, uvs):
                        inplace_writes.append((mi, u, v))
                else:
                    new_alloc_faces.append((fi, uvs))

            if not inplace_writes and not new_alloc_faces:
                return

            old_count = None
            if new_alloc_faces:
                try:
                    old_count = int(
                        rt.execute(f"polyop.getNumMapVerts $'{safe}' {map_channel}")
                    )
                except Exception:
                    old_count = None

            lines = [f"undo off (local o = $'{safe}'", f"local ch = {map_channel}"]

            if inplace_writes:
                data_items = []
                for mi, u, v in inplace_writes:
                    data_items.extend([str(mi), f"{u:.6f}", f"{v:.6f}"])
                lines.append(f"local d = #({', '.join(data_items)})")
                lines.append(
                    "for i = 1 to d.count by 3 do "
                    "(polyop.setMapVert o ch (d[i] as integer) "
                    "(point3 d[i+1] d[i+2] 0))"
                )

            if new_alloc_faces and old_count is not None:
                total_new = sum(len(uvs) for _, uvs in new_alloc_faces)
                lines.append(
                    f"polyop.setNumMapVerts o ch {old_count + total_new} keep:true"
                )
                idx = old_count + 1
                for fi, uvs in new_alloc_faces:
                    for u, v in uvs:
                        lines.append(
                            f"polyop.setMapVert o ch {idx} (point3 {u:.6f} {v:.6f} 0)"
                        )
                        idx += 1
                idx = old_count + 1
                for fi, uvs in new_alloc_faces:
                    nv = len(uvs)
                    idxs = ", ".join(str(idx + i) for i in range(nv))
                    lines.append(f"polyop.setMapFace o ch {fi} #({idxs})")
                    idx += nv

            lines.append(")")
            write_script = "\n".join(lines)

            try:
                rt.execute(write_script)

                if new_alloc_faces and old_count is not None:
                    idx = old_count + 1
                    obj_store = TextureOps._face_map_verts.setdefault(handle, {})
                    for fi, uvs in new_alloc_faces:
                        obj_store[fi] = list(range(idx, idx + len(uvs)))
                        idx += len(uvs)
            except Exception:
                pass

        finally:
            TextureOps._reprojecting = False
            TextureOps._last_reproject_time = time.time()

        TextureOps.refresh_tracking(obj)

        try:
            rt.redrawViews()
        except Exception:
            pass

    @staticmethod
    def recover_face_params(obj, map_channel: int = 1) -> dict | None:
        """Read current scene UVs and world-space verts for all stored faces,
        then solve for new tile/rot/offset params that reproduce those UVs.
        Updates _face_uv_store in place.  Returns the recovered params dict
        (keyed by face index) or None on failure."""
        if not TextureOps._is_base_editable_poly(obj):
            return None

        handle = TextureOps._obj_handle(obj)
        stored = TextureOps._face_uv_store.get(handle)
        if not stored:
            return None

        from . import uv_math

        safe = _safe_name(obj)
        face_list = sorted(stored.keys())

        read_script = f"""undo off (
            local o = $'{safe}'
            local xf = o.transform
            local ch = {map_channel}
            local faces = #({", ".join(str(f) for f in face_list)})
            local result = #()
            for fi in faces do (
                local vis = polyop.getFaceVerts o fi
                local nv = vis.count
                local faceData = #(fi, nv)
                for vi in vis do (
                    local wp = (polyop.getVert o vi) * xf
                    append faceData wp.x
                    append faceData wp.y
                    append faceData wp.z
                )
                local mf = polyop.getMapFace o ch fi
                for mi in mf do (
                    local mv = polyop.getMapVert o ch mi
                    append faceData mv.x
                    append faceData mv.y
                )
                append result faceData
            )
            result
        )"""

        try:
            all_face_data = rt.execute(read_script)
        except Exception:
            return None
        if all_face_data is None:
            return None

        recovered = {}
        for faceData in all_face_data:
            arr = list(faceData)
            fi = int(arr[0])
            nv = int(arr[1])
            if nv < 3:
                continue

            verts = []
            for vi in range(nv):
                base = 2 + vi * 3
                verts.append(
                    (float(arr[base]), float(arr[base + 1]), float(arr[base + 2]))
                )

            uv_base = 2 + nv * 3
            uvs = []
            for ui in range(nv):
                base = uv_base + ui * 2
                uvs.append((float(arr[base]), float(arr[base + 1])))

            if len(verts) < 3 or len(uvs) < 3:
                continue

            proj = uv_math.recover_projection(
                verts[0],
                verts[1],
                verts[2],
                uvs[0],
                uvs[1],
                uvs[2],
            )
            if proj is None:
                continue

            u_eff, v_eff, off_u, off_v = proj

            normal = uv_math.compute_polygon_normal(verts)
            q_u, q_v = uv_math.quake_axes(normal)

            new_params = uv_math.decompose_from_recovered_axes(
                u_eff,
                v_eff,
                off_u,
                off_v,
                q_u,
                q_v,
                WORLD_TILE_SIZE,
            )
            stored[fi] = new_params
            recovered[fi] = new_params

        TextureOps.refresh_tracking(obj)
        return recovered if recovered else None

    @staticmethod
    def project_new_faces(obj, map_channel: int = 1):
        if not TextureOps._is_base_editable_poly(obj):
            return

        handle = TextureOps._obj_handle(obj)

        TextureOps._face_map_verts.pop(handle, None)

        stored = TextureOps._face_uv_store.get(handle, {})
        if not stored:
            return

        safe = _safe_name(obj)
        try:
            num_faces = int(rt.execute(f"undo off (polyop.getNumFaces $'{safe}')"))
        except Exception:
            return

        stale = [fi for fi in stored if fi > num_faces]
        for fi in stale:
            del TextureOps._face_uv_store[handle][fi]
        if stale:
            stored = TextureOps._face_uv_store.get(handle, {})

        new_faces = [fi for fi in range(1, num_faces + 1) if fi not in stored]
        if not new_faces:
            return

        new_str = ", ".join(str(f) for f in new_faces)
        adj_map: dict[int, list[int]] = {}
        try:
            adj_data = rt.execute(f"""undo off (
                local o = $'{safe}'
                local result = #()
                for fi in #({new_str}) do (
                    local edges = polyop.getEdgesUsingFace o #{{fi}}
                    local adj = (polyop.getFacesUsingEdge o edges) as array
                    local idx = findItem adj fi
                    if idx > 0 do deleteItem adj idx
                    append result adj
                )
                result
            )""")
            if adj_data and len(adj_data) == len(new_faces):
                for i, fi in enumerate(new_faces):
                    adj_map[fi] = [int(f) for f in adj_data[i]] if adj_data[i] else []
        except Exception:
            pass

        unprocessed = list(new_faces)
        for _ in range(4):
            still_unprocessed = []
            for fi in unprocessed:
                current_store = TextureOps._face_uv_store.get(handle, {})
                source_fi = None
                for af in adj_map.get(fi, []):
                    if af in current_store:
                        source_fi = af
                        break
                if source_fi is None:
                    still_unprocessed.append(fi)
                    continue
                source_params = current_store[source_fi]
                try:
                    tu, tv, ou, ov = TextureOps._edge_matched_params(
                        obj,
                        source_fi,
                        obj,
                        fi,
                        source_params,
                    )
                except Exception:
                    tu = source_params["tile_u"]
                    tv = source_params["tile_v"]
                    ou = source_params["offset_u"]
                    ov = source_params["offset_v"]
                TextureOps.apply_uv_transform(
                    obj,
                    [fi],
                    tu,
                    tv,
                    source_params["rotation"],
                    ou,
                    ov,
                    map_channel,
                    redraw=False,
                    store=True,
                )
            if len(still_unprocessed) == len(unprocessed):
                break
            unprocessed = still_unprocessed

        if unprocessed:
            fallback = next(iter(stored.values()))
            mid_str = ", ".join(str(f) for f in unprocessed)
            try:
                fb_mids = rt.execute(f"""undo off (
                    local result = #()
                    for fi in #({mid_str}) do
                        append result (polyop.getFaceMatID $'{safe}' fi)
                    result
                )""")
                fb_mids = [int(m) for m in fb_mids] if fb_mids else []
            except Exception:
                fb_mids = []

            mat_to_params: dict[int, dict] = {}
            sample = list(stored.items())[:64]
            if sample:
                sample_str = ", ".join(str(fi) for fi, _ in sample)
                try:
                    sample_mids = rt.execute(f"""undo off (
                        local result = #()
                        for fi in #({sample_str}) do
                            append result (polyop.getFaceMatID $'{safe}' fi)
                        result
                    )""")
                    if sample_mids:
                        for (sfi, params), mid in zip(sample, sample_mids):
                            mid = int(mid)
                            if mid not in mat_to_params:
                                mat_to_params[mid] = params
                except Exception:
                    pass

            for i, fi in enumerate(unprocessed):
                mid = fb_mids[i] if i < len(fb_mids) else -1
                params = mat_to_params.get(mid, fallback)
                TextureOps.apply_uv_transform(
                    obj,
                    [fi],
                    params["tile_u"],
                    params["tile_v"],
                    params["rotation"],
                    params["offset_u"],
                    params["offset_v"],
                    map_channel,
                    redraw=False,
                    store=True,
                )

    @staticmethod
    def consolidate_materials_for_export():
        tex_to_mat: dict[str, object] = {}

        for obj in rt.objects:
            mat = obj.material
            if mat is None:
                continue
            cls = str(rt.classOf(mat))

            if cls == "Multimaterial":
                try:
                    n = int(mat.numsubs)
                except Exception:
                    continue
                for i in range(1, n + 1):
                    try:
                        sub = mat[i]
                        if sub is None:
                            continue
                        dm = sub.diffuseMap
                        if dm is None:
                            continue
                        key = os.path.normcase(os.path.abspath(str(dm.filename)))
                        if key not in tex_to_mat:
                            tex_to_mat[key] = sub
                    except Exception:
                        continue

            elif cls == "Standardmaterial":
                try:
                    dm = mat.diffuseMap
                    if dm is None:
                        continue
                    key = os.path.normcase(os.path.abspath(str(dm.filename)))
                    if key not in tex_to_mat:
                        tex_to_mat[key] = mat
                except Exception:
                    continue

        if not tex_to_mat:
            return

        for obj in rt.objects:
            mat = obj.material
            if mat is None:
                continue
            cls = str(rt.classOf(mat))

            if cls == "Multimaterial":
                try:
                    n = int(mat.numsubs)
                except Exception:
                    continue
                for i in range(1, n + 1):
                    try:
                        sub = mat[i]
                        if sub is None:
                            continue
                        dm = sub.diffuseMap
                        if dm is None:
                            continue
                        key = os.path.normcase(os.path.abspath(str(dm.filename)))
                        canonical = tex_to_mat.get(key)
                        if canonical is not None and canonical is not sub:
                            mat[i] = canonical
                    except Exception:
                        continue

            elif cls == "Standardmaterial":
                try:
                    dm = mat.diffuseMap
                    if dm is None:
                        continue
                    key = os.path.normcase(os.path.abspath(str(dm.filename)))
                    canonical = tex_to_mat.get(key)
                    if canonical is not None and canonical is not mat:
                        obj.material = canonical
                except Exception:
                    continue

    @staticmethod
    def _get_active_edit_poly():
        """Check if the user is currently editing inside an Edit_Poly modifier."""
        try:
            rt.execute("max modify mode")
            mod = rt.modPanel.getCurrentObject()
            if str(rt.classOf(mod)) == "Edit_Poly":
                return mod
        except Exception:
            pass
        return None

    @staticmethod
    def _snapshot_stack_state(obj) -> str:
        """Returns a string representing modifier count and enabled states to detect changes."""
        try:
            return str(
                rt.execute(f"""(
                local s = ""
                local o = $'{_safe_name(obj)}'
                if o != undefined do (
                    for m in o.modifiers do s += (if m.enabled then "1" else "0")
                )
                s
            )""")
            )
        except Exception:
            return ""

    @staticmethod
    def compile_stack_uvs(obj) -> dict:
        """Evaluates base mesh + modifiers from bottom to top, returning the flattened UV properties."""
        flattened = {}

        try:
            raw_base = rt.getUserProp(obj, "le_face_uvs")
            if raw_base and str(raw_base).strip() not in ("", "undefined"):
                data = json.loads(str(raw_base))
                for fi_str, vals in data.items():
                    flattened[int(fi_str)] = {
                        "tile_u": float(vals[0]),
                        "tile_v": float(vals[1]),
                        "rotation": float(vals[2]),
                        "offset_u": float(vals[3]),
                        "offset_v": float(vals[4]),
                    }
        except Exception:
            pass

        try:
            read_script = f"""(
                local safe_obj = $'{_safe_name(obj)}'
                local results = #()
                if safe_obj != undefined do (
                    for i = safe_obj.modifiers.count to 1 by -1 do (
                        local m = safe_obj.modifiers[i]
                        if m.enabled do (
                            local raw = try(m.le_layer_uvs)catch(undefined)
                            if raw != undefined and raw != "" do append results raw
                        )
                    )
                )
                results
            )"""
            layer_jsons = rt.execute(read_script)
            if layer_jsons:
                for raw_layer in layer_jsons:
                    try:
                        layer_data = json.loads(str(raw_layer))
                        for fi_str, vals in layer_data.items():
                            flattened[int(fi_str)] = {
                                "tile_u": float(vals[0]),
                                "tile_v": float(vals[1]),
                                "rotation": float(vals[2]),
                                "offset_u": float(vals[3]),
                                "offset_v": float(vals[4]),
                            }
                    except Exception:
                        pass
        except Exception:
            pass

        return flattened

    @staticmethod
    def reselect_faces(obj, face_indices: list[int]):
        """Forces the Edit_Poly modifier to visually hold the selection after a disruptive operation."""
        if not face_indices:
            return
        safe = _safe_name(obj)
        face_bits = ", ".join(str(fi) for fi in face_indices)
        rt.execute(f"""(try(
            local o = $'{safe}'
            local ep = undefined
            for m in o.modifiers where classOf m == Edit_Poly do (ep = m; exit)
            if ep != undefined then (
                max modify mode
                if modPanel.getCurrentObject() != ep do modPanel.setCurrentObject ep
                if subObjectLevel != 4 do subObjectLevel = 4
                ep.SetSelection #Face #{{{face_bits}}}
            ) else (
                polyop.setFaceSelection o #{{{face_bits}}}
            )
        )catch())""")
