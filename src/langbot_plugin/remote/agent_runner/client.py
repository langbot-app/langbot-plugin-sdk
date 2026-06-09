"""Client helpers for SDK-managed remote AgentRunner execution."""

from __future__ import annotations

import json
import typing
import urllib.error
import urllib.request

from langbot_plugin.api.entities.builtin.agent_runner import AgentRunContext


def default_workspace_key(
    ctx: AgentRunContext,
    *,
    configured: typing.Any = "",
) -> str:
    """Return a stable remote workspace key for a run context."""

    configured_text = str(configured or "").strip()
    if configured_text:
        return configured_text

    stored = str(ctx.state.conversation.get("external.workspace_key") or "").strip()
    if stored:
        return stored

    conversation = ctx.conversation
    parts = []
    for value in (
        getattr(conversation, "workspace_id", None),
        getattr(conversation, "bot_id", None),
        getattr(conversation, "conversation_id", None),
        getattr(conversation, "thread_id", None),
    ):
        if value:
            parts.append(str(value))
    return ":".join(parts) or str(ctx.state.conversation.get("external.conversation_id") or "default")


def post_remote_run(
    endpoint: str,
    token: str,
    request_payload: dict[str, typing.Any],
    timeout: float,
) -> dict[str, typing.Any]:
    """POST a one-shot remote run request to an SDK remote AgentRunner daemon."""

    data = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/run",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "code": "connection_error", "error": str(e), "retryable": True}

    try:
        parsed = json.loads(body) if body else {}
    except json.JSONDecodeError as e:
        return {"ok": False, "code": "invalid_response", "error": f"invalid remote response: {e}"}
    if not isinstance(parsed, dict):
        return {"ok": False, "code": "invalid_response", "error": "remote response must be an object"}
    return parsed
