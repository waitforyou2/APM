"""Compact resources and project manifest selection through real install flows."""

from __future__ import annotations

import copy
import os
import shutil

import pytest
from click.testing import CliRunner

from apm_cli.cli import cli
from apm_cli.core.project_manifest import project_manifest_path
from apm_cli.deps.lockfile import LockedDependency
from apm_cli.models.apm_package import APMPackage, clear_apm_yml_cache
from apm_cli.models.dependency.reference import DependencyReference
from apm_cli.models.dependency.resource import ResourceSpec
from apm_cli.utils.yaml_io import dump_yaml, load_yaml
from tests.unit.registry.test_skill_link import BASE, manifest
from tests.unit.registry.test_skill_link import credentials as credentials
from tests.unit.registry.test_skill_link import transport as transport
from tests.unit.registry.test_skill_link_auto_token import automatic as automatic
from tests.utils.local_git_repository import LocalGitRepositoryFactory


def git_entry(kind="knowledge", resource_id="sdk"):
    return {
        "id": resource_id,
        "kind": kind,
        "git": "https://codehub.example.test/team/assets.git",
        "ref": "main",
        "path": f"resources/{resource_id}",
    }


@pytest.mark.parametrize("kind", ["skills", "agents", "knowledge", "workflows"])
def test_git_and_lock_preserve_compact_declaration(kind):
    data = git_entry(kind)
    dep = DependencyReference.parse_from_dict(data)
    assert dep.source == "git" and dep.alias == "sdk"
    assert dep.resource == ResourceSpec(kind, "sdk")
    assert dep.to_apm_yml_entry() == {**data, "git": data["git"].removesuffix(".git")}
    locked = LockedDependency.from_dependency_ref(
        dep, resolved_commit="a" * 40, depth=0, resolved_by=None
    )
    restored = LockedDependency.from_dict(locked.to_dict()).to_dependency_ref()
    assert restored.to_apm_yml_entry() == dep.to_apm_yml_entry()


@pytest.mark.parametrize("kind", ["skills", "knowledge"])
def test_api_and_lock_preserve_kind(tmp_path, kind):
    entry = {"id": "frontend-design", "kind": kind, "version": "0.0.1"}
    dep = APMPackage.from_mapping(manifest(entry), package_path=tmp_path).get_apm_dependencies()[0]
    assert dep.repo_url == "frontend-design" and dep.resource.kind == kind
    assert dep.to_apm_yml_entry() == {**entry, "registry": "corp-skills"}
    restored = LockedDependency.from_dict(
        LockedDependency(
            repo_url=dep.repo_url,
            source="registry",
            version="0.0.1",
            skill_link_url=BASE,
            resource=dep.resource,
            compact_resource=True,
        ).to_dict()
    ).to_dependency_ref()
    assert restored.resource == dep.resource and restored.compact_resource


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "agents"},
        {"kind": "workflows"},
        {"kind": "skill"},
        {"id": "../escape"},
        {"alias": "different"},
        {"resource": {"kind": "skills", "name": "frontend-design"}},
    ],
)
def test_bad_api_declarations_fail_before_requests(tmp_path, transport, changes):
    entry = {"id": "frontend-design", "kind": "skills", "version": "0.0.1", **changes}
    with pytest.raises(ValueError):
        APMPackage.from_mapping(manifest(entry), package_path=tmp_path)
    assert not transport["requests"]


def test_git_only_compact_never_loads_private_profile(tmp_path, monkeypatch):
    from apm_cli import config

    monkeypatch.setattr(config, "_config_cache", {})

    def fail():
        raise AssertionError("Git-only resources must not read private profiles")

    monkeypatch.setattr("apm_cli.deps.registry.skill_link_auth._load_private_profiles", fail)
    data = {"name": "example", "version": "0.1.0", "dependencies": {"apm": [git_entry()]}}
    dep = APMPackage.from_mapping(data, package_path=tmp_path).get_apm_dependencies()[0]
    assert dep.source == "git"


def test_duplicate_id_across_transports_is_rejected(tmp_path):
    data = manifest({"id": "frontend-design", "kind": "knowledge", "version": "0.0.1"})
    data["dependencies"]["apm"].append(git_entry("agents", "frontend-design"))
    with pytest.raises(ValueError, match="Duplicate Workspace resource id"):
        APMPackage.from_mapping(data, package_path=tmp_path)


def test_one_git_directory_cannot_be_projected_twice(tmp_path):
    first = git_entry("knowledge", "sdk")
    second = {**first, "id": "other", "kind": "skills"}
    data = {"name": "example", "version": "0.1.0", "dependencies": {"apm": [first, second]}}
    with pytest.raises(ValueError, match="registered only once"):
        APMPackage.from_mapping(data, package_path=tmp_path)


def test_manifest_selection_is_presence_based(tmp_path):
    assert project_manifest_path(tmp_path) == tmp_path / "apm.yml"
    (tmp_path / "apm.yml").write_text("fallback")
    workspace = tmp_path / "workspace.yml"
    workspace.write_text("broken: [")
    assert project_manifest_path(tmp_path) == workspace
    workspace.unlink()
    workspace.mkdir()
    assert project_manifest_path(tmp_path) == workspace


@pytest.mark.parametrize("content", ["broken: [", "", "[]", "name: incomplete"])
def test_invalid_workspace_never_uses_apm(tmp_path, monkeypatch, transport, content):
    dump_yaml(manifest(), tmp_path / "apm.yml")
    (tmp_path / "workspace.yml").write_text(content)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("apm_cli.commands._helpers.check_for_updates", lambda *a, **kw: None)
    result = CliRunner().invoke(cli, ["install", "--no-policy"])
    assert result.exit_code != 0, result.output
    assert "workspace.yml" in result.output
    assert not transport["requests"]
    assert not (tmp_path / ".cac").exists()


@pytest.mark.parametrize("filename", ["workspace.yml", "apm.yml"])
def test_complete_workspace_lifecycle(tmp_path, monkeypatch, transport, automatic, filename):
    monkeypatch.setenv("APM_CACHE_DIR", str(tmp_path / "cache"))
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "APM Test")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "test@example.test")
    source = tmp_path / "source"
    files = {
        "auditor/role.md": "# Auditor\n",
        "review/FLOW.md": "# Review\n",
        "sdk/SKILL.md": "# SDK knowledge\n",
        "git-skill/SKILL.md": "---\nname: git-skill\ndescription: Example\n---\n# Skill\n",
    }
    for relative, content in files.items():
        path = source / "resources" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    factory = LocalGitRepositoryFactory(tmp_path / "repos", env=dict(os.environ))
    repo = factory.create("assets", source_tree=source)
    factory.commit(repo, message="fixtures")
    for key, value in factory.url_rewrite_subprocess_env(repo, git_entry()["git"]).items():
        if key.startswith("GIT_"):
            monkeypatch.setenv(key, value)
    project = tmp_path / "project"
    project.mkdir()
    data = manifest({"id": "frontend-design", "kind": "skills", "version": "0.0.1"})
    del data["registries"]  # Built-in default also coexists with Git id/kind.
    data["dependencies"]["apm"] += [
        git_entry("agents", "auditor"),
        git_entry("workflows", "review"),
        git_entry("knowledge", "sdk"),
        git_entry("skills", "git-skill"),
    ]
    data["relations"] = {
        "agents": {"auditor": {"usesSkills": ["frontend-design"], "usesKnowledge": ["sdk"]}}
    }
    data["product"] = {"name": "DME", "version": "DME V100R026C10"}
    data["workflowSequence"] = ["review"]
    selected = project / filename
    dump_yaml(data, selected)
    fallback_bytes = b"invalid: [do not read or overwrite\n"
    if filename == "workspace.yml":
        (project / "apm.yml").write_bytes(fallback_bytes)
    monkeypatch.chdir(project)
    monkeypatch.setattr("apm_cli.commands._helpers.check_for_updates", lambda *a, **kw: None)
    runner = CliRunner()

    def install(*options):
        clear_apm_yml_cache()
        result = runner.invoke(
            cli, ["install", "--no-policy", "--parallel-downloads", "0", *options]
        )
        assert result.exit_code == 0, result.output + repr(result.exception)
        return result

    original_bytes = selected.read_bytes()
    install()
    for relative in [
        "agents/auditor.md",
        "workflows/review/FLOW.md",
        "knowledge/sdk/SKILL.md",
        "skills/git-skill/SKILL.md",
        "skills/frontend-design/SKILL.md",
    ]:
        assert (project / ".cac" / relative).is_file(), relative
    assert selected.read_bytes() == original_bytes
    calls = transport["links"]
    install()
    assert transport["links"] == calls

    # Changing only kind is a deployment change, not a new API identity/version.
    data["dependencies"]["apm"][0]["kind"] = "knowledge"
    dump_yaml(data, selected)
    clear_apm_yml_cache()
    frozen = runner.invoke(cli, ["install", "--frozen", "--no-policy"])
    assert frozen.exit_code != 0 and transport["links"] == calls
    install()
    assert not (project / ".cac/skills/frontend-design/SKILL.md").exists()
    assert (project / ".cac/knowledge/frontend-design/SKILL.md").is_file()
    lock = load_yaml(project / "apm.lock.yaml")
    api_lock = next(d for d in lock["dependencies"] if d.get("skill_link_url") == BASE)
    assert api_lock["resource"] == {"kind": "knowledge", "name": "frontend-design"}
    assert api_lock["compact_resource"] is True
    calls = transport["links"]
    install()
    assert transport["links"] == calls
    shutil.rmtree(project / "apm_modules")
    shutil.rmtree(project / ".cac")
    install("--frozen")
    assert (project / ".cac/knowledge/frontend-design/SKILL.md").is_file()
    assert not (project / ".cac/skills/frontend-design").exists()
    install("--refresh")
    if filename == "workspace.yml":
        assert (project / "apm.yml").read_bytes() == fallback_bytes
    assert load_yaml(selected)["relations"] == data["relations"]

    # Uninstall edits the selected manifest only, retaining unrelated metadata.
    removed = runner.invoke(cli, ["uninstall", "frontend-design"])
    assert removed.exit_code == 0, removed.output + repr(removed.exception)
    remaining = load_yaml(selected)
    assert len(remaining["dependencies"]["apm"]) == 4
    assert remaining["relations"] == data["relations"]
    assert all("id" in dep and "kind" in dep for dep in remaining["dependencies"]["apm"])
    assert not (project / ".cac/knowledge/frontend-design/SKILL.md").exists()
    if filename == "workspace.yml":
        assert (project / "apm.yml").read_bytes() == fallback_bytes


def test_workspace_only_install_to_other_root(tmp_path, monkeypatch, transport, automatic):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    data = manifest({"id": "frontend-design", "kind": "knowledge", "version": "0.0.1"})
    del data["registries"]
    dump_yaml(data, source / "workspace.yml")
    monkeypatch.chdir(source)
    monkeypatch.setenv("APM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("apm_cli.commands._helpers.check_for_updates", lambda *a, **kw: None)
    result = CliRunner().invoke(cli, ["install", "--no-policy", "--root", str(destination)])
    assert result.exit_code == 0, result.output + repr(result.exception)
    assert (destination / ".cac/knowledge/frontend-design/SKILL.md").is_file()
    assert (destination / "apm.lock.yaml").is_file()
    assert not (source / "apm.yml").exists()
    assert not (destination / "apm.yml").exists()
    assert not (source / ".cac").exists()


def test_example_parses_all_resources_and_relations(tmp_path, automatic):
    from pathlib import Path

    example = Path(__file__).resolve().parents[3] / "examples/dme-workspace/workspace.yml"
    data = load_yaml(example)
    original = copy.deepcopy(data)
    deps = APMPackage.from_mapping(data, package_path=tmp_path).get_apm_dependencies()
    assert len(deps) == 14
    assert len([dep for dep in deps if dep.resource.kind == "knowledge"]) == 4
    assert data == original
