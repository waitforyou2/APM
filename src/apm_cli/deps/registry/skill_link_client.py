"""Two-hop Skill Link client. API credentials never reach ZIP hosts."""

from __future__ import annotations

import json
import os
from urllib.parse import urljoin, urlsplit

import requests

from .auth import _credential_origin_matches, _sanitized
from .skill_link_config import link_url, normalize_base_url

MAX_LINK_BYTES = 1024 * 1024
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
HEADER_ENV = {
    "X-HW-ID": "HW_ID",
    "X-HW-APPKEY": "HW_APPKEY",
    "X-AUTH-TOKEN": "AUTH_TOKEN",
}


class SkillLinkError(ValueError):
    """A redacted, user-actionable provider failure."""


class _NoImplicitAuth(requests.auth.AuthBase):
    def __call__(self, request):
        return request


def _download_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 16384:
        raise SkillLinkError("Skill Link returned an invalid download URL")
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
            and parsed.port != 0
            and "\\" not in value
            and not any(char.isspace() or ord(char) < 32 for char in value)
        )
    except ValueError:
        valid = False
    if not valid:
        raise SkillLinkError("Skill Link download URL must be HTTPS without embedded credentials")
    return value


def _request(url: str, headers: dict[str, str], limit: int, label: str):
    """One bounded request; no redirects, cookies or implicit netrc credentials.

    A fresh session per hop prevents custom API headers/cookies crossing origins.
    Keep trust_env for enterprise proxies and REQUESTS_CA_BUNDLE; TLS stays on.
    Exceptions suppress underlying requests URLs (which can contain signatures).
    """
    try:
        with requests.Session() as session:
            with session.get(
                url,
                headers=headers,
                auth=_NoImplicitAuth(),
                stream=True,
                allow_redirects=False,
                timeout=(10, 60),
            ) as response:
                status = response.status_code
                if status != 200:
                    return status, response.headers.get("Location"), b""
                body = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    body.extend(chunk)
                    if len(body) > limit:
                        raise SkillLinkError(f"{label} response exceeds the {limit}-byte limit")
                return status, None, bytes(body)
    except requests.RequestException:
        raise SkillLinkError(
            f"{label} request failed; check connectivity, proxy and TLS trust"
        ) from None


def credential_headers(registry_name: str, base_url: str) -> dict[str, str]:
    if not _credential_origin_matches(registry_name, base_url):
        raise SkillLinkError(
            f"Bind credentials to this service first: apm config set registry.{registry_name}.url <base-url>"
        )
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    for header, suffix in HEADER_ENV.items():
        key = f"APM_REGISTRY_{suffix}_{_sanitized(registry_name)}"
        value = os.environ.get(key)
        if not value:
            raise SkillLinkError(f"Missing Skill Link credential environment variable: {key}")
        if any(ord(char) < 32 or ord(char) > 126 for char in value) or value != value.strip():
            raise SkillLinkError(f"Invalid HTTP header value in {key}")
        headers[header] = value
    return headers


class SkillLinkClient:
    def __init__(self, registry_name: str, base_url: str):
        self.registry_name = registry_name
        self.base_url = normalize_base_url(base_url)

    def _get_link(self, skill_id: str, version: str) -> str:
        status, _, body = _request(
            link_url(self.base_url, skill_id, version),
            credential_headers(self.registry_name, self.base_url),
            MAX_LINK_BYTES,
            "Skill Link API",
        )
        if status != 200:
            raise SkillLinkError(
                f"Skill Link API returned HTTP {status}; redirects are not followed"
            )
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            raise SkillLinkError("Skill Link API returned invalid JSON") from None
        if not isinstance(data, dict) or type(data.get("code")) is not int or data["code"] != 200:
            raise SkillLinkError("Skill Link API reported failure (expected business code 200)")
        payload = data.get("data")
        return _download_url(payload.get("downloadUrl") if isinstance(payload, dict) else None)

    def download(self, skill_id: str, version: str) -> bytes:
        # An expired signed URL can be renewed once without changing package identity.
        for attempt in range(2):
            url = self._get_link(skill_id, version)
            for _ in range(6):
                status, location, body = _request(
                    url,
                    {"Accept": "application/zip"},
                    MAX_DOWNLOAD_BYTES,
                    "Skill ZIP",
                )
                if status in {301, 302, 303, 307, 308}:
                    if not location:
                        raise SkillLinkError("Skill ZIP redirect has no Location")
                    url = _download_url(urljoin(url, location))
                    continue
                break
            else:
                raise SkillLinkError("Skill ZIP exceeded the redirect limit")
            if status == 200:
                return body
            if status in {401, 403} and attempt == 0:
                continue
            raise SkillLinkError(f"Skill ZIP download returned HTTP {status}")
        raise SkillLinkError("Skill ZIP download failed")  # defensive
