"""Distribute workflow instructions without parsing or executing them."""

from pathlib import Path

from apm_cli.integration.opaque_file_integrator import OpaqueFileIntegrator


class WorkflowIntegrator(OpaqueFileIntegrator):
    """Copy .apm/workflows files and nested bundles byte-for-byte."""

    primitive = "workflows"

    @classmethod
    def find_workflow_files(cls, package_path: Path, source_plan=None) -> list[Path]:
        return cls.find_files(package_path, source_plan)

    integrate_workflows_for_target = OpaqueFileIntegrator.integrate_files_for_target
