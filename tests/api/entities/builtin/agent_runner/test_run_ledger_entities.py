"""Tests for Runtime Control Plane v2 run ledger entities."""

from __future__ import annotations

import pytest

from langbot_plugin.api.entities.builtin.agent_runner.run_ledger import (
    AgentRun,
    AgentRunEvent,
    AgentRunStatus,
    RunEventPage,
    RunPage,
)
from langbot_plugin.api.entities.builtin.agent_runner.runtime_registry import (
    AgentRuntime,
    RuntimePage,
)
from langbot_plugin.api.entities.builtin.agent_runner.stats import RunStats


def test_agent_run_accepts_host_ledger_shape():
    run = AgentRun.model_validate(
        {
            "id": 1,
            "run_id": "run_1",
            "event_id": "evt_1",
            "binding_id": "binding_1",
            "runner_id": "plugin:test/plugin/default",
            "conversation_id": "conv_1",
            "status": "claimed",
            "queue_name": "default",
            "priority": 10,
            "requested_runtime_id": "runtime_requested",
            "claimed_by_runtime_id": "runtime_1",
            "claim_token": "claim_token_1",
            "claim_lease_expires_at": 200,
            "dispatch_attempts": 2,
            "last_claimed_at": 100,
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            "metadata": {"source": "test"},
        }
    )

    assert run.status == AgentRunStatus.CLAIMED
    assert AgentRunStatus.QUEUED.value == "queued"
    assert run.queue_name == "default"
    assert run.claimed_by_runtime_id == "runtime_1"
    assert run.claim_token == "claim_token_1"
    assert run.usage is not None
    assert run.usage["prompt_tokens"] == 1


def test_run_event_page_accepts_unknown_result_types():
    page = RunEventPage.model_validate(
        {
            "items": [
                {
                    "id": 1,
                    "run_id": "run_1",
                    "sequence": 1,
                    "type": "custom.progress",
                    "data": {"pct": 50},
                    "metadata": {},
                }
            ],
            "next_cursor": None,
            "prev_cursor": "1",
            "has_more": False,
        }
    )

    assert page.items[0].type == "custom.progress"
    assert page.items[0].data == {"pct": 50}


def test_run_page_forbids_unexpected_fields():
    with pytest.raises(Exception):
        RunPage.model_validate({"items": [], "has_more": False, "unexpected": True})


def test_agent_run_event_requires_sequence():
    with pytest.raises(Exception):
        AgentRunEvent.model_validate(
            {
                "run_id": "run_1",
                "type": "message.completed",
            }
        )


def test_agent_runtime_accepts_host_registry_shape():
    runtime = AgentRuntime.model_validate(
        {
            "runtime_id": "runtime_1",
            "status": "online",
            "display_name": "Runtime 1",
            "endpoint": "http://runtime.local",
            "version": "1.2.3",
            "capabilities": {"queues": ["default"]},
            "labels": {"region": "local"},
            "metadata": {"owner": "test"},
            "last_heartbeat_at": 100,
            "heartbeat_deadline_at": 160,
            "created_at": 1,
            "updated_at": 100,
        }
    )

    assert runtime.runtime_id == "runtime_1"
    assert runtime.capabilities["queues"] == ["default"]
    assert runtime.labels["region"] == "local"


def test_runtime_page_forbids_unexpected_fields():
    with pytest.raises(Exception):
        RuntimePage.model_validate({"items": [], "has_more": False, "unexpected": True})


def test_run_stats_accepts_admin_shape():
    stats = RunStats.model_validate(
        {
            "start_time": 1,
            "end_time": 100,
            "total_count": 10,
            "completed_count": 8,
            "failed_count": 2,
            "success_rate": 0.8,
        }
    )

    assert stats.total_count == 10
    assert stats.success_rate == 0.8
