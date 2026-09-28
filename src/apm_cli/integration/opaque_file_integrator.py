"""Deploy opaque resource files to targets that explicitly support them."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from apm_cli.integration.base_integrator import (
    BaseIntegrator,
    IntegrationResult,
    _read_bytes_no_follow,
)
from apm_cli.integration.targets import TargetProfile
from apm_cli.utils.path_security import (
    PathTraversalError,
    ensure_path_within,
    has_symlink_component,
)
from apm_cli.utils.paths import portable_relpath


class OpaqueFileIntegrator(BaseIntegrator):
    """Preserve resource bytes and paths with shared ownership and sync rules."""

    primitive: str
    min_relative_parts = 1

    @classmethod
    def find_files(cls, package_path: Path, source_plan=None) -> list[Path]:
        source_root = Path(package_path)
        resource_root = source_root / ".apm" / cls.primitive
        if not resource_root.is_dir() or has_symlink_component(source_root, resource_root):
            return []

        if source_plan is not None:
            prefix = f".apm/{cls.primitive}/"
            files = [
                source_root / rel
                for rel in source_plan.paths
                if rel.startswith(prefix) and len(Path(rel).parts) >= 2 + cls.min_relative_parts
            ]
            return sorted(files)

        files = []
        for path in resource_root.rglob("*"):
            if not path.is_file() or has_symlink_component(source_root, path):
                continue
            if len(path.relative_to(resource_root).parts) < cls.min_relative_parts:
                continue
            try:
                ensure_path_within(path, resource_root)
            except PathTraversalError:
                continue
            files.append(path)
        return sorted(files)

    @staticmethod
    def _write_bytes_atomic(target: Path, content: bytes) -> None:
        """Replace a regular destination atomically, preserving binary data."""
        fd, temporary = tempfile.mkstemp(prefix="apm-resource-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def integrate_files_for_target(
        self,
        target: TargetProfile,
        package_info,
        project_root: Path,
        *,
        force: bool = False,
        managed_files: set[str] | None = None,
        diagnostics=None,
        scope=None,
        source_plan=None,
    ) -> IntegrationResult:
        mapping = target.primitives.get(self.primitive)
        if mapping is None:
            return IntegrationResult(0, 0, 0, [])
        if not target.auto_create and not (project_root / target.root_dir).is_dir():
            return IntegrationResult(0, 0, 0, [])

        package_root = Path(package_info.install_path)
        source_root = package_root / ".apm" / self.primitive
        files = self.find_files(package_root, source_plan)
        if not files:
            return IntegrationResult(0, 0, 0, [])

        effective_root = mapping.deploy_root or target.root_dir
        deploy_dir = project_root / effective_root / mapping.subdir
        target_paths: list[Path] = []
        integrated = skipped = adopted = 0
        for source_file in files:
            relative = source_file.relative_to(source_root)
            destination = deploy_dir / relative
            rel_path = portable_relpath(destination, project_root)
            try:
                # Check the complete path, including the final component, so
                # neither an existing link nor a linked parent is followed.
                self.resolve_deploy_path(rel_path, project_root, targets=[target])
                ensure_path_within(destination, deploy_dir)
            except PathTraversalError:
                if diagnostics is not None:
                    diagnostics.warn(f"Rejected unsafe {self.primitive} target path: {rel_path}")
                skipped += 1
                continue

            skip, was_adopted = self._check_adopt_or_skip(
                destination,
                source_file,
                rel_path,
                managed_files,
                force,
                diagnostics,
                target_paths,
            )
            if skip:
                adopted += int(was_adopted)
                skipped += int(not was_adopted)
                continue

            # Source admission and the security scan already happened in the
            # deployment plan. Recheck containment before the actual read.
            if has_symlink_component(package_root, source_file):
                skipped += 1
                continue
            ensure_path_within(source_file, source_root)
            content = _read_bytes_no_follow(source_file)
            destination.parent.mkdir(parents=True, exist_ok=True)
            self._write_bytes_atomic(destination, content)
            target_paths.append(destination)
            integrated += 1

        return IntegrationResult(
            files_integrated=integrated,
            files_updated=0,
            files_skipped=skipped,
            target_paths=target_paths,
            files_adopted=adopted,
        )

    def sync_for_target(
        self,
        target: TargetProfile,
        apm_package,
        project_root: Path,
        managed_files: set[str] | None = None,
    ) -> dict[str, int]:
        """Remove only lockfile-tracked resource files for this target."""
        mapping = target.primitives.get(self.primitive)
        if mapping is None:
            return {"files_removed": 0, "errors": 0}
        effective_root = mapping.deploy_root or target.root_dir
        prefix = f"{effective_root}/{mapping.subdir}/"
        return self.sync_remove_files(
            project_root,
            managed_files,
            prefix,
            targets=[target],
        )
