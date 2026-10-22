"""Complete AgentCenter locators, stable ownership and a deliberate format break."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from apm_cli.cli import cli
from apm_cli.deps.lockfile import LockedDependency, LockfileFormatError
from apm_cli.deps.registry.skill_link_config import agentcenter_identity, link_url
from apm_cli.models.apm_package import APMPackage, clear_apm_yml_cache
from apm_cli.utils.yaml_io import dump_yaml, load_yaml
from tests.unit.registry.test_skill_link import credentials as credentials
from tests.unit.registry.test_skill_link import manifest
from tests.unit.registry.test_skill_link import transport as transport
from tests.unit.registry.test_skill_link_auto_token import automatic as automatic

SERVICE = "https://skills.example.test/api/mcpService/external/skills/link/v1/get"
URL = SERVICE + "?skillId=frontend-design&version=0.0.1"
OWNER = "agentcenter:" + SERVICE + "?skillId=frontend-design"


@pytest.mark.parametrize("version", ["0.0.1", "1.0.0", "2.0.0-rc.1+build.3"])
def test_ownership_is_stable_across_versions(tmp_path, version):
    entry = {"id": "frontend-design", "kind": "knowledge", "version": version}
    dep = APMPackage.from_mapping(
        manifest(entry, url=SERVICE), package_path=tmp_path
    ).get_apm_dependencies()[0]
    assert dep.agentcenter_url == link_url(SERVICE, "frontend-design", version)
    assert dep.get_unique_key() == OWNER
    restored = LockedDependency.from_dict(
        {
            "repo_url": dep.repo_url,
            "source": "registry",
            "version": version,
            "agentcenter_url": dep.agentcenter_url,
            "resolved_url": dep.agentcenter_url,
        }
    )
    assert restored.get_unique_key() == restored.to_dependency_ref().get_unique_key() == OWNER
    assert (
        agentcenter_identity(
            link_url(SERVICE + "/other", "frontend-design", version), "frontend-design", version
        )
        != OWNER
    )


@pytest.mark.parametrize(
    "url",
    [
        SERVICE,
        URL.replace("frontend-design", "other-skill"),
        URL.replace("0.0.1", "0.0.2"),
        URL + "&version=0.0.1",
        URL + "&token=secret",
        URL + "#fragment",
        URL.replace("https://", "http://"),
        URL.replace("https://", "https://user:secret@"),
        "",
    ],
)
def test_invalid_complete_locator_is_rejected(url):
    with pytest.raises(ValueError, match="agentcenter_url"):
        LockedDependency.from_dict(
            {
                "repo_url": "frontend-design",
                "source": "registry",
                "version": "0.0.1",
                "agentcenter_url": url,
                "resolved_url": url,
            }
        )


def test_two_complete_locators_must_agree():
    with pytest.raises(ValueError, match="resolved_url must equal agentcenter_url"):
        LockedDependency.from_dict(
            {
                "repo_url": "frontend-design",
                "source": "registry",
                "version": "0.0.1",
                "agentcenter_url": URL,
                "resolved_url": URL.replace("0.0.1", "0.0.2"),
            }
        )


@pytest.mark.parametrize("include_new", [False, True])
@pytest.mark.parametrize("legacy_value", [None, SERVICE, URL])
def test_old_field_is_rejected_even_if_new_field_also_exists(include_new, legacy_value):
    data = {
        "repo_url": "frontend-design",
        "source": "registry",
        "version": "0.0.1",
        "resolved_url": URL,
        "skill_link_url": legacy_value,
    }
    if include_new:
        data["agentcenter_url"] = URL
    with pytest.raises(LockfileFormatError, match="skill_link_url is no longer supported"):
        LockedDependency.from_dict(data)


@pytest.mark.parametrize("kind", ["skills", "knowledge"])
def test_real_install_replay_ownership_and_old_lock_rejection(
    tmp_path, monkeypatch, transport, automatic, kind
):
    automatic["agentcenter_url"] = SERVICE
    transport["endpoint"] = SERVICE
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("apm_cli.commands._helpers.check_for_updates", lambda *a, **kw: None)
    data = manifest({"id": "frontend-design", "kind": kind, "version": "0.0.1"})
    del data["registries"]
    dump_yaml(data, tmp_path / "workspace.yml")
    manifest_bytes = (tmp_path / "workspace.yml").read_bytes()
    runner = CliRunner()

    def install(*args):
        clear_apm_yml_cache()
        return runner.invoke(cli, ["install", "--no-policy", "--parallel-downloads", "0", *args])

    result = install()
    assert result.exit_code == 0, result.output + repr(result.exception)
    lock_path = tmp_path / "apm.lock.yaml"
    initial = load_yaml(lock_path)
    entry = initial["dependencies"][0]
    assert entry["agentcenter_url"] == entry["resolved_url"] == URL
    assert entry["host"] == "skills.example.test"
    assert "skill_link_url" not in entry
    for deployment in initial["deployments"]:
        assert deployment["owners"] == [OWNER]
        assert deployment["active_owner"] == OWNER
    assert any(request.url == URL for request in transport["requests"])
    assert transport["links"] == transport["tokens"] == 1
    deployed = tmp_path / f".cac/{kind}/frontend-design/SKILL.md"
    deployed_bytes = deployed.read_bytes()

    lock_bytes = lock_path.read_bytes()
    result = install("--frozen")
    assert result.exit_code == 0, result.output + repr(result.exception)
    assert lock_path.read_bytes() == lock_bytes
    assert transport["links"] == 1

    # Simulate a lock emitted before the API host fix. Refresh must correct only
    # the source host without changing the immutable archive pin or ownership.
    old_lock = load_yaml(lock_path)
    old_lock["dependencies"][0]["host"] = "github.com"
    dump_yaml(old_lock, lock_path)
    result = install("--refresh")
    assert result.exit_code == 0, result.output + repr(result.exception)
    assert transport["links"] == transport["tokens"] == 2
    refreshed = load_yaml(lock_path)
    assert refreshed["dependencies"] == initial["dependencies"]
    assert refreshed["deployments"] == initial["deployments"]
    assert deployed.read_bytes() == deployed_bytes
    refreshed_bytes = lock_path.read_bytes()
    result = install("--frozen")
    assert result.exit_code == 0, result.output + repr(result.exception)
    assert lock_path.read_bytes() == refreshed_bytes
    assert transport["links"] == transport["tokens"] == 2

    # No compatibility read, even when both field names are present.
    invalid = load_yaml(lock_path)
    invalid["dependencies"][0]["skill_link_url"] = SERVICE
    dump_yaml(invalid, lock_path)
    invalid_bytes = lock_path.read_bytes()
    calls = len(transport["requests"])
    result = install()
    assert result.exit_code != 0
    assert "skill_link_url is no longer supported" in result.output + str(result.exception)
    assert len(transport["requests"]) == calls
    assert lock_path.read_bytes() == invalid_bytes
    assert deployed.read_bytes() == deployed_bytes

    # Explicitly set the old lock aside and regenerate, retaining existing output.
    lock_path.rename(tmp_path / "apm.lock.yaml.backup")
    result = install()
    assert result.exit_code == 0, result.output + repr(result.exception)
    assert "skill_link_url" not in lock_path.read_text()
    assert deployed.read_bytes() == deployed_bytes
    assert (tmp_path / "workspace.yml").read_bytes() == manifest_bytes

    removed = runner.invoke(cli, ["uninstall", "frontend-design"])
    assert removed.exit_code == 0, removed.output + repr(removed.exception)
    assert not deployed.exists()
