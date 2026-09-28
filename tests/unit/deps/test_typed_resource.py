"""Typed Git-resource contracts are opt-in and preserve legacy manifests."""

from pathlib import Path

import pytest

from apm_cli.deps.lockfile import LockedDependency, LockFile
from apm_cli.deps.resource_projection import project_resource_directory
from apm_cli.drift import detect_ref_change
from apm_cli.install.plan import build_update_plan, lockfile_satisfies_manifest
from apm_cli.models.dependency.reference import DependencyReference
from apm_cli.models.dependency.resource import ResourceSpec
from apm_cli.models.validation import validate_apm_package


@pytest.mark.parametrize(
    ("kind", "filename", "destination"),
    [
        ("skills", "SKILL.md", ".apm/skills/sample/SKILL.md"),
        ("agents", "old.agent.md", ".apm/agents/sample.agent.md"),
        ("knowledge", "index.md", ".apm/knowledge/sample/index.md"),
        ("workflows", "WORKFLOW.md", ".apm/workflows/sample/WORKFLOW.md"),
        ("playbooks", "index.md", ".apm/playbooks/sample/index.md"),
    ],
)
def test_projection_preserves_content_and_validates(
    tmp_path: Path, kind: str, filename: str, destination: str
) -> None:
    (tmp_path / filename).write_text("original bytes\n", encoding="utf-8")
    spec = ResourceSpec.parse({"kind": kind, "name": "sample"})
    project_resource_directory(tmp_path, spec)
    assert (tmp_path / destination).read_text(encoding="utf-8") == "original bytes\n"
    assert validate_apm_package(tmp_path).is_valid


def test_legacy_directory_is_untouched(tmp_path: Path) -> None:
    (tmp_path / "index.md").write_text("legacy\n", encoding="utf-8")
    project_resource_directory(tmp_path, None)
    assert not (tmp_path / "apm.yml").exists()
    assert (tmp_path / "index.md").read_text(encoding="utf-8") == "legacy\n"


def test_manifest_and_lockfile_round_trip() -> None:
    dep = DependencyReference.parse_from_dict(
        {
            "git": "https://github.com/example/resources.git",
            "path": "knowledge/sample",
            "ref": "main",
            "targets": ["cac"],
            "resource": {"kind": "knowledge", "name": "sample"},
        }
    )
    assert dep.resource == ResourceSpec("knowledge", "sample")
    assert dep.to_apm_yml_entry()["resource"] == {"kind": "knowledge", "name": "sample"}
    locked = LockedDependency.from_dependency_ref(
        dep, resolved_commit="a" * 40, depth=0, resolved_by=None
    )
    restored = LockedDependency.from_dict(locked.to_dict()).to_dependency_ref()
    assert restored.resource == dep.resource


def test_changing_only_resource_type_invalidates_locked_projection() -> None:
    dep = DependencyReference.parse_from_dict(
        {
            "git": "https://github.com/example/resources.git",
            "path": "shared/sdk",
            "ref": "main",
            "resource": {"kind": "playbooks", "name": "sdk"},
        }
    )
    locked = LockedDependency(
        repo_url=dep.repo_url,
        host=dep.host,
        virtual_path=dep.virtual_path,
        is_virtual=True,
        resolved_ref="main",
        resource=ResourceSpec("knowledge", "sdk"),
    )
    lockfile = LockFile(dependencies={dep.get_unique_key(): locked})
    assert detect_ref_change(dep, locked)
    assert detect_ref_change(dep, locked, update_refs=True)
    assert build_update_plan(lockfile, [dep]).entries[0].action == "update"
    satisfied, reasons = lockfile_satisfies_manifest(lockfile, [dep])
    assert not satisfied
    assert "resource kind/name" in reasons[0]


@pytest.mark.parametrize(
    "resource",
    [
        {"kind": "knowledge", "name": "../escape"},
        {"kind": "knowledge", "name": "con"},
        {"kind": "hooks", "name": "sample"},
        {"kind": "knowledge"},
    ],
)
def test_invalid_resource_rejected(resource: dict) -> None:
    with pytest.raises(ValueError):
        DependencyReference.parse_from_dict(
            {"git": "https://github.com/example/resources.git", "resource": resource}
        )


def test_typed_resource_does_not_accept_existing_package(tmp_path: Path) -> None:
    (tmp_path / "apm.yml").write_text("name: old\nversion: 1.0.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="plain directory"):
        project_resource_directory(tmp_path, ResourceSpec("knowledge", "sample"))


def test_empty_resource_tree_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="no files"):
        project_resource_directory(tmp_path, ResourceSpec("knowledge", "sample"))
