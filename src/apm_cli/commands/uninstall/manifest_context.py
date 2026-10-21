"""Bind uninstall selection to its scope-specific authoritative manifest."""

from functools import wraps

from apm_cli.core.scope import InstallScope, get_manifest_path
from apm_cli.models.dependency.selection_context import selection_manifest


def with_manifest_selection(command):
    @wraps(command)
    def wrapped(*args, **kwargs):
        scope = InstallScope.USER if kwargs.get("global_") else InstallScope.PROJECT
        token = selection_manifest.set(get_manifest_path(scope))
        try:
            return command(*args, **kwargs)
        finally:
            selection_manifest.reset(token)

    return wrapped
