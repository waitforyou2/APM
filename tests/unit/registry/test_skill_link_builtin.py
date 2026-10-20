"""Built-in Skill Link routing without an author-written registries block."""

from __future__ import annotations

import copy
import shutil

import pytest

from apm_cli.models.apm_package import APMPackage, clear_apm_yml_cache
from apm_cli.models.manifest_contract import OPENAPM_V01_SCHEMA_URI
from tests.unit.registry.test_skill_link import BASE, manifest
from tests.unit.registry.test_skill_link import credentials as credentials
from tests.unit.registry.test_skill_link import (
    test_cli_mixed_install_frozen_reinstall_and_noop as run_mixed_install,
)
from tests.unit.registry.test_skill_link import transport as transport
from tests.unit.registry.test_skill_link_auto_token import automatic as automatic


def implicit_manifest():
    data = manifest()
    del data["registries"]
    return data


def test_builtin_routes_objects_without_mutating_yaml(tmp_path, automatic, transport):
    data = implicit_manifest()
    original = copy.deepcopy(data)
    pkg = APMPackage.from_mapping(data, package_path=tmp_path)
    dep = pkg.get_apm_dependencies()[0]
    assert dep.skill_link_url == BASE
    assert dep.registry_name == pkg.default_registry == "corp-skills"
    assert pkg.registry_providers == {"corp-skills": "skill-link-v1"}
    assert pkg.registries["corp-skills"] == BASE
    assert data == original
    assert not transport["requests"]


def test_url_comes_from_current_profile_not_another_constant(tmp_path, automatic):
    automatic["service_url"] = "https://changed.example.test/api/mcpService/"
    pkg = APMPackage.from_mapping(implicit_manifest(), package_path=tmp_path)
    assert pkg.get_apm_dependencies()[0].skill_link_url == automatic["service_url"].rstrip("/")


def test_profile_routing_does_not_require_password_or_login(tmp_path, automatic, transport):
    # Parsing/linting does not authenticate. Download-time validation still does.
    automatic["password"] = ""
    pkg = APMPackage.from_mapping(implicit_manifest(), package_path=tmp_path)
    assert pkg.registries["corp-skills"] == BASE
    assert not transport["requests"]


def test_builtin_handles_dev_dependencies_and_serialized_registry_name(tmp_path, automatic):
    data = implicit_manifest()
    data["devDependencies"] = data.pop("dependencies")
    data["devDependencies"]["apm"][0]["registry"] = "corp-skills"
    pkg = APMPackage.from_mapping(data, package_path=tmp_path)
    dep = pkg.dev_dependencies["apm"][0]
    assert dep.skill_link_url == BASE
    roundtrip = dep.to_apm_yml_entry()
    data["devDependencies"]["apm"] = [roundtrip]
    assert APMPackage.from_mapping(data, package_path=tmp_path).dev_dependencies["apm"][0] == dep


def test_explicit_provider_and_native_registry_take_precedence(tmp_path, automatic):
    explicit = manifest(url="https://explicit.example.test")
    pkg = APMPackage.from_mapping(explicit, package_path=tmp_path)
    assert pkg.get_apm_dependencies()[0].skill_link_url == "https://explicit.example.test"
    explicit["registries"] = {"native": {"url": "https://native.test"}, "default": "native"}
    explicit["dependencies"]["apm"][0]["id"] = "acme/skill"
    pkg = APMPackage.from_mapping(explicit, package_path=tmp_path)
    dep = pkg.get_apm_dependencies()[0]
    assert dep.registry_name == "native" and dep.skill_link_url is None
    assert pkg.registry_providers is None


@pytest.mark.parametrize("block", [{}, None, {"default": "missing"}, "invalid"])
def test_explicit_empty_or_invalid_block_does_not_fall_back(tmp_path, automatic, block):
    data = implicit_manifest()
    data["registries"] = block
    with pytest.raises(ValueError):
        APMPackage.from_mapping(data, package_path=tmp_path)


def test_explicit_unknown_registry_does_not_fall_back(tmp_path, automatic, transport):
    data = implicit_manifest()
    data["dependencies"]["apm"][0]["registry"] = "misspelled"
    with pytest.raises(ValueError):
        APMPackage.from_mapping(data, package_path=tmp_path)
    assert not transport["requests"]


def test_mixed_git_objects_and_shorthands_keep_git_semantics(tmp_path, automatic):
    data = implicit_manifest()
    data["dependencies"]["apm"] += [
        {"git": "https://github.com/acme/assets.git", "ref": "main"},
        "acme/other#v1.0.0",
    ]
    _, explicit, shorthand = APMPackage.from_mapping(
        data, package_path=tmp_path
    ).get_apm_dependencies()
    assert explicit.source == "git" and explicit.skill_link_url is None
    assert shorthand.source != "registry" and shorthand.skill_link_url is None


def test_git_only_never_loads_profile_or_enables_registry(tmp_path, monkeypatch):
    from apm_cli import config

    monkeypatch.setattr(config, "_config_cache", {})

    def fail():
        raise AssertionError("Git-only install must not read private profiles")

    monkeypatch.setattr("apm_cli.deps.registry.skill_link_auth._load_private_profiles", fail)
    data = {"name": "git-only", "version": "0.1.0", "dependencies": {"apm": ["acme/repo"]}}
    pkg = APMPackage.from_mapping(data, package_path=tmp_path)
    assert pkg.registries is None and pkg.default_registry is None


def test_explicit_block_never_loads_builtin_profile(tmp_path, monkeypatch):
    def fail():
        raise AssertionError("Explicit registry routing must not read build credentials")

    monkeypatch.setattr("apm_cli.deps.registry.skill_link_auth._load_private_profiles", fail)
    pkg = APMPackage.from_mapping(manifest(), package_path=tmp_path)
    assert pkg.get_apm_dependencies()[0].skill_link_url == BASE


def test_feature_gate_still_required(tmp_path, monkeypatch, automatic):
    from apm_cli import config

    monkeypatch.setattr(config, "_config_cache", {})
    with pytest.raises(ValueError, match="experimental"):
        APMPackage.from_mapping(implicit_manifest(), package_path=tmp_path)


def test_builtin_does_not_change_explicit_openapm_contract(tmp_path, automatic):
    data = implicit_manifest()
    data["$schema"] = OPENAPM_V01_SCHEMA_URI
    with pytest.raises(ValueError, match="owner/repo"):
        APMPackage.from_mapping(data, package_path=tmp_path)


def test_missing_private_profile_keeps_native_behavior(tmp_path, monkeypatch):
    monkeypatch.setattr("apm_cli.deps.registry.skill_link_auth._load_private_profiles", lambda: {})
    data = implicit_manifest()
    data["dependencies"]["apm"][0] = {"id": "acme/skill", "version": "1.0.0"}
    dep = APMPackage.from_mapping(data, package_path=tmp_path).get_apm_dependencies()[0]
    assert dep.skill_link_url is None


def test_implicit_default_overrides_stale_local_url_and_default(tmp_path, monkeypatch, automatic):
    from apm_cli import config

    monkeypatch.setattr(
        config,
        "_config_cache",
        {
            "experimental": {"registries": True},
            "registries": {
                "corp-skills": {"url": "https://stale.test"},
                "other": {"url": "https://other.test", "default": True},
            },
        },
    )
    pkg = APMPackage.from_mapping(implicit_manifest(), package_path=tmp_path)
    assert pkg.registries["corp-skills"] == BASE
    assert pkg.get_apm_dependencies()[0].skill_link_url == BASE
    assert pkg.default_registry == "corp-skills"


@pytest.mark.parametrize("value", [None, {}, "http://insecure.test"])
def test_bad_builtin_address_fails_without_network(tmp_path, automatic, transport, value):
    automatic["service_url"] = value
    with pytest.raises(ValueError):
        APMPackage.from_mapping(implicit_manifest(), package_path=tmp_path)
    assert not transport["requests"]


def test_implicit_complete_mixed_cli_flow(tmp_path, monkeypatch, automatic, transport):
    from apm_cli import config
    from apm_cli.utils.yaml_io import load_yaml

    monkeypatch.setattr(config, "_config_cache", {"experimental": {"registries": True}})
    monkeypatch.setattr("tests.unit.registry.test_skill_link.manifest", implicit_manifest)
    run_mixed_install(tmp_path, monkeypatch, transport)
    project = tmp_path / "workspace"
    assert "registries" not in load_yaml(project / "apm.yml")
    assert transport["tokens"] == transport["links"] >= 4


def test_removing_explicit_block_preserves_lock_and_rejects_changed_origin(
    tmp_path, monkeypatch, automatic, transport
):
    from click.testing import CliRunner

    from apm_cli.cli import cli
    from apm_cli.utils.yaml_io import dump_yaml

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("APM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("apm_cli.commands._helpers.check_for_updates", lambda *a, **kw: None)
    data = manifest()
    path = tmp_path / "apm.yml"
    dump_yaml(data, path)
    runner = CliRunner()

    def install(*args):
        result = runner.invoke(cli, ["install", "--no-policy", "--parallel-downloads", "0", *args])
        assert result.exit_code == 0, result.output + repr(result.exception)

    install()
    original_lock = (tmp_path / "apm.lock.yaml").read_bytes()
    calls = transport["links"]
    del data["registries"]
    dump_yaml(data, path)
    clear_apm_yml_cache()
    install("--frozen")
    assert transport["links"] == calls
    assert (tmp_path / "apm.lock.yaml").read_bytes() == original_lock
    shutil.rmtree(tmp_path / "apm_modules")
    shutil.rmtree(tmp_path / ".cac")
    install("--frozen")
    assert transport["links"] > calls
    assert (tmp_path / ".cac/skills/frontend-design/SKILL.md").is_file()
    assert (tmp_path / "apm.lock.yaml").read_bytes() == original_lock
    assert "registries:" not in path.read_text()

    automatic["service_url"] = "https://other.example.test"
    clear_apm_yml_cache()
    calls = len(transport["requests"])
    result = runner.invoke(cli, ["install", "--no-policy", "--frozen"])
    assert result.exit_code != 0
    assert len(transport["requests"]) == calls
    assert (tmp_path / "apm.lock.yaml").read_bytes() == original_lock
