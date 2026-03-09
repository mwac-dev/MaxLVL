"""
Data models for entity templates and fields.
"""


class EntityField:
    def __init__(self, name: str, field_type: str = "string", default: str = ""):
        self.name = name
        self.field_type = field_type
        self.default = default

    def to_dict(self) -> dict:
        return {"name": self.name, "type": self.field_type, "default": self.default}

    @classmethod
    def from_dict(cls, data: dict) -> "EntityField":
        return cls(data["name"], data.get("type", "string"), data.get("default", ""))


class EntityTemplate:
    def __init__(
        self,
        name: str,
        is_trigger: bool = False,
        fields: list[EntityField] | None = None,
        proxy_model: str = "",
    ):
        self.name = name
        self.is_trigger = is_trigger
        self.fields: list[EntityField] = fields or []
        self.proxy_model = proxy_model or ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "is_trigger": self.is_trigger,
            "proxy_model": self.proxy_model,
            "fields": [f.to_dict() for f in self.fields],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EntityTemplate":
        fields = [EntityField.from_dict(f) for f in data.get("fields", [])]
        return cls(
            data["name"],
            data.get("is_trigger", False),
            fields,
            data.get("proxy_model", ""),
        )
