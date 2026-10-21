"""Compact Workspace resource declarations, independent of download transport."""

from __future__ import annotations

from .resource import ResourceSpec

WORKSPACE_KINDS = frozenset({"skills", "agents", "knowledge", "workflows"})


def compact_resource(entry: dict) -> ResourceSpec:
    """Validate the public id/kind contract using portable installation names."""
    resource = ResourceSpec.parse({"kind": entry.get("kind"), "name": entry.get("id")})
    if resource.kind not in WORKSPACE_KINDS:
        raise ValueError("'kind' must be skills, agents, knowledge, or workflows")
    if "resource" in entry:
        raise ValueError("Use either id/kind or resource.kind/name, not both")
    if "alias" in entry and entry["alias"] != resource.name:
        raise ValueError("'alias' must match 'id' for an id/kind resource")
    return resource


def normalize_compact_git(entry: dict) -> dict:
    """Adapt compact authoring to the existing typed Git download contract."""
    resource = compact_resource(entry)
    if not entry.get("path"):
        raise ValueError("A Git id/kind resource requires a directory 'path'")
    if entry.get("git") == "parent":
        raise ValueError("Git id/kind resources require an explicit repository URL")
    result = {key: value for key, value in entry.items() if key not in {"id", "kind"}}
    result["resource"] = resource.to_dict()
    return result


def compact_entry(dep, entry: dict) -> dict:
    """Keep compact declarations compact when a command rewrites a manifest."""
    if not dep.compact_resource or dep.resource is None:
        return entry
    result = {"id": dep.resource.name, "kind": dep.resource.kind}
    result.update(
        {key: value for key, value in entry.items() if key not in {"id", "alias", "resource"}}
    )
    return result


def validate_resource_ids(dependencies: list) -> None:
    """Reject ambiguous Workspace identifiers before downloading anything."""
    if not any(dep.compact_resource for dep in dependencies):
        return
    seen = set()
    sources = set()
    for dep in dependencies:
        if dep.resource is None:
            continue
        resource_id = dep.resource.name
        if resource_id in seen:
            raise ValueError(f"Duplicate Workspace resource id: {resource_id!r}")
        seen.add(resource_id)
        source_key = dep.get_unique_key()
        if source_key in sources:
            raise ValueError("A Workspace resource source must be registered only once")
        sources.add(source_key)
