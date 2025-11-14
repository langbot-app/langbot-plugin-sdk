from __future__ import annotations

import glob
import os
import shutil
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
import signal
import traceback
import logging
from langbot_plugin.utils.platform import get_platform
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
from langbot_plugin.entities.io.actions.enums import (
    RuntimeToLangBotAction,
    RuntimeToPluginAction,
)
from langbot_plugin.api.entities.builtin.command.context import (
    ExecuteContext,
    CommandReturn,
)
from langbot_plugin.runtime.settings import settings as runtime_settings
from langbot_plugin.runtime.helper import marketplace as marketplace_helper
from langbot_plugin.runtime.helper import pkgmgr as pkgmgr_helper

logger = logging.getLogger(__name__)


class PluginInstallSource(enum.Enum):
    """The source of plugin installation."""

    LOCAL = "local"
    GITHUB = "github"
    MARKETPLACE = "marketplace"

    DEBUG = "debug"


class PluginManager:
    """The manager for plugins."""

    context: context_module.RuntimeContext

    plugin_handlers: list[runtime_plugin_handler_cls.PluginConnectionHandler] = []

    plugins: list[runtime_plugin_container.PluginContainer] = []

    plugin_run_tasks: list[asyncio.Task] = []

    wait_for_control_connection: asyncio.Future[None] | None = None

    def __init__(self, context: context_module.RuntimeContext):
        self.context = context
        self.plugin_run_tasks = []
        self.wait_for_control_connection = None

    def get_plugin_path(self, plugin_author: str, plugin_name: str) -> str:
        return f"data/plugins/{plugin_author}__{plugin_name}"

    async def ensure_all_plugins_dependencies_installed(self):
        for plugin_path in glob.glob("data/plugins/*"):
            if not os.path.isdir(plugin_path):
                continue

            # install dependencies
            requirements_file = os.path.join(plugin_path, "requirements.txt")
            if os.path.exists(requirements_file):
                pkgmgr_helper.install_requirements(requirements_file)
                logger.info(f"Installed dependencies for plugin at {plugin_path}")

    async def launch_all_plugins(self):
        self.wait_for_control_connection = asyncio.Future()
        await self.wait_for_control_connection
        for plugin_path in glob.glob("data/plugins/*"):
            if not os.path.isdir(plugin_path):
                continue

            # launch plugin process
            task = self.launch_plugin(plugin_path)
            self.plugin_run_tasks.append(task)

        logger.info(f"launch all plugins: {len(self.plugin_run_tasks)}")
        await asyncio.gather(*self.plugin_run_tasks)

    async def launch_plugin(self, plugin_path: str):
        if get_platform() == 'win32':
            # Due to Windows's lack of supports for both stdio and subprocess:
            # See also: https://docs.python.org/zh-cn/3.13/library/asyncio-platforms.html
            # We have to launch plugin via cmd but communicate via ws.
            python_path = sys.executable
            process: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
                python_path,
                '-m', 'langbot_plugin.cli.__init__', 'run',
                '--prod',
                env={
                    "RUNTIME_WS_URL": f"ws://localhost:{self.context.ws_debug_port}/plugin/ws",
                    **os.environ.copy()
                },
                cwd=plugin_path,
            )
            
            # hold the process
            task = asyncio.create_task(process.wait())

            # the plugin will connect to the runtime via ws automatically

            await task
        else:
            python_path = sys.executable
            ctrl = stdio_client_controller.StdioClientController(
                command=python_path,
                args=["-m", "langbot_plugin.cli.__init__", "run", "-s"],
                env={},
                working_dir=plugin_path,
            )

            async def new_plugin_connection_callback(connection: Connection):
                handler = runtime_plugin_handler_cls.PluginConnectionHandler(
                    connection, self.context, stdio_process=ctrl.process
                )
                await self.add_plugin_handler(handler)

            try:
                await ctrl.run(new_plugin_connection_callback)
            except asyncio.CancelledError:
                logger.info(f"plugin process cancelled: {plugin_path}")
                return

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

    async def install_plugin_from_file(
        self, plugin_file: bytes
    ) -> tuple[str, str, str, str]:
        # read manifest.yaml file
        file_reader = io.BytesIO(plugin_file)
        manifest_file = zipfile.ZipFile(file_reader, "r")
        manifest_file_content = manifest_file.read("manifest.yaml")
        manifest = yaml.safe_load(manifest_file_content)

        # extract plugin name and author from manifest
        plugin_name = manifest["metadata"]["name"]
        plugin_author = manifest["metadata"]["author"]
        plugin_version = manifest["metadata"]["version"]

        # unzip to data/plugins/{plugin_author}__{plugin_name}
        plugin_path = self.get_plugin_path(plugin_author, plugin_name)

        # check if plugin already exists
        for plugin in self.plugins:
            if (
                plugin.manifest.metadata.author == plugin_author
                and plugin.manifest.metadata.name == plugin_name
            ):
                if plugin.manifest.metadata.version == plugin_version:
                    raise ValueError(
                        f"Plugin {plugin_author}/{plugin_name}:{plugin_version} already exists"
                    )
                elif plugin.debug:
                    raise ValueError(
                        f"Plugin {plugin_author}/{plugin_name}:{plugin_version} already exists, and it is a debugging plugin"
                    )
                else:
                    # shutdown old version
                    await self.shutdown_plugin(plugin)
                    # await self.remove_plugin_container(plugin)
                    # delete old version
                    shutil.rmtree(plugin_path)
                    break

        os.makedirs(plugin_path, exist_ok=True)
        manifest_file.extractall(plugin_path)

        return plugin_path, plugin_author, plugin_name, plugin_version

    async def install_plugin_from_marketplace(
        self, plugin_author: str, plugin_name: str, plugin_version: str
    ) -> tuple[str, str, str]:
        # download plugin zip file from marketplace
        plugin_zip_file = await marketplace_helper.download_plugin(
            plugin_author, plugin_name, plugin_version
        )
        return await self.install_plugin_from_file(plugin_zip_file)

    async def install_plugin(
        self, source: PluginInstallSource, install_info: dict[str, typing.Any]
    ) -> AsyncGenerator[dict[str, typing.Any], None]:
        yield {"current_action": "downloading plugin package"}

        if source == PluginInstallSource.LOCAL:
            # decode file
            plugin_file = install_info["plugin_file"]
            (
                plugin_path,
                plugin_author,
                plugin_name,
                plugin_version,
            ) = await self.install_plugin_from_file(plugin_file)
            del install_info["plugin_file"]
        elif source == PluginInstallSource.MARKETPLACE:
            (
                plugin_path,
                plugin_author,
                plugin_name,
                plugin_version,
            ) = await self.install_plugin_from_marketplace(
                install_info["plugin_author"],
                install_info["plugin_name"],
                install_info["plugin_version"],
            )
        elif source == PluginInstallSource.GITHUB:
            plugin_file = install_info["plugin_file"]
            (
                plugin_path,
                plugin_author,
                plugin_name,
                plugin_version,
            ) = await self.install_plugin_from_file(plugin_file)
            del install_info["plugin_file"]
        else:
            raise ValueError(f"Invalid source: {source}")

        # install deps
        logger.info("installing dependencies")
        yield {"current_action": "installing dependencies"}
        requirements_file = os.path.join(plugin_path, "requirements.txt")
        if os.path.exists(requirements_file):
            pkgmgr_helper.install_requirements(requirements_file)

        # initialize plugin settings
        yield {"current_action": "initializing plugin settings"}
        await self.context.control_handler.call_action(
            RuntimeToLangBotAction.INITIALIZE_PLUGIN_SETTINGS,
            {
                "plugin_author": plugin_author,
                "plugin_name": plugin_name,
                "install_source": source.value,
                "install_info": install_info
                if source != PluginInstallSource.LOCAL
                else {},
            },
        )

        # launch plugin
        yield {"current_action": "launching plugin"}
        task = self.launch_plugin(plugin_path)

        asyncio_task = asyncio.create_task(task)
        self.plugin_run_tasks.append(asyncio_task)

    async def register_plugin(
        self,
        handler: runtime_plugin_handler_cls.PluginConnectionHandler,
        container_data: dict[str, typing.Any],
        debug_plugin: bool = False,
    ):
        plugin_container = runtime_plugin_container.PluginContainer.from_dict(
            container_data
        )

        try:
            if not hasattr(self.context, "control_handler"):
                raise ValueError("Control handler not found")

            # if it's a debug plugin, we need to initialize the plugin settings first
            if debug_plugin:
                await self.context.control_handler.call_action(
                    RuntimeToLangBotAction.INITIALIZE_PLUGIN_SETTINGS,
                    {
                        "plugin_author": plugin_container.manifest.metadata.author,
                        "plugin_name": plugin_container.manifest.metadata.name,
                        "install_source": PluginInstallSource.DEBUG.value,
                        "install_info": {},
                    },
                )

            # get plugin settings from LangBot
            plugin_settings = await self.context.control_handler.call_action(
                RuntimeToLangBotAction.GET_PLUGIN_SETTINGS,
                {
                    "plugin_author": plugin_container.manifest.metadata.author,
                    "plugin_name": plugin_container.manifest.metadata.name,
                },
            )
        except Exception as e:
            raise ValueError(
                "Failed to get plugin settings, is LangBot connected?"
            ) from e

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
        plugin_container.install_info = plugin_settings["install_info"]

        plugin_container._runtime_plugin_handler = handler

        self.plugins.append(plugin_container)

    async def remove_plugin_container(
        self,
        plugin_container: runtime_plugin_container.PluginContainer,
    ):
        if plugin_container._runtime_plugin_handler is not None:
            await self.remove_plugin_handler(plugin_container._runtime_plugin_handler)

        if plugin_container in self.plugins:
            self.plugins.remove(plugin_container)

    async def restart_plugin(
        self,
        plugin_author: str,
        plugin_name: str,
    ):
        for plugin in self.plugins:
            if (
                plugin.manifest.metadata.author == plugin_author
                and plugin.manifest.metadata.name == plugin_name
            ):
                is_debugging = plugin.debug

                yield {"current_action": "shutting down plugin"}
                await self.shutdown_plugin(plugin)
                yield {"current_action": "removing plugin container"}
                await self.remove_plugin_container(plugin)
                if not is_debugging:
                    yield {"current_action": "launching plugin"}
                    task = self.launch_plugin(
                        self.get_plugin_path(plugin_author, plugin_name)
                    )
                    asyncio_task = asyncio.create_task(task)
                    self.plugin_run_tasks.append(asyncio_task)

                yield {"current_action": "plugin restarted"}
                break
        else:
            raise ValueError(f"Plugin {plugin_author}/{plugin_name} not found")

    async def delete_plugin(
        self,
        plugin_author: str,
        plugin_name: str,
    ):
        for plugin in self.plugins:
            if (
                plugin.manifest.metadata.author == plugin_author
                and plugin.manifest.metadata.name == plugin_name
            ):
                if plugin.debug:
                    raise ValueError(
                        f"Plugin {plugin_author}/{plugin_name} is a debugging plugin"
                    )
                else:
                    yield {"current_action": "shutting down plugin"}
                    await self.shutdown_plugin(plugin)
                    yield {"current_action": "removing plugin container"}
                    await self.remove_plugin_container(plugin)
                    yield {"current_action": "deleting plugin files"}
                    shutil.rmtree(self.get_plugin_path(plugin_author, plugin_name))
                    yield {"current_action": "plugin deleted"}
                    break
        else:
            raise ValueError(f"Plugin {plugin_author}/{plugin_name} not found")

    async def upgrade_plugin(
        self,
        plugin_author: str,
        plugin_name: str,
    ):
        for plugin in self.plugins:
            if (
                plugin.manifest.metadata.author == plugin_author
                and plugin.manifest.metadata.name == plugin_name
            ):
                if plugin.debug:
                    raise ValueError(
                        f"Plugin {plugin_author}/{plugin_name} is a debugging plugin"
                    )
                elif plugin.install_source != PluginInstallSource.MARKETPLACE.value:
                    raise ValueError(
                        f"Plugin {plugin_author}/{plugin_name} is not installed from marketplace"
                    )
                else:
                    yield {"current_action": "checking for latest version"}
                    latest_version = (
                        await marketplace_helper.get_plugin_info(
                            plugin_author, plugin_name
                        )
                    ).latest_version
                    if latest_version != plugin.manifest.metadata.version:
                        async for resp in self.install_plugin(
                            PluginInstallSource.MARKETPLACE,
                            {
                                "plugin_author": plugin_author,
                                "plugin_name": plugin_name,
                                "plugin_version": latest_version,
                            },
                        ):
                            yield resp
                        yield {"current_action": "plugin upgraded"}
                        break
                    else:
                        yield {"current_action": "plugin is up to date"}
                        break
        else:
            raise ValueError(f"Plugin {plugin_author}/{plugin_name} not found")

    async def shutdown_all_plugins(self):
        for plugin in self.plugins:
            await self.shutdown_plugin(plugin)

    async def shutdown_plugin(
        self,
        plugin_container: runtime_plugin_container.PluginContainer,
    ):
        await plugin_container._runtime_plugin_handler.conn.close()
        await self.remove_plugin_container(plugin_container)
        if plugin_container._runtime_plugin_handler.stdio_process is not None:
            plugin_container._runtime_plugin_handler.stdio_process.kill()

            if (
                plugin_container._runtime_plugin_handler.stdio_process.returncode
                is None
            ):
                await asyncio.wait_for(
                    plugin_container._runtime_plugin_handler.stdio_process.wait(),
                    timeout=2,
                )
            logger.info(
                f"plugin process terminated: {plugin_container.manifest.metadata.author}/{plugin_container.manifest.metadata.name}:{plugin_container.manifest.metadata.version}"
            )
        else:
            logger.debug(
                f"plugin process is none: {plugin_container.manifest.metadata.author}/{plugin_container.manifest.metadata.name}:{plugin_container.manifest.metadata.version}"
            )

    async def emit_event(
        self, event_context: EventContext, include_plugins: list[str] | None = None
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

            # Filter by include_plugins if specified (pipeline-specific filtering)
            if include_plugins is not None:
                plugin_id = f"{plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}"
                if plugin_id not in include_plugins:
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

        return emitted_plugins, event_context

    async def get_plugin_icon(
        self, plugin_author: str, plugin_name: str
    ) -> tuple[bytes, str]:
        for plugin in self.plugins:
            if (
                plugin.manifest.metadata.author == plugin_author
                and plugin.manifest.metadata.name == plugin_name
            ):
                resp = await plugin._runtime_plugin_handler.get_plugin_icon()

                icon_file_key = resp["plugin_icon_file_key"]
                icon_bytes = await plugin._runtime_plugin_handler.read_local_file(icon_file_key)
                await plugin._runtime_plugin_handler.delete_local_file(icon_file_key)
                return icon_bytes, resp["mime_type"]
        return b"", ""

    async def list_tools(self, include_plugins: list[str] | None = None) -> list[ComponentManifest]:
        tools: list[ComponentManifest] = []

        for plugin in self.plugins:
            # Filter by include_plugins if specified
            if include_plugins is not None:
                plugin_id = f"{plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}"
                if plugin_id not in include_plugins:
                    continue

            for component in plugin.components:
                if component.manifest.kind == Tool.__kind__:
                    tools.append(component.manifest)

        return tools

    async def call_tool(
        self, tool_name: str, tool_parameters: dict[str, typing.Any], include_plugins: list[str] | None = None
    ) -> dict[str, typing.Any]:
        for plugin in self.plugins:
            # Filter by include_plugins if specified
            if include_plugins is not None:
                plugin_id = f"{plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}"
                if plugin_id not in include_plugins:
                    continue

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

    async def list_commands(self, include_plugins: list[str] | None = None) -> list[ComponentManifest]:
        commands: list[ComponentManifest] = []

        for plugin in self.plugins:
            # Filter by include_plugins if specified
            if include_plugins is not None:
                plugin_id = f"{plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}"
                if plugin_id not in include_plugins:
                    continue

            for component in plugin.components:
                if component.manifest.kind == Command.__kind__:
                    commands.append(component.manifest)

        return commands

    async def execute_command(
        self, command_context: ExecuteContext, include_plugins: list[str] | None = None
    ) -> typing.AsyncGenerator[CommandReturn, None]:
        for plugin in self.plugins:
            # Filter by include_plugins if specified
            if include_plugins is not None:
                plugin_id = f"{plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}"
                if plugin_id not in include_plugins:
                    continue

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
