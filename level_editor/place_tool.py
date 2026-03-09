"""
MaxScript viewport placement tool: register and control the interactive
click-to-place / right-click-to-delete tool.
"""

from pymxs import runtime as rt

from .maxscript_gen import build_ca_definition, field_to_key
from .models import EntityTemplate


def register_place_tool():
    rt.execute("""
        try ( stopTool levelEditorPlaceTool ) catch ()

        global le_place_template_name = ""
        global le_place_is_trigger = false
        global le_place_ca_def = undefined
        global le_place_meta_keys = ""
        global le_place_trigger_id_keys = ""
        global le_place_trigger_ref_keys = ""
        global le_place_proxy_name = ""
        global le_place_keep_running = false

        tool levelEditorPlaceTool numPoints:1 (
            fn le_entity_root_from_node n = (
                local cur = n
                while cur != undefined do (
                    if (getUserProp cur "le_entity_type") != undefined then return cur
                    cur = try (cur.parent) catch (undefined)
                )
                undefined
            )

            fn le_delete_hierarchy rootNode = (
                if isValidNode rootNode do (
                    local children = for c in rootNode.children collect c
                    for c in children do le_delete_hierarchy c
                    try (delete rootNode) catch()
                )
            )

            fn le_instance_proxy_children src parentNode isRoot = (
                local instances = #()
                local inst = undefined
                try (inst = instance src) catch (
                    try (inst = copy src) catch (inst = undefined)
                )

                if inst != undefined do (
                    inst.name = (src.name + "_VIS")

                    if isRoot then (
                        inst.transform = src.transform
                        inst.position = parentNode.position
                    ) else (
                        if src.parent != undefined then (
                            local localTM = src.transform * inverse src.parent.transform
                            inst.transform = localTM * parentNode.transform
                        ) else (
                            inst.transform = src.transform
                        )
                    )

                    inst.parent = parentNode
                    try (inst.wireColor = src.wireColor) catch ()

                    local entityType = getUserProp src "le_entity_type"
                    if entityType != undefined then setUserProp inst "le_entity_type" entityType

                    local triggerIdKeys = getUserProp src "le_trigger_id_keys"
                    if triggerIdKeys != undefined then setUserProp inst "le_trigger_id_keys" triggerIdKeys

                    local triggerRefKeys = getUserProp src "le_trigger_ref_keys"
                    if triggerRefKeys != undefined then setUserProp inst "le_trigger_ref_keys" triggerRefKeys

                    local metaKeys = getUserProp src "le_meta_keys"
                    if metaKeys != undefined then setUserProp inst "le_meta_keys" metaKeys

                    try (setUserProp inst "le_visual_child" "true") catch ()
                    add instances inst

                    local children = #()
                    try (children = for c in src.children collect c) catch (children = #())
                    for child in children do (
                        local childInsts = le_instance_proxy_children child inst false
                        for i = 1 to childInsts.count do add instances childInsts[i]
                    )
                )
                instances
            )

            fn le_clear_level_editor_cas node = (
                if node == undefined then return false

                for i = (node.modifiers.count) to 1 by -1 do (
                    local md = node.modifiers[i]
                    if (matchPattern md.name pattern:"LE_*") do (
                        deleteModifier node i
                    )
                )

                for i = (custAttributes.count node) to 1 by -1 do (
                    local def = custAttributes.getDef node i
                    if def != undefined do (
                        local defName = ""
                        try (defName = (def.name as string)) catch (defName = "")
                        if matchPattern defName pattern:"LE_*" do (
                            custAttributes.delete node i
                        )
                    )
                )
                true
            )

            fn le_pick_entity_under_mouse = (
                local r = mapScreenToWorldRay mouse.pos
                if r == undefined then return undefined

                local bestObj = undefined
                local bestDist = 1e30

                for o in objects do (
                    local root = le_entity_root_from_node o
                    if root != undefined then (
                        local hit = undefined
                        try (hit = intersectRay o r) catch (hit = undefined)
                        if hit != undefined then (
                            local hitPos = undefined
                            try (hitPos = hit.pos) catch ()
                            if hitPos == undefined do try (hitPos = hit) catch ()
                            if hitPos != undefined then (
                                local d = distance r.pos hitPos
                                if d < bestDist then (
                                    bestDist = d
                                    bestObj = root
                                )
                            )
                        )
                    )
                )

                if bestObj != undefined then return bestObj

                local pickThreshold = 30.0
                for o in objects do (
                    local root = le_entity_root_from_node o
                    if root != undefined then (
                        local p = undefined
                        try (p = o.position) catch (p = undefined)
                        if p != undefined then (
                            local v = p - r.pos
                            local t = dot v r.dir
                            if t >= 0 then (
                                local closest = r.pos + (r.dir * t)
                                local dToRay = distance p closest
                                if dToRay <= pickThreshold and dToRay < bestDist then (
                                    bestDist = dToRay
                                    bestObj = root
                                )
                            )
                        )
                    )
                )

                bestObj
            )

            fn le_handle_abort = (
                local obj = le_pick_entity_under_mouse()
                if obj != undefined then (
                    if isValidNode obj then (
                        undo "LevelEditor Delete" on (
                            format "[LevelEditor] Deleted: %\n" obj.name
                            le_delete_hierarchy obj
                        )
                    )
                )
                le_place_keep_running = true
                #stop
            )

            on mousePoint click do (
                undo "LevelEditor Place" on (
                    local ts = timeStamp()
                    local newName = le_place_template_name + "_" + (ts as string)
                    local p = Point name:newName size:10 box:true cross:false centermarker:false axisTripod:false

                    local placePos = worldPoint
                    local r = mapScreenToWorldRay mouse.pos
                    if r != undefined do (
                        local hits = intersectRayScene r
                        if hits != undefined and hits.count > 0 then (
                            local h = hits[1]
                            local hitPos = undefined
                            try (hitPos = h.pos) catch ()
                            if hitPos == undefined do try (hitPos = h[2]) catch ()
                            if isKindOf hitPos Ray do hitPos = hitPos.pos
                            if isKindOf hitPos Point3 do placePos = hitPos
                        )
                    )
                    p.position = placePos

                    local v = undefined

                    if le_place_proxy_name != "" then (
                        local src = getNodeByName le_place_proxy_name exact:true ignoreCase:false
                        if src != undefined then (
                            local visChildren = le_instance_proxy_children src p true
                        )
                    )

                    try (unhide p) catch ()
                    if v != undefined do try (unhide v) catch ()

                    setUserProp p "le_entity_type" le_place_template_name
                    if le_place_is_trigger then setUserProp p "le_is_trigger" "true"
                    if le_place_meta_keys != "" then setUserProp p "le_meta_keys" le_place_meta_keys
                    if le_place_trigger_id_keys != "" then setUserProp p "le_trigger_id_keys" le_place_trigger_id_keys
                    if le_place_trigger_ref_keys != "" then setUserProp p "le_trigger_ref_keys" le_place_trigger_ref_keys

                    if le_place_ca_def != undefined then (
                        try (
                            le_clear_level_editor_cas p
                            local h = EmptyModifier()
                            h.name = ("LE_" + le_place_template_name + "_Attrs")
                            addModifier p h
                            custAttributes.add h le_place_ca_def #unique

                            if le_place_trigger_id_keys != "" then (
                                local keys = filterString le_place_trigger_id_keys ","
                                if keys.count > 0 then (
                                    local k = trimRight (trimLeft keys[1])
                                    if k != "" then (
                                        local sym = execute ("#" + k)
                                        local cur = try (getProperty h sym) catch (undefined)
                                        if cur == undefined or (cur as string) == "" do (
                                            try (setProperty h sym ((random 100000 999999 as string) + "_" + (timeStamp() as string))) catch ()
                                        )
                                    )
                                )
                            )
                        ) catch (
                            format "[LevelEditor] CA error: %\n" (getCurrentException())
                        )
                    )
                )

                le_place_keep_running = true
            )

            on mouseAbort do (
                le_handle_abort()
            )

            on mouseAbort click do (
                le_handle_abort()
            )
        )
    """)


def set_place_globals(template: EntityTemplate):
    rt.execute(f'global le_place_template_name = "{template.name}"')
    rt.execute(
        f"global le_place_is_trigger = {'true' if template.is_trigger else 'false'}"
    )
    rt.execute("global le_place_keep_running = true")

    proxy_name = (template.proxy_model or "").replace("\\", "\\\\").replace('"', '\\"')
    rt.execute(f'global le_place_proxy_name = "{proxy_name}"')

    ca_def = build_ca_definition(template, ca_name="LE_PlacedEntity")
    if ca_def:
        try:
            rt.execute(f"global le_place_ca_def = {ca_def}")
        except Exception as e:
            print(f"[LevelEditor] Place tool CA definition error: {e}")
            rt.execute("global le_place_ca_def = undefined")
    else:
        rt.execute("global le_place_ca_def = undefined")

    field_names = [field_to_key(f.name) for f in template.fields]
    rt.execute(f'global le_place_meta_keys = "{",".join(field_names)}"')

    trigger_id_keys = ",".join(
        field_to_key(f.name) for f in template.fields if f.field_type == "trigger_id"
    )
    trigger_ref_keys = ",".join(
        field_to_key(f.name) for f in template.fields if f.field_type == "trigger_ref"
    )
    rt.execute(f'global le_place_trigger_id_keys = "{trigger_id_keys}"')
    rt.execute(f'global le_place_trigger_ref_keys = "{trigger_ref_keys}"')


def start_tool():
    rt.execute("startTool levelEditorPlaceTool")


def stop_tool():
    rt.execute("global le_place_keep_running = false")
    rt.execute("try ( stopTool levelEditorPlaceTool ) catch ()")
