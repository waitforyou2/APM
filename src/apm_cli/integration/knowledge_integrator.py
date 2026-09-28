"""Deploy opaque knowledge bundles to targets that explicitly support them."""

from pathlib import Path

from apm_cli.integration.opaque_file_integrator import OpaqueFileIntegrator


class KnowledgeIntegrator(OpaqueFileIntegrator):
    """Copy .apm/knowledge/<name> trees without altering their contents."""

    primitive = "knowledge"
    min_relative_parts = 2

    @classmethod
    def find_knowledge_files(cls, package_path: Path, source_plan=None) -> list[Path]:
        return cls.find_files(package_path, source_plan)

    integrate_knowledge_for_target = OpaqueFileIntegrator.integrate_files_for_target
