"""Explicit, opt-in resource layout for Git dependencies."""

from __future__ import annotations

import re
from dataclasses import dataclass

_IDENTIFIER = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_WINDOWS_DEVICE = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$")
_BUILTIN_KINDS = frozenset({"skills", "agents", "knowledge", "workflows"})
_RESERVED_KINDS = frozenset(
    {
        "bin",
        "canvas",
        "chatmodes",
        "commands",
        "contexts",
        "hooks",
        "instructions",
        "mcp",
        "plugins",
        "prompts",
        "targets",
    }
)


@dataclass(frozen=True)
class ResourceSpec:
    """A directory to deploy as one named resource, not an inferred package."""

    kind: str
    name: str

    @classmethod
    def parse(cls, raw: object) -> ResourceSpec:
        if not isinstance(raw, dict) or set(raw) != {"kind", "name"}:
            raise ValueError("'resource' must contain exactly 'kind' and 'name'")
        kind = raw["kind"]
        name = raw["name"]
        for key, value in (("kind", kind), ("name", name)):
            if not isinstance(value, str) or len(value) > 64 or not _IDENTIFIER.fullmatch(value):
                raise ValueError(
                    f"'resource.{key}' must be a lowercase kebab-case name (max 64 characters)"
                )
            if _WINDOWS_DEVICE.fullmatch(value):
                raise ValueError(f"'resource.{key}' may not be a Windows device name")
        if kind in _RESERVED_KINDS:
            raise ValueError(f"'resource.kind' {kind!r} is reserved for an APM primitive")
        return cls(kind=kind, name=name)

    @property
    def is_custom(self) -> bool:
        return self.kind not in _BUILTIN_KINDS

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "name": self.name}
