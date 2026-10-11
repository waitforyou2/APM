"""Exercise the release prerequisite without installing runtimes or using tokens."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.component, pytest.mark.windows_compat]

ROOT = Path(__file__).resolve().parents[3]
PWSH = shutil.which("pwsh")


@pytest.mark.skipif(PWSH is None, reason="PowerShell is not installed")
@pytest.mark.parametrize(
    ("tokens", "inference", "expected"),
    [
        ({}, False, True),
        ({"GITHUB_API_TOKEN": "test-api-only"}, False, True),
        ({}, True, False),
        ({"GITHUB_API_TOKEN": "test-api-only"}, True, False),
        ({"GITHUB_APM_PAT": "test-package-pat"}, False, True),
        ({"GITHUB_TOKEN": "test-models-pat"}, True, True),
        (
            {"GITHUB_APM_PAT": "test-package-pat", "GITHUB_TOKEN": "test-models-pat"},
            True,
            True,
        ),
    ],
)
def test_release_prerequisites_only_require_auth_for_inference(
    tokens: dict[str, str], inference: bool, expected: bool
) -> None:
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        not in {
            "GITHUB_TOKEN",
            "GITHUB_APM_PAT",
            "GITHUB_API_TOKEN",
            "GITHUB_MODELS_KEY",
            "APM_RUN_INFERENCE_TESTS",
        }
    }
    env.update(tokens)
    env["APM_RUN_INFERENCE_TESTS"] = "1" if inference else "0"
    # Load function definitions through PowerShell's parser, never Main or any
    # other top-level action in the release script. All credentials are dummy.
    command = r"""
$ErrorActionPreference = 'Stop'
. ./scripts/windows/github-token-helper.ps1
$parseTokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PWD 'scripts/windows/test-release-validation.ps1'),
    [ref]$parseTokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Release script did not parse' }
$names = @('Write-TestHeader', 'Write-Info', 'Write-Success', 'Write-ErrorText', 'Test-Prerequisite')
foreach ($node in $ast.EndBlock.Statements) {
    if ($node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -in $names) {
        Invoke-Expression $node.Extent.Text
    }
}
$passed = Test-Prerequisite
@{
    passed = $passed
    modelsToken = $env:GITHUB_TOKEN
    packageToken = $env:GITHUB_APM_PAT
} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads(result.stdout.splitlines()[-1])
    assert state["passed"] is expected
    assert (state["modelsToken"] or None) == (
        tokens.get("GITHUB_TOKEN") or tokens.get("GITHUB_APM_PAT")
    )
    assert (state["packageToken"] or None) == (
        tokens.get("GITHUB_APM_PAT") or tokens.get("GITHUB_TOKEN")
    )
