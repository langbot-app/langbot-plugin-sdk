from __future__ import annotations

import os
import re
import sys

from .errors import BoxValidationError
from .models import BoxSpec


BOX_CONTROL_TOKEN_ENV = "LANGBOT_BOX_CONTROL_TOKEN"
BOX_TRUSTED_INSTANCE_ENV = "LANGBOT_BOX_TRUSTED_INSTANCE_UUID"
BOX_CONTROL_TOKEN_HEADER = "X-LangBot-Box-Control-Token"
BOX_INSTANCE_HEADER = "X-LangBot-Instance-Id"
BOX_WORKSPACE_HEADER = "X-LangBot-Workspace-Id"
BOX_PLACEMENT_GENERATION_HEADER = "X-LangBot-Placement-Generation"
CONTROL_TOKEN_MIN_LENGTH = 32

_INSTANCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

_BLOCKED_HOST_PATHS_POSIX = frozenset(
    {
        "/etc",
        "/proc",
        "/sys",
        "/dev",
        "/root",
        "/boot",
        "/run",
        "/var/run",
        "/run/docker.sock",
        "/var/run/docker.sock",
    }
)

_BLOCKED_HOST_PATHS_WINDOWS = frozenset(
    {
        r"C:\Windows",
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        r"C:\ProgramData",
        r"\\.\pipe\docker_engine",
    }
)

BLOCKED_HOST_PATHS = (
    _BLOCKED_HOST_PATHS_POSIX | _BLOCKED_HOST_PATHS_WINDOWS
    if sys.platform == "win32"
    else _BLOCKED_HOST_PATHS_POSIX
)


def normalize_instance_uuid(value: str) -> str:
    normalized = str(value or "").strip()
    if not _INSTANCE_ID_PATTERN.fullmatch(normalized):
        raise ValueError("A valid trusted LangBot instance UUID is required")
    return normalized


def validate_control_token(value: str) -> str:
    token = str(value or "").strip()
    if len(token) < CONTROL_TOKEN_MIN_LENGTH or any(
        character.isspace() for character in token
    ):
        raise ValueError(
            f"{BOX_CONTROL_TOKEN_ENV} must be a non-whitespace secret of at least "
            f"{CONTROL_TOKEN_MIN_LENGTH} characters"
        )
    return token


def validate_sandbox_security(spec: BoxSpec) -> None:
    """Validate that a BoxSpec does not request dangerous container config.

    Raises BoxValidationError when the spec contains a blocked host_path.
    """
    if spec.host_path:
        real = os.path.realpath(spec.host_path)
        sep = os.sep
        _norm = os.path.normcase
        for blocked in BLOCKED_HOST_PATHS:
            if _norm(real) == _norm(blocked) or _norm(real).startswith(
                _norm(blocked) + sep
            ):
                raise BoxValidationError(
                    f"host_path {spec.host_path} is blocked for security"
                )
