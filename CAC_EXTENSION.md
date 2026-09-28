# CAC target, knowledge, and workflow files

This fork adds an explicit, project-scoped `cac` target to APM. It deploys
Claude-compatible skills and agents plus opaque `knowledge` and `workflows`
primitives.
Package acquisition is unchanged: a regular Git-backed APM dependency is
enough; no registry or website downloader is required.

## Author the central package

```text
apm.yml
.apm/
  skills/review/SKILL.md
  agents/reviewer.agent.md
  knowledge/api/README.md
  knowledge/api/images/flow.png
  workflows/design-review/WORKFLOW.md
  workflows/design-review/templates/review.md
```

Each knowledge bundle must have its own directory under
`.apm/knowledge/<name>/`. Nested regular files are copied byte-for-byte;
loose files directly under `.apm/knowledge/` are not deployed. Symlinked
source files and directories are excluded by the deployment source plan.

Workflow files can be placed directly under `.apm/workflows/`, such as
`.apm/workflows/design-review.md`, or inside a named directory with supporting
files. APM copies their bytes and relative paths without parsing or executing
them. Use a documented entry file such as `WORKFLOW.md` and make the invoking
Skill, Agent, or user request point to it explicitly. Directory presence alone
does not cause an AI agent to read it or guarantee that it follows every step.

## Consume it in a project

```yaml
name: my-project
version: 1.0.0
targets: [cac]
dependencies:
  apm:
    - git: ssh://git@git.example.internal/team/agent-assets.git
      ref: v1.0.0
```

Run `apm install` with this fork. It creates `.cac/` as needed and deploys:

```text
.cac/
  skills/review/SKILL.md
  agents/reviewer.md
  knowledge/api/README.md
  knowledge/api/images/flow.png
  workflows/design-review/WORKFLOW.md
  workflows/design-review/templates/review.md
```

`apm install --target cac` is also supported. The target is explicit-only:
it is not selected by `--target all` or auto-detected from `.cac/`.
User-global (`-g`) deployment is not supported in this first version.
Because stock APM does not know `cac`, `knowledge`, or this workflow mapping, consumers of a project
with `targets: [cac]` must use this fork.

Knowledge and workflow files participate in the normal source security scan, deployment
inventory, lockfile, refresh, and uninstall workflow. A pre-existing
different file is not overwritten unless it is already APM-managed or
`--force` is given; identical files can be adopted. Uninstall removes only
lockfile-tracked files, leaving unrelated user files in place. The `cac`
target is file distribution only; it does not provide a workflow engine,
approval enforcement, or automatic workflow discovery.

## Verification

```text
python -m pytest tests/unit/integration/test_cac_knowledge.py tests/unit/integration/test_cac_workflows.py tests/integration/test_cac_knowledge_git_e2e.py -q
```

The Git end-to-end test uses a local bare repository with a process-scoped
Git URL rewrite, so it exercises the real Git acquisition and CLI install
path without contacting a remote service. It covers installation, refresh,
stale-file pruning, reinstall, and uninstall.
