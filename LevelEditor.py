"""
MaxLVL Level Editor Tool for 3ds Max
"""

import importlib
import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)

import level_editor
import level_editor.dialogs
import level_editor.exporter
import level_editor.maxscript_gen
import level_editor.models
import level_editor.panel
import level_editor.place_tool
import level_editor.scene_ops
import level_editor.template_manager
import level_editor.texture_browser
import level_editor.texture_ops
import level_editor.texture_properties
import level_editor.uv_math

for mod in [
    level_editor.models,
    level_editor.template_manager,
    level_editor.scene_ops,
    level_editor.maxscript_gen,
    level_editor.dialogs,
    level_editor.uv_math,
    level_editor.texture_ops,
    level_editor.texture_browser,
    level_editor.texture_properties,
    level_editor.exporter,
    level_editor.place_tool,
    level_editor.panel,
    level_editor,
]:
    importlib.reload(mod)

from level_editor import launch

launch()
