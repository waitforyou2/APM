"""Project-owned CAC knowledge is installed without any dependency."""

from pathlib import Path

from click.testing import CliRunner

from apm_cli.cli import cli


def test_install_project_owned_knowledge_only(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    bundle = project / ".apm" / "knowledge" / "team"
    bundle.mkdir(parents=True)
    (project / "apm.yml").write_text(
        "name: cac-project\nversion: 1.0.0\ntargets: [cac]\n", encoding="utf-8"
    )
    (bundle / "README.md").write_text("# Team\n", encoding="utf-8")
    monkeypatch.chdir(project)

    result = CliRunner().invoke(cli, ["install", "--no-policy"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert (project / ".cac" / "knowledge" / "team" / "README.md").read_text() == "# Team\n"
