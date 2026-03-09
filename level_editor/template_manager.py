"""
Template persistence: load/save entity templates to JSON on disk.
"""

import json
import os

from pymxs import runtime as rt

from .models import EntityField, EntityTemplate


class TemplateManager:
    def __init__(self):
        scripts_dir = str(rt.getDir(rt.Name("userScripts")))
        self.filepath = os.path.join(scripts_dir, "LevelEditor_Templates.json")
        self.templates: list[EntityTemplate] = []
        self.load()

    def load(self):
        if not os.path.exists(self.filepath):
            self.templates = []
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.templates = [EntityTemplate.from_dict(t) for t in data]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"[LevelEditor] Failed to load templates: {e}")
            self.templates = []

    def save(self):
        data = [t.to_dict() for t in self.templates]
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # === CRUD ===

    def add(self, template: EntityTemplate) -> bool:
        if any(t.name == template.name for t in self.templates):
            return False
        self.templates.append(template)
        self.save()
        return True

    def remove(self, name: str) -> bool:
        for i, t in enumerate(self.templates):
            if t.name == name:
                self.templates.pop(i)
                self.save()
                return True
        return False

    def get(self, name: str) -> EntityTemplate | None:
        for t in self.templates:
            if t.name == name:
                return t
        return None

    def names(self) -> list[str]:
        return [t.name for t in self.templates]

    def add_field(self, template_name: str, field: EntityField) -> bool:
        tpl = self.get(template_name)
        if tpl is None or any(f.name == field.name for f in tpl.fields):
            return False
        tpl.fields.append(field)
        self.save()
        return True

    def remove_field(self, template_name: str, field_index: int) -> bool:
        tpl = self.get(template_name)
        if tpl is None or field_index < 0 or field_index >= len(tpl.fields):
            return False
        tpl.fields.pop(field_index)
        self.save()
        return True

    def set_proxy_model(self, template_name: str, proxy_model: str) -> bool:
        tpl = self.get(template_name)
        if tpl is None:
            return False
        tpl.proxy_model = proxy_model or ""
        self.save()
        return True
