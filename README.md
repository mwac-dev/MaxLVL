# MaxLVL - 3ds Max Level Editor inspired by Trenchbroom

A level editing toolkit for Autodesk 3ds Max that provides entity placement, per-face texture management, and export to Godot Engine via FBX and JSON sidecar files.

Built as a Python plugin using PySide6 for the UI and pymxs for 3ds Max integration.

## Features

- **Entity System**: Define entity templates with typed fields (string, float, int, bool, trigger ID, trigger reference). Place entities interactively in the viewport or spawn them at the origin. Entities are stored as 3ds Max Point helpers with custom attributes and user properties.

- **Trigger Connections**: Link entities together with trigger ID and trigger reference fields. Debug lines are drawn in the viewport between connected entities when selected.

- **Proxy Models**: Assign scene objects as visual proxies for entity templates. When an entity is placed, the proxy hierarchy is instanced and parented to the entity root.

- **Per-Face Texture Tool**: Apply textures to individual polygon faces with control over tiling, rotation, and offset. Includes a visual preview widget with drag-to-offset, scroll-to-zoom, and a rotation handle.

- **Texture Continuation**: Pick a source face and select adjacent faces to seamlessly continue the texture across them, automatically computing offset corrections even across different surface orientations.

- **Texture Lock / UV Lock**: Texture Lock recovers UV parameters after geometry edits so the texture stays anchored to the surface. UV Lock freezes UVs entirely during geometry changes.

- **Automatic Reprojection**: Tracked objects are polled for vertex, transform, and topology changes. When edits are detected, stored UV parameters are re-applied so textures remain consistent. New faces created by operations like extrude or bevel are projected from their neighbors.

- **Edit Poly Modifier Support**: UV parameters are stored per Edit Poly modifier layer using custom attributes, then flattened at export time. This allows non-destructive workflows with multiple modifier layers.

- **Normal Map Detection**: When a texture is applied, the tool automatically looks for a corresponding normal map in a `normals` subdirectory and assigns it to the material's bump slot.

- **FBX Export**: Exports visible geometry as FBX with Unreal-compatible settings. Shared materials are consolidated, unused material slots are compacted, and smoothing groups are auto-assigned where missing.

- **JSON Sidecar Export**: Exports all entity data (type, transform, metadata, trigger references) alongside mesh collision metadata and light properties to a JSON file.

- **Godot/Unreal Importers**: Coming soon.

## Requirements

- Autodesk 3ds Max (2022 or later recommended)
- Python 3.9+ (ships with 3ds Max)
- PySide6 (ships with 3ds Max)
- pymxs (ships with 3ds Max)

## Installation

1. Clone or download this repository to a location accessible from 3ds Max.

2. Edit `LevelEditor_macro.mcr` and update the path to point to your local copy of `LevelEditor.py`:

```
python.executefile @"C:\path\to\3dsMaxLevelEditor\LevelEditor.py"
```

3. Place `LevelEditor_macro.mcr` in your 3ds Max macros directory, or run it once from the MaxScript editor to register the macro.

4. The macro will appear under the "Level Editor" category in the toolbar customization dialog. Assign it to a toolbar button, menu, or keyboard shortcut.

## Usage

### Getting Started

1. Launch the Level Editor from the toolbar or menu.
2. Set your project directory using the Browse button in the Project group.

### Entity Workflow

1. Open the Entities tab.
2. Create a template by typing a name and clicking Add.
3. Add fields to the template (string, float, int, bool, trigger_id, trigger_ref).
4. Optionally pick a proxy model from the scene to use as a visual representation.
5. Place entities using Spawn at Origin, Mark Selected (to convert an existing object), or Place Mode (click in the viewport to place, right-click to delete).
6. Select a placed entity to view and edit its fields in the 3ds Max Modify panel.

### Texture Workflow

1. Open the Textures tab.
2. Select an object in the scene.
3. Enter face sub-object mode (Edit Poly, sub-object level 4).
4. Select one or more faces.
5. Click a texture in the browser to apply it.
6. Adjust tiling, rotation, and offset using the spinboxes, the preview widget, or the alignment buttons (Fit H, Fit V, Fit, +90, +45, World).
7. Use Pick Source / face selection to continue textures seamlessly across faces.

### Exporting

1. Click Export Sidecar JSON to export entity data only.
2. Click Export FBX + Sidecar to export both the scene geometry and entity data.
3. Files are saved to the project directory using the 3ds Max scene filename.

## Texture Directory

The tool expects a `textures` directory inside the project path you configure. The texture browser scans this directory recursively for supported image formats (png, jpg, jpeg, tga, bmp, tif, tiff, dds).

Normal maps are detected automatically. Place them in a `normals` subdirectory alongside your diffuse textures, using the same filename with a `_normal` suffix. For example:

```
textures/
    brick.png
    normals/
        brick_normal.png
    metal/
        panel.tga
        normals/
            panel_normal.tga
```

When a texture is applied to a face, the tool looks for a matching normal map and assigns it to the material's bump slot automatically.

## Project Structure

```
3dsMaxLevelEditor/
    LevelEditor.py              # Entry point, module reloading
    LevelEditor_macro.mcr       # 3ds Max macro for toolbar integration
    level_editor/
        __init__.py             # Package init, launch() entry point
        models.py               # EntityField and EntityTemplate data classes
        template_manager.py     # Template CRUD and JSON persistence
        scene_ops.py            # Entity metadata, custom attributes, spawning
        maxscript_gen.py        # MaxScript code generation for custom attributes
        texture_ops.py          # Material management, UV projection, reprojection
        uv_math.py              # Pure Python vector math and UV decomposition
        texture_browser.py      # Filterable texture thumbnail grid widget
        texture_properties.py   # Tiling/rotation/offset controls widget
        texture_preview.py      # Tiled texture preview with face overlay
        exporter.py             # JSON sidecar and FBX export
        place_tool.py           # MaxScript viewport placement tool
        panel.py                # Main Qt dock panel
        dialogs.py              # Trigger picker dialog
```

## Configuration Files

The following files are created in the 3ds Max user scripts directory at runtime:

- `LevelEditor_Templates.json`: Saved entity template definitions.
- `LevelEditor_Config.json`: Project directory setting.
- `LevelEditor_TextureDefaults.json`: Default UV property values.

## License

MIT License. This software is provided "as is", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement. In no event shall the authors be liable for any claim, damages, or other liability arising from the use of this software.
