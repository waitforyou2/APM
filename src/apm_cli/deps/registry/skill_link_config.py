"""Manifest contract for the opt-in, exact-version Skill Link v1 provider."""

from __future__ import annotations

import re
from urllib.parse import urlencode, urlsplit, urlunsplit

PROVIDER = "skill-link-v1"
BUILTIN_REGISTRY = "corp-skills"
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


def agentcenter_base_url(url: str, skill_id: str, version: str) -> str:
    """Validate a complete request locator and recover its trusted service base."""
    validate_version(version)
    if not isinstance(url, str):
        raise ValueError("agentcenter_url must be a complete HTTPS request URL")
    try:
        parsed = urlsplit(url)
        if not parsed.path.endswith(ENDPOINT):
            raise ValueError
        base = normalize_base_url(
            urlunsplit((parsed.scheme, parsed.netloc, parsed.path[: -len(ENDPOINT)], "", ""))
        )
    except (ValueError, TypeError):
        raise ValueError("agentcenter_url must contain the complete Skill Link endpoint") from None
    if url != link_url(base, skill_id, version):
        raise ValueError("agentcenter_url must match the dependency's skillId and exact version")
    return base


def agentcenter_identity(url: str, skill_id: str, version: str) -> str:
    """Version-independent ownership key with the complete service endpoint."""
    base = agentcenter_base_url(url, skill_id, version)
    return f"agentcenter:{base}{ENDPOINT}?{urlencode({'skillId': skill_id})}"


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
    from ...models.dependency.workspace_resource import compact_resource

    if set(entry) - {"id", "kind", "version", "registry", "alias", "targets"}:
        raise ValueError("skill-link-v1 accepts only id, kind, version, registry, alias, targets")
    resource = compact_resource(entry) if "kind" in entry else None
    if resource is not None and resource.kind not in {"skills", "knowledge"}:
        raise ValueError("skill-link-v1 supports only skills and knowledge resources")
    dep = parse_registry_object_entry(
        DependencyReference,
        {key: value for key, value in entry.items() if key != "kind"},
        allow_single_id=True,
    )
    # Keep IDs portable to Windows and case-sensitive service identities unambiguous.
    ResourceSpec.parse({"kind": "skills", "name": dep.repo_url})
    dep.resource = resource or ResourceSpec.parse(
        {"kind": "skills", "name": dep.alias or dep.repo_url}
    )
    dep.compact_resource = resource is not None
    validate_version(dep.reference)
    dep.alias = dep.alias or dep.repo_url
    dep.registry_name = registry_name
    dep.agentcenter_url = link_url(base_url, dep.repo_url, dep.reference)
    return dep


def builtin_registry_block(data: dict) -> dict | None:
    """Supply a public default for id objects only when registries is omitted.

    Explicit blocks (including empty/null) keep their existing semantics. Pure
    Git manifests never load private configuration or enable registry behavior.
    The caller limits this extension to working-draft manifests.
    """
    if "registries" in data:
        return None
    needs_builtin = False
    for key in ("dependencies", "devDependencies"):
        bucket = data.get(key)
        entries = bucket.get("apm") if isinstance(bucket, dict) else None
        if not isinstance(entries, list):
            continue
        if any(
            isinstance(entry, dict)
            and "id" in entry
            and "git" not in entry
            and entry.get("registry", BUILTIN_REGISTRY) == BUILTIN_REGISTRY
            for entry in entries
        ):
            needs_builtin = True
            break
    if not needs_builtin:
        return None
    from .skill_link_auth import get_builtin_service_url

    url = get_builtin_service_url(BUILTIN_REGISTRY)
    if url is None:
        return None
    return {BUILTIN_REGISTRY: {"provider": PROVIDER, "url": url}, "default": BUILTIN_REGISTRY}


def parse_provider_entry(entry: dict, registries: dict | None):
    """Use an explicit or administrator-supplied provider declaration.

    User config only binds credentials; it cannot silently change the protocol.
    """
    if "git" in entry or not registries or not ({"id", "registry"} & entry.keys()):
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
        if isinstance(body, dict) and body.get("provider") == PROVIDER and not dep.agentcenter_url:
            raise ValueError(
                "skill-link-v1 requires an object with id + version; declare Git sources with 'git:'"
            )


def can_replay_skill_link(dep, locked) -> bool:
    """Keep immutable-version hashes even on --refresh or alias-only changes."""
    locator = getattr(dep, "agentcenter_url", None)
    return bool(
        isinstance(locator, str)
        and locked
        and locator == getattr(locked, "agentcenter_url", None)
        and dep.reference == locked.version
        and locked.resolved_url
        and locked.resolved_hash
    )
