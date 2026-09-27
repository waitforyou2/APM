"""CAC target and first-class knowledge deployment tests."""

from pathlib import Path

from apm_cli.core.target_catalog import manifest_target_names
from apm_cli.deps.package_validator import PackageValidator
from apm_cli.install.deployable_source_plan import DeployableSourcePlan
from apm_cli.integration.base_integrator import BaseIntegrator
from apm_cli.integration.coverage import check_primitive_coverage
from apm_cli.integration.dispatch import get_dispatch_table
from apm_cli.integration.knowledge_integrator import KnowledgeIntegrator
from apm_cli.integration.targets import KNOWN_TARGETS, resolve_targets
from apm_cli.models.apm_package import APMPackage, PackageInfo, PackageType
from apm_cli.models.validation import validate_apm_package
from apm_cli.utils.diagnostics import DiagnosticCollector

CAC = KNOWN_TARGETS["cac"]


def _package(root: Path) -> PackageInfo:
    package = APMPackage(name="team-assets", version="1.0.0", package_path=root, source="local")
    return PackageInfo(package=package, install_path=root, package_type=PackageType.APM_PACKAGE)


def _plan(package: PackageInfo) -> DeployableSourcePlan:
    return DeployableSourcePlan.create(
        package,
        [CAC],
        skill_subset=None,
        hooks_approved=False,
        canvas_approved=False,
        skip_bin=True,
    )


def test_cac_is_explicit_project_target_with_all_three_directories(tmp_path):
    assert "cac" in manifest_target_names()
    assert resolve_targets(tmp_path, explicit_target="cac") == [CAC]
    assert CAC.root_dir == ".cac"
    assert {name: mapping.subdir for name, mapping in CAC.primitives.items()} == {
        "agents": "agents",
        "skills": "skills",
        "knowledge": "knowledge",
    }
    assert CAC.for_scope(user_scope=True) is None
    check_primitive_coverage(get_dispatch_table())


def test_knowledge_bundle_preserves_nested_binary_data_and_is_tracked(tmp_path):
    package_root = tmp_path / "package"
    bundle = package_root / ".apm" / "knowledge" / "api"
    (bundle / "images").mkdir(parents=True)
    (bundle / "README.md").write_text("# API\n", encoding="utf-8")
    (bundle / "images" / "flow.bin").write_bytes(b"\x00\xff\x10")
    (bundle.parent / "loose.md").write_text("not a bundle", encoding="utf-8")
    package = _package(package_root)
    plan = _plan(package)
    assert ".apm/knowledge/api/README.md" in plan.paths
    assert ".apm/knowledge/api/images/flow.bin" in plan.paths
    assert ".apm/knowledge/loose.md" not in plan.paths

    project = tmp_path / "project"
    project.mkdir()
    result = KnowledgeIntegrator().integrate_knowledge_for_target(
        CAC,
        package,
        project,
        managed_files=set(),
        diagnostics=DiagnosticCollector(),
        source_plan=plan,
    )
    assert result.files_integrated == 2
    assert (project / ".cac" / "knowledge" / "api" / "README.md").read_text() == "# API\n"
    assert (
        project / ".cac" / "knowledge" / "api" / "images" / "flow.bin"
    ).read_bytes() == b"\x00\xff\x10"
    assert {path.relative_to(project).as_posix() for path in result.target_paths} == {
        ".cac/knowledge/api/README.md",
        ".cac/knowledge/api/images/flow.bin",
    }
    assert not (project / ".cac" / "knowledge" / "loose.md").exists()


def test_knowledge_collision_adoption_and_managed_update(tmp_path):
    package_root = tmp_path / "package"
    bundle = package_root / ".apm" / "knowledge" / "api"
    bundle.mkdir(parents=True)
    source = bundle / "README.md"
    source.write_text("first", encoding="utf-8")
    package = _package(package_root)
    project = tmp_path / "project"
    dest = project / ".cac" / "knowledge" / "api" / "README.md"
    dest.parent.mkdir(parents=True)
    dest.write_text("user-owned", encoding="utf-8")
    integrator = KnowledgeIntegrator()
    kwargs = dict(
        managed_files=set(), diagnostics=DiagnosticCollector(), source_plan=_plan(package)
    )

    collision = integrator.integrate_knowledge_for_target(CAC, package, project, **kwargs)
    assert collision.files_skipped == 1
    assert dest.read_text() == "user-owned"

    dest.write_text("first", encoding="utf-8")
    adopted = integrator.integrate_knowledge_for_target(CAC, package, project, **kwargs)
    assert adopted.files_adopted == 1
    assert adopted.target_paths == [dest]

    source.write_text("second", encoding="utf-8")
    managed = {".cac/knowledge/api/README.md"}
    updated = integrator.integrate_knowledge_for_target(
        CAC, package, project, managed_files=managed, source_plan=_plan(package)
    )
    assert updated.files_integrated == 1
    assert dest.read_text() == "second"


def test_knowledge_sync_removes_only_tracked_files(tmp_path):
    project = tmp_path / "project"
    owned = project / ".cac" / "knowledge" / "api" / "README.md"
    user_file = project / ".cac" / "knowledge" / "notes.md"
    owned.parent.mkdir(parents=True)
    owned.write_text("managed", encoding="utf-8")
    user_file.write_text("personal", encoding="utf-8")
    managed = {".cac/knowledge/api/README.md"}
    assert BaseIntegrator.partition_managed_files(managed)["knowledge_cac"] == managed

    stats = KnowledgeIntegrator().sync_for_target(CAC, None, project, managed_files=managed)
    assert stats == {"files_removed": 1, "errors": 0}
    assert not owned.exists()
    assert user_file.read_text() == "personal"


def test_knowledge_only_package_is_valid_and_not_reported_empty(tmp_path):
    package_root = tmp_path / "knowledge-only"
    bundle = package_root / ".apm" / "knowledge" / "api"
    bundle.mkdir(parents=True)
    (package_root / "apm.yml").write_text(
        "name: knowledge-only\nversion: 1.0.0\n", encoding="utf-8"
    )
    (bundle / "README.md").write_text("# API", encoding="utf-8")

    for result in (
        validate_apm_package(package_root),
        PackageValidator().validate_package_structure(package_root),
    ):
        assert result.is_valid, result.errors
        assert not any("No primitive files" in warning for warning in result.warnings)
