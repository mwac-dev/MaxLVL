"""
Main Level Editor Qt panel: UI, selection tracking, texture tool, and debug links.
"""

import json
import os
import re
import time

from pymxs import runtime as rt

from PySide6.QtWidgets import (
    QWidget,
    QDockWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QComboBox,
    QPushButton,
    QDialog,
    QMessageBox,
    QFileDialog,
    QScrollArea,
    QTabWidget,
)
from PySide6.QtCore import Qt, QTimer

from .models import EntityField, EntityTemplate
from .template_manager import TemplateManager
from .scene_ops import EntityOps
from .exporter import SidecarExporter
from .dialogs import TriggerPickerDialog
from .texture_ops import TextureOps
from .texture_browser import TextureBrowserWidget
from .texture_properties import TexturePropertiesWidget
from .texture_preview import TexturePreviewWidget
from . import place_tool
from . import uv_math


class LevelEditorPanel(QDockWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Level Editor")
        self.setWindowFlags(Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMinimumWidth(320)

        self.mgr = TemplateManager()
        self._project_dir = ""
        self._config_path = self._resolve_config_path()
        self._load_config()
        self._place_mode = False
        self._active_debug_pairs: list[tuple] = []
        self._gw_callback_registered = False

        self._cont_state = "idle"
        self._cont_source_obj = None
        self._cont_source_face: int | None = None
        self._cont_last_applied: int | None = None

        self._texture_lock = False
        self._uv_lock = False
        self._last_face_sel_key = None
        self._settle_until = 0.0

        self._build_ui()
        self._refresh_templates()
        self._refresh_entity_info()

        self._last_selection = None
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._check_selection_changed)
        self._poll_timer.start(80)

    @staticmethod
    def _resolve_config_path() -> str:
        try:
            d = str(rt.getDir(rt.Name("userScripts")))
        except Exception:
            d = os.path.expanduser("~")
        return os.path.join(d, "LevelEditor_Config.json")

    def _load_config(self):
        try:
            with open(self._config_path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._project_dir = data.get("project_dir", "")
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            pass

    def _save_config(self):
        try:
            with open(self._config_path, "w") as f:
                json.dump({"project_dir": self._project_dir}, f, indent=2)
        except OSError:
            pass

    def _get_textures_dir(self) -> str:
        if self._project_dir:
            return os.path.join(self._project_dir, "textures")
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "textures",
        )

    def _build_ui(self):
        wrapper = QWidget()
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(4, 4, 4, 4)
        wrapper_layout.setSpacing(4)

        wrapper_layout.addWidget(self._build_project_group())

        tabs = QTabWidget()
        tabs.addTab(self._build_entities_tab(), "Entities")
        tabs.addTab(self._build_textures_tab(), "Textures")
        wrapper_layout.addWidget(tabs)

        wrapper_layout.addWidget(self._build_export_group())
        wrapper_layout.addWidget(self._build_utils_group())

        self.setWidget(wrapper)

    def _build_project_group(self) -> QGroupBox:
        grp = QGroupBox("Project")
        layout = QHBoxLayout(grp)
        self._project_dir_input = QLineEdit(self._project_dir)
        self._project_dir_input.setPlaceholderText("Godot project directory...")
        self._project_dir_input.setReadOnly(True)
        layout.addWidget(self._project_dir_input, 1)
        btn = QPushButton("Browse")
        btn.clicked.connect(self._browse_project_dir)
        layout.addWidget(btn)
        return grp

    def _browse_project_dir(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Godot Project Directory", self._project_dir
        )
        if not dir_path:
            return
        self._project_dir = dir_path
        self._project_dir_input.setText(dir_path)
        self._save_config()
        self._texture_browser.set_directory(self._get_textures_dir())

    def _build_entities_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        layout.addWidget(self._build_templates_group())
        layout.addWidget(self._build_spawn_group())
        layout.addWidget(self._build_triggers_group())
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _build_textures_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._texture_browser = TextureBrowserWidget(self._get_textures_dir())
        self._texture_browser.texture_selected.connect(self._on_texture_selected)
        layout.addWidget(self._texture_browser)

        self._texture_preview = TexturePreviewWidget()
        self._texture_preview.offset_changed.connect(self._on_preview_offset)
        self._texture_preview.tiling_changed.connect(self._on_preview_tiling)
        self._texture_preview.rotation_changed.connect(self._on_preview_rotation)
        layout.addWidget(self._texture_preview)

        self._texture_props = TexturePropertiesWidget()
        self._texture_props.texture_lock_toggled.connect(self._toggle_texture_lock)
        self._texture_props.uv_lock_toggled.connect(self._toggle_uv_lock)
        self._texture_props.properties_changed.connect(self._on_props_changed)
        self._texture_props.fit_requested.connect(self._handle_fit_request)
        self._texture_props.continuation_pick_requested.connect(
            self._on_continuation_pick_requested
        )
        self._texture_props.continuation_cleared.connect(
            self._on_continuation_cleared
        )
        layout.addWidget(self._texture_props)

        self._texture_props.set_properties(self._texture_props.get_defaults())

        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _build_templates_group(self) -> QGroupBox:
        grp = QGroupBox("Entity Templates")
        layout = QVBoxLayout(grp)

        self.template_list = QListWidget()
        self.template_list.setMaximumHeight(100)
        self.template_list.currentRowChanged.connect(self._on_template_selected)
        layout.addWidget(self.template_list)

        row = QHBoxLayout()
        self.template_name_input = QLineEdit()
        self.template_name_input.setPlaceholderText("Template name...")
        row.addWidget(self.template_name_input)
        btn = QPushButton("Add")
        btn.clicked.connect(self._add_template)
        row.addWidget(btn)
        layout.addLayout(row)

        prow = QHBoxLayout()
        self.proxy_label = QLabel("Proxy: (none)")
        self.proxy_label.setWordWrap(True)
        prow.addWidget(self.proxy_label, 1)
        btn_pick_proxy = QPushButton("Pick Proxy")
        btn_pick_proxy.setToolTip(
            "Pick a scene object to use as this template's spawned proxy"
        )
        btn_pick_proxy.clicked.connect(self._pick_proxy_model)
        prow.addWidget(btn_pick_proxy)
        btn_clear_proxy = QPushButton("Clear")
        btn_clear_proxy.clicked.connect(self._clear_proxy_model)
        prow.addWidget(btn_clear_proxy)
        layout.addLayout(prow)

        layout.addWidget(QLabel("Template Fields:"))
        self.field_list = QListWidget()
        self.field_list.setMaximumHeight(80)
        layout.addWidget(self.field_list)

        frow = QHBoxLayout()
        self.field_name_input = QLineEdit()
        self.field_name_input.setPlaceholderText("Field name")
        frow.addWidget(self.field_name_input)
        self.field_type_combo = QComboBox()
        self.field_type_combo.addItems(
            ["string", "float", "int", "bool", "trigger_id", "trigger_ref"]
        )
        self.field_type_combo.setFixedWidth(70)
        frow.addWidget(self.field_type_combo)
        self.field_default_input = QLineEdit()
        self.field_default_input.setPlaceholderText("Default")
        self.field_default_input.setFixedWidth(80)
        frow.addWidget(self.field_default_input)
        layout.addLayout(frow)

        brow = QHBoxLayout()
        b1 = QPushButton("Add Field")
        b1.clicked.connect(self._add_field)
        brow.addWidget(b1)
        b2 = QPushButton("Remove Field")
        b2.clicked.connect(self._remove_field)
        brow.addWidget(b2)
        b3 = QPushButton("Remove Template")
        b3.clicked.connect(self._remove_template)
        brow.addWidget(b3)
        layout.addLayout(brow)

        return grp

    def _build_spawn_group(self) -> QGroupBox:
        grp = QGroupBox("Place Entities")
        layout = QVBoxLayout(grp)

        brow = QHBoxLayout()
        btn_spawn = QPushButton("Spawn at Origin")
        btn_spawn.clicked.connect(self._spawn_entity)
        brow.addWidget(btn_spawn)
        btn_mark = QPushButton("Mark Selected")
        btn_mark.setToolTip("Apply template to currently selected object")
        btn_mark.clicked.connect(self._mark_selected)
        brow.addWidget(btn_mark)
        layout.addLayout(brow)

        self.place_mode_btn = QPushButton("Place Mode: OFF")
        self.place_mode_btn.setCheckable(True)
        self.place_mode_btn.setToolTip(
            "LClick = place entity, RClick = delete entity under cursor"
        )
        self.place_mode_btn.toggled.connect(self._toggle_place_mode)
        layout.addWidget(self.place_mode_btn)

        self.entity_info_label = QLabel(
            "(select a level entity to see its fields in Modify panel)"
        )
        self.entity_info_label.setWordWrap(True)
        layout.addWidget(self.entity_info_label)

        return grp

    def _build_triggers_group(self) -> QGroupBox:
        grp = QGroupBox("Trigger References")
        layout = QVBoxLayout(grp)

        self.trigger_refs_input = QLineEdit()
        self.trigger_refs_input.setPlaceholderText(
            "Comma-separated trigger names..."
        )
        layout.addWidget(self.trigger_refs_input)

        row = QHBoxLayout()
        btn_set = QPushButton("Set Trigger Refs")
        btn_set.clicked.connect(self._set_triggers)
        row.addWidget(btn_set)
        btn_pick = QPushButton("Pick from Scene")
        btn_pick.clicked.connect(self._pick_trigger)
        row.addWidget(btn_pick)
        layout.addLayout(row)

        return grp

    def _build_export_group(self) -> QGroupBox:
        grp = QGroupBox("Export")
        layout = QVBoxLayout(grp)

        row = QHBoxLayout()
        btn_json = QPushButton("Export Sidecar JSON")
        btn_json.clicked.connect(self._export_json)
        row.addWidget(btn_json)
        btn_fbx = QPushButton("Export FBX + Sidecar")
        btn_fbx.clicked.connect(self._export_fbx_and_json)
        row.addWidget(btn_fbx)
        layout.addLayout(row)

        self.export_status = QLabel("")
        layout.addWidget(self.export_status)

        return grp

    def _build_utils_group(self) -> QGroupBox:
        grp = QGroupBox("Utilities")
        layout = QHBoxLayout(grp)
        btn = QPushButton("Select All Entities")
        btn.clicked.connect(self._select_all_entities)
        layout.addWidget(btn)
        btn2 = QPushButton("List All Entities")
        btn2.clicked.connect(self._list_all_entities)
        layout.addWidget(btn2)
        return grp

    def _on_texture_selected(self, texture_path: str):
        self._texture_preview.set_texture(texture_path)

        sel = list(rt.selection)
        if len(sel) != 1:
            QMessageBox.warning(self, "Level Editor", "Select one object.")
            return

        obj = sel[0]
        props = self._texture_props.get_properties()

        is_subobj = TextureOps.is_in_face_subobject_mode(obj)

        if is_subobj:
            faces = TextureOps.get_selected_faces(obj)
            if faces:
                if TextureOps.ensure_editable_poly(obj):
                    TextureOps.apply_texture_to_faces(obj, faces, texture_path)
                    TextureOps.apply_uv_transform(
                        obj, faces,
                        props["tile_u"], props["tile_v"],
                        props["rotation"],
                        props["offset_u"], props["offset_v"],
                    )
            else:
                TextureOps.apply_texture_to_object(obj, texture_path)
                self._apply_uv_to_all_faces(obj, props)
        else:
            TextureOps.apply_texture_to_object(obj, texture_path)
            self._apply_uv_to_all_faces(obj, props)

        TextureOps.track_object(obj)

    def _apply_uv_to_all_faces(self, obj, props: dict):
        if not TextureOps._is_base_editable_poly(obj):
            return
        num = TextureOps._get_num_faces(obj)
        if num < 1:
            return
        TextureOps.apply_uv_transform(
            obj, list(range(1, num + 1)),
            props["tile_u"], props["tile_v"],
            props["rotation"],
            props["offset_u"], props["offset_v"],
        )

    def _on_props_changed(self):
        props = self._texture_props.get_properties()
        self._texture_preview.set_uv_params(
            props["tile_u"], props["tile_v"], props["rotation"],
            props["offset_u"], props["offset_v"],
        )
        sel = list(rt.selection)
        if len(sel) != 1:
            return
        obj = sel[0]
        if not TextureOps.is_in_face_subobject_mode(obj):
            return
        faces = TextureOps.get_selected_faces(obj)
        if not faces:
            return
        TextureOps.apply_uv_transform(
            obj, faces,
            props["tile_u"], props["tile_v"],
            props["rotation"],
            props["offset_u"], props["offset_v"],
        )

    def _on_preview_offset(self, offset_u: float, offset_v: float):
        self._texture_props._suppress_change = True
        try:
            self._texture_props.offset_u.setValue(offset_u)
            self._texture_props.offset_v.setValue(offset_v)
        finally:
            self._texture_props._suppress_change = False
        self._apply_current_props_to_selection()

    def _on_preview_tiling(self, tile_u: float, tile_v: float):
        self._texture_props._suppress_change = True
        try:
            self._texture_props.tile_u.setValue(tile_u)
            self._texture_props.tile_v.setValue(tile_v)
        finally:
            self._texture_props._suppress_change = False
        self._apply_current_props_to_selection()

    def _on_preview_rotation(self, rotation: float):
        self._texture_props._suppress_change = True
        try:
            self._texture_props.rotation.setValue(rotation)
        finally:
            self._texture_props._suppress_change = False
        self._apply_current_props_to_selection()



    def _apply_current_props_to_selection(self):
        sel = list(rt.selection)
        if len(sel) != 1:
            return
        obj = sel[0]
        if not TextureOps.is_in_face_subobject_mode(obj):
            return
        faces = TextureOps.get_selected_faces(obj)
        if not faces:
            return
        props = self._texture_props.get_properties()
        TextureOps.apply_uv_transform(
            obj, faces,
            props["tile_u"], props["tile_v"],
            props["rotation"],
            props["offset_u"], props["offset_v"],
        )

    def _handle_fit_request(self, mode: str):
        sel = list(rt.selection)
        if len(sel) != 1:
            return
        obj = sel[0]
        if not TextureOps.is_in_face_subobject_mode(obj):
            return
        faces = TextureOps.get_selected_faces(obj)
        if len(faces) != 1:
            return

        verts = TextureOps.get_face_verts_world(obj, faces[0])
        if len(verts) < 3:
            return

        e1 = uv_math.vec_sub(verts[1], verts[0])
        e2 = uv_math.vec_sub(verts[2], verts[0])
        normal = uv_math.vec_normalize(uv_math.vec_cross(e1, e2))
        u_axis, v_axis = uv_math.quake_axes(normal)

        u_vals = [uv_math.vec_dot(v, u_axis) for v in verts]
        v_vals = [uv_math.vec_dot(v, v_axis) for v in verts]
        span_u = max(u_vals) - min(u_vals)
        span_v = max(v_vals) - min(v_vals)

        props = self._texture_props.get_properties()
        from .texture_ops import WORLD_TILE_SIZE
        if mode in ("h", "both") and span_u > 0.001:
            props["tile_u"] = WORLD_TILE_SIZE / span_u
        if mode in ("v", "both") and span_v > 0.001:
            props["tile_v"] = WORLD_TILE_SIZE / span_v

        self._texture_props.set_properties(props)
        TextureOps.apply_uv_transform(
            obj, faces,
            props["tile_u"], props["tile_v"],
            props["rotation"],
            props["offset_u"], props["offset_v"],
        )
        self._texture_preview.set_uv_params(
            props["tile_u"], props["tile_v"], props["rotation"],
            props["offset_u"], props["offset_v"],
        )

    def _toggle_texture_lock(self, checked: bool):
        self._texture_lock = checked

    def _toggle_uv_lock(self, checked: bool):
        self._uv_lock = checked

    def _on_continuation_pick_requested(self):
        self._cont_state = "picking"
        self._cont_source_obj = None
        self._cont_source_face = None
        self._cont_last_applied = None

    def _on_continuation_cleared(self):
        self._cont_state = "idle"
        self._cont_source_obj = None
        self._cont_source_face = None
        self._cont_last_applied = None

    def _refresh_templates(self):
        self.template_list.clear()
        for tpl in self.mgr.templates:
            self.template_list.addItem(tpl.name)
        self._refresh_fields_definition()
        self._refresh_proxy_label()

    def _get_active_template(self) -> EntityTemplate | None:
        row = self.template_list.currentRow()
        if row < 0 or row >= len(self.mgr.templates):
            return None
        return self.mgr.templates[row]

    def _refresh_fields_definition(self):
        self.field_list.clear()
        row = self.template_list.currentRow()
        if row < 0 or row >= len(self.mgr.templates):
            return
        tpl = self.mgr.templates[row]
        for f in tpl.fields:
            self.field_list.addItem(f"{f.name} ({f.field_type}) = {f.default}")

    def _on_template_selected(self, row):
        self._refresh_fields_definition()
        self._refresh_proxy_label()
        if self._place_mode:
            tpl = self._get_active_template()
            if tpl is not None:
                self._start_place_tool(tpl)

    def _refresh_proxy_label(self):
        row = self.template_list.currentRow()
        if row < 0 or row >= len(self.mgr.templates):
            self.proxy_label.setText("Proxy: (none)")
            return
        proxy_name = (self.mgr.templates[row].proxy_model or "").strip()
        self.proxy_label.setText(
            f"Proxy: {proxy_name}" if proxy_name else "Proxy: (none)"
        )

    def _add_template(self):
        name = self.template_name_input.text().strip()
        if not name:
            return
        if not self.mgr.add(EntityTemplate(name, False)):
            QMessageBox.warning(self, "Level Editor", "Template already exists.")
            return
        self.template_name_input.clear()
        self._refresh_templates()
        self.template_list.setCurrentRow(self.template_list.count() - 1)

    def _remove_template(self):
        row = self.template_list.currentRow()
        if row < 0:
            return
        self.mgr.remove(self.mgr.templates[row].name)
        self._refresh_templates()

    def _add_field(self):
        row = self.template_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Level Editor", "Select a template first.")
            return
        fname = self.field_name_input.text().strip()
        if not fname:
            return
        if not self.mgr.add_field(
            self.mgr.templates[row].name,
            EntityField(
                fname,
                self.field_type_combo.currentText(),
                self.field_default_input.text(),
            ),
        ):
            QMessageBox.warning(self, "Level Editor", "Field already exists.")
            return
        self.field_name_input.clear()
        self.field_default_input.clear()
        self._refresh_fields_definition()

    def _remove_field(self):
        trow = self.template_list.currentRow()
        frow = self.field_list.currentRow()
        if trow < 0 or frow < 0:
            return
        self.mgr.remove_field(self.mgr.templates[trow].name, frow)
        self._refresh_fields_definition()

    def _pick_proxy_model(self):
        row = self.template_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Level Editor", "Select a template first.")
            return

        node = None
        try:
            node = rt.pickObject(prompt="Pick proxy model for template")
        except Exception:
            node = None

        if node is None:
            return

        tpl_name = self.mgr.templates[row].name
        self.mgr.set_proxy_model(tpl_name, str(node.name))
        self._refresh_proxy_label()

    def _clear_proxy_model(self):
        row = self.template_list.currentRow()
        if row < 0:
            return
        self.mgr.set_proxy_model(self.mgr.templates[row].name, "")
        self._refresh_proxy_label()

    def _spawn_entity(self):
        tpl = self._get_active_template()
        if tpl is None:
            QMessageBox.warning(self, "Level Editor", "Select a template first.")
            return
        obj = EntityOps.spawn_entity_at(tpl)
        rt.select(obj)
        rt.redrawViews()

    def _mark_selected(self):
        sel = list(rt.selection)
        if len(sel) != 1:
            QMessageBox.warning(
                self, "Level Editor", "Select exactly one object."
            )
            return
        tpl = self._get_active_template()
        if tpl is None:
            QMessageBox.warning(self, "Level Editor", "Select a template first.")
            return
        target = EntityOps.resolve_entity_root(sel[0]) or sel[0]
        EntityOps.apply_template(target, tpl)
        self._refresh_entity_info()

    def _toggle_place_mode(self, checked: bool):
        if checked:
            tpl = self._get_active_template()
            if tpl is None:
                self.place_mode_btn.setChecked(False)
                QMessageBox.warning(
                    self, "Level Editor", "Select a template first."
                )
                return
            self._place_mode = True
            self.place_mode_btn.setText("Place Mode: ON")
            self.place_mode_btn.setStyleSheet("background-color: #4a7a4a;")
            self._start_place_tool(tpl)
        else:
            self._place_mode = False
            self.place_mode_btn.setText("Place Mode: OFF")
            self.place_mode_btn.setStyleSheet("")
            place_tool.stop_tool()

    def _start_place_tool(self, template: EntityTemplate):
        if hasattr(self, "_tool_poll") and self._tool_poll is not None:
            self._tool_poll.stop()

        place_tool.set_place_globals(template)
        place_tool.start_tool()

        self._tool_poll = QTimer(self)
        self._tool_poll.timeout.connect(self._check_tool_ended)
        self._tool_poll.start(200)

    def _check_tool_ended(self):
        if not self._place_mode:
            self._tool_poll.stop()
            return
        try:
            in_tool = rt.execute("toolMode.commandMode == #tool")
            if not in_tool:
                should_continue = rt.execute(
                    "try (le_place_keep_running) catch (false)"
                )
                if self._place_mode and should_continue:
                    place_tool.start_tool()
                else:
                    self._tool_poll.stop()
                    self._place_mode = False
                    self.place_mode_btn.setChecked(False)
        except Exception:
            self._tool_poll.stop()

    @staticmethod
    def _escape_ms_string(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _sync_debug_transform_handler(self):
        try:
            rt.execute("""(
                try(unRegisterRedrawViewsCallback le_debug_gw_draw)catch()
                try(callbacks.removeScripts id:#LE_DEBUG_LINKS)catch()
            )""")
        except Exception:
            pass
        self._gw_callback_registered = False

        if not self._active_debug_pairs:
            try:
                rt.execute("global le_dbg_from = #(); global le_dbg_to = #()")
            except Exception:
                pass
            return

        entries = []
        for a, b in self._active_debug_pairs:
            if rt.isValidNode(a) and rt.isValidNode(b):
                entries.append((str(a.name), str(b.name)))

        if not entries:
            return

        script_lines = ["global le_dbg_from = #()", "global le_dbg_to = #()"]
        for a_name, b_name in entries:
            script_lines.append(
                f'append le_dbg_from (getNodeByName "{self._escape_ms_string(a_name)}" exact:true)'
            )
            script_lines.append(
                f'append le_dbg_to (getNodeByName "{self._escape_ms_string(b_name)}" exact:true)'
            )

        script_lines.extend(
            [
                "fn le_debug_gw_draw = (",
                "  gw.setTransform (matrix3 1)",
                "  gw.setColor #line (color 255 190 0)",
                "  for i = 1 to le_dbg_from.count do (",
                "    local a = le_dbg_from[i]",
                "    local b = le_dbg_to[i]",
                "    if a != undefined and b != undefined and isValidNode a and isValidNode b do (",
                "      local pts = #(a.position, b.position)",
                "      gw.polyLine pts false",
                "    )",
                "  )",
                "  gw.enlargeUpdateRect #whole",
                "  gw.updateScreen()",
                ")",
                "registerRedrawViewsCallback le_debug_gw_draw",
                "completeredraw()",
            ]
        )

        try:
            rt.execute("\n".join(script_lines))
            self._gw_callback_registered = True
        except Exception:
            pass

    def _get_current_selection_key(self):
        sel = list(rt.selection)
        if not sel:
            return None
        return tuple(str(obj.name) for obj in sel)

    def _check_selection_changed(self):
        sel = list(rt.selection)
        if len(sel) == 1:
            root = EntityOps.resolve_entity_root(sel[0])
            if root is not None and root != sel[0]:
                try:
                    rt.select(root)
                    sel = [root]
                except Exception:
                    pass

        current = self._get_current_selection_key()
        if current != self._last_selection:
            self._last_selection = current
            self._refresh_entity_info()
            self._update_debug_links()

        if self._should_skip_poll():
            return

        if len(sel) == 1:
            obj = sel[0]
            try:
                if (rt.isValidNode(obj)
                        and TextureOps._is_base_editable_poly(obj)
                        and not TextureOps.is_tracked(obj)):
                    TextureOps.track_object(obj)
            except Exception:
                pass

        self._update_texture_face_state(sel)
        try:
            self._poll_tracked_objects()
        except Exception:
            pass

    def _should_skip_poll(self) -> bool:
        import ctypes
        _user32 = ctypes.windll.user32
        VK_LBUTTON, VK_RBUTTON, VK_MBUTTON = 0x01, 0x02, 0x04
        SETTLE_SECS = 0.15
        mouse_down = (
            _user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000
            or _user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000
            or _user32.GetAsyncKeyState(VK_MBUTTON) & 0x8000
        )
        if mouse_down:
            self._settle_until = time.time() + SETTLE_SECS
            return True
        if time.time() < self._settle_until:
            return True

        _SAFE_CMD_IDS = {7, 8, 10, 12}
        try:
            cmd_id = int(rt.execute("toolmode.commandmodeID"))
        except Exception:
            cmd_id = 12
        if cmd_id not in _SAFE_CMD_IDS:
            self._settle_until = time.time() + SETTLE_SECS
            return True

        return False

    def _update_texture_face_state(self, sel):
        if len(sel) == 1 and TextureOps.is_in_face_subobject_mode(sel[0]):
            obj = sel[0]
            faces = TextureOps.get_selected_faces(obj)
            self._texture_props.set_face_count(len(faces))

            face_key = (str(obj.name), tuple(faces))
            if face_key != self._last_face_sel_key:
                self._last_face_sel_key = face_key
                self._on_face_selection_changed(obj, faces)

            self._handle_continuation(obj, faces)
        else:
            self._texture_props.set_face_count(0)
            self._last_face_sel_key = None

    def _on_face_selection_changed(self, obj, faces: list[int]):
        if len(faces) == 1:
            stored = TextureOps.get_face_uv_params(obj, faces[0])
            if stored is not None:
                self._texture_props.set_properties(stored)
                self._texture_preview.set_uv_params(
                    stored["tile_u"], stored["tile_v"],
                    stored["rotation"],
                    stored["offset_u"], stored["offset_v"],
                )
            self._update_face_preview(obj, faces[0])
        else:
            self._texture_preview.set_face_shape([])

    def _update_face_preview(self, obj, face_index: int):
        from .texture_ops import WORLD_TILE_SIZE
        try:
            wv = TextureOps.get_face_verts_world(obj, face_index)
            if len(wv) >= 3:
                normal = uv_math.compute_polygon_normal(wv)
                ua, va = uv_math.quake_axes(normal)
                proj = [
                    (uv_math.vec_dot(v, ua) / WORLD_TILE_SIZE,
                     uv_math.vec_dot(v, va) / WORLD_TILE_SIZE)
                    for v in wv
                ]
                self._texture_preview.set_face_shape(proj)
            else:
                self._texture_preview.set_face_shape([])
        except Exception:
            self._texture_preview.set_face_shape([])

        try:
            tex_path = TextureOps.get_face_texture_path(obj, face_index)
            if tex_path:
                self._texture_preview.set_texture(tex_path)
                self._texture_browser.set_active_by_path(tex_path)
        except Exception:
            pass

    def _handle_continuation(self, obj, faces: list[int]):
        if self._cont_state == "picking" and len(faces) == 1:
            self._cont_source_obj = obj
            self._cont_source_face = faces[0]
            self._cont_state = "active"
            self._cont_last_applied = None
            self._texture_props.set_continuation_status(
                f"Source: Face {faces[0]} on {obj.name}"
            )
            try:
                tex_path = TextureOps.get_face_texture_path(obj, faces[0])
                if tex_path:
                    self._texture_browser.set_active_by_path(tex_path)
                    self._texture_preview.set_texture(tex_path)
            except Exception:
                pass
            stored = TextureOps.get_face_uv_params(obj, faces[0])
            if stored is not None:
                self._texture_props.set_properties(stored)

        elif (self._cont_state == "active"
                and len(faces) == 1
                and faces[0] != self._cont_last_applied):
            if (self._cont_source_obj is None
                    or not rt.isValidNode(self._cont_source_obj)):
                self._cont_state = "idle"
                self._cont_source_obj = None
                self._cont_source_face = None
                self._texture_props.set_continuation_status("")
                return
            is_same_face = (obj == self._cont_source_obj
                            and faces[0] == self._cont_source_face)
            if not is_same_face:
                try:
                    if obj == self._cont_source_obj:
                        TextureOps.continue_texture(
                            obj, self._cont_source_face, [faces[0]],
                        )
                    else:
                        TextureOps.continue_texture_cross_object(
                            self._cont_source_obj, self._cont_source_face,
                            obj, [faces[0]],
                        )
                    self._cont_last_applied = faces[0]
                except Exception:
                    pass

    def _poll_tracked_objects(self):
        changed = TextureOps.check_tracked_objects()
        for cobj, topo_changed, xform_changed, local_verts_changed in changed:
            if not rt.isValidNode(cobj):
                continue

            if topo_changed:
                TextureOps.project_new_faces(cobj)
                TextureOps.reproject_object(cobj)
                continue

            if self._texture_lock and (xform_changed or local_verts_changed):
                recovered = TextureOps.recover_face_params(cobj)
                if recovered:
                    self._push_recovered_params_to_ui(cobj, recovered)
                if not self._uv_lock:
                    TextureOps.reproject_object(cobj)
                continue

            if self._uv_lock and (local_verts_changed or xform_changed):
                TextureOps.refresh_tracking(cobj)
                continue

            TextureOps.reproject_object(cobj)

    def _push_recovered_params_to_ui(self, obj, recovered: dict):
        """If the currently selected face(s) belong to *obj*, push the
        recovered UV params into the spinboxes and preview widget."""
        sel = list(rt.selection)
        if len(sel) != 1 or sel[0] != obj:
            return
        faces = TextureOps.get_selected_faces(obj)
        if not faces:
            return
        for fi in faces:
            params = recovered.get(fi)
            if params is not None:
                self._texture_props.set_properties(params)
                self._texture_preview.set_uv_params(
                    params["tile_u"], params["tile_v"],
                    params["rotation"],
                    params["offset_u"], params["offset_v"],
                )
                break

    def _clear_debug_lines(self):
        self._active_debug_pairs = []
        self._gw_callback_registered = False
        try:
            rt.execute("""(
                try(unRegisterRedrawViewsCallback le_debug_gw_draw)catch()
                try(callbacks.removeScripts id:#LE_DEBUG_LINKS)catch()
                global le_dbg_from = #()
                global le_dbg_to = #()
                local root = getNodeByName "LE_GIZMOS"
                if root != undefined do delete root
                for n in (getNodeByName "LE_DebugLink_*" all:true) do try(delete n)catch()
                completeredraw()
            )""")
        except Exception:
            pass

    def _update_debug_links(self):
        self._active_debug_pairs = []

        sel = list(rt.selection)
        if len(sel) != 1:
            self._sync_debug_transform_handler()
            return

        selected = EntityOps.resolve_entity_root(sel[0])
        if selected is None:
            self._sync_debug_transform_handler()
            return

        links = []
        selected_is_trigger = bool(EntityOps.get_trigger_id_keys(selected))

        if selected_is_trigger:
            trigger_ids = {
                EntityOps.get_meta(selected, key).strip()
                for key in EntityOps.get_trigger_id_keys(selected)
                if EntityOps.get_meta(selected, key).strip()
            }
            if not trigger_ids:
                self._sync_debug_transform_handler()
                return

            for obj in EntityOps.get_all_entities():
                if obj == selected:
                    continue
                for key in EntityOps.get_trigger_ref_keys(obj):
                    ref = EntityOps.get_meta(obj, key).strip()
                    if not ref:
                        continue
                    ref_ids = [
                        r.strip() for r in re.split(r"[,;]", ref) if r.strip()
                    ]
                    if any(rid in trigger_ids for rid in ref_ids):
                        links.append((obj, selected))
                        break
        else:
            for key in EntityOps.get_trigger_ref_keys(selected):
                ref = EntityOps.get_meta(selected, key).strip()
                if not ref:
                    continue
                for ref_id in [
                    r.strip() for r in re.split(r"[,;]", ref) if r.strip()
                ]:
                    target = EntityOps.find_trigger_by_id(ref_id)
                    if target is not None:
                        links.append((selected, target))

        self._active_debug_pairs = links
        self._sync_debug_transform_handler()

    def _refresh_entity_info(self):
        sel = list(rt.selection)
        if len(sel) != 1:
            self.entity_info_label.setText(
                "(select a level entity to see its fields in Modify panel)"
            )
            self.trigger_refs_input.clear()
            return

        obj = EntityOps.resolve_entity_root(sel[0])
        if obj is None:
            self.entity_info_label.setText(
                "(select a level entity to see its fields in Modify panel)"
            )
            self.trigger_refs_input.clear()
            return

        etype = EntityOps.get_prop(obj, "le_entity_type")
        keys = EntityOps.get_meta_keys(obj)
        field_info = [f"  {key}: {EntityOps.get_meta(obj, key)}" for key in keys]

        info = f"{obj.name} [{etype}]"
        if field_info:
            info += "\n" + "\n".join(field_info)
        info += "\n\nEdit values in Modify panel →"

        self.entity_info_label.setText(info)
        self.trigger_refs_input.setText(
            ", ".join(EntityOps.get_trigger_refs(obj))
        )

    def _get_selected_entity(self):
        sel = list(rt.selection)
        if len(sel) != 1:
            return None
        return EntityOps.resolve_entity_root(sel[0])

    def _set_triggers(self):
        obj = self._get_selected_entity()
        if obj is None:
            return
        raw = self.trigger_refs_input.text()
        refs = [r.strip() for r in raw.split(",") if r.strip()]
        EntityOps.set_trigger_refs(obj, refs)

    def _pick_trigger(self):
        obj = self._get_selected_entity()
        if obj is None:
            return
        trigger_names = [
            str(e.name)
            for e in EntityOps.get_all_entities()
            if EntityOps.get_prop(e, "le_is_trigger") == "true"
        ]
        if not trigger_names:
            QMessageBox.information(
                self, "Level Editor", "No trigger entities in scene."
            )
            return
        dlg = TriggerPickerDialog(trigger_names, parent=self)
        if dlg.exec_() == QDialog.Accepted and dlg.picked:
            current = self.trigger_refs_input.text().strip()
            if current:
                current += ", "
            current += dlg.picked
            self.trigger_refs_input.setText(current)
            refs = [r.strip() for r in current.split(",") if r.strip()]
            EntityOps.set_trigger_refs(obj, refs)

    def _get_export_dir(self) -> str | None:
        if self._project_dir:
            return self._project_dir
        dir_path = QFileDialog.getExistingDirectory(
            self, "Select Export Directory"
        )
        return dir_path or None

    def _export_json(self):
        dir_path = self._get_export_dir()
        if not dir_path:
            return
        scene_name = str(rt.getFilenameFile(rt.maxFileName)) or "level"
        json_path = os.path.join(dir_path, f"{scene_name}_entities.json")
        count = SidecarExporter.export(json_path)
        if count > 0:
            self.export_status.setText(f"Exported {count} entities → {dir_path}")
        else:
            self.export_status.setText(f"Exported sidecar (0 entities) → {dir_path}")

    def _export_fbx_and_json(self):
        dir_path = self._get_export_dir()
        if not dir_path:
            return
        count = SidecarExporter.export_with_fbx(dir_path)
        if count > 0:
            self.export_status.setText(f"Exported FBX + {count} entities → {dir_path}")
        else:
            self.export_status.setText(f"Exported FBX + sidecar (0 entities) → {dir_path}")

    def _select_all_entities(self):
        ents = EntityOps.get_all_entities()
        if ents:
            rt.select(ents)
        else:
            QMessageBox.information(
                self, "Level Editor", "No entities in scene."
            )

    def _list_all_entities(self):
        ents = EntityOps.get_all_entities()
        if not ents:
            QMessageBox.information(
                self, "Level Editor", "No entities in scene."
            )
            return
        lines = [
            f"{obj.name} [{EntityOps.get_prop(obj, 'le_entity_type')}]"
            for obj in ents
        ]
        QMessageBox.information(
            self,
            "Level Editor",
            f"Level Entities ({len(ents)}):\n\n" + "\n".join(lines),
        )

    def closeEvent(self, event):
        self._place_mode = False
        self._cont_state = "idle"
        self._poll_timer.stop()
        self._clear_debug_lines()
        TextureOps.untrack_all()
        place_tool.stop_tool()
        super().closeEvent(event)
