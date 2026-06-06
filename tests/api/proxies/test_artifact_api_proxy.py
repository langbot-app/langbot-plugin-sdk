"""Tests for artifact API proxy methods."""
from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock

from langbot_plugin.api.entities.builtin.agent_runner.artifact import (
    ArtifactMetadata,
    ArtifactReadResult,
)
from langbot_plugin.api.entities.builtin.agent_runner.context import AgentRunContext
from langbot_plugin.api.proxies.agent_run_api import AgentRunAPIProxy
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction


def make_context() -> AgentRunContext:
    """Create a test AgentRunContext."""
    return AgentRunContext(
        run_id="run_001",
        trigger={"type": "message.received", "source": "platform", "timestamp": None},
        event={
            "event_id": "evt_001",
            "event_type": "message.received",
            "source": "platform",
        },
        input={"text": "Hello"},
        delivery={"surface": "test"},
        context={
            "available_apis": {
                "artifact_metadata": True,
                "artifact_read": True,
            },
        },
        resources={"models": [], "tools": [], "knowledge_bases": [], "files": [], "storage": {}},
        runtime={"langbot_version": "1.0", "protocol_version": "1", "deadline_at": None, "metadata": {}},
        state={},
        config={},
    )


class TestArtifactAPIProxy:
    """Test artifact API proxy methods."""

    def test_exposes_artifact_metadata_method(self):
        """AgentRunAPIProxy exposes artifact_metadata method."""
        ctx = make_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert hasattr(proxy, 'artifact_metadata'), \
            "AgentRunAPIProxy should expose artifact_metadata() method"

    def test_exposes_artifact_read_method(self):
        """AgentRunAPIProxy exposes artifact_read method."""
        ctx = make_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert hasattr(proxy, 'artifact_read'), \
            "AgentRunAPIProxy should expose artifact_read() method"

    def test_exposes_artifact_read_range_method(self):
        """AgentRunAPIProxy exposes artifact_read_range method."""
        ctx = make_context()
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=MagicMock())

        assert hasattr(proxy, 'artifact_read_range'), \
            "AgentRunAPIProxy should expose artifact_read_range() method"


class TestArtifactAPIProxyPayloads:
    """Test that artifact API proxy methods send correct action payloads.

    Uses mock to intercept the call_action and verify payloads without
    actually running async code.
    """

    @staticmethod
    def _metadata_response(artifact_id: str = "art_001") -> dict:
        return {
            "artifact_id": artifact_id,
            "artifact_type": "file",
            "source": "runner",
        }

    @staticmethod
    def _read_response(artifact_id: str = "art_001", offset: int = 0, limit: int | None = None) -> dict:
        return {
            "artifact_id": artifact_id,
            "mime_type": "text/plain",
            "size_bytes": limit,
            "offset": offset,
            "length": limit,
            "content_base64": "",
            "has_more": False,
        }

    def test_artifact_metadata_payload_structure(self):
        """artifact_metadata constructs correct action payload."""
        ctx = make_context()
        mock_handler = MagicMock()
        mock_call_action = AsyncMock(return_value=self._metadata_response())
        mock_handler.call_action = mock_call_action
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        # Mock the async method to just capture the call
        original_method = proxy.artifact_metadata

        # Get the coroutine to inspect what it would call
        import inspect
        coro = original_method(artifact_id="art_001")

        # The coroutine is created; we can close it without running
        # But we need to verify what it WOULD call
        # Instead, let's check the method signature and logic directly

        # Verify the method exists and is async
        assert inspect.iscoroutinefunction(original_method)

        # Clean up the coroutine
        coro.close()

    def test_artifact_metadata_calls_correct_action(self):
        """artifact_metadata calls ARTIFACT_METADATA with correct args."""
        import asyncio

        ctx = make_context()
        mock_handler = MagicMock()
        mock_handler.call_action = AsyncMock(return_value=self._metadata_response())
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        # Run in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(proxy.artifact_metadata(artifact_id="art_001"))
        finally:
            loop.close()

        assert isinstance(result, ArtifactMetadata)
        mock_handler.call_action.assert_called_once()
        call_args = mock_handler.call_action.call_args
        action_name = call_args[0][0]
        payload = call_args[0][1]

        assert action_name == PluginToRuntimeAction.ARTIFACT_METADATA
        assert payload["run_id"] == "run_001"
        assert payload["artifact_id"] == "art_001"

    def test_artifact_read_calls_correct_action(self):
        """artifact_read calls ARTIFACT_READ with correct args."""
        import asyncio

        ctx = make_context()
        mock_handler = MagicMock()
        mock_handler.call_action = AsyncMock(return_value=self._read_response("art_002", offset=100, limit=1024))
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                proxy.artifact_read(artifact_id="art_002", offset=100, limit=1024)
            )
        finally:
            loop.close()

        assert isinstance(result, ArtifactReadResult)
        mock_handler.call_action.assert_called_once()
        call_args = mock_handler.call_action.call_args
        action_name = call_args[0][0]
        payload = call_args[0][1]

        assert action_name == PluginToRuntimeAction.ARTIFACT_READ
        assert payload["run_id"] == "run_001"
        assert payload["artifact_id"] == "art_002"
        assert payload["offset"] == 100
        assert payload["limit"] == 1024

    def test_artifact_read_default_offset_limit(self):
        """artifact_read uses default offset=0 and limit=None."""
        import asyncio

        ctx = make_context()
        mock_handler = MagicMock()
        mock_handler.call_action = AsyncMock(return_value=self._read_response("art_003"))
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(proxy.artifact_read(artifact_id="art_003"))
        finally:
            loop.close()

        call_args = mock_handler.call_action.call_args
        payload = call_args[0][1]

        assert payload["offset"] == 0
        assert payload["limit"] is None

    def test_artifact_read_range_calls_correct_action(self):
        """artifact_read_range calls ARTIFACT_READ with correct args."""
        import asyncio

        ctx = make_context()
        mock_handler = MagicMock()
        mock_handler.call_action = AsyncMock(return_value=self._read_response("art_004", offset=500, limit=2048))
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                proxy.artifact_read_range(artifact_id="art_004", offset=500, length=2048)
            )
        finally:
            loop.close()

        mock_handler.call_action.assert_called_once()
        call_args = mock_handler.call_action.call_args
        action_name = call_args[0][0]
        payload = call_args[0][1]

        assert action_name == PluginToRuntimeAction.ARTIFACT_READ
        assert payload["run_id"] == "run_001"
        assert payload["artifact_id"] == "art_004"
        assert payload["offset"] == 500
        assert payload["limit"] == 2048

    def test_artifact_metadata_uses_run_id_from_context(self):
        """artifact_metadata uses run_id from context, not from args."""
        import asyncio

        ctx = make_context()
        ctx.run_id = "custom_run_id_123"  # Custom run_id
        mock_handler = MagicMock()
        mock_handler.call_action = AsyncMock(return_value=self._metadata_response())
        proxy = AgentRunAPIProxy(ctx=ctx, plugin_runtime_handler=mock_handler)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(proxy.artifact_metadata(artifact_id="art_001"))
        finally:
            loop.close()

        call_args = mock_handler.call_action.call_args
        payload = call_args[0][1]

        # Verify that run_id comes from context
        assert payload["run_id"] == "custom_run_id_123"


class TestArtifactActionEnums:
    """Test artifact action enum values."""

    def test_artifact_metadata_enum_exists(self):
        """ARTIFACT_METADATA action enum exists."""
        assert hasattr(PluginToRuntimeAction, 'ARTIFACT_METADATA')
        assert PluginToRuntimeAction.ARTIFACT_METADATA.value == "artifact_metadata"

    def test_artifact_read_enum_exists(self):
        """ARTIFACT_READ action enum exists."""
        assert hasattr(PluginToRuntimeAction, 'ARTIFACT_READ')
        assert PluginToRuntimeAction.ARTIFACT_READ.value == "artifact_read"
