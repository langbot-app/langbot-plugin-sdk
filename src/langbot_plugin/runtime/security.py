from __future__ import annotations

import re


PLUGIN_RUNTIME_CONTROL_TOKEN_ENV = "LANGBOT_PLUGIN_RUNTIME_CONTROL_TOKEN"
PLUGIN_RUNTIME_CONTROL_TOKEN_HEADER = "X-LangBot-Plugin-Runtime-Token"
PLUGIN_DEBUG_KEY_ENV = "PLUGIN_DEBUG_KEY"
PLUGIN_DEBUG_KEY_HEADER = "X-LangBot-Plugin-Debug-Key"
PLUGIN_REGISTRATION_CAPABILITY_ENV = "LANGBOT_PLUGIN_REGISTRATION_CAPABILITY"
PLUGIN_REGISTRATION_CAPABILITY_HEADER = "X-LangBot-Plugin-Registration-Capability"
PLUGIN_RUNTIME_PROFILE_ENV = "LANGBOT_PLUGIN_RUNTIME_PROFILE"
RUNTIME_SECRET_MIN_LENGTH = 32

_SECRET_PATTERN = re.compile(r"^[^\s]{32,}$")


def validate_runtime_secret(value: str, *, name: str) -> str:
    """Validate a control/debug secret without ever returning it in errors."""

    secret = str(value or "").strip()
    if not _SECRET_PATTERN.fullmatch(secret):
        raise ValueError(
            f"{name} must be a non-whitespace secret of at least "
            f"{RUNTIME_SECRET_MIN_LENGTH} characters"
        )
    return secret
