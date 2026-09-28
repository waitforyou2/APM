"""Workflow distribution preserves content, ownership, and target boundaries."""

from pathlib import Path

import pytest

from apm_cli.deps.package_validator import PackageValidator
from apm_cli.install.deployable_source_plan import DeployableSourcePlan
from apm_cli.integration.base_integrator import BaseIntegrator
from apm_cli.integration.targets import KNOWN_TARGETS
from apm_cli.integration.workflow_integrator import WorkflowIntegrator
from apm_cli.models.apm_package import APMPackage, PackageInfo, PackageType
from apm_cli.models.validation import validate_apm_package
from apm_cli.utils.diagnostics import DiagnosticCollector

CAC = KNOWN_TARGETS["cac"]


def _package(root: Path) -> PackageInfo:
    return PackageInfo(
        package=APMPackage(
            name="design-workflow", version="1.0.0", package_path=root, source="local"
        ),
        install_path=root,
        package_type=PackageType.APM_PACKAGE,
    )


def _plan(package: PackageInfo, target=CAC) -> DeployableSourcePlan:
    return DeployableSourcePlan.create(
        package,
        [target],
        skill_subset=None,
        hooks_approved=False,
        canvas_approved=False,
        skip_bin=True,
    )


@pytest.mark.parametrize("use_plan", [False, True])
def test_workflow_files_and_assets_are_copied_verbatim(tmp_path, use_plan):
    root = tmp_path / "package"
    workflows = root / ".apm" / "workflows"
    payloads = {
        "design-review.yaml": b"# Keep comments\r\nsteps:\r\n  - review\r\n",
        "design/WORKFLOW.md": "# 设计流程\n按步骤阅读技能和知识。\n".encode(),
        "design/assets/diagram.bin": b"\x00\xff\x10",
    }
    for relative, content in payloads.items():
        source = workflows / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
    package = _package(root)
    plan = _plan(package)
    assert plan.paths == {f".apm/workflows/{name}" for name in payloads}
    project = tmp_path / "project"
    project.mkdir()
    result = WorkflowIntegrator().integrate_workflows_for_target(
        CAC, package, project, source_plan=plan if use_plan else None
    )
    assert result.files_integrated == len(payloads)
    assert {path.relative_to(project).as_posix() for path in result.target_paths} == {
        f".cac/workflows/{name}" for name in payloads
    }
    for relative, content in payloads.items():
        assert (project / ".cac" / "workflows" / relative).read_bytes() == content


def test_workflow_respects_source_plan_and_unsupported_target(tmp_path):
    root = tmp_path / "package"
    workflows = root / ".apm" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "allowed.yaml").write_text("steps: []", encoding="utf-8")
    (workflows / "excluded.yaml").write_text("steps: []", encoding="utf-8")
    package = _package(root)
    plan = DeployableSourcePlan(root, frozenset({".apm/workflows/allowed.yaml"}))
    project = tmp_path / "project"
    project.mkdir()
    result = WorkflowIntegrator().integrate_workflows_for_target(
        CAC, package, project, source_plan=plan
    )
    assert result.files_integrated == 1
    assert not (project / ".cac/workflows/excluded.yaml").exists()
    claude = KNOWN_TARGETS["claude"]
    assert not _plan(package, claude).paths
    result = WorkflowIntegrator().integrate_workflows_for_target(claude, package, project)
    assert not result.target_paths
    assert not (project / ".claude").exists()


def test_workflow_collision_adoption_force_and_owned_updates(tmp_path):
    root = tmp_path / "package"
    source = root / ".apm/workflows/review.yaml"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"steps: [review]\n")
    package = _package(root)
    project = tmp_path / "project"
    destination = project / ".cac/workflows/review.yaml"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"personal flow")
    integrator = WorkflowIntegrator()
    kwargs = {
        "managed_files": set(),
        "source_plan": _plan(package),
        "diagnostics": DiagnosticCollector(),
    }
    result = integrator.integrate_workflows_for_target(CAC, package, project, **kwargs)
    assert result.files_skipped == 1
    assert destination.read_bytes() == b"personal flow"
    assert not result.target_paths

    result = integrator.integrate_workflows_for_target(CAC, package, project, force=True, **kwargs)
    assert result.files_integrated == 1
    assert destination.read_bytes() == source.read_bytes()

    result = integrator.integrate_workflows_for_target(CAC, package, project, **kwargs)
    assert result.files_adopted == 1
    assert result.target_paths == [destination]

    source.write_bytes(b"steps: [draft, review]\n")
    result = integrator.integrate_workflows_for_target(
        CAC,
        package,
        project,
        managed_files={".cac/workflows/review.yaml"},
        source_plan=_plan(package),
    )
    assert result.files_integrated == 1
    assert destination.read_bytes() == source.read_bytes()


def test_workflow_sync_only_removes_tracked_workflows(tmp_path):
    project = tmp_path / "project"
    payloads = {
        ".cac/workflows/review.yaml": b"managed",
        ".cac/workflows/personal.md": b"personal",
        ".cac/knowledge/team/README.md": b"knowledge",
    }
    for name, content in payloads.items():
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    managed = {".cac/workflows/review.yaml", ".cac/knowledge/team/README.md"}
    assert BaseIntegrator.partition_managed_files(managed)["workflows_cac"] == {
        ".cac/workflows/review.yaml"
    }
    stats = WorkflowIntegrator().sync_for_target(CAC, None, project, managed_files=managed)
    assert stats == {"files_removed": 1, "errors": 0}
    assert not (project / ".cac/workflows/review.yaml").exists()
    assert (project / ".cac/workflows/personal.md").read_bytes() == b"personal"
    assert (project / ".cac/knowledge/team/README.md").read_bytes() == b"knowledge"


@pytest.mark.parametrize("relative", ["review.yaml", "design/WORKFLOW.md"])
def test_workflow_only_package_is_valid(tmp_path, relative):
    (tmp_path / "apm.yml").write_text("name: workflow-only\nversion: 1.0.0\n", encoding="utf-8")
    source = tmp_path / ".apm" / "workflows" / relative
    source.parent.mkdir(parents=True)
    source.write_text("Read the design and review it.", encoding="utf-8")
    for result in (
        validate_apm_package(tmp_path),
        PackageValidator().validate_package_structure(tmp_path),
    ):
        assert result.is_valid, result.errors
        assert not any("No primitive files" in warning for warning in result.warnings)


@pytest.mark.parametrize("link_source", [True, False])
def test_workflow_does_not_follow_symlinks(tmp_path, link_source):
    root = tmp_path / "package"
    source = root / ".apm/workflows/review.yaml"
    source.parent.mkdir(parents=True)
    project = tmp_path / "project"
    destination = project / ".cac/workflows/review.yaml"
    destination.parent.mkdir(parents=True)
    outside = tmp_path / "outside.yaml"
    outside.write_bytes(b"outside")
    link = source if link_source else destination
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"Symlink creation is unavailable: {exc}")
    if not link_source:
        source.write_bytes(b"steps: [review]")
    package = _package(root)
    result = WorkflowIntegrator().integrate_workflows_for_target(
        CAC, package, project, source_plan=_plan(package), force=True
    )
    assert not result.target_paths
    assert outside.read_bytes() == b"outside"
    if link_source:
        assert not _plan(package).paths
        assert not WorkflowIntegrator.find_workflow_files(root)
        assert not destination.exists()
