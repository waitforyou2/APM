"""Invocation-local manifest context for provider-aware dependency selection."""

from contextvars import ContextVar
from pathlib import Path

selection_manifest: ContextVar[Path | None] = ContextVar("selection_manifest", default=None)


def parse_selected_provider(entry: dict):
    """Read the authoritative manifest after lifecycle scripts may have edited it."""
    path = selection_manifest.get()
    if path is None or "git" in entry:
        return None
    from ...deps.registry.skill_link_config import builtin_registry_block, parse_provider_entry
    from ...utils.yaml_io import load_yaml

    data = load_yaml(path) or {}
    registries = (
        data.get("registries")
        if "registries" in data
        else builtin_registry_block({"dependencies": {"apm": [entry]}})
    )
    return parse_provider_entry(entry, registries)
