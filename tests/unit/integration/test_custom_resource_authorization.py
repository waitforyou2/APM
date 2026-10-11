"""Custom primitive mappings never widen the authorized target set."""

from pathlib import Path

import pytest

from apm_cli.install.integrator_bundle import IntegratorBundle
from apm_cli.install.services import integrate_package_primitives
from apm_cli.integration.custom_resource import custom_resource_target
from apm_cli.integration.skill_integrator import SkillIntegrator
from apm_cli.integration.targets import KNOWN_TARGETS
from apm_cli.models.apm_package import APMPackage, PackageInfo, PackageType
from apm_cli.models.dependency.reference import DependencyReference
from apm_cli.models.dependency.resource import ResourceSpec
from apm_cli.utils.diagnostics import DiagnosticCollector

pytestmark = pytest.mark.component


def test_custom_mapping_preserves_target_identity_and_shared_profiles() -> None:
    cac = KNOWN_TARGETS["cac"]
    enriched = custom_resource_target(cac, "playbooks")
    assert enriched.name == cac.name
    assert enriched.root_dir == cac.root_dir
    assert enriched.resolved_deploy_root == cac.resolved_deploy_root
    assert enriched.primitives.keys() == cac.primitives.keys() | {"playbooks"}
    assert "playbooks" not in cac.primitives
    claude = KNOWN_TARGETS["claude"]
    assert custom_resource_target(claude, "playbooks") is claude


@pytest.mark.parametrize(
    ("active", "consumer", "declared", "deploys"),
    [
        (["cac"], None, None, True),
        (["cac", "claude"], ["cac"], ["cac"], True),
        (["claude"], None, None, False),
        ([], None, None, False),
        (["cac", "claude"], ["claude"], None, False),
        (["cac", "claude"], None, ["claude"], False),
        (["cac", "claude"], ["cac"], ["claude"], False),
    ],
)
def test_custom_resource_deployment_obeys_all_target_restrictions(
    tmp_path: Path,
    active: list[str],
    consumer: list[str] | None,
    declared: list[str] | None,
    deploys: bool,
) -> None:
    package_root = tmp_path / "package"
    source = package_root / ".apm/playbooks/sample/index.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Original playbook\n", encoding="utf-8")
    package = PackageInfo(
        package=APMPackage(
            name="sample", version="1.0.0", package_path=package_root, targets=declared
        ),
        install_path=package_root,
        package_type=PackageType.APM_PACKAGE,
        dependency_ref=DependencyReference(
            repo_url="example/resources", resource=ResourceSpec("playbooks", "sample")
        ),
    )
    project = tmp_path / "project"
    project.mkdir()
    result = integrate_package_primitives(
        package,
        project,
        targets=[KNOWN_TARGETS[name] for name in active],
        dep_target_subset=consumer,
        integrators=IntegratorBundle(
            prompt=None,
            agent=None,
            skill=SkillIntegrator(),
            instruction=None,
            command=None,
            hook=None,
        ),
        force=False,
        managed_files=set(),
        diagnostics=DiagnosticCollector(),
        package_name="sample",
    )
    destination = project / ".cac/playbooks/sample/index.md"
    assert destination.exists() is deploys
    assert result["playbooks"] == int(deploys)
    assert not (project / ".claude").exists()
    assert "playbooks" not in KNOWN_TARGETS["cac"].primitives
    if deploys:
        assert destination.read_bytes() == source.read_bytes()
        assert result["deployed_files"] == [".cac/playbooks/sample/index.md"]
    else:
        assert result["deployed_files"] == []
