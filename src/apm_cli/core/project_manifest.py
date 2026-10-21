"""Select the authoritative project manifest without merging or silent fallback."""

from pathlib import Path


def project_manifest_path(root: Path | str = ".") -> Path:
    """Prefer workspace.yml; fall back to apm.yml only when it is absent.

    Keep an existing directory or dangling symlink selected too, so the reader
    reports the error instead of installing from an unrelated fallback file.
    Package-internal/generated manifests and user-scope manifests retain apm.yml.
    """
    root = Path(root)
    workspace = root / "workspace.yml"
    if workspace.exists() or workspace.is_symlink():
        return workspace
    return root / "apm.yml"
