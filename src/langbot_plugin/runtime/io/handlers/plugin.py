# handle connection to/from plugin
from __future__ import annotations

from typing import Any, AsyncGenerator
import logging

from langbot_plugin.runtime.io import handler, connection
from langbot_plugin.entities.io.actions.enums import (
    PluginToRuntimeAction,
    RuntimeToPluginAction,
    RuntimeToLangBotAction,
)
from langbot_plugin.runtime import context as context_module
import asyncio
from langbot_plugin.runtime.settings import settings as runtime_settings

logger = logging.getLogger(__name__)

# Timeout for long-running operations like command execution and tool calls (3 minutes)
LONG_RUNNING_OPERATION_TIMEOUT = 180.0


class PluginConnectionHandler(handler.Handler):
    """The handler for plugin connection."""

    context: context_module.RuntimeContext

    debug_plugin: bool = False
    """If this plugin is a debug plugin."""

    stdio_process: asyncio.subprocess.Process | None = None
    """The stdio process of the plugin."""
    
    subprocess_on_windows_task: asyncio.Task | None = None
    """The task for the subprocess on Windows."""

    def __init__(
        self,
        connection: connection.Connection,
        context: context_module.RuntimeContext,
        stdio_process: asyncio.subprocess.Process | None = None,
        debug_plugin: bool = False,
    ):
        async def disconnect_callback(hdl: handler.Handler):
            logger.debug("disconnect_callback")
            for plugin_container in self.context.plugin_mgr.plugins:
                if plugin_container._runtime_plugin_handler == self:
                    logger.info(
                        f"Removing plugin {plugin_container.manifest.metadata.name} due to disconnect"
                    )
                    await self.context.plugin_mgr.remove_plugin_container(
                        plugin_container
                    )
                    break

        super().__init__(connection, disconnect_callback)
        self.context = context
        self.name = "FromPlugin"
        self.debug_plugin = debug_plugin
        self.stdio_process = stdio_process

        @self.action(PluginToRuntimeAction.REGISTER_PLUGIN)
        async def register_plugin(data: dict[str, Any]) -> handler.ActionResponse:

            if "prod_mode" in data and data["prod_mode"]:
                self.debug_plugin = False

            # Verify PLUGIN_DEBUG_KEY if it's set in runtime settings
            if runtime_settings.plugin_debug_key:
                # Get the debug key from plugin data
                plugin_debug_key = data.get("plugin_debug_key", "")

                if plugin_debug_key != runtime_settings.plugin_debug_key:
                    logger.warning(f"Plugin debug key verification failed. Expected key does not match.")
                    return handler.ActionResponse.error("Plugin debug key verification failed")

            await self.context.plugin_mgr.register_plugin(
                self, data["plugin_container"],
                self.debug_plugin
            )
            return handler.ActionResponse.success({})

        @self.action(PluginToRuntimeAction.REPLY_MESSAGE)
        async def reply_message(data: dict[str, Any]) -> handler.ActionResponse:
            result = await self.context.control_handler.call_action(
                PluginToRuntimeAction.REPLY_MESSAGE,
                {
                    **data,
                },
                timeout=180,
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.GET_BOT_UUID)
        async def get_bot_uuid(data: dict[str, Any]) -> handler.ActionResponse:
            result = await self.context.control_handler.call_action(
                PluginToRuntimeAction.GET_BOT_UUID,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.SET_QUERY_VAR)
        async def set_query_var(data: dict[str, Any]) -> handler.ActionResponse:
            result = await self.context.control_handler.call_action(
                PluginToRuntimeAction.SET_QUERY_VAR,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.GET_QUERY_VAR)
        async def get_query_var(data: dict[str, Any]) -> handler.ActionResponse:
            result = await self.context.control_handler.call_action(
                PluginToRuntimeAction.GET_QUERY_VAR,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.GET_QUERY_VARS)
        async def get_query_vars(data: dict[str, Any]) -> handler.ActionResponse:
            result = await self.context.control_handler.call_action(
                PluginToRuntimeAction.GET_QUERY_VARS,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.CREATE_NEW_CONVERSATION)
        async def create_new_conversation(
            data: dict[str, Any],
        ) -> handler.ActionResponse:
            result = await self.context.control_handler.call_action(
                PluginToRuntimeAction.CREATE_NEW_CONVERSATION,
                {
                    "query_id": data["query_id"],
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.GET_LANGBOT_VERSION)
        async def get_langbot_version(data: dict[str, Any]) -> handler.ActionResponse:
            result = await self.context.control_handler.call_action(
                PluginToRuntimeAction.GET_LANGBOT_VERSION,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.GET_BOTS)
        async def get_bots(data: dict[str, Any]) -> handler.ActionResponse:
            result = await self.context.control_handler.call_action(
                PluginToRuntimeAction.GET_BOTS,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.GET_BOT_INFO)
        async def get_bot_info(data: dict[str, Any]) -> handler.ActionResponse:
            result = await self.context.control_handler.call_action(
                PluginToRuntimeAction.GET_BOT_INFO,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.SEND_MESSAGE)
        async def send_message(data: dict[str, Any]) -> handler.ActionResponse:
            result = await self.context.control_handler.call_action(
                PluginToRuntimeAction.SEND_MESSAGE,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.GET_LLM_MODELS)
        async def get_llm_models(data: dict[str, Any]) -> handler.ActionResponse:
            result = await self.context.control_handler.call_action(
                PluginToRuntimeAction.GET_LLM_MODELS,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        # @self.action(PluginToRuntimeAction.GET_LLM_MODEL_INFO)
        # async def get_llm_model_info(data: dict[str, Any]) -> handler.ActionResponse:
        #     result = await self.context.control_handler.call_action(
        #         PluginToRuntimeAction.GET_LLM_MODEL_INFO,
        #         {
        #             **data,
        #         },
        #     )
        #     return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.INVOKE_LLM)
        async def invoke_llm(data: dict[str, Any]) -> handler.ActionResponse:
            result = await self.context.control_handler.call_action(
                PluginToRuntimeAction.INVOKE_LLM,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.SET_PLUGIN_STORAGE)
        async def set_plugin_storage(data: dict[str, Any]) -> handler.ActionResponse:
            data["owner_type"] = "plugin"

            for plugin_container in self.context.plugin_mgr.plugins:
                if plugin_container._runtime_plugin_handler == self:
                    data["owner"] = (
                        f"{plugin_container.manifest.metadata.author}/{plugin_container.manifest.metadata.name}"
                    )
                    break

            result = await self.context.control_handler.call_action(
                RuntimeToLangBotAction.SET_BINARY_STORAGE,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.GET_PLUGIN_STORAGE)
        async def get_plugin_storage(data: dict[str, Any]) -> handler.ActionResponse:
            data["owner_type"] = "plugin"

            for plugin_container in self.context.plugin_mgr.plugins:
                if plugin_container._runtime_plugin_handler == self:
                    data["owner"] = (
                        f"{plugin_container.manifest.metadata.author}/{plugin_container.manifest.metadata.name}"
                    )
                    break

            result = await self.context.control_handler.call_action(
                RuntimeToLangBotAction.GET_BINARY_STORAGE,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.GET_PLUGIN_STORAGE_KEYS)
        async def get_plugin_storage_keys(
            data: dict[str, Any],
        ) -> handler.ActionResponse:
            data["owner_type"] = "plugin"

            for plugin_container in self.context.plugin_mgr.plugins:
                if plugin_container._runtime_plugin_handler == self:
                    data["owner"] = (
                        f"{plugin_container.manifest.metadata.author}/{plugin_container.manifest.metadata.name}"
                    )
                    break

            result = await self.context.control_handler.call_action(
                RuntimeToLangBotAction.GET_BINARY_STORAGE_KEYS,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.DELETE_PLUGIN_STORAGE)
        async def delete_plugin_storage(data: dict[str, Any]) -> handler.ActionResponse:
            data["owner_type"] = "plugin"

            for plugin_container in self.context.plugin_mgr.plugins:
                if plugin_container._runtime_plugin_handler == self:
                    data["owner"] = (
                        f"{plugin_container.manifest.metadata.author}/{plugin_container.manifest.metadata.name}"
                    )
                    break

            result = await self.context.control_handler.call_action(
                RuntimeToLangBotAction.DELETE_BINARY_STORAGE,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.SET_WORKSPACE_STORAGE)
        async def set_workspace_storage(data: dict[str, Any]) -> handler.ActionResponse:
            data["owner_type"] = "workspace"
            data["owner"] = "default"

            result = await self.context.control_handler.call_action(
                RuntimeToLangBotAction.SET_BINARY_STORAGE,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.GET_WORKSPACE_STORAGE)
        async def get_workspace_storage(data: dict[str, Any]) -> handler.ActionResponse:
            data["owner_type"] = "workspace"
            data["owner"] = "default"

            result = await self.context.control_handler.call_action(
                RuntimeToLangBotAction.GET_BINARY_STORAGE,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.GET_WORKSPACE_STORAGE_KEYS)
        async def get_workspace_storage_keys(
            data: dict[str, Any],
        ) -> handler.ActionResponse:
            data["owner_type"] = "workspace"
            data["owner"] = "default"

            result = await self.context.control_handler.call_action(
                RuntimeToLangBotAction.GET_BINARY_STORAGE_KEYS,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.DELETE_WORKSPACE_STORAGE)
        async def delete_workspace_storage(
            data: dict[str, Any],
        ) -> handler.ActionResponse:
            data["owner_type"] = "workspace"
            data["owner"] = "default"

            result = await self.context.control_handler.call_action(
                RuntimeToLangBotAction.DELETE_BINARY_STORAGE,
                {
                    **data,
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.GET_CONFIG_FILE)
        async def get_config_file(data: dict[str, Any]) -> handler.ActionResponse:
            """Get a config file by file key"""
            # Forward the request to LangBot
            result = await self.context.control_handler.call_action(
                RuntimeToLangBotAction.GET_CONFIG_FILE,
                {
                    "file_key": data["file_key"],
                },
            )
            return handler.ActionResponse.success(result)

        @self.action(PluginToRuntimeAction.LIST_COMMANDS)
        async def list_commands(data: dict[str, Any]) -> handler.ActionResponse:
            commands = await self.context.plugin_mgr.list_commands()
            return handler.ActionResponse.success(
                {"commands": [command.model_dump() for command in commands]}
            )

        @self.action(PluginToRuntimeAction.LIST_TOOLS)
        async def list_tools(data: dict[str, Any]) -> handler.ActionResponse:
            tools = await self.context.plugin_mgr.list_tools()
            return handler.ActionResponse.success(
                {"tools": [tool.model_dump() for tool in tools]}
            )

        @self.action(PluginToRuntimeAction.LIST_PLUGINS_MANIFEST)
        async def list_plugins_manifest(data: dict[str, Any]) -> handler.ActionResponse:
            return handler.ActionResponse.success(
                {
                    "plugins": [
                        plugin.model_dump()["manifest"]
                        for plugin in self.context.plugin_mgr.plugins
                    ]
                }
            )

    async def initialize_plugin(
        self, plugin_settings: dict[str, Any]
    ) -> dict[str, Any]:
        resp = await self.call_action(
            RuntimeToPluginAction.INITIALIZE_PLUGIN,
            {"plugin_settings": plugin_settings},
        )

        return resp

    async def get_plugin_container(self) -> dict[str, Any]:
        resp = await self.call_action(RuntimeToPluginAction.GET_PLUGIN_CONTAINER, {})

        return resp

    async def get_plugin_icon(self) -> dict[str, Any]:
        resp = await self.call_action(RuntimeToPluginAction.GET_PLUGIN_ICON, {})
        return resp
    
    async def get_plugin_readme(self, language: str) -> dict[str, Any]:
        resp = await self.call_action(RuntimeToPluginAction.GET_PLUGIN_README, {"language": language})
        return resp

    async def get_plugin_assets_file(self, file_key: str) -> dict[str, Any]:
        resp = await self.call_action(RuntimeToPluginAction.GET_PLUGIN_ASSETS_FILE, {"file_key": file_key})
        return resp

    async def emit_event(self, event_context: dict[str, Any]) -> dict[str, Any]:
        resp = await self.call_action(
            RuntimeToPluginAction.EMIT_EVENT, {"event_context": event_context},
            timeout=LONG_RUNNING_OPERATION_TIMEOUT
        )

        return resp

    async def call_tool(
        self, tool_name: str, tool_parameters: dict[str, Any], session: dict[str, Any], query_id: int
    ) -> dict[str, Any]:
        resp = await self.call_action(
            RuntimeToPluginAction.CALL_TOOL,
            {"tool_name": tool_name, "tool_parameters": tool_parameters, "session": session, "query_id": query_id},
            timeout=LONG_RUNNING_OPERATION_TIMEOUT
        )

        return resp

    async def execute_command(
        self, command_context: dict[str, Any]
    ) -> AsyncGenerator[dict[str, Any], None]:
        gen = self.call_action_generator(
            RuntimeToPluginAction.EXECUTE_COMMAND, {"command_context": command_context},
            timeout=LONG_RUNNING_OPERATION_TIMEOUT
        )

        async for resp in gen:
            yield resp

    async def retrieve_knowledge(
        self, retriever_name: str, instance_id: str, retrieval_context: dict[str, Any]
    ) -> dict[str, Any]:
        resp = await self.call_action(
            RuntimeToPluginAction.RETRIEVE_KNOWLEDGE,
            {"retriever_name": retriever_name, "instance_id": instance_id, "retrieval_context": retrieval_context},
        )
        return resp

    # Polymorphic component methods (generic)
    async def create_polymorphic_component_instance(
        self, instance_id: str, component_kind: str, component_name: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a polymorphic component instance (generic method for any polymorphic component)."""
        resp = await self.call_action(
            RuntimeToPluginAction.CREATE_POLYMORPHIC_COMPONENT_INSTANCE,
            {
                "instance_id": instance_id,
                "component_kind": component_kind,
                "component_name": component_name,
                "config": config
            },
        )
        return resp

    async def delete_polymorphic_component_instance(
        self, instance_id: str, component_kind: str, component_name: str
    ) -> dict[str, Any]:
        """Delete a polymorphic component instance (generic method for any polymorphic component)."""
        resp = await self.call_action(
            RuntimeToPluginAction.DELETE_POLYMORPHIC_COMPONENT_INSTANCE,
            {
                "instance_id": instance_id,
                "component_kind": component_kind,
                "component_name": component_name
            },
        )
        return resp

    async def sync_polymorphic_component_instances(
        self, required_instances: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Sync polymorphic component instances for this plugin.

        Sends the complete list of required instances to the plugin process,
        which will handle creation and deletion internally.
        """
        resp = await self.call_action(
            RuntimeToPluginAction.SYNC_POLYMORPHIC_COMPONENT_INSTANCES,
            {"required_instances": required_instances},
        )
        return resp

    async def shutdown_plugin(self) -> dict[str, Any]:
        """Send shutdown notification to the plugin.

        For debug plugins, this will trigger reconnection.
        For production plugins, this is just a notification before shutdown.
        """
        resp = await self.call_action(
            RuntimeToPluginAction.SHUTDOWN,
            {},
        )
        return resp
