from __future__ import annotations

import hashlib
import re

from langbot_plugin.entities.io.context import ActionContext


def box_namespace(action_context: ActionContext) -> str:
    """Return the persistent namespace for one Workspace.

    This namespace deliberately excludes ``placement_generation``.  It owns
    durable Workspace data such as installed skills and the mounted host
    workspace, which must survive a placement hand-off.
    """

    context = ActionContext.model_validate(action_context)
    digest = hashlib.sha256(
        f"{context.instance_uuid}\0{context.workspace_uuid}".encode("utf-8")
    ).hexdigest()[:24]
    return f"ws-{digest}"


def box_runtime_namespace(action_context: ActionContext) -> str:
    """Return the ephemeral runtime namespace for one Workspace placement."""

    context = ActionContext.model_validate(action_context)
    return f"{box_namespace(context)}-g{context.placement_generation}"


def namespace_session_id(action_context: ActionContext, session_id: str) -> str:
    """Map a logical session id into a placement-owned physical id."""

    logical_id = str(session_id or "").strip()
    if not logical_id:
        raise ValueError("Box session_id must not be empty")
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", logical_id).strip("-")
    if not safe_id:
        raise ValueError("Box session_id must contain a valid character")
    return f"{box_runtime_namespace(action_context)}-{safe_id}"


def session_namespace_prefix(action_context: ActionContext) -> str:
    return f"{box_runtime_namespace(action_context)}-"


def workspace_session_namespace_prefix(action_context: ActionContext) -> str:
    """Return the prefix shared by every placement of one Workspace."""

    return f"{box_namespace(action_context)}-"


def session_belongs_to_placement(
    action_context: ActionContext,
    session_id: str,
) -> bool:
    """Return whether a physical session belongs to the exact placement."""

    physical_id = str(session_id or "").strip()
    prefix = session_namespace_prefix(action_context)
    return physical_id.startswith(prefix) and len(physical_id) > len(prefix)


def logical_session_id(action_context: ActionContext, session_id: str) -> str:
    """Return the caller-visible id for a Workspace-owned physical session.

    Values outside the exact placement namespace are preserved rather than
    exposed as another placement's logical id.
    """

    physical_id = str(session_id or "").strip()
    prefix = session_namespace_prefix(action_context)
    if physical_id.startswith(prefix):
        return physical_id[len(prefix) :]
    return physical_id
