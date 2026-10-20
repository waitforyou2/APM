"""Automatic W3 auth: exact origin binding, per-link freshness, and no secret spill."""

from __future__ import annotations

import json
import sys
from types import ModuleType

import pytest
import requests

from apm_cli.deps.registry.skill_link_auth import _load_private_profiles, get_w3_profile
from apm_cli.deps.registry.skill_link_client import SkillLinkClient, SkillLinkError
from tests.unit.registry.test_skill_link import BASE, W3_URL
from tests.unit.registry.test_skill_link import credentials as credentials
from tests.unit.registry.test_skill_link import (
    test_cli_mixed_install_frozen_reinstall_and_noop as run_mixed_install,
)
from tests.unit.registry.test_skill_link import transport as transport


@pytest.fixture
def automatic(monkeypatch, transport, credentials):
    profile = {
        "service_url": BASE,
        "token_url": W3_URL,
        "hw_id": "test-application-id",
        "hw_appkey": "test-application-key",
        "account": "test-account",
        "password": 'test-password#with"quotes\\and-中文',
    }
    monkeypatch.setattr(
        "apm_cli.deps.registry.skill_link_auth._load_private_profiles",
        lambda: {"corp-skills": profile},
    )
    transport["profile"] = profile
    return profile


def test_each_link_gets_new_token_and_ignores_old_environment(automatic, transport):
    client = SkillLinkClient("corp-skills", BASE)
    client.download("frontend-design", "0.0.1")
    client.download("frontend-design", "0.0.1")
    assert transport["tokens"] == transport["links"] == transport["downloads"] == 2
    assert [r.method for r in transport["requests"]] == ["POST", "GET", "GET"] * 2
    assert "account" not in transport["requests"][1].url
    assert "password" not in transport["requests"][1].url


def test_new_token_is_obtained_when_signed_url_is_renewed(automatic, transport):
    transport["expire_once"] = True
    SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
    assert transport["tokens"] == transport["links"] == 2


def test_built_in_binding_does_not_need_end_user_secrets_or_config(
    monkeypatch, automatic, transport
):
    from apm_cli import config

    monkeypatch.setattr(config, "_config_cache", {"experimental": {"registries": True}})
    for suffix in ("HW_ID", "HW_APPKEY", "AUTH_TOKEN"):
        monkeypatch.delenv(f"APM_REGISTRY_{suffix}_CORP_SKILLS")
    SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
    assert transport["tokens"] == 1


@pytest.mark.parametrize(
    "target", ["https://evil.example.test", BASE + "/extra", BASE.replace("https:", "http:")]
)
def test_workspace_cannot_change_profile_service_origin(automatic, transport, target):
    with pytest.raises((ValueError, SkillLinkError)):
        SkillLinkClient("corp-skills", target).download("frontend-design", "0.0.1")
    assert not transport["requests"]


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 500])
def test_token_failure_stops_without_link_call_or_login_retry(automatic, transport, status):
    transport["token_http_status"] = status
    with pytest.raises(SkillLinkError, match=f"HTTP {status}"):
        SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
    assert transport["tokens"] == 1 and transport["links"] == transport["downloads"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"status": "failed", "message": "test-password"},
        {"status": "ok"},
        {"status": "ok", "result": {"token": "old-token-only"}},
        {"status": "ok", "result": {"newToken": ""}},
        {"status": "ok", "result": {"newToken": "bad\r\nheader"}},
        {"status": "ok", "result": {"newToken": 123}},
    ],
)
def test_token_payload_validation_does_not_echo_secrets(automatic, transport, payload):
    transport["token_json"] = payload
    with pytest.raises(SkillLinkError) as exc:
        SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
    assert "test-password" not in str(exc.value) and "old-token-only" not in str(exc.value)
    assert transport["links"] == 0


def test_bad_token_json_redacted(automatic, transport):
    transport["token_non_json"] = True
    with pytest.raises(SkillLinkError, match="invalid JSON") as exc:
        SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
    assert "private data" not in str(exc.value)


def test_token_transport_exception_redacted(monkeypatch, automatic, transport):
    def fail(*args, **kwargs):
        raise requests.ConnectionError(json.dumps(automatic))

    monkeypatch.setattr(requests.Session, "send", fail)
    with pytest.raises(SkillLinkError) as exc:
        SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
    assert automatic["password"] not in str(exc.value)
    assert automatic["hw_appkey"] not in str(exc.value)
    assert exc.value.__suppress_context__


@pytest.mark.parametrize(
    "field,value",
    [
        ("service_url", None),
        ("token_url", {}),
        ("token_url", "http://sso.example.test/token"),
        ("token_url", "https://sso.example.test/token?key=private"),
        ("hw_id", ""),
        ("hw_appkey", "invalid\nheader"),
        ("account", ""),
        ("password", ""),
    ],
)
def test_invalid_admin_profile_fails_before_network(automatic, transport, field, value):
    automatic[field] = value
    with pytest.raises(SkillLinkError):
        SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
    assert not transport["requests"]


def test_profile_repr_omits_credentials(automatic):
    profile = get_w3_profile("corp-skills", BASE)
    for field in ("hw_id", "hw_appkey", "account", "password"):
        assert automatic[field] not in repr(profile)


def test_optional_private_module_loading(monkeypatch):
    module_name = "apm_cli.deps.registry._skill_link_private"
    module = ModuleType(module_name)
    module.PROFILES = {"corp-skills": {"example": True}}
    monkeypatch.setitem(sys.modules, module_name, module)
    assert _load_private_profiles() == module.PROFILES
    module.PROFILES = "bad mapping"
    with pytest.raises(ValueError, match="must be a mapping"):
        _load_private_profiles()


def test_auto_auth_complete_mixed_install_and_frozen_reinstall(
    tmp_path, monkeypatch, automatic, transport
):
    run_mixed_install(tmp_path, monkeypatch, transport)
    assert transport["tokens"] == transport["links"]
    assert transport["tokens"] >= 4
    workspace = tmp_path / "workspace"
    for relative in ("apm.yml", "apm.lock.yaml"):
        content = (workspace / relative).read_text()
        assert "fresh-test-token" not in content and "Signature" not in content
        for field in ("hw_appkey", "account", "password"):
            assert automatic[field] not in content
