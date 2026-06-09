"""Tests for PluginManager AgentRunner methods (Protocol v1)."""

from __future__ import annotations

import time
import typing
from unittest.mock import Mock

import pytest

from langbot_plugin.api.definition.components.base import NoneComponent
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.entities.builtin.agent_runner.capabilities import (
    AgentRunnerCapabilities,
)
from langbot_plugin.api.entities.builtin.agent_runner.permissions import (
    AgentRunnerPermissions,
)
from langbot_plugin.api.entities.builtin.agent_runner.result import AgentRunResult
from langbot_plugin.api.entities.builtin.agent_runner.trigger import AgentTrigger
from langbot_plugin.api.entities.builtin.agent_runner.input import AgentInput
from langbot_plugin.api.entities.builtin.agent_runner.resources import AgentResources
from langbot_plugin.api.entities.builtin.agent_runner.runtime import AgentRuntimeContext
from langbot_plugin.api.entities.builtin.agent_runner.event import AgentEventContext
from langbot_plugin.api.entities.builtin.agent_runner.delivery import DeliveryContext
from langbot_plugin.api.entities.builtin.provider.message import Message, MessageChunk
from langbot_plugin.api.definition.components.agent_runner.runner import AgentRunner
from langbot_plugin.runtime.plugin.container import RuntimeContainerStatus


class MockAgentRunner(AgentRunner):
    """Mock AgentRunner for testing."""

    async def run(
        self, ctx: AgentRunContext
    ) -> typing.AsyncGenerator[AgentRunResult, None]:
        """Mock run that yields results."""
        yield AgentRunResult.message_completed(
            run_id=ctx.run_id,
            message=Message(role="assistant", content=f"Echo: {ctx.input.to_text()}"),
        )
        yield AgentRunResult.run_completed(run_id=ctx.run_id, finish_reason="stop")


class StreamingAgentRunner(AgentRunner):
    """Mock AgentRunner that streams."""

    async def run(
        self, ctx: AgentRunContext
    ) -> typing.AsyncGenerator[AgentRunResult, None]:
        """Mock run that streams chunks using MessageChunk."""
        for word in ["Hello", " ", "world"]:
            chunk = MessageChunk(role="assistant", content=word)
            yield AgentRunResult.message_delta(run_id=ctx.run_id, chunk=chunk)
        yield AgentRunResult.run_completed(run_id=ctx.run_id, finish_reason="stop")


class FailingAgentRunner(AgentRunner):
    """Mock AgentRunner that fails."""

    async def run(
        self, ctx: AgentRunContext
    ) -> typing.AsyncGenerator[AgentRunResult, None]:
        """Mock run that raises an exception after yielding."""
        # Must have at least one yield to be an async generator
        chunk = MessageChunk(role="assistant", content="Starting...")
        yield AgentRunResult.message_delta(run_id=ctx.run_id, chunk=chunk)
        raise RuntimeError("Intentional test failure")


class SlowAgentRunner(AgentRunner):
    """Mock AgentRunner that exceeds the run deadline."""

    async def run(
        self, ctx: AgentRunContext
    ) -> typing.AsyncGenerator[AgentRunResult, None]:
        import asyncio

        await asyncio.sleep(0.05)
        yield AgentRunResult.run_completed(run_id=ctx.run_id, finish_reason="stop")


class ClassDeclaredAgentRunner(AgentRunner):
    """AgentRunner that declares runner metadata in Python class defaults."""

    @classmethod
    def get_capabilities(cls) -> AgentRunnerCapabilities:
        return AgentRunnerCapabilities(streaming=True, tool_calling=True)

    @classmethod
    def get_config_schema(cls) -> list[dict[str, typing.Any]]:
        return [{"type": "llm-model-selector", "name": "model"}]

    @classmethod
    def get_permissions(cls) -> AgentRunnerPermissions:
        return AgentRunnerPermissions(models=["invoke"], tools=["call"])

    async def run(
        self, ctx: AgentRunContext
    ) -> typing.AsyncGenerator[AgentRunResult, None]:
        yield AgentRunResult.run_completed(run_id=ctx.run_id, finish_reason="stop")


def create_mock_component_manifest(
    runner_name: str,
    spec: dict | None = None,
):
    """Create a mock ComponentManifest-like object."""
    mock_manifest = Mock()
    mock_manifest.kind = "AgentRunner"
    mock_manifest.metadata = Mock()
    mock_manifest.metadata.name = runner_name
    mock_manifest.metadata.description = f"Test runner {runner_name}"
    mock_manifest.spec = spec or {
        "config": [],
        "capabilities": {},
        "permissions": {},
    }
    mock_manifest.model_dump = Mock(
        return_value={
            "kind": "AgentRunner",
            "metadata": {
                "name": runner_name,
                "description": f"Test runner {runner_name}",
            },
            "spec": mock_manifest.spec,
        }
    )
    return mock_manifest


def create_mock_plugin(
    author: str,
    name: str,
    runner_components: list[tuple[str, AgentRunner | None]],
    capabilities: dict | None = None,
    permissions: dict | None = None,
    mock_handler_responses: list[list[dict]] | None = None,
    status: RuntimeContainerStatus = RuntimeContainerStatus.INITIALIZED,
    enabled: bool = True,
):
    """Create a mock plugin container with AgentRunner components.

    Args:
        author: Plugin author
        name: Plugin name
        runner_components: List of (runner_name, runner_instance) tuples
        capabilities: Optional capabilities dict
        permissions: Optional permissions dict
        mock_handler_responses: Optional list of response lists for each runner.
            Each element is a list of responses to yield for that runner.
    """
    plugin = Mock()
    plugin.manifest = Mock()
    plugin.manifest.metadata = Mock()
    plugin.manifest.metadata.author = author
    plugin.manifest.metadata.name = name

    components = []
    for runner_name, runner_instance in runner_components:
        spec = {
            "config": [],
            "capabilities": capabilities or {},
            "permissions": permissions or {},
        }
        component = Mock()
        component.manifest = create_mock_component_manifest(runner_name, spec)
        component.component_instance = runner_instance
        components.append(component)

    plugin.components = components
    plugin.status = status
    plugin.enabled = enabled

    # Mock runtime plugin handler for forwarding
    if mock_handler_responses:

        async def mock_call_action_generator(action, data, timeout=300):
            runner_name = data.get("runner_name")
            # Find matching responses for this runner
            for idx, (rname, _) in enumerate(runner_components):
                if rname == runner_name and idx < len(mock_handler_responses):
                    for resp in mock_handler_responses[idx]:
                        yield resp  # Yield response data directly (matches real call_action_generator)
                    return
            # No matching responses found
            yield {
                "type": "run.failed",
                "data": {
                    "error": f"No mock responses for {runner_name}",
                    "code": "runner.mock_error",
                },
            }

        mock_handler = Mock()
        mock_handler.call_action_generator = mock_call_action_generator
        plugin._runtime_plugin_handler = mock_handler
    else:
        # Default: no handler (will cause handler_not_found error)
        plugin._runtime_plugin_handler = None

    return plugin


class RecordingRuntimeHandler:
    """Minimal runtime handler that records whether runner forwarding happens."""

    def __init__(self, responses: list[dict] | None = None):
        self.calls: list[tuple[typing.Any, dict, float]] = []
        self.responses = responses or [
            {"type": "run.completed", "data": {"finish_reason": "stop"}}
        ]

    async def call_action_generator(self, action, data, timeout=300):
        self.calls.append((action, data, timeout))
        for response in self.responses:
            yield response


def create_run_context() -> AgentRunContext:
    """Create a valid AgentRunContext for testing."""
    return AgentRunContext(
        run_id="test_run",
        trigger=AgentTrigger(type="message.received"),
        event=AgentEventContext(
            event_id="test_event",
            event_type="message.received",
            source="test",
        ),
        input=AgentInput(text="Hello"),
        delivery=DeliveryContext(surface="test"),
        resources=AgentResources(),
        runtime=AgentRuntimeContext(),
    )


class TestListAgentRunners:
    """Test PluginManager.list_agent_runners v1 protocol."""

    @pytest.mark.anyio
    async def test_single_plugin_single_runner(self):
        """Test listing a plugin with one runner."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)

        runner = MockAgentRunner()
        plugin = create_mock_plugin("test-author", "test-plugin", [("default", runner)])
        mgr.plugins = [plugin]

        runners = await mgr.list_agent_runners()

        assert len(runners) == 1
        assert runners[0]["plugin_author"] == "test-author"
        assert runners[0]["plugin_name"] == "test-plugin"
        assert runners[0]["runner_name"] == "default"
        assert "protocol_version" not in runners[0]
        assert "capabilities" in runners[0]
        assert "permissions" in runners[0]

    @pytest.mark.anyio
    async def test_single_plugin_multiple_runners(self):
        """Test listing a plugin with multiple runners (key feature of v1)."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)

        # Create plugin with multiple AgentRunner components
        plugin = create_mock_plugin(
            "test-author",
            "multi-runner-plugin",
            [
                ("default", MockAgentRunner()),
                ("streaming", StreamingAgentRunner()),
                ("tool_based", MockAgentRunner()),
            ],
            capabilities={"streaming": True, "tool_calling": True},
            permissions={"models": ["invoke"], "tools": ["call"]},
        )
        mgr.plugins = [plugin]

        runners = await mgr.list_agent_runners()

        assert len(runners) == 3
        runner_names = [r["runner_name"] for r in runners]
        assert "default" in runner_names
        assert "streaming" in runner_names
        assert "tool_based" in runner_names

        # Check capabilities and permissions are included
        for runner in runners:
            assert "protocol_version" not in runner
            assert "capabilities" in runner
            assert "permissions" in runner

    @pytest.mark.anyio
    async def test_include_plugins_filter(self):
        """Test include_plugins filtering."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)

        plugin1 = create_mock_plugin(
            "author1", "plugin1", [("runner1", MockAgentRunner())]
        )
        plugin2 = create_mock_plugin(
            "author2", "plugin2", [("runner2", MockAgentRunner())]
        )
        mgr.plugins = [plugin1, plugin2]

        # Only include plugin1
        runners = await mgr.list_agent_runners(include_plugins=["author1/plugin1"])
        assert len(runners) == 1
        assert runners[0]["plugin_author"] == "author1"

        # Empty filter returns all
        runners = await mgr.list_agent_runners()
        assert len(runners) == 2

    @pytest.mark.anyio
    async def test_skips_disabled_and_uninitialized_plugins(self):
        """Runner listing uses the same plugin lifecycle gate as event dispatch."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)
        mgr.plugins = [
            create_mock_plugin(
                "author",
                "ready",
                [("ready_runner", MockAgentRunner())],
            ),
            create_mock_plugin(
                "author",
                "disabled",
                [("disabled_runner", MockAgentRunner())],
                enabled=False,
            ),
            create_mock_plugin(
                "author",
                "mounted",
                [("mounted_runner", MockAgentRunner())],
                status=RuntimeContainerStatus.MOUNTED,
            ),
        ]

        runners = await mgr.list_agent_runners()

        assert [runner["plugin_name"] for runner in runners] == ["ready"]

    @pytest.mark.anyio
    async def test_uses_runner_class_defaults_when_manifest_omits_spec_details(self):
        """Python AgentRunner declarations are reflected in LIST_AGENT_RUNNERS."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)
        plugin = create_mock_plugin(
            "test-author",
            "class-declared-plugin",
            [("default", ClassDeclaredAgentRunner())],
        )
        plugin.components[0].manifest = create_mock_component_manifest(
            "default",
            spec={},
        )
        mgr.plugins = [plugin]

        runners = await mgr.list_agent_runners()

        assert len(runners) == 1
        assert runners[0]["capabilities"]["streaming"] is True
        assert runners[0]["capabilities"]["tool_calling"] is True
        assert runners[0]["permissions"]["models"] == ["invoke"]
        assert runners[0]["permissions"]["tools"] == ["call"]
        assert runners[0]["config"] == [{"type": "llm-model-selector", "name": "model"}]


class TestRunAgent:
    """Test PluginManager.run_agent v1 protocol."""

    @pytest.mark.anyio
    async def test_run_agent_success_streaming(self):
        """Test successful run_agent with streaming output."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)

        # Create mock responses for streaming
        mock_responses = [
            {
                "type": "message.delta",
                "data": {"chunk": {"role": "assistant", "content": "Hello"}},
            },
            {
                "type": "message.delta",
                "data": {"chunk": {"role": "assistant", "content": " world"}},
            },
            {"type": "run.completed", "data": {"finish_reason": "stop"}},
        ]

        plugin = create_mock_plugin(
            "test-author",
            "test-plugin",
            [("streaming", None)],
            mock_handler_responses=[mock_responses],
        )
        mgr.plugins = [plugin]

        ctx = create_run_context()
        results = []
        async for result in mgr.run_agent(
            "test-author",
            "test-plugin",
            "streaming",
            ctx.model_dump(mode="json"),
        ):
            results.append(result)

        # Should have streaming chunks + run.completed
        assert len(results) >= 2
        assert results[-1]["type"] == "run.completed"

    @pytest.mark.anyio
    async def test_run_agent_plugin_not_found(self):
        """Test run_agent returns run.failed when plugin not found."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)
        mgr.plugins = []

        ctx = create_run_context()
        results = []
        async for result in mgr.run_agent(
            "unknown",
            "unknown-plugin",
            "default",
            ctx.model_dump(mode="json"),
        ):
            results.append(result)

        assert len(results) == 1
        assert results[0]["type"] == "run.failed"
        assert results[0]["data"]["code"] == "runner.plugin_not_found"

    @pytest.mark.anyio
    async def test_run_agent_runner_not_found(self):
        """Test run_agent returns run.failed when runner not found."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)

        # Plugin exists but no matching runner
        plugin = create_mock_plugin(
            "test-author", "test-plugin", [("other_runner", MockAgentRunner())]
        )
        mgr.plugins = [plugin]

        ctx = create_run_context()
        results = []
        async for result in mgr.run_agent(
            "test-author",
            "test-plugin",
            "default",  # Not found
            ctx.model_dump(mode="json"),
        ):
            results.append(result)

        assert len(results) == 1
        assert results[0]["type"] == "run.failed"
        assert results[0]["data"]["code"] == "runner.not_found"

    @pytest.mark.anyio
    async def test_run_agent_runner_exception_converted_to_run_failed(self):
        """Test that runner exceptions are converted to run.failed (critical requirement)."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)

        # Create mock responses simulating an exception
        mock_responses = [
            {
                "type": "message.delta",
                "data": {"chunk": {"role": "assistant", "content": "Starting..."}},
            },
            {
                "type": "run.failed",
                "data": {
                    "error": "Intentional test failure",
                    "code": "runner.exception",
                },
            },
        ]

        plugin = create_mock_plugin(
            "test-author",
            "test-plugin",
            [("failing", None)],
            mock_handler_responses=[mock_responses],
        )
        mgr.plugins = [plugin]

        ctx = create_run_context()
        results = []
        async for result in mgr.run_agent(
            "test-author",
            "test-plugin",
            "failing",
            ctx.model_dump(mode="json"),
        ):
            results.append(result)

        # Must convert exception to run.failed, not raise
        assert len(results) >= 1
        assert results[-1]["type"] == "run.failed"
        assert results[-1]["data"]["code"] == "runner.exception"
        assert "Intentional test failure" in results[-1]["data"]["error"]

    @pytest.mark.anyio
    async def test_run_agent_context_validation_failure(self):
        """Test that invalid context produces run.failed when forwarded."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)

        # Create mock responses for context validation failure
        mock_responses = [
            {
                "type": "run.failed",
                "data": {
                    "error": "Context validation failed",
                    "code": "runner.context_invalid",
                },
            },
        ]

        plugin = create_mock_plugin(
            "test-author",
            "test-plugin",
            [("default", None)],
            mock_handler_responses=[mock_responses],
        )
        mgr.plugins = [plugin]

        # Invalid context (missing required fields)
        invalid_context = {"invalid": "data"}

        results = []
        async for result in mgr.run_agent(
            "test-author",
            "test-plugin",
            "default",
            invalid_context,
        ):
            results.append(result)

        assert len(results) == 1
        assert results[0]["type"] == "run.failed"
        assert results[0]["data"]["code"] == "runner.context_invalid"

    @pytest.mark.anyio
    async def test_run_agent_handler_not_found(self):
        """Test run_agent when plugin has no runtime handler."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)

        # Plugin without handler (default when no mock_handler_responses provided)
        plugin = create_mock_plugin("test-author", "test-plugin", [("default", None)])
        mgr.plugins = [plugin]

        ctx = create_run_context()
        results = []
        async for result in mgr.run_agent(
            "test-author",
            "test-plugin",
            "default",
            ctx.model_dump(mode="json"),
        ):
            results.append(result)

        assert len(results) == 1
        assert results[0]["type"] == "run.failed"
        assert results[0]["data"]["code"] == "runner.handler_not_found"

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("enabled", "status", "expected_code"),
        [
            (False, RuntimeContainerStatus.INITIALIZED, "runner.plugin_disabled"),
            (True, RuntimeContainerStatus.MOUNTED, "runner.plugin_not_initialized"),
        ],
    )
    async def test_run_agent_rejects_plugins_outside_ready_gate(
        self,
        enabled: bool,
        status: RuntimeContainerStatus,
        expected_code: str,
    ):
        """Disabled or uninitialized plugins are denied before handler forwarding."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)
        plugin = create_mock_plugin(
            "test-author",
            "test-plugin",
            [("default", MockAgentRunner())],
            enabled=enabled,
            status=status,
        )
        runtime_handler = RecordingRuntimeHandler()
        plugin._runtime_plugin_handler = runtime_handler
        mgr.plugins = [plugin]

        ctx = create_run_context()
        results = []
        async for result in mgr.run_agent(
            "test-author",
            "test-plugin",
            "default",
            ctx.model_dump(mode="json"),
        ):
            results.append(result)

        assert runtime_handler.calls == []
        assert len(results) == 1
        assert results[0]["type"] == "run.failed"
        assert results[0]["data"]["code"] == expected_code

    @pytest.mark.anyio
    async def test_run_agent_runner_not_initialized_forwarded(self):
        """Test run_agent when plugin handler returns not_initialized error."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)

        # Mock responses for not initialized error
        mock_responses = [
            {
                "type": "run.failed",
                "data": {
                    "error": "AgentRunner default not initialized",
                    "code": "runner.not_initialized",
                },
            },
        ]

        plugin = create_mock_plugin(
            "test-author",
            "test-plugin",
            [("default", None)],
            mock_handler_responses=[mock_responses],
        )
        mgr.plugins = [plugin]

        ctx = create_run_context()
        results = []
        async for result in mgr.run_agent(
            "test-author",
            "test-plugin",
            "default",
            ctx.model_dump(mode="json"),
        ):
            results.append(result)

        assert len(results) == 1
        assert results[0]["type"] == "run.failed"
        assert results[0]["data"]["code"] == "runner.not_initialized"

    @pytest.mark.anyio
    async def test_run_agent_deadline_returns_timeout(self):
        """PluginManager enforces total runner deadline while forwarding."""
        from langbot_plugin.runtime.plugin.mgr import PluginManager
        from langbot_plugin.runtime.context import RuntimeContext

        mock_context = Mock(spec=RuntimeContext)
        mgr = PluginManager(mock_context)

        mock_responses = [
            {"type": "run.completed", "data": {"finish_reason": "stop"}},
        ]
        plugin = create_mock_plugin(
            "test-author",
            "test-plugin",
            [("default", None)],
            mock_handler_responses=[mock_responses],
        )
        mgr.plugins = [plugin]

        ctx = create_run_context()
        ctx.runtime.deadline_at = time.time() - 1

        results = []
        async for result in mgr.run_agent(
            "test-author",
            "test-plugin",
            "default",
            ctx.model_dump(mode="json"),
        ):
            results.append(result)

        assert len(results) == 1
        assert results[0]["type"] == "run.failed"
        assert results[0]["data"]["code"] == "runner.timeout"
        assert results[0]["data"]["retryable"] is True


@pytest.mark.anyio
async def test_plugin_runtime_runner_deadline_cancels_runner_coroutine():
    """The plugin-process helper converts an expired runner coroutine to run.failed."""
    from langbot_plugin.cli.run.handler import _iter_runner_results_with_deadline

    ctx = create_run_context()
    ctx.runtime.deadline_at = time.time() + 0.01

    results = [
        result
        async for result in _iter_runner_results_with_deadline(SlowAgentRunner(), ctx)
    ]

    assert len(results) == 1
    assert results[0].type.value == "run.failed"
    assert results[0].data["code"] == "runner.timeout"
    assert results[0].data["retryable"] is True


@pytest.mark.anyio
async def test_plugin_runtime_runner_exception_includes_run_id():
    """The plugin-process RUN_AGENT handler must convert runner exceptions to run.failed."""
    from langbot_plugin.cli.run.handler import PluginRuntimeHandler
    from langbot_plugin.entities.io.actions.enums import RuntimeToPluginAction

    async def initialize_plugin(_settings):
        return None

    handler = PluginRuntimeHandler(Mock(), initialize_plugin)
    component = Mock()
    component.manifest = create_mock_component_manifest("failing")
    component.component_instance = FailingAgentRunner()
    handler.plugin_container = Mock(components=[component])

    run_agent = handler.actions[RuntimeToPluginAction.RUN_AGENT.value]
    results = [
        response.data
        async for response in run_agent(
            {
                "runner_name": "failing",
                "context": create_run_context().model_dump(mode="json"),
            }
        )
    ]

    assert results[-1]["type"] == "run.failed"
    assert results[-1]["run_id"] == "test_run"
    assert results[-1]["data"]["code"] == "runner.exception"
    assert "Intentional test failure" in results[-1]["data"]["error"]


@pytest.mark.anyio
async def test_plugin_runtime_context_validation_returns_structured_run_failed():
    """RUN_AGENT context validation failure must stay inside the runner stream."""
    from langbot_plugin.cli.run.handler import PluginRuntimeHandler
    from langbot_plugin.entities.io.actions.enums import RuntimeToPluginAction

    async def initialize_plugin(_settings):
        return None

    handler = PluginRuntimeHandler(Mock(), initialize_plugin)
    handler.plugin_container = Mock(components=[])

    run_agent = handler.actions[RuntimeToPluginAction.RUN_AGENT.value]
    responses = [
        response
        async for response in run_agent(
            {
                "runner_name": "default",
                "context": {"run_id": "bad_run", "invalid": "data"},
            }
        )
    ]

    assert len(responses) == 1
    assert responses[0].code == 0
    assert responses[0].data["type"] == "run.failed"
    assert responses[0].data["run_id"] == "bad_run"
    assert responses[0].data["data"]["code"] == "runner.context_invalid"


@pytest.mark.anyio
async def test_plugin_runtime_runner_not_found_returns_structured_run_failed():
    """RUN_AGENT not-found must be a stream payload, not an ActionResponse signature error."""
    from langbot_plugin.cli.run.handler import PluginRuntimeHandler
    from langbot_plugin.entities.io.actions.enums import RuntimeToPluginAction

    async def initialize_plugin(_settings):
        return None

    handler = PluginRuntimeHandler(Mock(), initialize_plugin)
    component = Mock()
    component.manifest = create_mock_component_manifest("other")
    component.component_instance = MockAgentRunner()
    handler.plugin_container = Mock(components=[component])

    run_agent = handler.actions[RuntimeToPluginAction.RUN_AGENT.value]
    responses = [
        response
        async for response in run_agent(
            {
                "runner_name": "missing",
                "context": create_run_context().model_dump(mode="json"),
            }
        )
    ]

    assert len(responses) == 1
    assert responses[0].code == 0
    assert responses[0].data["type"] == "run.failed"
    assert responses[0].data["run_id"] == "test_run"
    assert responses[0].data["data"]["code"] == "runner.not_found"


@pytest.mark.anyio
async def test_plugin_runtime_uninitialized_runner_returns_structured_run_failed():
    """RUN_AGENT uninitialized branch must preserve runner.not_initialized."""
    from langbot_plugin.cli.run.handler import PluginRuntimeHandler
    from langbot_plugin.entities.io.actions.enums import RuntimeToPluginAction

    async def initialize_plugin(_settings):
        return None

    handler = PluginRuntimeHandler(Mock(), initialize_plugin)
    component = Mock()
    component.manifest = create_mock_component_manifest("default")
    component.component_instance = NoneComponent()
    handler.plugin_container = Mock(components=[component])

    run_agent = handler.actions[RuntimeToPluginAction.RUN_AGENT.value]
    responses = [
        response
        async for response in run_agent(
            {
                "runner_name": "default",
                "context": create_run_context().model_dump(mode="json"),
            }
        )
    ]

    assert len(responses) == 1
    assert responses[0].code == 0
    assert responses[0].data["type"] == "run.failed"
    assert responses[0].data["run_id"] == "test_run"
    assert responses[0].data["data"]["code"] == "runner.not_initialized"
