"""Offline Git-dependency install through the real CAC deployment pipeline."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from apm_cli.utils.yaml_io import load_yaml
from tests.utils.isolated_apm_environment import IsolatedApmEnvironment
from tests.utils.local_git_repository import LocalGitRepositoryFactory
from tests.utils.local_package import LocalPackageFactory

pytestmark = [pytest.mark.e2e, pytest.mark.integration, pytest.mark.requires_apm_binary]


def _run_apm(binary: Path, project: Path, environment: dict[str, str], *args: str):
    return subprocess.run(
        (str(binary), *args),
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_git_package_installs_all_four_cac_resource_types(
    tmp_path: Path,
    apm_binary_path: Path,
) -> None:
    isolated = IsolatedApmEnvironment.create(tmp_path / "scenario", base_env=dict(os.environ))
    environment = isolated.subprocess_env()
    source = isolated.package_root / "cac-assets"
    source.mkdir(parents=True)
    (source / "apm.yml").write_text(
        "name: cac-assets\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    skill = source / ".apm" / "skills" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: review\ndescription: Review code\n---\n# Review\n",
        encoding="utf-8",
    )
    agent = source / ".apm" / "agents" / "reviewer.agent.md"
    agent.parent.mkdir(parents=True)
    agent.write_text("---\ndescription: Review code\n---\n# Reviewer\n", encoding="utf-8")
    knowledge = source / ".apm" / "knowledge" / "api" / "README.md"
    knowledge.parent.mkdir(parents=True)
    knowledge.write_text("# API v1\n", encoding="utf-8")
    obsolete = knowledge.parent / "obsolete.md"
    obsolete.write_text("old", encoding="utf-8")
    workflow = source / ".apm" / "workflows" / "design-review.yaml"
    workflow.parent.mkdir(parents=True)
    workflow_v1 = b"# Keep formatting\r\nsteps: [draft, review]\r\n"
    workflow.write_bytes(workflow_v1)
    workflow_obsolete = workflow.parent / "design" / "old.md"
    workflow_obsolete.parent.mkdir()
    workflow_obsolete.write_text("old workflow", encoding="utf-8")

    remote_url = "https://github.com/apm-fixture-org/cac-assets"
    repositories = LocalGitRepositoryFactory(isolated.repository_root, env=environment)
    repository = repositories.create("cac-assets", source_tree=source)
    repositories.commit(repository, message="seed CAC package")
    child_env = repositories.url_rewrite_subprocess_env(repository, remote_url)

    project = LocalPackageFactory(isolated.work_root).create(
        "cac-consumer",
        dependencies=("apm-fixture-org/cac-assets#main",),
        targets=("cac",),
    )
    installed = _run_apm(
        apm_binary_path,
        project.root,
        child_env,
        "install",
        "--no-policy",
        "--parallel-downloads",
        "0",
    )
    assert installed.returncode == 0, f"stdout={installed.stdout}\nstderr={installed.stderr}"
    assert (project.root / ".cac" / "skills" / "review" / "SKILL.md").is_file()
    assert (project.root / ".cac" / "agents" / "reviewer.md").is_file()
    deployed_knowledge = project.root / ".cac" / "knowledge" / "api" / "README.md"
    assert deployed_knowledge.read_text(encoding="utf-8") == "# API v1\n"
    deployed_workflow = project.root / ".cac" / "workflows" / "design-review.yaml"
    # Git may normalize source line endings; deployment must preserve the
    # bytes actually acquired into the managed package cache.
    cached_workflows = list((project.root / "apm_modules").rglob("design-review.yaml"))
    assert len(cached_workflows) == 1
    assert deployed_workflow.read_bytes() == cached_workflows[0].read_bytes()
    assert b"steps: [draft, review]" in deployed_workflow.read_bytes()
    lock = load_yaml(project.root / "apm.lock.yaml")
    deployed_files = set(lock["dependencies"][0]["deployed_files"])
    assert ".cac/knowledge/api/README.md" in deployed_files
    assert ".cac/agents/reviewer.md" in deployed_files
    assert ".cac/workflows/design-review.yaml" in deployed_files
    assert ".cac/workflows/design/old.md" in deployed_files

    # A new Git commit refreshes managed knowledge and prunes a deleted file.
    worktree_knowledge = repository.worktree / ".apm" / "knowledge" / "api" / "README.md"
    worktree_knowledge.write_text("# API v2\n", encoding="utf-8")
    (worktree_knowledge.parent / "obsolete.md").unlink()
    worktree_workflow = repository.worktree / ".apm" / "workflows" / "design-review.yaml"
    worktree_workflow.write_text("steps: [draft, review, revise]\n", encoding="utf-8")
    (worktree_workflow.parent / "design" / "old.md").unlink()
    repositories.commit(repository, message="update CAC knowledge and workflows")
    refreshed = _run_apm(
        apm_binary_path,
        project.root,
        child_env,
        "install",
        "--refresh",
        "--no-policy",
        "--parallel-downloads",
        "0",
    )
    assert refreshed.returncode == 0, f"stdout={refreshed.stdout}\nstderr={refreshed.stderr}"
    assert deployed_knowledge.read_text(encoding="utf-8") == "# API v2\n"
    assert not (deployed_knowledge.parent / "obsolete.md").exists()
    assert deployed_workflow.read_text(encoding="utf-8") == "steps: [draft, review, revise]\n"
    assert not (deployed_workflow.parent / "design" / "old.md").exists()
    refreshed_lock = load_yaml(project.root / "apm.lock.yaml")
    assert ".cac/workflows/design/old.md" not in refreshed_lock["dependencies"][0]["deployed_files"]

    # Reinstall is safe, and uninstall removes managed files without
    # disturbing user-authored knowledge in the same target directory.
    repeated = _run_apm(apm_binary_path, project.root, child_env, "install", "--no-policy")
    assert repeated.returncode == 0, f"stdout={repeated.stdout}\nstderr={repeated.stderr}"
    audited = _run_apm(apm_binary_path, project.root, child_env, "audit", "--ci", "--no-policy")
    assert audited.returncode == 0, f"stdout={audited.stdout}\nstderr={audited.stderr}"
    personal = project.root / ".cac" / "knowledge" / "personal.md"
    personal.write_text("personal", encoding="utf-8")
    personal_workflow = deployed_workflow.parent / "personal.md"
    personal_workflow.write_text("personal workflow", encoding="utf-8")
    removed = _run_apm(
        apm_binary_path,
        project.root,
        child_env,
        "uninstall",
        "apm-fixture-org/cac-assets",
    )
    assert removed.returncode == 0, f"stdout={removed.stdout}\nstderr={removed.stderr}"
    assert not deployed_knowledge.exists()
    assert not deployed_workflow.exists()
    assert not (project.root / ".cac" / "agents" / "reviewer.md").exists()
    assert not (project.root / ".cac" / "skills" / "review" / "SKILL.md").exists()
    assert personal.read_text(encoding="utf-8") == "personal"
    assert personal_workflow.read_text(encoding="utf-8") == "personal workflow"


def test_project_owned_workflow_install_update_and_prune(tmp_path: Path, apm_binary_path: Path):
    isolated = IsolatedApmEnvironment.create(tmp_path / "scenario", base_env=dict(os.environ))
    environment = isolated.subprocess_env()
    project = LocalPackageFactory(isolated.work_root).create("local-workflow", targets=("cac",))
    source = project.root / ".apm" / "workflows" / "review.md"
    source.parent.mkdir(parents=True)
    source.write_text("Read the design and review it.\n", encoding="utf-8")
    installed = _run_apm(apm_binary_path, project.root, environment, "install", "--no-policy")
    assert installed.returncode == 0, f"stdout={installed.stdout}\nstderr={installed.stderr}"
    destination = project.root / ".cac" / "workflows" / "review.md"
    assert destination.read_bytes() == source.read_bytes()
    source.write_text("Read the design, review it, and report findings.\n", encoding="utf-8")
    updated = _run_apm(apm_binary_path, project.root, environment, "install", "--no-policy")
    assert updated.returncode == 0, f"stdout={updated.stdout}\nstderr={updated.stderr}"
    assert destination.read_bytes() == source.read_bytes()
    personal = destination.parent / "personal.md"
    personal.write_text("personal", encoding="utf-8")
    source.unlink()
    pruned = _run_apm(apm_binary_path, project.root, environment, "install", "--no-policy")
    assert pruned.returncode == 0, f"stdout={pruned.stdout}\nstderr={pruned.stderr}"
    assert not destination.exists(), f"stdout={pruned.stdout}\nstderr={pruned.stderr}"
    assert personal.read_text(encoding="utf-8") == "personal"
