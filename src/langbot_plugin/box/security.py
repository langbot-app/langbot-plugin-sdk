from __future__ import annotations

import os
import sys

from .errors import BoxValidationError
from .models import BoxSpec

_BLOCKED_HOST_PATHS_POSIX = frozenset(
    {
        '/etc',
        '/proc',
        '/sys',
        '/dev',
        '/root',
        '/boot',
        '/run',
        '/var/run',
        '/run/docker.sock',
        '/var/run/docker.sock',
        '/run/podman',
        '/var/run/podman',
    }
)

_BLOCKED_HOST_PATHS_WINDOWS = frozenset(
    {
        r'C:\Windows',
        r'C:\Program Files',
        r'C:\Program Files (x86)',
        r'C:\ProgramData',
        r'\\.\pipe\docker_engine',
    }
)

BLOCKED_HOST_PATHS = (
    _BLOCKED_HOST_PATHS_POSIX | _BLOCKED_HOST_PATHS_WINDOWS
    if sys.platform == 'win32'
    else _BLOCKED_HOST_PATHS_POSIX
)


def validate_sandbox_security(spec: BoxSpec) -> None:
    """Validate that a BoxSpec does not request dangerous container config.

    Raises BoxValidationError when the spec contains a blocked host_path.
    """
    if spec.host_path:
        real = os.path.realpath(spec.host_path)
        sep = os.sep
        _norm = os.path.normcase
        for blocked in BLOCKED_HOST_PATHS:
            if _norm(real) == _norm(blocked) or _norm(real).startswith(_norm(blocked) + sep):
                raise BoxValidationError(f'host_path {spec.host_path} is blocked for security')
