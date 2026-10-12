# Mutation baseline review

Run the bounded pilot on Linux with the pinned development dependencies:

```sh
uv run --frozen --extra dev python scripts/run_mutation_pilot.py --max-children 2
```

Do not accept new survivors solely to make CI pass. Inspect each mutant with
`uv run mutmut show <name>` and add behavioral assertions to the owner's selected
test seam first. Mutant numbers are positional, so source changes can make an old
allowlist refer to entirely different mutations.

## Update-plan review (2026-10-12)

The typed-resource comparison and selective-update retention changed the
`build_update_plan` mutation inventory. The previous baseline no longer identified
the same operations. The selected seam, `tests/unit/install/test_plan.py`, now
also checks:

- Resource type/name changes and typed/untyped transitions at an unchanged Git
  revision; identical resource declarations remain unchanged.
- All retained lock-entry fields, including old/new revision, content hash,
  deployed files, and the virtual resource's display name on a private Git host.
- Display-name ordering within each action, independently of host-qualified keys.

The reviewed update-plan allowlist contains only these equivalent mutations
(prefix: `apm_cli.install.plan.build_update_plan__mutmut_`):

| IDs | Mutation | Why it is equivalent for the supported model inputs |
| --- | --- | --- |
| 26, 45, 83, 91 | Omit the `None` default from `getattr` | `source` and `resource` are declared `DependencyReference` fields; `resolved_tag` and `resource` are declared `LockedDependency` fields. The attribute exists even when its value is `None`. |
| 113, 137, 165, 186 | Pass `None` as the first argument of `_display_name(key, old)` | Each call is in a branch with a non-null locked entry. `_display_name` derives the name from that entry, without reading the fallback key. |
| 194, 196, 197 | Change/remove the fallback action-order value | This function constructs only the four actions present in `_ACTION_ORDER`; the fallback cannot be reached. |

There are 200 update-plan mutants: the strengthened seam kills 189 and leaves
these 11 equivalents. No production branch, mutation owner, or test gate has been
disabled. Other owners' baselines are unchanged.
