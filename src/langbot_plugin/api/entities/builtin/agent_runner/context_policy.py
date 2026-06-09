"""AgentRunner context capability declaration."""

from __future__ import annotations

import pydantic


class AgentRunnerContextPolicy(pydantic.BaseModel):
    """Context capabilities declared by an AgentRunner component.

    Runner owns working context assembly and compaction. Host does not use this
    declaration to inline history windows.
    """

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
