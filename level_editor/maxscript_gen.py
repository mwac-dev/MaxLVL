"""
Shared MaxScript code-generation helpers.
"""

import re

from pymxs import runtime as rt


def field_to_key(name: str) -> str:
    """Sanitise a field name into a valid MaxScript identifier."""
    key = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip())
    if not key:
        key = "field"
    if key[0].isdigit():
        key = f"f_{key}"
    return key


def register_helper_functions():
    """Register global MaxScript helpers (le_root_from_node, le_read_trigger_id)."""
    rt.execute("""
        global le_root_from_node
        global le_read_trigger_id

        fn le_root_from_node n = (
            local cur = n
            while cur != undefined do (
                if (getUserProp cur "le_entity_type") != undefined then return cur
                cur = try (cur.parent) catch (undefined)
            )
            undefined
        )

        fn le_read_trigger_id n = (
            local root = le_root_from_node n
            if root == undefined then return undefined
            local raw = getUserProp root "le_trigger_id_keys"
            if raw == undefined then return undefined
            local keys = filterString raw ","
            for k in keys do (
                local kk = trimRight (trimLeft k)
                if kk != "" do (
                    local sym = execute ("#" + kk)
                    for i = 1 to root.modifiers.count do (
                        local m = root.modifiers[i]
                        if matchPattern m.name pattern:"LE_*" then (
                            local v = try (getProperty m sym) catch (undefined)
                            if v != undefined and (v as string) != "" do return (v as string)
                        )
                    )
                )
            )
            undefined
        )
    """)


def _build_field_lines(fields, *, field_to_key_fn=field_to_key):
    param_lines: list[str] = []
    ui_lines: list[str] = []
    event_lines: list[str] = []

    for field in fields:
        fname = field_to_key_fn(field.name)

        if field.field_type == "float":
            default = field.default or "0.0"
            param_lines.append(
                f"        {fname} type:#float ui:spn_{fname} default:{default}"
            )
            ui_lines.append(
                f'        spinner spn_{fname} "{field.name}" type:#float range:[-99999, 99999, {default}]'
            )

        elif field.field_type == "int":
            default = field.default or "0"
            param_lines.append(
                f"        {fname} type:#integer ui:spn_{fname} default:{default}"
            )
            ui_lines.append(
                f'        spinner spn_{fname} "{field.name}" type:#integer range:[-99999, 99999, {default}]'
            )

        elif field.field_type == "bool":
            def_val = (
                "true" if field.default.lower() in ("true", "1", "yes") else "false"
            )
            param_lines.append(
                f"        {fname} type:#boolean ui:chk_{fname} default:{def_val}"
            )
            ui_lines.append(
                f'        checkbox chk_{fname} "{field.name}" checked:{def_val}'
            )

        elif field.field_type in ("trigger_id", "trigger_ref"):
            escaped = field.default.replace('"', '\\"')
            param_lines.append(
                f'        {fname} type:#string ui:edt_{fname} default:"{escaped}"'
            )
            ui_lines.append(
                f'        edittext edt_{fname} "{field.name}" text:"{escaped}"'
            )
            if field.field_type == "trigger_ref":
                ui_lines.append(
                    f'        pickbutton pb_{fname} "Pick Trigger" autoDisplay:false'
                )
                event_lines.append(
                    f"""        on pb_{fname} picked pickedObj do (
            local root = pickedObj
            local foundRoot = false
            while root != undefined do (
                if (getUserProp root "le_entity_type") != undefined then (foundRoot = true; exit)
                root = try (root.parent) catch (undefined)
            )
            if not foundRoot then root = undefined

            local triggerId = undefined
            if root != undefined then (
                local raw = getUserProp root "le_trigger_id_keys"
                if raw != undefined then (
                    local keys = filterString raw ","
                    for k in keys while triggerId == undefined do (
                        local kk = trimRight (trimLeft k)
                        if kk != "" do (
                            local sym = execute ("#" + kk)
                            for i = 1 to root.modifiers.count while triggerId == undefined do (
                                local m = root.modifiers[i]
                                if matchPattern m.name pattern:"LE_*" then (
                                    local v = try (getProperty m sym) catch (undefined)
                                    if v != undefined and (v as string) != "" do triggerId = (v as string)
                                )
                            )
                        )
                    )
                )
            )
            if triggerId != undefined then (
                {fname} = triggerId
                edt_{fname}.text = triggerId
            )
        )"""
                )

        else:
            escaped = field.default.replace('"', '\\"')
            param_lines.append(
                f'        {fname} type:#string ui:edt_{fname} default:"{escaped}"'
            )
            ui_lines.append(
                f'        edittext edt_{fname} "{field.name}" text:"{escaped}"'
            )

    return param_lines, ui_lines, event_lines


def build_ca_definition(template, *, ca_name: str) -> str:
    if not template.fields:
        return ""

    param_lines, ui_lines, event_lines = _build_field_lines(template.fields)

    trigger_label = " [trigger]" if template.is_trigger else ""

    return f"""attributes "{ca_name}" (
            parameters main rollout:params (
{chr(10).join(param_lines)}
            )
            rollout params "{template.name}{trigger_label}" (
{chr(10).join(ui_lines)}
{chr(10).join(event_lines)}
            )
        )"""
