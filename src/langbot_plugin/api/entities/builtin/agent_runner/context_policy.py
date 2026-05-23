"""AgentRunner context policy as defined in Protocol v1.

Context policy controls how Host should provide context to the runner.
"""

from __future__ import annotations

import typing
import pydantic


class AgentRunnerContextPolicy(pydantic.BaseModel):
    """Context policy declared by an AgentRunner component.

    Host uses this declaration to decide whether/how to inline bootstrap history.
    Default principle: Host MUST NOT inline full history by default.
    """

    ownership: typing.Literal["self_managed", "host_bootstrap", "hybrid"] = "self_managed"
    """Context ownership mode.

    - self_managed: Host does not inline history, only provides event and handles.
    - host_bootstrap: Host inlines a small window for simple runners.
    - hybrid: Host inlines summary/tail, runner can still pull more.
    """

    bootstrap: typing.Literal["none", "current_event", "recent_tail", "summary_tail"] = "current_event"
    """Bootstrap mode for context provisioning.

    - none: No bootstrap context.
    - current_event: Only current event/input.
    - recent_tail: Recent message tail.
    - summary_tail: Summary with tail messages.
    """

    max_inline_events: int = 0
    """Maximum number of events to inline. 0 means no limit beyond bootstrap."""

    max_inline_bytes: int = 0
    """Maximum bytes to inline. 0 means no limit beyond bootstrap."""

    supports_history_pull: bool = True
    """Whether runner can pull history via API."""

    supports_history_search: bool = False
    """Whether runner can search history."""

    supports_artifact_pull: bool = True
    """Whether runner can pull artifacts."""

    owns_compaction: bool = True
    """Runner owns context compaction. Host should not do semantic summarization."""

    wants_static_context_refs: bool = True
    """Host should use ref/hash for static content to reduce repeated payload."""
