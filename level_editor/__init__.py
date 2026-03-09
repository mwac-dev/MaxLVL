"""
level_editor: 3ds Max Level Editor tool package.
"""

import qtmax

from .maxscript_gen import register_helper_functions
from .place_tool import register_place_tool
from .panel import LevelEditorPanel

_level_editor_panel = None


def launch():
    global _level_editor_panel

    main_window = qtmax.GetQMaxMainWindow()

    try:
        if _level_editor_panel is not None:
            try:
                _level_editor_panel.close()
            except RuntimeError:
                pass
            _level_editor_panel = None
    except NameError:
        _level_editor_panel = None

    register_helper_functions()
    register_place_tool()

    _level_editor_panel = LevelEditorPanel(parent=main_window)
    qtmax.DisableMaxAcceleratorsOnFocus(_level_editor_panel, True)
    _level_editor_panel.show()
    print("[LevelEditor] Level Editor launched.")
