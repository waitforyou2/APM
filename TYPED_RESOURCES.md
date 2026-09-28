# Typed Git resource dependencies (custom APM extension)

This fork supports an optional `resource` object on a Git dependency. It lets
APM install a plain resource directory without requiring `apm.yml` or `.apm/`
inside that directory. Microsoft's upstream APM does not define this field.

```yaml
name: team-workspace
version: 1.0.0
targets: [cac]
dependencies:
  apm:
    - git: https://git.example.com/team/assets.git
      ref: v1.0.0
      path: knowledge/dme-sdk
      alias: dme-sdk
      targets: [cac]
      resource:
        kind: knowledge
        name: dme-sdk
```

`path` selects a directory in the Git repository; omit it to use the repository
root. Multiple resources can use the same repository when they select different
directories. The identity is still the repository plus `path`, so do not select
the *same* directory twice under different resource names or kinds.

The source directory's files are deployed as follows:

| `kind` | Source requirement | CAC destination |
| --- | --- | --- |
| `skills` | Root-level `SKILL.md` | `.cac/skills/<name>/` |
| `agents` | Exactly one Markdown file | `.cac/agents/<name>.md` |
| `knowledge` | Any non-empty file tree | `.cac/knowledge/<name>/` |
| `workflows` | Any non-empty file tree | `.cac/workflows/<name>/` |
| Safe custom kind, e.g. `playbooks` | Any non-empty file tree | `.cac/playbooks/<name>/` |

APM copies Knowledge, Workflow and custom resource files unchanged. It does not
execute them or instruct CAC to load them automatically. Symlinks and existing
APM package structure in a typed source are rejected. Custom kinds deploy only
to CAC. Names and kinds are lowercase kebab-case; executable or built-in APM
primitive names are reserved.

The `resource` field is optional in a hand-written APM manifest. Dependencies
without it retain their original parsing, validation and deployment behavior.
The Workspace compiler emits it for every selected resource, deriving `kind`
from the `resources.<kind>` category in `workspace.yaml`; individual resource
declarations do not need a `kind` or `layout` field.
