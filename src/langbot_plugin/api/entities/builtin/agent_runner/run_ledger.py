"""Run ledger entities for Runtime Control Plane v2."""

from __future__ import annotations

import enum
import typing

import pydantic


class AgentRunStatus(str, enum.Enum):
    """Host-owned run lifecycle status."""

    CREATED = "created"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class AgentRun(pydantic.BaseModel):
    """Persisted Host-owned AgentRunner execution record."""

    id: int | None = None
    run_id: str
    event_id: str | None = None
    agent_id: str | None = None
    binding_id: str | None = None
    runner_id: str | None = None
    conversation_id: str | None = None
    thread_id: str | None = None
    workspace_id: str | None = None
    bot_id: str | None = None
    status: AgentRunStatus | str
    status_reason: str | None = None
    created_at: int | None = None
    started_at: int | None = None
    finished_at: int | None = None
    updated_at: int | None = None
    deadline_at: int | None = None
    cancel_requested_at: int | None = None
    queue_name: str | None = None
    priority: int | None = None
    requested_runtime_id: str | None = None
    claimed_by_runtime_id: str | None = None
    claim_token: str | None = None
    claim_lease_expires_at: int | None = None
    dispatch_attempts: int | None = None
    last_claimed_at: int | None = None
    usage: dict[str, typing.Any] | None = None
    cost: dict[str, typing.Any] | None = None
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)

    model_config = pydantic.ConfigDict(extra="forbid")


class AgentRunEvent(pydantic.BaseModel):
    """Persisted result event emitted by one AgentRunner execution."""

    id: int | None = None
    run_id: str
    sequence: int
    type: str
    data: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    usage: dict[str, typing.Any] | None = None
    created_at: int | None = None
    source: str | None = None
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)

    model_config = pydantic.ConfigDict(extra="forbid")


class RunPage(pydantic.BaseModel):
    """Paged result for run.list APIs."""

    items: list[AgentRun] = pydantic.Field(default_factory=list)
    next_cursor: str | None = None
    prev_cursor: str | None = None
    has_more: bool = False
    total_count: int = 0

    model_config = pydantic.ConfigDict(extra="forbid")


class RunEventPage(pydantic.BaseModel):
    """Paged result for run.events.page APIs."""

    items: list[AgentRunEvent] = pydantic.Field(default_factory=list)
    next_cursor: str | None = None
    prev_cursor: str | None = None
    has_more: bool = False
    total_count: int | None = None

    model_config = pydantic.ConfigDict(extra="forbid")


class AgentRuntime(pydantic.BaseModel):
    """Host-owned runtime registry record."""

    runtime_id: str
    status: str
    display_name: str | None = None
    endpoint: str | None = None
    version: str | None = None
    capabilities: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    labels: dict[str, str] = pydantic.Field(default_factory=dict)
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    last_heartbeat_at: int | None = None
    heartbeat_deadline_at: int | None = None
    created_at: int | None = None
    updated_at: int | None = None

    model_config = pydantic.ConfigDict(extra="forbid")


class RuntimePage(pydantic.BaseModel):
    """Paged result for runtime.list APIs."""

    items: list[AgentRuntime] = pydantic.Field(default_factory=list)
    next_cursor: str | None = None
    prev_cursor: str | None = None
    has_more: bool = False
    total_count: int = 0

    model_config = pydantic.ConfigDict(extra="forbid")


class RunStats(pydantic.BaseModel):
    """Statistics for runs within a time window."""

    # Time window
    start_time: int | None = None
    end_time: int | None = None

    # Counts by status
    total_count: int = 0
    created_count: int = 0
    queued_count: int = 0
    claimed_count: int = 0
    running_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    timeout_count: int = 0

    # Rates (per hour)
    throughput_per_hour: float | None = None
    success_rate: float | None = None
    failure_rate: float | None = None

    # Duration stats (in seconds)
    avg_duration_seconds: float | None = None
    p50_duration_seconds: float | None = None
    p95_duration_seconds: float | None = None
    p99_duration_seconds: float | None = None
    avg_queue_wait_seconds: float | None = None

    model_config = pydantic.ConfigDict(extra="forbid")


class RuntimeStats(pydantic.BaseModel):
    """Statistics for runtimes."""

    total_count: int = 0
    online_count: int = 0
    stale_count: int = 0

    # Heartbeat health
    avg_heartbeat_age_seconds: float | None = None
    max_heartbeat_age_seconds: float | None = None

    # Capacity (if reported by runtimes in metadata)
    active_runs: int = 0
    claimed_runs: int = 0

    model_config = pydantic.ConfigDict(extra="forbid")


class RunnerStats(pydantic.BaseModel):
    """Statistics aggregated by runner."""

    runner_id: str
    runner_label: str | None = None
    plugin_identity: str | None = None

    # Run counts
    total_runs: int = 0
    active_runs: int = 0
    completed_runs: int = 0
    failed_runs: int = 0

    # Rates
    success_rate: float | None = None
    avg_duration_seconds: float | None = None

    model_config = pydantic.ConfigDict(extra="forbid")


class RunnerStatsPage(pydantic.BaseModel):
    """Paged result for runner stats."""

    items: list[RunnerStats] = pydantic.Field(default_factory=list)
    total_count: int = 0
    has_more: bool = False

    model_config = pydantic.ConfigDict(extra="forbid")
