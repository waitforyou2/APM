"""Adapt a single Skill ZIP to the existing APM installation transaction."""

from __future__ import annotations

import hashlib
import io
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PureWindowsPath

from ...models.apm_package import PackageInfo, validate_apm_package
from ...models.dependency.resource import ResourceSpec
from ...models.dependency.types import GitReferenceType, ResolvedReference
from ...utils.yaml_io import dump_yaml
from ..resource_projection import project_resource_directory
from .extractor import extract_zip
from .skill_link_client import SkillLinkClient, SkillLinkError
from .skill_link_config import link_url, normalize_base_url, validate_version


def _validate_members(data: bytes) -> None:
    # The common extractor rejects links, escapes and bombs. Also reject portable
    # path collisions: ZIPs must not unpack differently on Windows and Linux.
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            seen = set()
            spellings = {}
            for member in archive.infolist():
                parts = member.filename.rstrip("/").split("/")
                if any(
                    "\\" in part
                    or ":" in part
                    or part.endswith((" ", "."))
                    or PureWindowsPath(part).is_reserved()
                    for part in parts
                ):
                    raise SkillLinkError("Skill ZIP contains a non-portable path")
                for index in range(1, len(parts) + 1):
                    spelling = "/".join(parts[:index])
                    old = spellings.setdefault(spelling.casefold(), spelling)
                    if old != spelling:
                        raise SkillLinkError("Skill ZIP contains case-colliding paths")
                key = member.filename.rstrip("/").casefold()
                if key in seen:
                    raise SkillLinkError("Skill ZIP contains duplicate or case-colliding paths")
                seen.add(key)
    except zipfile.BadZipFile:
        raise SkillLinkError("Skill Link download is not a valid ZIP") from None


def _skill_root(root: Path) -> Path:
    if (root / "SKILL.md").is_file():
        return root
    entries = list(root.iterdir())
    if len(entries) == 1 and entries[0].is_dir() and (entries[0] / "SKILL.md").is_file():
        return entries[0]
    raise SkillLinkError(
        "Skill ZIP must contain SKILL.md at root or inside one top-level directory"
    )


def download_skill_link(
    dep,
    target: Path,
    configured_url: str,
    *,
    resolved_url=None,
    resolved_hash=None,
    version=None,
):
    """Return PackageInfo + lock metadata; temporary signed links stay in memory."""
    from .resolver import RegistryResolution

    base = normalize_base_url(dep.skill_link_url)
    if base != normalize_base_url(configured_url):
        raise SkillLinkError(
            "Skill Link source differs from the configured registry; regenerate the lock explicitly"
        )
    version = version or dep.reference
    validate_version(version)
    if dep.reference != version:
        raise SkillLinkError(
            "Skill Link locked version does not match the manifest's exact version"
        )
    resource = ResourceSpec.parse({"kind": "skills", "name": dep.alias or dep.repo_url})
    ResourceSpec.parse({"kind": "skills", "name": dep.repo_url})
    if dep.virtual_path or dep.skill_subset:
        raise SkillLinkError("Skill Link packages do not support path or skills subsets")
    locator = link_url(base, dep.repo_url, version)
    if resolved_url is not None and (resolved_url != locator or not resolved_hash):
        raise SkillLinkError(
            "Skill Link lockfile locator/hash does not match the configured dependency"
        )
    data = SkillLinkClient(dep.registry_name, base).download(dep.repo_url, version)
    digest = hashlib.sha256(data).hexdigest()
    _validate_members(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".skill-link-", dir=target.parent) as temporary:
        extracted = Path(temporary) / "content"
        extract_zip(data, resolved_hash or digest, extracted)
        root = _skill_root(extracted)
        project_resource_directory(root, resource)
        dump_yaml({"name": resource.name, "version": version}, root / "apm.yml")
        validation = validate_apm_package(root)
        if not validation.is_valid or validation.package is None:
            raise SkillLinkError("Skill ZIP could not be converted to a valid APM package")
        # Only replace the staging target after all validation has succeeded.
        if target.is_symlink():
            raise SkillLinkError("Refusing a symlinked Skill Link installation target")
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(root), str(target))
    package = validation.package
    package.package_path = target
    package.source_path = target
    package.source = locator
    info = PackageInfo(
        package=package,
        install_path=target,
        dependency_ref=dep,
        installed_at=datetime.now().isoformat(),
        package_type=validation.package_type,
        resolved_reference=ResolvedReference(
            original_ref=dep.reference,
            ref_type=GitReferenceType.TAG,
            ref_name=version,
            resolved_commit=None,
        ),
    )
    return info, RegistryResolution(locator, f"sha256:{digest}", version)
