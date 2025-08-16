from __future__ import annotations

import glob
import os
import typing
from typing import AsyncGenerator
import asyncio
import io
import enum
import sys
import zipfile
import yaml
import base64
import httpx
from langbot_plugin.runtime.io.connection import Connection
from langbot_plugin.runtime.io.controllers.stdio import (
    client as stdio_client_controller,
)
from langbot_plugin.runtime.plugin import container as runtime_plugin_container
from langbot_plugin.runtime.io.handlers import plugin as runtime_plugin_handler_cls
from langbot_plugin.runtime import context as context_module
from langbot_plugin.api.entities.context import EventContext
from langbot_plugin.api.definition.components.manifest import ComponentManifest
from langbot_plugin.api.definition.components.tool.tool import Tool
from langbot_plugin.api.definition.components.command.command import Command
from langbot_plugin.entities.io.actions.enums import RuntimeToLangBotAction
from langbot_plugin.api.entities.builtin.command.context import (
    ExecuteContext,
    CommandReturn,
)
from langbot_plugin.runtime.settings import settings as runtime_settings


class PluginInstallSource(enum.Enum):
    """The source of plugin installation."""
    LOCAL = "local"
    GITHUB = "github"
    MARKETPLACE = "marketplace"


class PluginManager:
    """The manager for plugins."""

    context: context_module.RuntimeContext

    plugin_handlers: list[runtime_plugin_handler_cls.PluginConnectionHandler] = []

    plugins: list[runtime_plugin_container.PluginContainer] = []

    plugin_run_tasks: list[asyncio.Task] = []

    def __init__(self, context: context_module.RuntimeContext):
        self.context = context
        self.plugin_run_tasks = []

    async def launch_all_plugins(self):
        await asyncio.sleep(10)
        for plugin_path in glob.glob("data/plugins/*"):
            if not os.path.isdir(plugin_path):
                continue

            # launch plugin process
            task = self.launch_plugin(plugin_path)
            self.plugin_run_tasks.append(task)

        await asyncio.gather(*self.plugin_run_tasks)

    async def launch_plugin(self, plugin_path: str):
        python_path = sys.executable
        ctrl = stdio_client_controller.StdioClientController(
            command=python_path,
            args=["-m", "langbot_plugin.cli.__init__", "run", "-s"],
            env={},
            working_dir=plugin_path,
        )

        async def new_plugin_connection_callback(connection: Connection):
            handler = runtime_plugin_handler_cls.PluginConnectionHandler(
                connection, self.context
            )
            await self.add_plugin_handler(handler)

        await ctrl.run(new_plugin_connection_callback)

    async def add_plugin_handler(
        self,
        handler: runtime_plugin_handler_cls.PluginConnectionHandler,
    ):
        self.plugin_handlers.append(handler)

        await handler.run()

    async def remove_plugin_handler(
        self,
        handler: runtime_plugin_handler_cls.PluginConnectionHandler,
    ):
        if handler not in self.plugin_handlers:
            return

        self.plugin_handlers.remove(handler)

    async def install_plugin_from_file(self, plugin_file: bytes) -> tuple[str, str, str]:
        # read manifest.yaml file
        file_reader = io.BytesIO(plugin_file)
        manifest_file = zipfile.ZipFile(file_reader, "r")
        manifest_file_content = manifest_file.read("manifest.yaml")
        manifest = yaml.safe_load(manifest_file_content)

        # extract plugin name and author from manifest
        plugin_name = manifest["metadata"]["name"]
        plugin_author = manifest["metadata"]["author"]

        # check if plugin already exists
        for plugin in self.plugins:
            if plugin.manifest.metadata.author == plugin_author and plugin.manifest.metadata.name == plugin_name:
                raise ValueError(f"Plugin {plugin_author}/{plugin_name} already exists")

        # unzip to data/plugins/{plugin_author}__{plugin_name}
        plugin_path = f"data/plugins/{plugin_author}__{plugin_name}"
        os.makedirs(plugin_path, exist_ok=True)
        manifest_file.extractall(plugin_path)

        return plugin_path, plugin_author, plugin_name

    async def install_plugin_from_marketplace(self, plugin_author: str, plugin_name: str, plugin_version: str) -> tuple[str, str, str]:
        # download plugin zip file from marketplace
        cloud_service_url = runtime_settings.cloud_service_url
        # /api/v1/marketplace/plugins/download/{plugin_id}/{plugin_version}
        url = f"{cloud_service_url}/api/v1/marketplace/plugins/download/{plugin_author}/{plugin_name}/{plugin_version}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            plugin_zip_file = response.content
            plugin_path, plugin_author, plugin_name = await self.install_plugin_from_file(plugin_zip_file)
            return plugin_path, plugin_author, plugin_name

    async def install_plugin(self, source: PluginInstallSource, install_info: dict[str, typing.Any]) -> AsyncGenerator[dict[str, typing.Any], None]:
        yield {"current_action": "downloading plugin package"}
        
        if source == PluginInstallSource.LOCAL:
            # decode file base64
            plugin_file = base64.b64decode(install_info["plugin_file"])
            plugin_path, plugin_author, plugin_name = await self.install_plugin_from_file(plugin_file)
        elif source == PluginInstallSource.MARKETPLACE:
            plugin_path, plugin_author, plugin_name = await self.install_plugin_from_marketplace(install_info["plugin_author"], install_info["plugin_name"], install_info["plugin_version"])
            
        else:
            raise ValueError(f"Invalid source: {source}")

        # install deps
        yield {"current_action": "installing dependencies"}

        # initialize plugin settings
        plugin_settings = await self.context.control_handler.call_action(
            RuntimeToLangBotAction.INITIALIZE_PLUGIN_SETTINGS,
            {
                "plugin_author": plugin_author,
                "plugin_name": plugin_name,
                "install_source": source.value,
            },
        )

        # launch plugin
        task = self.launch_plugin(plugin_path)
        yield {"current_action": "launching plugin"}
        
        asyncio_task = asyncio.create_task(task)
        self.plugin_run_tasks.append(asyncio_task)

    async def register_plugin(
        self,
        handler: runtime_plugin_handler_cls.PluginConnectionHandler,
        container_data: dict[str, typing.Any],
    ):

        plugin_container = runtime_plugin_container.PluginContainer.from_dict(
            container_data
        )

        # get plugin settings from LangBot
        plugin_settings = await self.context.control_handler.call_action(
            RuntimeToLangBotAction.GET_PLUGIN_SETTINGS,
            {
                "plugin_author": plugin_container.manifest.metadata.author,
                "plugin_name": plugin_container.manifest.metadata.name,
            },
        )

        print("initialize plugin with plugin_settings", plugin_settings)

        # initialize plugin
        await handler.initialize_plugin(plugin_settings)

        # get plugin container from plugin
        plugin_container = runtime_plugin_container.PluginContainer.from_dict(
            await handler.get_plugin_container()
        )

        if handler.debug_plugin:  # due to python's fucking typing system, we need to explicitly set the debug flag
            plugin_container.debug = True
        else:
            plugin_container.debug = False

        plugin_container.install_source = plugin_settings["install_source"]

        plugin_container._runtime_plugin_handler = handler

        print("register_plugin", plugin_container)

        self.plugins.append(plugin_container)

    async def remove_plugin(
        self,
        plugin_container: runtime_plugin_container.PluginContainer,
    ):
        if plugin_container._runtime_plugin_handler is not None:
            await self.remove_plugin_handler(plugin_container._runtime_plugin_handler)

        self.plugins.remove(plugin_container)

    async def emit_event(
        self, event_context: EventContext
    ) -> tuple[list[runtime_plugin_container.PluginContainer], EventContext]:
        emitted_plugins: list[runtime_plugin_container.PluginContainer] = []

        for plugin in self.plugins:
            if (
                plugin.status
                != runtime_plugin_container.RuntimeContainerStatus.INITIALIZED
            ):
                continue

            if not plugin.enabled:
                continue

            if plugin._runtime_plugin_handler is None:
                continue

            resp = await plugin._runtime_plugin_handler.emit_event(
                event_context.model_dump()
            )

            if resp["emitted"]:
                emitted_plugins.append(plugin)

            emitted_plugins.append(plugin)

            event_context = EventContext.model_validate(resp["event_context"])

            if event_context.is_prevented_postorder():
                break

        for key in event_context.return_value.keys():
            if hasattr(event_context.event, key):
                setattr(event_context.event, key, event_context.get_return_value(key))

        return emitted_plugins, event_context

    async def list_tools(self) -> list[ComponentManifest]:
        tools: list[ComponentManifest] = []

        for plugin in self.plugins:
            for component in plugin.components:
                if component.manifest.kind == Tool.__kind__:
                    tools.append(component.manifest)

        return tools

    async def call_tool(
        self, tool_name: str, tool_parameters: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        for plugin in self.plugins:
            for component in plugin.components:
                if component.manifest.kind == Tool.__kind__:
                    if component.manifest.metadata.name != tool_name:
                        continue

                    if plugin._runtime_plugin_handler is None:
                        continue

                    resp = await plugin._runtime_plugin_handler.call_tool(
                        tool_name, tool_parameters
                    )

                    return resp["tool_response"]

        return {}

    async def list_commands(self) -> list[ComponentManifest]:
        commands: list[ComponentManifest] = []

        for plugin in self.plugins:
            for component in plugin.components:
                if component.manifest.kind == Command.__kind__:
                    commands.append(component.manifest)

        return commands

    async def execute_command(
        self, command_context: ExecuteContext
    ) -> typing.AsyncGenerator[CommandReturn, None]:
        for plugin in self.plugins:
            for component in plugin.components:
                if component.manifest.kind == Command.__kind__:
                    if component.manifest.metadata.name != command_context.command:
                        continue

                    if plugin._runtime_plugin_handler is None:
                        continue

                    async for resp in plugin._runtime_plugin_handler.execute_command(
                        command_context.model_dump(mode="json")
                    ):
                        yield CommandReturn.model_validate(resp["command_response"])

                    break
