from __future__ import annotations

import asyncio
import os
import mimetypes
import typing
import base64
import aiofiles
from copy import deepcopy

from langbot_plugin.api.entities.builtin.pipeline.query import provider_session
from langbot_plugin.runtime.io import connection
from langbot_plugin.entities.io.resp import ActionResponse
from langbot_plugin.runtime.plugin.container import PluginContainer, ComponentContainer
from langbot_plugin.runtime.io.handler import Handler
from langbot_plugin.api.entities import events
from langbot_plugin.api.definition.components.base import NoneComponent
from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.entities.io.actions.enums import PluginToRuntimeAction
from langbot_plugin.entities.io.actions.enums import RuntimeToPluginAction
from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.definition.components.command.command import Command
from langbot_plugin.api.definition.components.rag_engine.engine import RAGEngine
from langbot_plugin.api.entities.builtin.rag.context import RetrievalContext
from langbot_plugin.api.entities.builtin.rag.models import IngestionContext
from langbot_plugin.api.proxies.event_context import EventContextProxy
from langbot_plugin.api.proxies.execute_context import ExecuteContextProxy


class PluginRuntimeHandler(Handler):
    """The handler for running plugins."""

    plugin_container: PluginContainer

    shutdown_callback: typing.Callable[[], typing.Coroutine[typing.Any, typing.Any, None]] | None = None
    """Callback to trigger shutdown and reconnect."""

    def __init__(
        self,
        connection: connection.Connection,
        plugin_initialize_callback: typing.Callable[
            [dict[str, typing.Any]], typing.Coroutine[typing.Any, typing.Any, None]
        ],
    ):
        super().__init__(connection)
        self.name = "FromRuntime"

        @self.action(RuntimeToPluginAction.INITIALIZE_PLUGIN)
        async def initialize_plugin(data: dict[str, typing.Any]) -> ActionResponse:
            await plugin_initialize_callback(data["plugin_settings"])
            return ActionResponse.success({})

        @self.action(RuntimeToPluginAction.GET_PLUGIN_CONTAINER)
        async def get_plugin_container(data: dict[str, typing.Any]) -> ActionResponse:
            return ActionResponse.success(self.plugin_container.model_dump())

        @self.action(RuntimeToPluginAction.GET_PLUGIN_ICON)
        async def get_plugin_icon(data: dict[str, typing.Any]) -> ActionResponse:
            icon_path = self.plugin_container.manifest.icon_rel_path
            if icon_path is None:
                return ActionResponse.success({"plugin_icon_file_key": "", "mime_type": ""})
            async with aiofiles.open(icon_path, "rb") as f:
                # icon_base64 = base64.b64encode(f.read()).decode("utf-8")
                icon_bytes = await f.read()

            mime_type = mimetypes.guess_type(icon_path)[0]

            plugin_icon_file_key = await self.send_file(icon_bytes, '')

            return ActionResponse.success(
                {"plugin_icon_file_key": plugin_icon_file_key, "mime_type": mime_type}
            )
        
        @self.action(RuntimeToPluginAction.GET_PLUGIN_README)
        async def get_plugin_readme(data: dict[str, typing.Any]) -> ActionResponse:
            language = data["language"]
            readme_path = os.path.join("readme", f"README_{language}.md") if language != "en" else "README.md"
            if not os.path.exists(readme_path):
                readme_path = "README.md"

            async with aiofiles.open(readme_path, "rb") as f:
                readme_bytes = await f.read()
            readme_file_key = await self.send_file(readme_bytes, "md")
            return ActionResponse.success({"plugin_readme_file_key": readme_file_key, "mime_type": "text/markdown"})

        @self.action(RuntimeToPluginAction.GET_PLUGIN_ASSETS_FILE)
        async def get_plugin_assets_file(data: dict[str, typing.Any]) -> ActionResponse:
            file_key = data["file_key"]
            file_path = os.path.join("assets", file_key)
            if not os.path.exists(file_path):
                return ActionResponse.success({"file_file_key": "", "mime_type": ""})

            async with aiofiles.open(file_path, "rb") as f:
                file_bytes = await f.read()

            mime_type = mimetypes.guess_type(file_path)[0]
            file_file_key = await self.send_file(file_bytes, "")
            return ActionResponse.success({"file_file_key": file_file_key, "mime_type": mime_type})

        @self.action(RuntimeToPluginAction.EMIT_EVENT)
        async def emit_event(data: dict[str, typing.Any]) -> ActionResponse:
            """Emit an event to the plugin.

            {
                "event_context": dict[str, typing.Any],
            }
            """

            event_name = data["event_context"]["event_name"]

            if getattr(events, event_name) is None:
                return ActionResponse.error(f"Event {event_name} not found")

            args = deepcopy(data["event_context"])

            args["plugin_runtime_handler"] = self

            event_context = EventContextProxy.model_validate(args)

            emitted: bool = False

            # check if the event is registered
            for component in self.plugin_container.components:
                if component.manifest.kind == EventListener.__kind__:
                    if component.component_instance is None:
                        return ActionResponse.error("Event listener is not initialized")

                    assert isinstance(component.component_instance, EventListener)

                    if (
                        event_context.event.__class__
                        not in component.component_instance.registered_handlers
                    ):
                        continue

                    for handler in component.component_instance.registered_handlers[
                        event_context.event.__class__
                    ]:
                        await handler(event_context)
                        emitted = True

                    break

            return ActionResponse.success(
                data={
                    "emitted": emitted,
                    "event_context": event_context.model_dump(),
                }
            )

        @self.action(RuntimeToPluginAction.CALL_TOOL)
        async def call_tool(data: dict[str, typing.Any]) -> ActionResponse:
            """Call a tool."""
            tool_name = data["tool_name"]
            tool_parameters = data["tool_parameters"]
            session = data["session"]
            query_id = data["query_id"]

            for component in self.plugin_container.components:
                if component.manifest.kind == Tool.__kind__:
                    if component.manifest.metadata.name != tool_name:
                        continue

                    if isinstance(component.component_instance, NoneComponent):
                        return ActionResponse.error("Tool is not initialized")

                    assert isinstance(component.component_instance, Tool)

                    tool_instance = component.component_instance

                    # 检查 call 方法是否接受 session 和 query_id 参数，如果接受则传入，否则只传 tool_parameters
                    import inspect

                    call_sig = inspect.signature(tool_instance.call)
                    params = call_sig.parameters

                    if "session" in params and "query_id" in params:
                        session = provider_session.Session.model_validate(session)
                        resp = await tool_instance.call(tool_parameters, session=session, query_id=query_id)
                    else:
                        resp = await tool_instance.call(tool_parameters)

                    return ActionResponse.success(
                        data={
                            "tool_response": resp,
                        }
                    )

            return ActionResponse.error(f"Tool {tool_name} not found")

        @self.action(RuntimeToPluginAction.EXECUTE_COMMAND)
        async def execute_command(
            data: dict[str, typing.Any],
        ) -> typing.AsyncGenerator[ActionResponse, None]:
            """Execute a command."""

            args = deepcopy(data["command_context"])
            args["plugin_runtime_handler"] = self
            command_context = ExecuteContextProxy.model_validate(args)

            for component in self.plugin_container.components:
                if component.manifest.kind == Command.__kind__:
                    if component.manifest.metadata.name != command_context.command:
                        continue

                    if isinstance(component.component_instance, NoneComponent):
                        yield ActionResponse.error("Command is not initialized")

                    command_instance = component.component_instance
                    assert isinstance(command_instance, Command)
                    async for return_value in command_instance._execute(
                        command_context
                    ):
                        yield ActionResponse.success(
                            data={
                                "command_response": return_value.model_dump(mode="json")
                            }
                        )
                    break
            else:
                yield ActionResponse.error(
                    f"Command {command_context.command} not found"
                )

        @self.action(RuntimeToPluginAction.RETRIEVE_KNOWLEDGE)
        async def retrieve_knowledge(data: dict[str, typing.Any]) -> ActionResponse:
            """Retrieve knowledge using a RAGEngine instance."""
            retriever_name = data["retriever_name"]
            retrieval_context = RetrievalContext.model_validate(data["retrieval_context"])

            rag_component = None
            for component in self.plugin_container.components:
                if component.manifest.kind == RAGEngine.__kind__:
                    # If retriever_name is empty, use the first found RAGEngine.
                    # Otherwise, find the specific named component.
                    if not retriever_name or component.manifest.metadata.name == retriever_name:
                        rag_component = component
                        break

            if rag_component is None:
                return ActionResponse.error(f"RAGEngine {retriever_name} not found")

            if isinstance(rag_component.component_instance, NoneComponent):
                return ActionResponse.error(f"RAGEngine {retriever_name} is not initialized")

            assert isinstance(rag_component.component_instance, RAGEngine)

            # Call retrieve method - RAGEngine returns RetrievalResponse
            response = await rag_component.component_instance.retrieve(retrieval_context)

            return ActionResponse.success(response.model_dump(mode="json"))

        @self.action(RuntimeToPluginAction.SHUTDOWN)
        async def shutdown(data: dict[str, typing.Any]) -> ActionResponse:
            """Handle shutdown request from runtime.

            In debug mode (when shutdown_callback is set), this will trigger reconnection.
            In production mode, this will just acknowledge the shutdown.
            """
            if self.shutdown_callback is not None:
                # In debug mode, trigger reconnection
                asyncio.create_task(self.shutdown_callback())

            return ActionResponse.success({})

        # ================= RAG Engine Actions =================

        def _find_rag_engine_component() -> ComponentContainer | None:
            """Find the RAGEngine component in the plugin."""
            for component in self.plugin_container.components:
                if component.manifest.kind == RAGEngine.__kind__:
                    return component
            return None

        def _get_rag_engine_or_error() -> tuple[RAGEngine | None, ActionResponse | None]:
            """Get RAGEngine singleton instance or error response.

            Returns:
                (rag_engine, None) if successful
                (None, error_response) if failed
            """
            rag_component = _find_rag_engine_component()
            if rag_component is None:
                return None, ActionResponse.error("RAGEngine component not found in this plugin")

            if isinstance(rag_component.component_instance, NoneComponent):
                return None, ActionResponse.error("RAGEngine component is not initialized")
            assert isinstance(rag_component.component_instance, RAGEngine)
            return rag_component.component_instance, None

        @self.action(RuntimeToPluginAction.INGEST_DOCUMENT)
        async def ingest_document(data: dict[str, typing.Any]) -> ActionResponse:
            """Ingest a document using the RAGEngine component."""
            context_data = data["context"]

            ingestion_context = IngestionContext.model_validate(context_data)
            rag_engine, error = _get_rag_engine_or_error()
            if error:
                return error

            result = await rag_engine.ingest(ingestion_context)

            return ActionResponse.success(result.model_dump(mode="json"))

        @self.action(RuntimeToPluginAction.DELETE_DOCUMENT)
        async def delete_document(data: dict[str, typing.Any]) -> ActionResponse:
            """Delete a document using the RAGEngine component."""
            kb_id = data["kb_id"]
            document_id = data["document_id"]

            rag_engine, error = _get_rag_engine_or_error()
            if error:
                return error

            success = await rag_engine.delete_document(kb_id, document_id)

            return ActionResponse.success({"success": success})

        @self.action(RuntimeToPluginAction.ON_KB_CREATE)
        async def on_kb_create(data: dict[str, typing.Any]) -> ActionResponse:
            """Notify RAGEngine about KB creation."""
            kb_id = data["kb_id"]
            config = data.get("config", {})

            rag_engine, error = _get_rag_engine_or_error()
            if error:
                return error

            await rag_engine.on_knowledge_base_create(kb_id, config)

            return ActionResponse.success({"success": True})

        @self.action(RuntimeToPluginAction.ON_KB_DELETE)
        async def on_kb_delete(data: dict[str, typing.Any]) -> ActionResponse:
            """Notify RAGEngine about KB deletion."""
            kb_id = data["kb_id"]

            rag_engine, error = _get_rag_engine_or_error()
            if error:
                return error

            await rag_engine.on_knowledge_base_delete(kb_id)

            return ActionResponse.success({"success": True})

        @self.action(RuntimeToPluginAction.GET_RAG_CAPABILITIES)
        async def get_rag_capabilities(data: dict[str, typing.Any]) -> ActionResponse:
            """Get RAG capabilities from the RAGEngine component."""
            rag_component = _find_rag_engine_component()
            if rag_component is None:
                return ActionResponse.error("RAGEngine component not found in this plugin")

            # Get capabilities from the class method (doesn't need instance)
            component_class = rag_component.manifest.get_python_component_class()
            if issubclass(component_class, RAGEngine):
                capabilities = component_class.get_capabilities()
            else:
                capabilities = []

            return ActionResponse.success({"capabilities": capabilities})

    async def register_plugin(self, prod_mode: bool = False) -> dict[str, typing.Any]:
        # Read PLUGIN_DEBUG_KEY from environment variable
        plugin_debug_key = os.environ.get("PLUGIN_DEBUG_KEY", "")

        resp = await self.call_action(
            PluginToRuntimeAction.REGISTER_PLUGIN,
            {
                "plugin_container": self.plugin_container.model_dump(),
                "prod_mode": prod_mode,
                "plugin_debug_key": plugin_debug_key,
            },
        )
        return resp

    async def get_plugin_container(self) -> dict[str, typing.Any]:
        """Get the current plugin container data."""
        return self.plugin_container.model_dump()


# {"action": "get_plugin_container", "data": {}, "seq_id": 1}
