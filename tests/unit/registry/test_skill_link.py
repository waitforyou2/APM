"""Skill Link contract tests; HTTP transport is mocked, provider code is real."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from apm_cli.deps.lockfile import LockedDependency
from apm_cli.deps.registry.auth import dependency_ref_with_registry_name_from_lockfile
from apm_cli.deps.registry.extractor import HashMismatchError, UnsafeTarballError
from apm_cli.deps.registry.resolver import RegistryPackageResolver, RegistryResolutionError
from apm_cli.deps.registry.skill_link_client import SkillLinkClient, SkillLinkError
from apm_cli.deps.registry.skill_link_config import link_url
from apm_cli.models.apm_package import APMPackage
from apm_cli.models.dependency.reference import DependencyReference

BASE = "https://skills.example.test"
SIGNED = "https://objects.example.test/package.zip?Signature=private-signature"
W3_URL = "https://sso.example.test/api/ssoproxysvr/v2/w3tokens"


def skill_zip(files=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, body in (
            files
            or {
                "vendor-name/SKILL.md": "---\nname: frontend-design\ndescription: UI design\n---\n# Design\n",
                "vendor-name/references/test.md": "unchanged reference\n",
            }
        ).items():
            archive.writestr(name, body)
    return buf.getvalue()


def manifest(entry=None, url=BASE):
    return {
        "name": "workspace",
        "version": "0.1.0",
        "targets": ["cac"],
        "registries": {
            "corp-skills": {"url": url, "provider": "skill-link-v1"},
            "default": "corp-skills",
        },
        "dependencies": {"apm": [entry or {"id": "frontend-design", "version": "0.0.1"}]},
    }


def dependency(tmp_path, **kwargs):
    return APMPackage.from_mapping(
        manifest(**kwargs), package_path=tmp_path
    ).get_apm_dependencies()[0]


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    from apm_cli import config

    # Never read an administrator's real private build profile during tests.
    monkeypatch.setattr("apm_cli.deps.registry.skill_link_auth._load_private_profiles", lambda: {})

    monkeypatch.setattr(
        config,
        "_config_cache",
        {
            "experimental": {"registries": True},
            "registries": {"corp-skills": {"url": BASE}},
        },
    )
    for key in ("HW_ID", "HW_APPKEY", "AUTH_TOKEN"):
        monkeypatch.setenv(f"APM_REGISTRY_{key}_CORP_SKILLS", f"private-{key}")


@pytest.fixture
def transport(monkeypatch):
    state = {"requests": [], "zip": skill_zip(), "links": 0, "downloads": 0, "tokens": 0}

    def send(session, request, **kwargs):
        state["requests"].append(request)
        response = requests.Response()
        response.url = request.url
        response.status_code = 200
        response.request = request
        if request.url == W3_URL:
            state["tokens"] += 1
            assert request.method == "POST"
            profile = state["profile"]
            assert json.loads(request.body) == {
                "account": profile["account"],
                "password": profile["password"],
            }
            assert request.headers["X-HW-ID"] == profile["hw_id"]
            assert request.headers["X-HW-APPKEY"] == profile["hw_appkey"]
            assert request.headers["Content-Type"] == "application/json"
            assert not {"X-AUTH-TOKEN", "Authorization", "Cookie"} & set(request.headers)
            response._content = json.dumps(
                state.get(
                    "token_json",
                    {
                        "status": "ok",
                        "result": {
                            "newToken": f"fresh-test-token-{state['tokens']}",
                            "token": "old-token",
                        },
                    },
                )
            ).encode()
            response.status_code = state.get("token_http_status", 200)
            if response.status_code == 302:
                response.headers["Location"] = SIGNED
            if state.get("token_non_json"):
                response._content = b"invalid JSON containing private data"
        elif request.url.startswith(BASE):
            state["links"] += 1
            assert request.method == "GET"
            assert not request.body
            query = parse_qs(urlsplit(request.url).query)
            assert query == {"skillId": ["frontend-design"], "version": ["0.0.1"]}
            assert request.headers["Content-Type"] == "application/json"
            if "profile" in state:
                assert request.headers["X-HW-ID"] == state["profile"]["hw_id"]
                assert request.headers["X-HW-APPKEY"] == state["profile"]["hw_appkey"]
                assert request.headers["X-AUTH-TOKEN"] == f"fresh-test-token-{state['tokens']}"
            else:
                for header, key in [
                    ("X-HW-ID", "HW_ID"),
                    ("X-HW-APPKEY", "HW_APPKEY"),
                    ("X-AUTH-TOKEN", "AUTH_TOKEN"),
                ]:
                    assert request.headers[header] == f"private-{key}"
            response._content = json.dumps(
                state.get(
                    "json",
                    {
                        "code": 200,
                        "data": {"downloadUrl": SIGNED + f"&n={state['links']}"},
                    },
                )
            ).encode()
            response.status_code = state.get("api_status", 200)
            if response.status_code == 302:
                response.headers["Location"] = SIGNED
        else:
            assert request.url.startswith(SIGNED), "Unexpected mock HTTP destination"
            state["downloads"] += 1
            assert not {"X-HW-ID", "X-HW-APPKEY", "X-AUTH-TOKEN", "Authorization", "Cookie"} & set(
                request.headers
            )
            response._content = state["zip"]
            if state.get("expire_once") and state["downloads"] == 1:
                response.status_code = 403
            if state.get("redirect"):
                response.status_code = 302
                response.headers["Location"] = state["redirect"]
        response._content_consumed = True
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    return state


def test_manifest_mixes_git_and_skill_and_roundtrips(tmp_path):
    data = manifest()
    data["dependencies"]["apm"].append({"git": "https://github.com/acme/assets.git", "ref": "main"})
    pkg = APMPackage.from_mapping(data, package_path=tmp_path)
    skill, git = pkg.get_apm_dependencies()
    assert skill.skill_link_url == BASE and skill.alias == "frontend-design"
    assert git.source == "git" and git.skill_link_url is None
    assert skill.to_apm_yml_entry() == {
        "id": "frontend-design",
        "version": "0.0.1",
        "alias": "frontend-design",
        "registry": "corp-skills",
    }
    other = dependency(tmp_path, url="https://other.example.test")
    assert other.get_unique_key() != skill.get_unique_key()
    with pytest.raises(ValueError, match="owner/repo"):
        DependencyReference.parse_from_dict({"id": "frontend-design", "version": "0.0.1"})


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "frontend-design", "version": "latest"},
        {"id": "frontend-design", "version": "^0.0.1"},
        {"id": "../escape", "version": "0.0.1"},
        {"id": "CON", "version": "0.0.1"},
        {"id": "frontend-design", "version": "0.0.1", "git": "acme/repo"},
        {"id": "frontend-design", "version": "0.0.1", "path": "nested"},
        {"id": "frontend-design", "version": "0.0.1", "alias": "../escape"},
    ],
)
def test_invalid_dependency_rejected(tmp_path, entry):
    with pytest.raises(ValueError):
        dependency(tmp_path, entry=entry)


@pytest.mark.parametrize(
    "url",
    ["http://service.test", "https://user:secret@service.test", "https://service.test?key=secret"],
)
def test_invalid_base_rejected(tmp_path, url):
    with pytest.raises(ValueError):
        dependency(tmp_path, url=url)


def test_download_lock_roundtrip_renewal_and_hash(tmp_path, transport):
    dep = dependency(tmp_path)
    resolver = RegistryPackageResolver({"corp-skills": BASE})
    target = tmp_path / "package"
    info = resolver.download_package(dep, target)
    assert (
        target / ".apm/skills/frontend-design/references/test.md"
    ).read_text() == "unchanged reference\n"
    assert info.package.version == "0.0.1"
    resolution = resolver.last_resolutions[dep.get_unique_key()]
    assert resolution.resolved_hash == "sha256:" + hashlib.sha256(transport["zip"]).hexdigest()
    locked = LockedDependency.from_dependency_ref(
        dep,
        resolved_commit=None,
        depth=0,
        resolved_by=None,
        registry_resolution=resolution,
    )
    saved = locked.to_dict()
    assert "Signature" not in json.dumps(saved) and "private-" not in json.dumps(saved)
    restored = LockedDependency.from_dict(saved)
    assert restored.get_unique_key() == dep.get_unique_key()
    replay_dep = dependency_ref_with_registry_name_from_lockfile(
        restored.to_dependency_ref(),
        {"corp-skills": BASE},
        locked_dep=restored,
    )
    shutil.rmtree(target)
    resolver.download_from_lockfile(
        replay_dep,
        target,
        resolved_url=resolution.resolved_url,
        resolved_hash=resolution.resolved_hash,
        version=resolution.version,
    )
    assert transport["links"] == 2
    transport["zip"] = skill_zip({"SKILL.md": "tampered"})
    original = (target / ".apm/skills/frontend-design/SKILL.md").read_bytes()
    with pytest.raises(HashMismatchError, match="sha256 mismatch"):
        resolver.download_from_lockfile(
            replay_dep,
            target,
            resolved_url=resolution.resolved_url,
            resolved_hash=resolution.resolved_hash,
            version=resolution.version,
        )
    assert (target / ".apm/skills/frontend-design/SKILL.md").read_bytes() == original


def test_expired_link_renewed_once(transport):
    transport["expire_once"] = True
    assert (
        SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
        == transport["zip"]
    )
    assert transport["links"] == transport["downloads"] == 2


@pytest.mark.parametrize(
    "payload", [{"code": 403, "message": SIGNED}, {"code": 200, "data": {}}, [], {"code": "200"}]
)
def test_api_invalid_payload_redacted(transport, payload):
    transport["json"] = payload
    with pytest.raises(SkillLinkError) as exc:
        SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
    assert "Signature" not in str(exc.value)
    assert transport["downloads"] == 0


def test_api_redirect_never_leaks_credentials(transport):
    transport["api_status"] = 302
    with pytest.raises(SkillLinkError, match="redirects"):
        SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
    assert len(transport["requests"]) == 1


def test_download_cannot_redirect_to_http(transport):
    transport["redirect"] = "http://objects.example.test/file"
    with pytest.raises(SkillLinkError, match="HTTPS"):
        SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
    assert transport["downloads"] == 1


def test_credentials_require_local_url_binding(monkeypatch, transport):
    from apm_cli import config

    monkeypatch.setattr(
        config, "_config_cache", {"registries": {"corp-skills": {"url": "https://trusted.test"}}}
    )
    with pytest.raises(SkillLinkError, match="Bind credentials"):
        SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
    assert not transport["requests"]


def test_transport_errors_do_not_include_signed_url(monkeypatch, transport):
    def fail(*args, **kwargs):
        raise requests.ConnectionError(SIGNED)

    monkeypatch.setattr(requests.Session, "send", fail)
    with pytest.raises(SkillLinkError) as exc:
        SkillLinkClient("corp-skills", BASE).download("frontend-design", "0.0.1")
    assert "Signature" not in str(exc.value) and exc.value.__suppress_context__


@pytest.mark.parametrize(
    "files",
    [
        {"../escape": "bad", "SKILL.md": "ok"},
        {"skill/SKILL.md": "ok", "other/SKILL.md": "ambiguous"},
        {"deep/skill/SKILL.md": "too deep"},
        {"SKILL.md": "ok", "skill.md": "collision"},
        {"SKILL.md": "ok", "refs/x:stream": "ads"},
        {"SKILL.md": "ok", "Refs/a.md": "one", "refs/b.md": "two"},
        {"SKILL.md": "ok", "refs/CON.txt": "device"},
    ],
)
def test_bad_archive_does_not_replace_target(tmp_path, transport, files):
    transport["zip"] = skill_zip(files)
    target = tmp_path / "package"
    target.mkdir()
    (target / "existing").write_text("keep")
    with pytest.raises((RegistryResolutionError, UnsafeTarballError)):
        RegistryPackageResolver({"corp-skills": BASE}).download_package(
            dependency(tmp_path), target
        )
    assert (target / "existing").read_text() == "keep"


def test_lock_source_and_version_mismatch_rejected_before_network(tmp_path, transport):
    dep = dependency(tmp_path)
    resolver = RegistryPackageResolver({"corp-skills": BASE})
    with pytest.raises(RegistryResolutionError, match="locked version"):
        resolver.download_from_lockfile(
            dep,
            tmp_path / "pkg",
            resolved_url=link_url(BASE, dep.repo_url, "0.0.2"),
            resolved_hash="sha256:abc",
            version="0.0.2",
        )
    with pytest.raises(RegistryResolutionError, match="locator"):
        resolver.download_from_lockfile(
            dep, tmp_path / "pkg", resolved_url=SIGNED, resolved_hash="sha256:abc", version="0.0.1"
        )
    assert not transport["requests"]


def test_cli_mixed_install_frozen_reinstall_and_noop(tmp_path, monkeypatch, transport):
    """Real Git checkout + mocked HTTPS transport through the entire CAC pipeline."""
    import os

    from click.testing import CliRunner

    from apm_cli.cli import cli
    from apm_cli.utils.yaml_io import dump_yaml, load_yaml
    from tests.utils.local_git_repository import LocalGitRepositoryFactory

    monkeypatch.setenv("APM_CACHE_DIR", str(tmp_path / "cache"))
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "APM Test")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "test@example.test")
    source = tmp_path / "source"
    agent = source / "agents/security-auditor"
    agent.mkdir(parents=True)
    (agent / "security.agent.md").write_text("---\ndescription: Security audit\n---\n# Security\n")
    factory = LocalGitRepositoryFactory(tmp_path / "repos", env=dict(os.environ))
    repo = factory.create("assets", source_tree=source)
    factory.commit(repo, message="fixture")
    remote = "https://codehub.example.test/team/assets.git"
    for key, value in factory.url_rewrite_subprocess_env(repo, remote).items():
        if key.startswith("GIT_"):
            monkeypatch.setenv(key, value)
    project = tmp_path / "workspace"
    project.mkdir()
    data = manifest()
    data["dependencies"]["apm"].append(
        {
            "git": remote,
            "ref": "main",
            "path": "agents/security-auditor",
            "alias": "security-auditor",
            "targets": ["cac"],
            "resource": {"kind": "agents", "name": "security-auditor"},
        }
    )
    dump_yaml(data, project / "apm.yml")
    monkeypatch.chdir(project)
    monkeypatch.setattr("apm_cli.commands._helpers.check_for_updates", lambda *a, **kw: None)
    runner = CliRunner()

    def install(*options):
        result = runner.invoke(
            cli, ["install", "--no-policy", "--parallel-downloads", "0", *options]
        )
        assert result.exit_code == 0, result.output + repr(result.exception)

    install()
    assert (project / ".cac/skills/frontend-design/SKILL.md").is_file()
    assert (project / ".cac/agents/security-auditor.md").is_file()
    lock_before = load_yaml(project / "apm.lock.yaml")
    assert len(lock_before["dependencies"]) == 2
    assert "Signature" not in (project / "apm.lock.yaml").read_text()
    calls = transport["links"]
    install()
    assert transport["links"] == calls
    shutil.rmtree(project / "apm_modules")
    shutil.rmtree(project / ".cac")
    install("--frozen")
    assert (project / ".cac/skills/frontend-design/SKILL.md").is_file()
    assert (project / ".cac/agents/security-auditor.md").is_file()
    assert transport["links"] > calls
    lock_after = load_yaml(project / "apm.lock.yaml")
    assert lock_before["dependencies"] == lock_after["dependencies"]

    # Alias changes must rebuild the internal skill path and remove old deployment.
    from apm_cli.models.apm_package import clear_apm_yml_cache

    data["dependencies"]["apm"][0]["alias"] = "ui-design"
    dump_yaml(data, project / "apm.yml")
    clear_apm_yml_cache()
    install()
    assert (project / ".cac/skills/ui-design/SKILL.md").is_file()
    assert not (project / ".cac/skills/frontend-design/SKILL.md").exists()

    # Frozen rejects manifest version changes before obtaining a link.
    calls = transport["links"]
    data["dependencies"]["apm"][0]["version"] = "0.0.2"
    dump_yaml(data, project / "apm.yml")
    clear_apm_yml_cache()
    result = runner.invoke(cli, ["install", "--no-policy", "--frozen"])
    assert result.exit_code != 0 and transport["links"] == calls
    data["dependencies"]["apm"][0]["version"] = "0.0.1"
    dump_yaml(data, project / "apm.yml")
    clear_apm_yml_cache()

    # Same-version mutation cannot be blessed by --refresh; preserve committed files.
    lock_bytes = (project / "apm.lock.yaml").read_bytes()
    skill_bytes = (project / ".cac/skills/ui-design/SKILL.md").read_bytes()
    transport["zip"] = skill_zip({"SKILL.md": "changed immutable version"})
    result = runner.invoke(
        cli, ["install", "--no-policy", "--refresh", "--parallel-downloads", "0"]
    )
    assert result.exit_code != 0 and "sha256 mismatch" in result.output
    assert (project / "apm.lock.yaml").read_bytes() == lock_bytes
    assert (project / ".cac/skills/ui-design/SKILL.md").read_bytes() == skill_bytes
