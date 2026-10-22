"""Skill Link client with optional W3 token acquisition before each link request."""

from __future__ import annotations

import json
import os
from urllib.parse import urljoin, urlsplit

import requests

from .auth import _sanitized
from .skill_link_auth import W3AuthProfile, get_w3_profile, validate_header
from .skill_link_config import link_url, normalize_endpoint_url

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


def _request(
    url: str,
    headers: dict[str, str],
    limit: int,
    label: str,
    *,
    method: str = "GET",
    json_body: dict | None = None,
):
    """One bounded request; no redirects, cookies or implicit netrc credentials.

    A fresh session per hop prevents custom API headers/cookies crossing origins.
    Keep trust_env for enterprise proxies and REQUESTS_CA_BUNDLE; TLS stays on.
    Exceptions suppress underlying requests URLs (which can contain signatures).
    """
    try:
        with requests.Session() as session:
            with session.request(
                method,
                url,
                headers=headers,
                json=json_body,
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


def _fetch_w3_token(profile: W3AuthProfile) -> str:
    status, _, body = _request(
        profile.token_url,
        {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-HW-ID": profile.hw_id,
            "X-HW-APPKEY": profile.hw_appkey,
        },
        MAX_LINK_BYTES,
        "W3 token API",
        method="POST",
        json_body={"account": profile.account, "password": profile.password},
    )
    if status != 200:
        raise SkillLinkError(f"W3 token API returned HTTP {status}; redirects are not followed")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        raise SkillLinkError("W3 token API returned invalid JSON") from None
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise SkillLinkError("W3 token API reported authentication failure (expected status 'ok')")
    result = payload.get("result")
    token = result.get("newToken") if isinstance(result, dict) else None
    try:
        return validate_header(token, "result.newToken")
    except ValueError:
        raise SkillLinkError("W3 token API did not return a valid result.newToken") from None


def _credential_endpoint_matches(registry_name: str, endpoint_url: str) -> bool:
    """Manual credentials must be bound to this exact endpoint, including its path."""
    from ...config import get_registry_config

    configured = get_registry_config(registry_name)
    try:
        return isinstance(configured, dict) and normalize_endpoint_url(
            configured.get("url")
        ) == normalize_endpoint_url(endpoint_url)
    except ValueError:
        return False


def credential_headers(registry_name: str, endpoint_url: str) -> dict[str, str]:
    try:
        profile = get_w3_profile(registry_name, endpoint_url)
    except ValueError as exc:
        raise SkillLinkError(str(exc)) from None
    if profile is not None:
        # Built-in agentcenter_url is the administrator's trust binding. Neither
        # a workspace nor a stale environment token can override this profile.
        token = _fetch_w3_token(profile)
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-HW-ID": profile.hw_id,
            "X-HW-APPKEY": profile.hw_appkey,
            "X-AUTH-TOKEN": token,
        }
    if not _credential_endpoint_matches(registry_name, endpoint_url):
        raise SkillLinkError(
            f"Bind credentials to this endpoint first: apm config set registry.{registry_name}.url <full-endpoint-url>"
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
    def __init__(self, registry_name: str, endpoint_url: str):
        self.registry_name = registry_name
        self.endpoint_url = normalize_endpoint_url(endpoint_url)

    def _get_link(self, skill_id: str, version: str) -> str:
        status, _, body = _request(
            link_url(self.endpoint_url, skill_id, version),
            credential_headers(self.registry_name, self.endpoint_url),
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
