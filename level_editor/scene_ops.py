"""
Scene operations: entity metadata, custom attributes, triggers, and spawning.
"""

import time
import uuid

from pymxs import runtime as rt

from .maxscript_gen import build_ca_definition, field_to_key
from .models import EntityTemplate


def _safe_name(obj) -> str:
    """Escape a node name for MaxScript $'name' selectors."""
    return str(obj.name).replace("'", "\\'")


class EntityOps:
    field_to_key = staticmethod(field_to_key)

    @staticmethod
    def is_entity(obj) -> bool:
        return rt.getUserProp(obj, "le_entity_type") is not None

    @staticmethod
    def resolve_entity_root(obj):
        cur = obj
        while cur is not None:
            try:
                if EntityOps.is_entity(cur):
                    return cur
                parent = cur.parent
            except Exception:
                parent = None
            if parent is None or str(parent) == "undefined":
                return None
            cur = parent
        return None

    @staticmethod
    def get_all_entities() -> list:
        return [obj for obj in rt.objects if EntityOps.is_entity(obj)]

    @staticmethod
    def set_prop(obj, key: str, val: str):
        rt.setUserProp(obj, key, val)

    @staticmethod
    def get_prop(obj, key: str) -> str | None:
        val = rt.getUserProp(obj, key)
        return str(val) if val is not None else None

    @staticmethod
    def clear_level_editor_custom_attributes(obj):
        safe_name = _safe_name(obj)
        rt.execute(f"""
            if $'{safe_name}' != undefined do (
                for i = ($'{safe_name}'.modifiers.count) to 1 by -1 do (
                    local md = $'{safe_name}'.modifiers[i]
                    if (matchPattern md.name pattern:"LE_*") do (
                        deleteModifier $'{safe_name}' i
                    )
                )
            )

            for i = (custAttributes.count $'{safe_name}') to 1 by -1 do (
                local def = custAttributes.getDef $'{safe_name}' i
                if def != undefined do (
                    local defName = ""
                    try (defName = (def.name as string)) catch (defName = "")
                    if matchPattern defName pattern:"LE_*" do (
                        custAttributes.delete $'{safe_name}' i
                    )
                )
            )

            try (
                for i = (custAttributes.count ($'{safe_name}'.baseObject)) to 1 by -1 do (
                    local def = custAttributes.getDef ($'{safe_name}'.baseObject) i
                    if def != undefined do (
                        local defName = ""
                        try (defName = (def.name as string)) catch (defName = "")
                        if matchPattern defName pattern:"LE_*" do (
                            custAttributes.delete ($'{safe_name}'.baseObject) i
                        )
                    )
                )
            ) catch ()
        """)

    @staticmethod
    def _create_proxy_hierarchy(src_node, parent_node):
        """
        Recursively creates instances/copies of a proxy node and its children,
        attaching them to the specified parent_node (the placed entity root).
        Mirrors the MaxScript le_instance_proxy_children logic.
        """
        instances = []

        visual = None
        try:
            visual = rt.instance(src_node)
        except:
            try:
                visual = rt.copy(src_node)
            except:
                pass

        if visual is None:
            return instances

        try:
            visual.name = f"{src_node.name}_VIS"
        except:
            pass

        try:
            visual.transform = src_node.transform
            visual.position = parent_node.position
            visual.parent = parent_node
            rt.setUserProp(visual, "le_visual_child", "true")
        except:
            pass

        instances.append(visual)

        try:
            children = src_node.children
        except:
            children = []

        for child in children:
            child_insts = EntityOps._create_proxy_hierarchy(child, parent_node)
            instances.extend(child_insts)

        return instances

    @staticmethod
    def apply_template(obj, template: EntityTemplate):
        EntityOps.set_prop(obj, "le_entity_type", template.name)

        trig_id_keys = [
            field_to_key(f.name)
            for f in template.fields
            if f.field_type == "trigger_id"
        ]
        trig_ref_keys = [
            field_to_key(f.name)
            for f in template.fields
            if f.field_type == "trigger_ref"
        ]

        if template.is_trigger or bool(trig_id_keys):
            EntityOps.set_prop(obj, "le_is_trigger", "true")

        key_list = [field_to_key(f.name) for f in template.fields]
        EntityOps.set_prop(obj, "le_meta_keys", ",".join(key_list))
        EntityOps.set_prop(obj, "le_trigger_id_keys", ",".join(trig_id_keys))
        EntityOps.set_prop(obj, "le_trigger_ref_keys", ",".join(trig_ref_keys))

        EntityOps._apply_custom_attributes(obj, template)

        if trig_id_keys:
            first_key = trig_id_keys[0]
            cur = EntityOps.get_meta(obj, first_key).strip()
            if not cur:
                EntityOps.set_meta(obj, first_key, uuid.uuid4().hex[:10])

    @staticmethod
    def _apply_custom_attributes(obj, template: EntityTemplate):
        if not template.fields:
            return

        safe_name = _safe_name(obj)

        EntityOps.clear_level_editor_custom_attributes(obj)

        ca_name = f"LE_{field_to_key(template.name)}_{int(time.time() * 1000)}"
        ca_def = build_ca_definition(template, ca_name=ca_name)
        if not ca_def:
            return

        holder_name = f"LE_{field_to_key(template.name)}_Attrs"

        maxscript = f"""(
            local le_ca_def = {ca_def}
            local n = $'{safe_name}'
            if n != undefined then (
                local h = EmptyModifier()
                h.name = "{holder_name}"
                addModifier n h
                custAttributes.add h le_ca_def #unique
            )
        )"""

        try:
            rt.execute(maxscript)
        except Exception as e:
            print(f"[LevelEditor] Custom attributes error: {e}")
            print(f"[LevelEditor] Generated MaxScript:\n{maxscript[:500]}")

    @staticmethod
    def get_meta_keys(obj) -> list[str]:
        raw = EntityOps.get_prop(obj, "le_meta_keys")
        if not raw:
            return []
        return [k.strip() for k in raw.split(",") if k.strip()]

    @staticmethod
    def get_meta(obj, key: str) -> str:
        safe_name = _safe_name(obj)
        safe_key = field_to_key(key)
        try:
            val = rt.execute(f"""(
                local n = $'{safe_name}'
                local k = #{safe_key}
                local out = undefined
                if n != undefined do (
                    for i = 1 to n.modifiers.count while out == undefined do (
                        local m = n.modifiers[i]
                        if (matchPattern m.name pattern:"LE_*") then (
                            out = try (getProperty m k) catch (undefined)
                        )
                    )
                    if out == undefined do out = try (getProperty n k) catch (undefined)
                )
                out
            )""")
            if val is not None and str(val) != "undefined":
                out = str(val)
                if key in EntityOps.get_trigger_ref_keys(obj):
                    if (
                        out.strip()
                        and EntityOps.find_trigger_by_id(out.strip()) is None
                    ):
                        EntityOps.set_meta(obj, key, "")
                        return ""
                return out
        except Exception:
            pass
        val = EntityOps.get_prop(obj, f"le_meta_{key}")
        return val if val is not None else ""

    @staticmethod
    def set_meta(obj, key: str, value: str):
        safe_name = _safe_name(obj)
        safe_key = field_to_key(key)
        safe_value = str(value).replace("\\", "\\\\").replace('"', '\\"')
        try:
            rt.execute(f"""(
                local n = $'{safe_name}'
                local k = #{safe_key}
                if n != undefined do (
                    local didSet = false
                    for i = 1 to n.modifiers.count while didSet == false do (
                        local m = n.modifiers[i]
                        if (matchPattern m.name pattern:"LE_*") then (
                            try (setProperty m k \"{safe_value}\"; didSet = true) catch ()
                        )
                    )
                    if didSet == false do try (setProperty n k \"{safe_value}\") catch ()
                )
            )""")
        except Exception:
            pass

    @staticmethod
    def get_trigger_id_keys(obj) -> list[str]:
        raw = EntityOps.get_prop(obj, "le_trigger_id_keys")
        if not raw:
            return []
        return [k.strip() for k in raw.split(",") if k.strip()]

    @staticmethod
    def get_trigger_ref_keys(obj) -> list[str]:
        raw = EntityOps.get_prop(obj, "le_trigger_ref_keys")
        if not raw:
            return []
        return [k.strip() for k in raw.split(",") if k.strip()]

    @staticmethod
    def find_trigger_by_id(trigger_id: str):
        value = (trigger_id or "").strip()
        if not value:
            return None
        for obj in EntityOps.get_all_entities():
            if not EntityOps.get_trigger_id_keys(obj):
                continue
            for key in EntityOps.get_trigger_id_keys(obj):
                if EntityOps.get_meta(obj, key).strip() == value:
                    return obj
        return None

    @staticmethod
    def get_trigger_refs(obj) -> list[str]:
        raw = EntityOps.get_prop(obj, "le_trigger_refs")
        if not raw:
            return []
        return [r.strip() for r in raw.split(",") if r.strip()]

    @staticmethod
    def set_trigger_refs(obj, refs: list[str]):
        EntityOps.set_prop(obj, "le_trigger_refs", ", ".join(refs))

    @staticmethod
    def spawn_entity_at(template: EntityTemplate, pos=None):
        name = f"{template.name}_{int(time.time() * 1000)}"
        root = rt.Point(
            name=name,
            size=10,
            box=True,
            cross=False,
            centermarker=False,
            axisTripod=False,
        )
        print(f"Spawning entity '{name}' from template '{template.name}'")

        if pos is not None:
            root.position = pos

        visual_instances = []
        src = rt.getNodeByName(template.proxy_model) if template.proxy_model else None

        if src is not None:
            visual_instances = EntityOps._create_proxy_hierarchy(src, root)

        try:
            rt.unhide(root)
        except:
            pass

        for v in visual_instances:
            try:
                rt.unhide(v)
            except:
                pass

        EntityOps.clear_level_editor_custom_attributes(root)
        EntityOps.apply_template(root, template)
        return root
