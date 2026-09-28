"""CAC-only, opt-in opaque resource kinds."""

from __future__ import annotations

from dataclasses import replace

from apm_cli.integration.dispatch import PrimitiveDispatch
from apm_cli.integration.opaque_file_integrator import OpaqueFileIntegrator
from apm_cli.integration.targets import PrimitiveMapping, TargetProfile


def custom_resource_integrator(kind: str) -> type[OpaqueFileIntegrator]:
    """Build an integrator with a fixed, validated source subdirectory."""
    return type(
        f"CustomResource_{kind.replace('-', '_')}",
        (OpaqueFileIntegrator,),
        {"primitive": kind, "min_relative_parts": 2},
    )


def custom_resource_target(target: TargetProfile, kind: str) -> TargetProfile:
    if target.name != "cac":
        return target
    return replace(
        target,
        primitives={
            **target.primitives,
            kind: PrimitiveMapping(kind, "", "cac_opaque"),
        },
    )


def custom_resource_dispatch(kind: str) -> PrimitiveDispatch:
    return PrimitiveDispatch(
        custom_resource_integrator(kind),
        "integrate_files_for_target",
        "sync_for_target",
        kind,
    )
