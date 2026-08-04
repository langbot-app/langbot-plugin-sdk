from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


PLUGIN_RUNTIME_CONTROL_TOKEN_ENV = "LANGBOT_PLUGIN_RUNTIME_CONTROL_TOKEN"
PLUGIN_RUNTIME_CONTROL_TOKEN_HEADER = "X-LangBot-Plugin-Runtime-Token"
PLUGIN_DEBUG_KEY_ENV = "PLUGIN_DEBUG_KEY"
PLUGIN_DEBUG_KEY_HEADER = "X-LangBot-Plugin-Debug-Key"
PLUGIN_REGISTRATION_CAPABILITY_ENV = "LANGBOT_PLUGIN_REGISTRATION_CAPABILITY"
PLUGIN_REGISTRATION_CAPABILITY_HEADER = "X-LangBot-Plugin-Registration-Capability"
PLUGIN_RUNTIME_PROFILE_ENV = "LANGBOT_PLUGIN_RUNTIME_PROFILE"
RUNTIME_SECRET_MIN_LENGTH = 32
WORKSPACE_DEBUG_TOKEN_TTL_SECONDS = 2 * 60 * 60

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


@dataclass(frozen=True, slots=True)
class WorkspaceDebugCredential:
    token: str
    expires_at: str


class WorkspaceDebugTokenStore:
    """Issue one random debug credential per Workspace and rotation window."""

    def __init__(self, *, clock=time.time, ttl_seconds: int = WORKSPACE_DEBUG_TOKEN_TTL_SECONDS):
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._credentials: dict[str, tuple[str, float, Any]] = {}

    @staticmethod
    def _format_time(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")

    def issue(self, binding: Any) -> WorkspaceDebugCredential:
        workspace_uuid = str(getattr(binding, "workspace_uuid", "") or "").strip()
        if not workspace_uuid:
            raise ValueError("Workspace debug credentials require Workspace context")
        now = float(self._clock())
        token, expires, existing_binding = self._credentials.get(workspace_uuid, ("", 0.0, None))
        if existing_binding is not None and (
            getattr(existing_binding, "instance_uuid", None) != getattr(binding, "instance_uuid", None)
            or getattr(existing_binding, "placement_generation", None)
            != getattr(binding, "placement_generation", None)
        ):
            token, expires = "", 0.0
        if not token or now >= expires:
            token = secrets.token_urlsafe(48)
            expires = now + self._ttl_seconds
        self._credentials[workspace_uuid] = (token, expires, binding)
        return WorkspaceDebugCredential(token=token, expires_at=self._format_time(expires))

    def binding_for_token(self, supplied_token: str) -> Any | None:
        supplied_token = str(supplied_token or "")
        if not supplied_token:
            return None
        now = float(self._clock())
        for workspace_uuid, (token, expires, binding) in tuple(self._credentials.items()):
            if now >= expires:
                self._credentials.pop(workspace_uuid, None)
                continue
            if secrets.compare_digest(token, supplied_token):
                return binding
        return None
