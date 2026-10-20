"""Manifest contract for the opt-in, exact-version Skill Link v1 provider."""

from __future__ import annotations

import re
from urllib.parse import urlencode, urlsplit, urlunsplit

PROVIDER = "skill-link-v1"
ENDPOINT = "/external/skills/link/v1/get"
_VERSION = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def normalize_base_url(value: str) -> str:
    """Validate a credential-free HTTPS service base, preserving path case."""
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and parsed.port != 0
            and not any(char.isspace() or ord(char) < 32 for char in value)
            and "\\" not in value
            and not any(part in {".", ".."} for part in parsed.path.split("/"))
        )
        port = parsed.port
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ValueError("skill-link-v1 url must be an HTTPS base URL without credentials or query")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    authority = host + (f":{port}" if port and port != 443 else "")
    return urlunsplit(("https", authority, parsed.path.rstrip("/"), "", ""))


def link_url(base_url: str, skill_id: str, version: str) -> str:
    """Stable lockfile locator; never a signed object-storage download URL."""
    return (
        normalize_base_url(base_url)
        + ENDPOINT
        + "?"
        + urlencode({"skillId": skill_id, "version": version})
    )


def validate_version(version: str) -> None:
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError(
            "skill-link-v1 requires an exact version such as '0.0.1'; ranges/latest are unsupported"
        )


def parse_skill_link_entry(entry: dict, registry_name: str, base_url: str):
    """Parse a single skill, retaining the existing dependency/target contracts."""
    from ...models.dependency.reference import DependencyReference
    from ...models.dependency.registry_entry import parse_registry_object_entry
    from ...models.dependency.resource import ResourceSpec

    if set(entry) - {"id", "version", "registry", "alias", "targets"}:
        raise ValueError("skill-link-v1 accepts only id, version, registry, alias, targets")
    dep = parse_registry_object_entry(DependencyReference, entry, allow_single_id=True)
    # Keep IDs portable to Windows and case-sensitive service identities unambiguous.
    ResourceSpec.parse({"kind": "skills", "name": dep.repo_url})
    dep.resource = ResourceSpec.parse({"kind": "skills", "name": dep.alias or dep.repo_url})
    validate_version(dep.reference)
    dep.alias = dep.alias or dep.repo_url
    dep.registry_name = registry_name
    dep.skill_link_url = normalize_base_url(base_url)
    return dep


def parse_provider_entry(entry: dict, registries: dict | None):
    """Return a custom dependency, or None to preserve native parser behavior.

    Provider declarations are project-local. User config only binds credentials;
    it cannot silently reinterpret a project's native registry dependencies.
    """
    if not registries or not ({"id", "registry"} & entry.keys()):
        return None
    name = entry.get("registry", registries.get("default"))
    body = registries.get(name) if isinstance(name, str) else None
    if isinstance(body, dict) and body.get("provider") == PROVIDER:
        return parse_skill_link_entry(entry, name, body["url"])
    return None


def validate_provider_routing(dependencies, registries):
    """Do not accidentally send Git shorthand to a custom service's native API."""
    for dep in dependencies:
        if not isinstance(getattr(dep, "registry_name", None), str):
            continue
        body = (registries or {}).get(dep.registry_name)
        if isinstance(body, dict) and body.get("provider") == PROVIDER and not dep.skill_link_url:
            raise ValueError(
                "skill-link-v1 requires an object with id + version; declare Git sources with 'git:'"
            )


def can_replay_skill_link(dep, locked) -> bool:
    """Keep immutable-version hashes even on --refresh or alias-only changes."""
    base = getattr(dep, "skill_link_url", None)
    return bool(
        isinstance(base, str)
        and locked
        and base == getattr(locked, "skill_link_url", None)
        and dep.reference == locked.version
        and locked.resolved_url
        and locked.resolved_hash
    )
