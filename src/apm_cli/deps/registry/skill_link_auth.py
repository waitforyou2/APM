"""Administrator-owned authentication profiles for Skill Link.

The optional private module is a build input, never a workspace YAML setting.
Embedding it removes end-user setup; it does NOT make shared credentials secret
from someone who possesses the executable. Keep real values out of Git.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .skill_link_config import normalize_base_url


@dataclass(frozen=True)
class W3AuthProfile:
    service_url: str
    token_url: str
    hw_id: str = field(repr=False)
    hw_appkey: str = field(repr=False)
    account: str = field(repr=False)
    password: str = field(repr=False)


def _load_private_profiles() -> dict:
    try:
        from ._skill_link_private import PROFILES
    except ModuleNotFoundError as exc:
        if exc.name != f"{__package__}._skill_link_private":
            raise ValueError("Cannot load administrator Skill Link profile") from None
        return {}
    except Exception:
        # Do not print source lines or exception messages from a secret-bearing file.
        raise ValueError("Cannot load administrator Skill Link profile; check its syntax") from None
    if not isinstance(PROFILES, dict):
        raise ValueError("Administrator Skill Link PROFILES must be a mapping")
    return PROFILES


def validate_header(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) > 126 for char in value)
    ):
        raise ValueError(f"Invalid or missing HTTP header credential: {label}")
    return value


def get_w3_profile(registry_name: str, base_url: str) -> W3AuthProfile | None:
    """Return an exact-origin-bound build profile, or keep legacy environment auth.

    A profile with the right name and wrong service URL fails closed. It must not
    fall back to an old environment token or send credentials to the manifest URL.
    """
    profiles = _load_private_profiles()
    if registry_name not in profiles:
        return None
    raw = profiles[registry_name]
    required = {"service_url", "token_url", "hw_id", "hw_appkey", "account", "password"}
    if not isinstance(raw, dict) or set(raw) != required:
        raise ValueError("Administrator Skill Link profile has missing or unknown fields")
    if not all(isinstance(raw[key], str) for key in ("service_url", "token_url")):
        raise ValueError("Administrator Skill Link service_url and token_url must be strings")
    service = normalize_base_url(raw["service_url"])
    if service != normalize_base_url(base_url):
        raise ValueError("Skill Link service URL does not match the administrator profile")
    token_url = normalize_base_url(raw["token_url"])
    if not urlsplit(token_url).path:
        raise ValueError("Administrator Skill Link token_url must include the token endpoint path")
    hw_id = validate_header(raw["hw_id"], "X-HW-ID")
    hw_appkey = validate_header(raw["hw_appkey"], "X-HW-APPKEY")
    for key in ("account", "password"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise ValueError(f"Administrator Skill Link profile is missing {key}")
    return W3AuthProfile(service, token_url, hw_id, hw_appkey, raw["account"], raw["password"])
