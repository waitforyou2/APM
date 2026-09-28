"""Turn an explicitly typed Git directory into a normal APM package."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from apm_cli.models.dependency.resource import ResourceSpec


def project_resource_directory(root: Path, resource: ResourceSpec | None) -> None:
    """Project only an opted-in source directory; legacy packages are untouched."""
    if resource is None:
        return
    if (root / "apm.yml").exists() or (root / ".apm").exists():
        raise ValueError("Typed resource source must be a plain directory, not an APM package")

    entries = [entry for entry in root.iterdir() if entry.name != ".git"]
    if not entries:
        raise ValueError(f"Resource {resource.kind}/{resource.name} is empty")
    has_file = False
    for parent, dirs, files in os.walk(root, followlinks=False):
        if Path(parent) == root and ".git" in dirs:
            dirs.remove(".git")
        for name in dirs + files:
            path = Path(parent) / name
            if path.is_symlink():
                raise ValueError(f"Typed resource contains a symlink: {path.relative_to(root)}")
            if path.is_file():
                has_file = True
    if not has_file:
        raise ValueError(f"Resource {resource.kind}/{resource.name} has no files")

    if resource.kind == "skills" and not (root / "SKILL.md").is_file():
        raise ValueError("A typed skill directory must contain SKILL.md")
    if resource.kind == "agents":
        agent_files = [entry for entry in entries if entry.is_file() and entry.name.endswith(".md")]
        if len(entries) != 1 or len(agent_files) != 1:
            raise ValueError("A typed agent directory must contain exactly one Markdown file")

    destination = root / ".apm" / resource.kind
    if resource.kind != "agents":
        destination /= resource.name
    destination.mkdir(parents=True)
    for entry in entries:
        name = f"{resource.name}.agent.md" if resource.kind == "agents" else entry.name
        shutil.move(str(entry), str(destination / name))
    (root / "apm.yml").write_text(f"name: {resource.name}\nversion: 0.0.0\n", encoding="utf-8")
