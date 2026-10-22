"""The configured endpoint owns the entire path for download and replay."""

from __future__ import annotations

import shutil

import pytest
from click.testing import CliRunner

from apm_cli.cli import cli
from apm_cli.deps.registry.skill_link_auth import get_builtin_agentcenter_url, get_w3_profile
from apm_cli.deps.registry.skill_link_client import SkillLinkClient, SkillLinkError
from apm_cli.models.apm_package import APMPackage, clear_apm_yml_cache
from apm_cli.utils.yaml_io import dump_yaml, load_yaml
from tests.unit.registry.test_skill_link import BASE, W3_URL, manifest
from tests.unit.registry.test_skill_link import credentials as credentials
from tests.unit.registry.test_skill_link import transport as transport
from tests.unit.registry.test_skill_link_auto_token import automatic as automatic


@pytest.mark.parametrize(
    "endpoint",
    [
        BASE,
        "https://skills.example.test/api/mcpService/external/skills/link/v1/get",
        "https://skills.example.test/Gateway/v7/ArtifactLink",
        "https://skills.example.test/Gateway/v7/ArtifactLink/",
    ],
)
def test_configured_path_is_used_exactly_in_install_and_cold_replay(
    tmp_path, monkeypatch, automatic, transport, endpoint
):
    automatic["agentcenter_url"] = endpoint
    transport["endpoint"] = endpoint
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("apm_cli.commands._helpers.check_for_updates", lambda *a, **kw: None)
    data = manifest({"id": "frontend-design", "kind": "knowledge", "version": "0.0.1"})
    del data["registries"]
    dump_yaml(data, tmp_path / "workspace.yml")
    runner = CliRunner()

    def install(*args):
        clear_apm_yml_cache()
        result = runner.invoke(cli, ["install", "--no-policy", "--parallel-downloads", "0", *args])
        assert result.exit_code == 0, result.output + repr(result.exception)

    install()
    lock_path = tmp_path / "apm.lock.yaml"
    lock = load_yaml(lock_path)
    entry = lock["dependencies"][0]
    requested = endpoint + "?skillId=frontend-design&version=0.0.1"
    assert entry["agentcenter_url"] == entry["resolved_url"] == requested
    for item in lock["deployments"]:
        assert item["owners"] == ["agentcenter:" + endpoint + "?skillId=frontend-design"]
        assert item["active_owner"] == item["owners"][0]
    assert [r.url for r in transport["requests"][:2]] == [W3_URL, requested]
    assert transport["tokens"] == 1

    original_lock = lock_path.read_bytes()
    install("--frozen")
    assert transport["tokens"] == 1
    shutil.rmtree(tmp_path / "apm_modules")
    shutil.rmtree(tmp_path / ".cac")
    install("--frozen")
    assert transport["tokens"] == 2
    assert [r.url for r in transport["requests"] if r.url.startswith(endpoint)] == [
        requested,
        requested,
    ]
    assert lock_path.read_bytes() == original_lock
    assert (tmp_path / ".cac/knowledge/frontend-design/SKILL.md").is_file()


@pytest.mark.parametrize("keep_new_field", [False, True])
def test_old_admin_service_url_is_rejected(automatic, transport, keep_new_field):
    automatic["service_url"] = "https://skills.example.test/api/mcpService"
    if not keep_new_field:
        del automatic["agentcenter_url"]
    for read in (get_builtin_agentcenter_url, lambda name: get_w3_profile(name, BASE)):
        with pytest.raises(ValueError, match="service_url is no longer supported"):
            read("corp-skills")
    assert not transport["requests"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://skills.example.test",
        "https://skills.example.test/",
        BASE + "?version=0.0.1",
        BASE + "#fragment",
        BASE.replace("https://", "https://user:secret@"),
        BASE.replace("https:", "http:"),
    ],
)
def test_invalid_endpoints_rejected_before_http(tmp_path, transport, endpoint):
    with pytest.raises(ValueError):
        APMPackage.from_mapping(manifest(url=endpoint), package_path=tmp_path)
    assert not transport["requests"]


def test_manual_credentials_require_exact_endpoint_not_parent_binding(monkeypatch, transport):
    from apm_cli import config

    monkeypatch.setattr(
        config, "_config_cache", {"registries": {"corp-skills": {"url": BASE.rsplit("/", 1)[0]}}}
    )
    with pytest.raises(SkillLinkError, match="Bind credentials to this endpoint"):
        SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
    assert not transport["requests"]
