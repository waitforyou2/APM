"""Typed set of primitive integrators used by package installation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apm_cli.integration.base_integrator import BaseIntegrator


@dataclass(frozen=True)
class IntegratorBundle:
    """Group primitive handlers passed to package integration."""

    prompt: BaseIntegrator
    agent: BaseIntegrator
    skill: BaseIntegrator
    instruction: BaseIntegrator
    command: BaseIntegrator
    hook: BaseIntegrator
    canvas: BaseIntegrator | None = None
    knowledge: BaseIntegrator | None = None
    workflow: BaseIntegrator | None = None
