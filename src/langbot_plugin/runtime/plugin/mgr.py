from __future__ import annotations

import glob
import os
import shutil
import typing
from typing import AsyncGenerator
import asyncio
import io
import enum
import time
import zipfile
import yaml
import logging
import contextlib
import uuid
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
from langbot_plugin.api.definition.components.knowledge_engine.engine import (
    KnowledgeEngine,
)
from langbot_plugin.api.definition.components.parser.parser import Parser
from langbot_plugin.entities.io.actions.enums import (
    RuntimeToLangBotAction,
)
from langbot_plugin.api.entities.builtin.command.context import (
    ExecuteContext,
    CommandReturn,
)
from langbot_plugin.runtime.helper import marketplace as marketplace_helper
from langbot_plugin.runtime.helper import pkgmgr as pkgmgr_helper
from langbot_plugin.entities.io.errors import (
    DependencyInstallError,
    DependencyVerificationError,
)

logger = logging.getLogger(__name__)

_PLUGIN_RESTART_INITIAL_DELAY_SEC = 1.0
_PLUGIN_RESTART_MAX_DELAY_SEC = 60.0
_PLUGIN_STABLE_WINDOW_SEC = 60.0
_PLUGIN_READY_TIMEOUT_SEC = 30.0


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
        self.plugin_handlers = []
        self.plugins = []
        self.plugin_run_tasks = []
        self.wait_for_control_connection = None
        self._control_connection_ready = asyncio.Event()
        self._plugin_supervisors: dict[str, asyncio.Task[None]] = {}
        self._desired_plugin_paths: set[str] = set()
        self._shutting_down = False
        self._dependency_errors: dict[str, str] = {}

    def get_plugin_path(self, plugin_author: str, plugin_name: str) -> str:
        return f"data/plugins/{plugin_author}__{plugin_name}"

    def find_plugin(
        self, plugin_author: str, plugin_name: str
    ) -> runtime_plugin_container.PluginContainer | None:
        """Find a plugin by author and name.

        Args:
            plugin_author: The plugin author.
            plugin_name: The plugin name.

        Returns:
            The plugin container if found, otherwise None.
        """
        for plugin in self.plugins:
            if (
                plugin.manifest.metadata.author == plugin_author
                and plugin.manifest.metadata.name == plugin_name
            ):
                return plugin
        return None

    async def notify_plugin_diagnostic(self, diagnostic: dict[str, typing.Any]) -> None:
        """Best-effort route a host-side diagnostic to a plugin process."""
        plugin_ref = diagnostic.get("plugin")
        if not isinstance(plugin_ref, dict):
            logger.warning(
                "Plugin diagnostic has no target plugin: "
                f"{_format_plugin_diagnostic(diagnostic)}"
            )
            return

        plugin_author = plugin_ref.get("author") or plugin_ref.get("plugin_author")
        plugin_name = plugin_ref.get("name") or plugin_ref.get("plugin_name")
        if not plugin_author or not plugin_name:
            logger.warning(
                "Plugin diagnostic target is incomplete: "
                f"{_format_plugin_diagnostic(diagnostic)}"
            )
            return

        plugin = self.find_plugin(str(plugin_author), str(plugin_name))
        plugin_id = f"{plugin_author}/{plugin_name}"
        if plugin is None:
            logger.warning(
                f"Plugin diagnostic target not found ({plugin_id}): "
                f"{_format_plugin_diagnostic(diagnostic)}"
            )
            return

        plugin_handler = plugin._runtime_plugin_handler
        if plugin_handler is None:
            logger.warning(
                f"Plugin diagnostic target is not connected ({plugin_id}): "
                f"{_format_plugin_diagnostic(diagnostic)}"
            )
            return

        log_buffer = getattr(plugin_handler, "log_buffer", None)
        plugin_diagnostic = _to_plugin_diagnostic(diagnostic)
        has_log_reader = bool(getattr(log_buffer, "has_active_reader", False))
        if (
            log_buffer is not None
            and not has_log_reader
            and hasattr(log_buffer, "add_entry")
        ):
            try:
                log_buffer.add_entry(
                    str(diagnostic.get("level", "ERROR")),
                    _format_plugin_diagnostic(diagnostic),
                )
            except Exception as e:  # noqa: BLE001 - diagnostics must stay best-effort
                logger.debug(f"Failed to append plugin diagnostic log buffer: {e}")

        try:
            await plugin_handler.notify_plugin_diagnostic(plugin_diagnostic)
        except Exception as e:  # noqa: BLE001 - diagnostics must stay best-effort
            logger.warning(f"Failed to notify plugin diagnostic for {plugin_id}: {e}")

    async def ensure_all_plugins_dependencies_installed(self):
        semaphore = asyncio.Semaphore(2)

        async def reconcile(plugin_path: str) -> None:
            async with semaphore:
                returncode, output = await pkgmgr_helper.install_requirements_isolated(
                    plugin_path
                )
                if returncode == 0:
                    self._dependency_errors.pop(plugin_path, None)
                    logger.info(
                        "Installed isolated dependencies for plugin at %s",
                        plugin_path,
                    )
                    return
                tail = output.strip()[-2000:]
                self._dependency_errors[plugin_path] = tail
                logger.error(
                    "Failed to install dependencies for plugin at %s: %s",
                    plugin_path,
                    tail,
                )

        plugin_paths = [
            path for path in glob.glob("data/plugins/*") if os.path.isdir(path)
        ]
        await asyncio.gather(*(reconcile(path) for path in plugin_paths))

    async def launch_all_plugins(self):
        await self._control_connection_ready.wait()
        for plugin_path in glob.glob("data/plugins/*"):
            if not os.path.isdir(plugin_path):
                continue

            self.start_plugin_supervisor(plugin_path)

        logger.info(f"launch all plugins: {len(self.plugin_run_tasks)}")
        if self.plugin_run_tasks:
            await asyncio.gather(*list(self.plugin_run_tasks))

    def start_plugin_supervisor(self, plugin_path: str) -> asyncio.Task[None]:
        """Ensure one crash-restarting supervisor owns a production plugin."""
        existing = self._plugin_supervisors.get(plugin_path)
        if existing is not None and not existing.done():
            return existing

        self._desired_plugin_paths.add(plugin_path)
        task = asyncio.create_task(self._supervise_plugin(plugin_path))
        self._plugin_supervisors[plugin_path] = task
        self.plugin_run_tasks.append(task)
        task.add_done_callback(
            lambda completed, path=plugin_path: self._supervisor_done(path, completed)
        )
        return task

    def _supervisor_done(self, plugin_path: str, task: asyncio.Task[None]) -> None:
        if self._plugin_supervisors.get(plugin_path) is task:
            self._plugin_supervisors.pop(plugin_path, None)
        with contextlib.suppress(ValueError):
            self.plugin_run_tasks.remove(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "Plugin supervisor failed for %s",
                plugin_path,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    async def _supervise_plugin(self, plugin_path: str) -> None:
        delay = _PLUGIN_RESTART_INITIAL_DELAY_SEC
        while (
            not self._shutting_down
            and plugin_path in self._desired_plugin_paths
            and os.path.isdir(plugin_path)
        ):
            started_at = asyncio.get_running_loop().time()
            try:
                await self.launch_plugin(plugin_path)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Plugin process failed: %s", plugin_path)

            if (
                self._shutting_down
                or plugin_path not in self._desired_plugin_paths
                or not os.path.isdir(plugin_path)
            ):
                return

            uptime = asyncio.get_running_loop().time() - started_at
            if uptime >= _PLUGIN_STABLE_WINDOW_SEC:
                delay = _PLUGIN_RESTART_INITIAL_DELAY_SEC
            logger.warning(
                "Plugin process exited unexpectedly; restarting %s in %.1fs",
                plugin_path,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, _PLUGIN_RESTART_MAX_DELAY_SEC)

    async def stop_plugin_supervisor(self, plugin_path: str) -> None:
        self._desired_plugin_paths.discard(plugin_path)
        task = self._plugin_supervisors.get(plugin_path)
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def mark_control_connection_ready(self) -> None:
        self._control_connection_ready.set()

    async def launch_plugin(self, plugin_path: str):
        from langbot_plugin.runtime.settings import settings as runtime_settings

        if get_platform() == "win32":
            # Due to Windows's lack of supports for both stdio and subprocess:
            # See also: https://docs.python.org/zh-cn/3.13/library/asyncio-platforms.html
            # We have to launch plugin via cmd but communicate via ws.
            python_path = pkgmgr_helper.get_plugin_python(plugin_path)

            # Build command with debug key if set
            cmd_args = [
                python_path,
                "-m",
                "langbot_plugin.cli.__init__",
                "run",
                "--prod",
            ]
            if runtime_settings.plugin_debug_key:
                cmd_args.extend(
                    ["--plugin-debug-key", runtime_settings.plugin_debug_key]
                )

            process: asyncio.subprocess.Process = await asyncio.create_subprocess_exec(
                *cmd_args,
                env={
                    "RUNTIME_WS_URL": f"ws://localhost:{self.context.ws_debug_port}/plugin/ws",
                    **os.environ.copy(),
                },
                cwd=plugin_path,
            )

            try:
                # The plugin connects to the runtime via websocket automatically.
                await process.wait()
            except asyncio.CancelledError:
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                raise
        else:
            python_path = pkgmgr_helper.get_plugin_python(plugin_path)

            # Build args with debug key if set
            args = ["-m", "langbot_plugin.cli.__init__", "run", "-s", "--prod"]
            if runtime_settings.plugin_debug_key:
                args.extend(["--plugin-debug-key", runtime_settings.plugin_debug_key])

            ctrl = stdio_client_controller.StdioClientController(
                command=python_path,
                args=args,
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
                raise

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
        """Validate and extract a package into an isolated staging directory."""
        with zipfile.ZipFile(io.BytesIO(plugin_file), "r") as manifest_file:
            manifest = yaml.safe_load(manifest_file.read("manifest.yaml"))

        plugin_name = manifest["metadata"]["name"]
        plugin_author = manifest["metadata"]["author"]
        plugin_version = manifest["metadata"]["version"]

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

        staging_path = os.path.join(
            "data",
            ".plugin-staging",
            f"{plugin_author}__{plugin_name}-{uuid.uuid4().hex}",
        )

        def extract() -> None:
            os.makedirs(staging_path, exist_ok=False)
            try:
                with zipfile.ZipFile(io.BytesIO(plugin_file), "r") as archive:
                    archive.extractall(staging_path)
            except Exception:
                shutil.rmtree(staging_path, ignore_errors=True)
                raise

        await asyncio.to_thread(extract)
        return staging_path, plugin_author, plugin_name, plugin_version

    async def install_plugin_from_marketplace(
        self, plugin_author: str, plugin_name: str, plugin_version: str
    ) -> tuple[str, str, str, str]:
        # download plugin zip file from marketplace
        plugin_zip_file = await marketplace_helper.download_plugin(
            plugin_author, plugin_name, plugin_version
        )
        return await self.install_plugin_from_file(plugin_zip_file)

    async def _activate_staged_plugin(
        self, staging_path: str, plugin_author: str, plugin_name: str
    ) -> str | None:
        """Atomically replace plugin files after stopping the old generation."""
        target_path = self.get_plugin_path(plugin_author, plugin_name)
        old_plugin = self.find_plugin(plugin_author, plugin_name)
        if old_plugin is not None:
            self._desired_plugin_paths.discard(target_path)
            await self.shutdown_plugin(old_plugin)
            await self.stop_plugin_supervisor(target_path)

        backup_path: str | None = None
        if os.path.isdir(target_path):
            backup_path = os.path.join(
                "data",
                ".plugin-backups",
                f"{plugin_author}__{plugin_name}-{uuid.uuid4().hex}",
            )
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            os.replace(target_path, backup_path)

        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            os.replace(staging_path, target_path)
        except Exception:
            if backup_path is not None and os.path.isdir(backup_path):
                os.replace(backup_path, target_path)
            raise
        return backup_path

    async def _wait_for_plugin_ready(
        self, plugin_author: str, plugin_name: str, timeout: float
    ) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            plugin = self.find_plugin(plugin_author, plugin_name)
            if (
                plugin is not None
                and plugin.status
                == runtime_plugin_container.RuntimeContainerStatus.INITIALIZED
            ):
                return
            await asyncio.sleep(0.1)
        raise RuntimeError(
            f"Plugin {plugin_author}/{plugin_name} did not become ready within {timeout:.0f}s"
        )

    async def _rollback_plugin_activation(
        self,
        plugin_author: str,
        plugin_name: str,
        backup_path: str | None,
    ) -> None:
        target_path = self.get_plugin_path(plugin_author, plugin_name)
        self._desired_plugin_paths.discard(target_path)
        current = self.find_plugin(plugin_author, plugin_name)
        if current is not None:
            await self.shutdown_plugin(current)
        await self.stop_plugin_supervisor(target_path)
        shutil.rmtree(target_path, ignore_errors=True)
        if backup_path is not None and os.path.isdir(backup_path):
            os.replace(backup_path, target_path)
            self.start_plugin_supervisor(target_path)

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
            # Stream download with progress
            plugin_file_data = None
            async for progress in marketplace_helper.download_plugin_streaming(
                install_info["plugin_author"],
                install_info["plugin_name"],
                install_info["plugin_version"],
            ):
                if progress["done"]:
                    plugin_file_data = progress["data"]
                else:
                    yield {
                        "current_action": "downloading plugin package",
                        "metadata": {
                            "download_current": progress["downloaded"],
                            "download_total": progress["total"],
                            "download_speed": progress["speed"],
                        },
                    }

            (
                plugin_path,
                plugin_author,
                plugin_name,
                plugin_version,
            ) = await self.install_plugin_from_file(plugin_file_data)
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

        backup_path: str | None = None
        activated = False
        try:
            logger.info("installing isolated plugin dependencies")
            yield {"current_action": "installing dependencies"}
            requirements_file = os.path.join(plugin_path, "requirements.txt")
            if os.path.exists(requirements_file):
                deps = pkgmgr_helper.parse_requirements(requirements_file)
                python_path = await pkgmgr_helper.ensure_plugin_environment(
                    plugin_path
                )
                total_downloaded = 0
                started_at = time.time()
                failures: dict[str, str] = {}
                for index, dep in enumerate(deps):
                    elapsed = time.time() - started_at
                    yield {
                        "current_action": "installing dependencies",
                        "metadata": {
                            "deps_total": len(deps),
                            "deps_installed": index,
                            "deps_remaining": len(deps) - index,
                            "current_dep": dep,
                            "deps_downloaded_size": total_downloaded,
                            "deps_speed": total_downloaded / elapsed
                            if elapsed > 0
                            else 0,
                            "already_installed": 0,
                            "to_install": len(deps),
                        },
                    }
                    returncode, downloaded, error = (
                        await pkgmgr_helper.install_with_retry(
                            dep,
                            max_retries=3,
                            python_executable=python_path,
                        )
                    )
                    total_downloaded += downloaded
                    if returncode != 0:
                        failures[dep] = error

                elapsed = time.time() - started_at
                yield {
                    "current_action": "installing dependencies",
                    "metadata": {
                        "deps_total": len(deps),
                        "deps_installed": len(deps) - len(failures),
                        "deps_remaining": 0,
                        "deps_failed": len(failures),
                        "failed_deps": list(failures),
                        "current_dep": "",
                        "deps_downloaded_size": total_downloaded,
                        "deps_speed": total_downloaded / elapsed
                        if elapsed > 0
                        else 0,
                    },
                }
                if failures:
                    raise DependencyInstallError(
                        failed=list(failures),
                        plugin=f"{plugin_author}/{plugin_name}",
                        details=failures,
                    )

                missing, version_mismatch = (
                    await pkgmgr_helper.classify_requirements_in_environment(
                        python_path, deps
                    )
                )
                if missing or version_mismatch:
                    raise DependencyVerificationError(
                        missing=missing,
                        version_mismatch=version_mismatch,
                        plugin=f"{plugin_author}/{plugin_name}",
                    )

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

            yield {"current_action": "launching plugin"}
            backup_path = await self._activate_staged_plugin(
                plugin_path, plugin_author, plugin_name
            )
            activated = True
            target_path = self.get_plugin_path(plugin_author, plugin_name)
            self.start_plugin_supervisor(target_path)
            await self._wait_for_plugin_ready(
                plugin_author, plugin_name, _PLUGIN_READY_TIMEOUT_SEC
            )
            if backup_path is not None:
                shutil.rmtree(backup_path, ignore_errors=True)
        except Exception:
            if activated:
                await self._rollback_plugin_activation(
                    plugin_author, plugin_name, backup_path
                )
            else:
                shutil.rmtree(plugin_path, ignore_errors=True)
            raise

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

        # Register the plugin container BEFORE calling initialize_plugin so
        # that storage API calls during initialize() can resolve the owner.
        plugin_container._runtime_plugin_handler = handler
        plugin_container.debug = bool(handler.debug_plugin)
        plugin_container.install_source = plugin_settings["install_source"]
        plugin_container.install_info = plugin_settings["install_info"]
        self.plugins.append(plugin_container)

        try:
            # initialize plugin
            await handler.initialize_plugin(plugin_settings)

            # refresh plugin container from plugin (components may have changed)
            plugin_container_data = await handler.get_plugin_container()
            refreshed = runtime_plugin_container.PluginContainer.from_dict(
                plugin_container_data
            )
            plugin_container.components = refreshed.components
            plugin_container.manifest = refreshed.manifest
            plugin_container.status = refreshed.status
        except Exception:
            await self.remove_plugin_container(plugin_container)
            raise

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
                plugin_path = self.get_plugin_path(plugin_author, plugin_name)

                yield {"current_action": "shutting down plugin"}
                if not is_debugging:
                    self._desired_plugin_paths.discard(plugin_path)
                await self.shutdown_plugin(plugin)
                if not is_debugging:
                    await self.stop_plugin_supervisor(plugin_path)
                yield {"current_action": "removing plugin container"}
                await self.remove_plugin_container(plugin)
                if not is_debugging:
                    yield {"current_action": "launching plugin"}
                    self.start_plugin_supervisor(plugin_path)

                    # Poll until the plugin appears in self.plugins (with timeout)
                    plugin_key = f"{plugin_author}/{plugin_name}"
                    for _ in range(30):
                        if self.find_plugin(plugin_author, plugin_name) is not None:
                            logger.info(f"Plugin {plugin_key} restarted and registered")
                            break
                        await asyncio.sleep(1)
                    else:
                        raise RuntimeError(
                            f"Plugin {plugin_key} restart timed out waiting for registration"
                        )

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
                    plugin_path = self.get_plugin_path(plugin_author, plugin_name)
                    self._desired_plugin_paths.discard(plugin_path)
                    yield {"current_action": "shutting down plugin"}
                    await self.shutdown_plugin(plugin)
                    await self.stop_plugin_supervisor(plugin_path)
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
        if self._shutting_down:
            return
        self._shutting_down = True
        self._desired_plugin_paths.clear()
        for plugin in list(self.plugins):
            await self.shutdown_plugin(plugin)

        tasks = list(self._plugin_supervisors.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._plugin_supervisors.clear()
        self.plugin_run_tasks.clear()

    async def shutdown_plugin(
        self,
        plugin_container: runtime_plugin_container.PluginContainer,
    ):
        # Send shutdown notification to plugin before closing connection
        # For debug plugins, this will trigger reconnection; for production plugins, it's just a notification
        handler = plugin_container._runtime_plugin_handler
        if handler is None:
            await self.remove_plugin_container(plugin_container)
            return
        try:
            await handler.shutdown_plugin()
        except Exception as e:
            logger.warning(f"Failed to send shutdown notification: {e}")

        close = getattr(handler, "close", None)
        if close is not None:
            await close()
        else:
            await handler.conn.close()
        await self.remove_plugin_container(plugin_container)
        if handler.stdio_process is not None:
            process = handler.stdio_process
            if process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=2)
                except asyncio.TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        with contextlib.suppress(ProcessLookupError):
                            process.kill()
                        await process.wait()
            logger.info(
                f"plugin process terminated: {plugin_container.manifest.metadata.author}/{plugin_container.manifest.metadata.name}:{plugin_container.manifest.metadata.version}"
            )
        else:
            logger.debug(
                f"plugin process is none: {plugin_container.manifest.metadata.author}/{plugin_container.manifest.metadata.name}:{plugin_container.manifest.metadata.version}"
            )

    async def emit_event(
        self, event_context: EventContext, include_plugins: list[str] | None = None
    ) -> tuple[
        list[runtime_plugin_container.PluginContainer],
        EventContext,
        list[dict[str, typing.Any]],
    ]:
        emitted_plugins: list[runtime_plugin_container.PluginContainer] = []
        response_sources: list[dict[str, typing.Any]] = []

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
                plugin_id = (
                    f"{plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}"
                )
                if plugin_id not in include_plugins:
                    continue

            reply_message_chain_before = _dump_reply_message_chain(event_context)
            resp = await plugin._runtime_plugin_handler.emit_event(
                event_context.model_dump()
            )

            if resp["emitted"]:
                emitted_plugins.append(plugin)

            event_context = EventContext.model_validate(resp["event_context"])
            reply_message_chain_after = _dump_reply_message_chain(event_context)
            if reply_message_chain_after != reply_message_chain_before:
                response_sources.append(
                    {
                        "kind": "reply_message_chain",
                        "plugin": _plugin_ref(plugin),
                    }
                )

            if event_context.is_prevented_postorder():
                break

        return emitted_plugins, event_context, response_sources

    async def get_plugin_icon(
        self, plugin_author: str, plugin_name: str
    ) -> tuple[bytes, str]:
        plugin = self.find_plugin(plugin_author, plugin_name)
        if plugin is not None:
            resp = await plugin._runtime_plugin_handler.get_plugin_icon()

            icon_file_key = resp["plugin_icon_file_key"]
            icon_bytes = await plugin._runtime_plugin_handler.read_local_file(
                icon_file_key
            )
            await plugin._runtime_plugin_handler.delete_local_file(icon_file_key)
            return icon_bytes, resp["mime_type"]
        return b"", ""

    async def get_plugin_readme(
        self, plugin_author: str, plugin_name: str, language: str = "en"
    ) -> bytes:
        plugin = self.find_plugin(plugin_author, plugin_name)
        if plugin is not None:
            resp = await plugin._runtime_plugin_handler.get_plugin_readme(
                language=language
            )

            readme_file_key = resp["plugin_readme_file_key"]
            readme_bytes = await plugin._runtime_plugin_handler.read_local_file(
                readme_file_key
            )
            await plugin._runtime_plugin_handler.delete_local_file(readme_file_key)
            return readme_bytes

        return b""

    async def get_plugin_logs(
        self,
        plugin_author: str,
        plugin_name: str,
        limit: int = 200,
        level: str | None = None,
    ) -> list[dict[str, typing.Any]]:
        """Return recent log entries captured from the plugin's stderr.

        Each entry: {"ts": float, "level": str, "text": str}.
        Returns an empty list if the plugin is not running.
        """
        plugin = self.find_plugin(plugin_author, plugin_name)
        if plugin is not None and plugin._runtime_plugin_handler is not None:
            log_buffer = getattr(plugin._runtime_plugin_handler, "log_buffer", None)
            if log_buffer is not None:
                return log_buffer.get_logs(limit=limit, level=level)
        return []

    async def get_plugin_assets_file(
        self, plugin_author: str, plugin_name: str, file_key: str
    ) -> tuple[bytes, str]:
        plugin = self.find_plugin(plugin_author, plugin_name)
        if plugin is not None:
            resp = await plugin._runtime_plugin_handler.get_plugin_assets_file(
                file_key=file_key
            )
            file_file_key = resp["file_file_key"]
            if not file_file_key:
                return b"", ""
            file_bytes = await plugin._runtime_plugin_handler.read_local_file(
                file_file_key
            )
            await plugin._runtime_plugin_handler.delete_local_file(file_file_key)
            return file_bytes, resp["mime_type"]
        return b"", ""

    async def handle_page_api(
        self,
        plugin_author: str,
        plugin_name: str,
        page_id: str,
        endpoint: str,
        method: str,
        body: typing.Any = None,
    ) -> dict[str, typing.Any]:
        plugin = self.find_plugin(plugin_author, plugin_name)
        if plugin is None:
            return {"data": None, "error": "Plugin not found"}
        if plugin._runtime_plugin_handler is None:
            return {"data": None, "error": "Plugin is not connected"}
        return await plugin._runtime_plugin_handler.call_page_api(
            page_id=page_id,
            endpoint=endpoint,
            method=method,
            body=body,
        )

    async def list_tools(
        self, include_plugins: list[str] | None = None
    ) -> list[ComponentManifest]:
        tools: list[ComponentManifest] = []

        for plugin in self.plugins:
            # Filter by include_plugins if specified
            if include_plugins is not None:
                plugin_id = (
                    f"{plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}"
                )
                if plugin_id not in include_plugins:
                    continue

            for component in plugin.components:
                if component.manifest.kind == Tool.__kind__:
                    tools.append(component.manifest)

        return tools

    async def call_tool(
        self,
        tool_name: str,
        tool_parameters: dict[str, typing.Any],
        session: dict[str, typing.Any],
        query_id: int,
        include_plugins: list[str] | None = None,
    ) -> dict[str, typing.Any]:
        for plugin in self.plugins:
            # Filter by include_plugins if specified
            if include_plugins is not None:
                plugin_id = (
                    f"{plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}"
                )
                if plugin_id not in include_plugins:
                    continue

            for component in plugin.components:
                if component.manifest.kind == Tool.__kind__:
                    if component.manifest.metadata.name != tool_name:
                        continue

                    if plugin._runtime_plugin_handler is None:
                        continue

                    resp = await plugin._runtime_plugin_handler.call_tool(
                        tool_name, tool_parameters, session, query_id
                    )

                    return resp["tool_response"]

        return {}

    async def list_commands(
        self, include_plugins: list[str] | None = None
    ) -> list[ComponentManifest]:
        commands: list[ComponentManifest] = []

        for plugin in self.plugins:
            # Filter by include_plugins if specified
            if include_plugins is not None:
                plugin_id = (
                    f"{plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}"
                )
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
                plugin_id = (
                    f"{plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}"
                )
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

    async def retrieve_knowledge(
        self,
        plugin_author: str,
        plugin_name: str,
        retriever_name: str,
        retrieval_context: dict[str, typing.Any],
    ) -> dict[str, typing.Any]:
        """Retrieve knowledge using a KnowledgeEngine instance."""
        target_plugin = self.find_plugin(plugin_author, plugin_name)

        if target_plugin is None:
            raise ValueError(f"Plugin {plugin_author}/{plugin_name} not found")

        if target_plugin._runtime_plugin_handler is None:
            raise ValueError(f"Plugin {plugin_author}/{plugin_name} is not connected")

        resp = await target_plugin._runtime_plugin_handler.retrieve_knowledge(
            retriever_name, retrieval_context
        )
        return resp

    # ================= Knowledge Engine Methods =================

    def _find_knowledge_engine_plugin(
        self, plugin_author: str, plugin_name: str
    ) -> tuple[runtime_plugin_container.PluginContainer | None, str | None]:
        """Find plugin with KnowledgeEngine component and return (plugin, component_name)."""
        plugin = self.find_plugin(plugin_author, plugin_name)
        if plugin is None:
            return None, None

        # Find KnowledgeEngine component
        for component in plugin.components:
            if component.manifest.kind == KnowledgeEngine.__kind__:
                return plugin, component.manifest.metadata.name
        # No RAG component found, but plugin exists
        return plugin, None

    def _get_connected_rag_plugin(
        self, plugin_author: str, plugin_name: str
    ) -> tuple[runtime_plugin_container.PluginContainer, str]:
        """Helper to find a RAG plugin and ensure it's connected.

        Args:
            plugin_author: Author of the plugin
            plugin_name: Name of the plugin

        Returns:
            Tuple of (plugin_container, component_name)

        Raises:
            ValueError: If plugin not found, has no RAG component, or is not connected.
        """
        plugin, component_name = self._find_knowledge_engine_plugin(
            plugin_author, plugin_name
        )

        if plugin is None:
            raise ValueError(f"Plugin {plugin_author}/{plugin_name} not found")
        if component_name is None:
            raise ValueError(
                f"Plugin {plugin_author}/{plugin_name} has no KnowledgeEngine component"
            )
        if plugin._runtime_plugin_handler is None:
            raise ValueError(f"Plugin {plugin_author}/{plugin_name} is not connected")

        return plugin, component_name

    async def list_knowledge_engines(self) -> list[dict[str, typing.Any]]:
        """List all available Knowledge Engines from plugins.

        Returns a list of Knowledge Engines with their capabilities and configuration schemas.
        """
        engines: list[dict[str, typing.Any]] = []

        for plugin in self.plugins:
            if (
                plugin.status
                != runtime_plugin_container.RuntimeContainerStatus.INITIALIZED
            ):
                continue

            for component in plugin.components:
                if component.manifest.kind == KnowledgeEngine.__kind__:
                    # Get capabilities from the plugin
                    try:
                        capabilities_resp = (
                            await plugin._runtime_plugin_handler.get_rag_capabilities()
                        )
                        capabilities = capabilities_resp.get("capabilities", [])
                    except Exception as e:
                        logger.warning(
                            f"Failed to get capabilities from {plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}: {e}"
                        )
                        capabilities = []

                    # Read schemas from manifest YAML
                    creation_schema = {
                        "schema": component.manifest.spec.get("creation_schema", [])
                    }
                    retrieval_schema = {
                        "schema": component.manifest.spec.get("retrieval_schema", [])
                    }

                    meta = component.manifest.metadata
                    engines.append(
                        {
                            "plugin_id": f"{plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}",
                            "name": meta.label
                            or meta.name,  # Pass I18n object or string directly
                            "description": meta.description,  # Pass I18n object directly
                            "capabilities": capabilities,
                            "creation_schema": creation_schema,
                            "retrieval_schema": retrieval_schema,
                        }
                    )
        return engines

    async def rag_ingest_document(
        self, plugin_author: str, plugin_name: str, context_data: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        """Call plugin to ingest a document."""
        plugin, _ = self._get_connected_rag_plugin(plugin_author, plugin_name)
        resp = await plugin._runtime_plugin_handler.rag_ingest_document(context_data)
        return resp

    async def rag_delete_document(
        self, plugin_author: str, plugin_name: str, kb_id: str, document_id: str
    ) -> dict[str, typing.Any]:
        """Call plugin to delete a document."""
        plugin, _ = self._get_connected_rag_plugin(plugin_author, plugin_name)
        resp = await plugin._runtime_plugin_handler.rag_delete_document(
            kb_id, document_id
        )
        return resp

    async def rag_on_kb_create(
        self,
        plugin_author: str,
        plugin_name: str,
        kb_id: str,
        config: dict[str, typing.Any],
    ) -> dict[str, typing.Any]:
        """Notify plugin about KB creation."""
        plugin, _ = self._get_connected_rag_plugin(plugin_author, plugin_name)
        resp = await plugin._runtime_plugin_handler.rag_on_kb_create(kb_id, config)
        return resp

    async def rag_on_kb_delete(
        self, plugin_author: str, plugin_name: str, kb_id: str
    ) -> dict[str, typing.Any]:
        """Notify plugin about KB deletion."""
        plugin, _ = self._get_connected_rag_plugin(plugin_author, plugin_name)
        resp = await plugin._runtime_plugin_handler.rag_on_kb_delete(kb_id)
        return resp

    async def get_rag_creation_schema(
        self, plugin_author: str, plugin_name: str
    ) -> dict[str, typing.Any]:
        """Get RAG creation settings schema from plugin manifest."""
        plugin, _ = self._find_knowledge_engine_plugin(plugin_author, plugin_name)
        if plugin is None:
            return {"schema": []}
        for component in plugin.components:
            if component.manifest.kind == KnowledgeEngine.__kind__:
                return {"schema": component.manifest.spec.get("creation_schema", [])}
        return {"schema": []}

    async def get_rag_retrieval_schema(
        self, plugin_author: str, plugin_name: str
    ) -> dict[str, typing.Any]:
        """Get RAG retrieval settings schema from plugin manifest."""
        plugin, _ = self._find_knowledge_engine_plugin(plugin_author, plugin_name)
        if plugin is None:
            return {"schema": []}
        for component in plugin.components:
            if component.manifest.kind == KnowledgeEngine.__kind__:
                return {"schema": component.manifest.spec.get("retrieval_schema", [])}
        return {"schema": []}

    # ================= Parser Methods =================

    def _find_parser_plugin(
        self, plugin_author: str, plugin_name: str
    ) -> tuple[runtime_plugin_container.PluginContainer | None, str | None]:
        """Find plugin with Parser component and return (plugin, component_name)."""
        plugin = self.find_plugin(plugin_author, plugin_name)
        if plugin is None:
            return None, None

        for component in plugin.components:
            if component.manifest.kind == Parser.__kind__:
                return plugin, component.manifest.metadata.name
        return plugin, None

    def _get_connected_parser_plugin(
        self, plugin_author: str, plugin_name: str
    ) -> tuple[runtime_plugin_container.PluginContainer, str]:
        """Helper to find a Parser plugin and ensure it's connected.

        Args:
            plugin_author: Author of the plugin.
            plugin_name: Name of the plugin.

        Returns:
            Tuple of (plugin_container, component_name).

        Raises:
            ValueError: If plugin not found, has no Parser component, or is not connected.
        """
        plugin, component_name = self._find_parser_plugin(plugin_author, plugin_name)

        if plugin is None:
            raise ValueError(f"Plugin {plugin_author}/{plugin_name} not found")
        if component_name is None:
            raise ValueError(
                f"Plugin {plugin_author}/{plugin_name} has no Parser component"
            )
        if plugin._runtime_plugin_handler is None:
            raise ValueError(f"Plugin {plugin_author}/{plugin_name} is not connected")

        return plugin, component_name

    async def list_parsers(self) -> list[dict[str, typing.Any]]:
        """List all available parsers from plugins.

        Returns a list of parsers with their supported MIME types.
        """
        parsers: list[dict[str, typing.Any]] = []

        for plugin in self.plugins:
            if (
                plugin.status
                != runtime_plugin_container.RuntimeContainerStatus.INITIALIZED
            ):
                continue

            for component in plugin.components:
                if component.manifest.kind == Parser.__kind__:
                    meta = component.manifest.metadata
                    supported_mime_types = component.manifest.spec.get(
                        "supported_mime_types", []
                    )

                    parsers.append(
                        {
                            "plugin_id": f"{plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}",
                            "plugin_author": plugin.manifest.metadata.author,
                            "plugin_name": plugin.manifest.metadata.name,
                            "name": meta.label or meta.name,
                            "description": meta.description,
                            "supported_mime_types": supported_mime_types,
                        }
                    )
        return parsers

    async def parse_document(
        self,
        plugin_author: str,
        plugin_name: str,
        context_data: dict[str, typing.Any],
        file_bytes: bytes,
    ) -> dict[str, typing.Any]:
        """Call plugin to parse a document."""
        plugin, _ = self._get_connected_parser_plugin(plugin_author, plugin_name)
        resp = await plugin._runtime_plugin_handler.parse_document(
            context_data, file_bytes
        )
        return resp


def _format_plugin_diagnostic(diagnostic: dict[str, typing.Any]) -> str:
    code = diagnostic.get("code") or "plugin_diagnostic"
    message = diagnostic.get("message") or "Plugin diagnostic"
    query = diagnostic.get("query")
    query_id = None
    event_name = None
    stage = None
    if isinstance(query, dict):
        query_id = query.get("query_id")
        event_name = query.get("event_name")
        stage = query.get("stage")

    delivery = diagnostic.get("delivery")
    error_type = None
    error_message = None
    if isinstance(delivery, dict):
        error_type = delivery.get("error_type")
        error_message = delivery.get("error_message")

    parts = [f"[{code}] {message}"]
    if query_id is not None:
        parts.append(f"query_id={query_id}")
    if event_name:
        parts.append(f"event={event_name}")
    if stage:
        parts.append(f"stage={stage}")
    if error_type or error_message:
        error = f"{error_type}: {error_message}" if error_type else str(error_message)
        parts.append(f"delivery_error={error}")

    return " | ".join(parts)


def _to_plugin_diagnostic(
    diagnostic: dict[str, typing.Any],
) -> dict[str, typing.Any]:
    details: dict[str, typing.Any] = {}
    original_details = diagnostic.get("details")
    if isinstance(original_details, dict):
        details.update(original_details)

    query = diagnostic.get("query")
    if isinstance(query, dict):
        for key in ("query_id", "event_name", "stage"):
            if key in query and key not in details:
                details[key] = query[key]

    delivery = diagnostic.get("delivery")
    if isinstance(delivery, dict) and "delivery_error" not in details:
        error_type = delivery.get("error_type")
        error_message = delivery.get("error_message")
        if error_type and error_message:
            details["delivery_error"] = f"{error_type}: {error_message}"
        elif error_message:
            details["delivery_error"] = error_message

    if "message_chain" in diagnostic and "message_chain" not in details:
        details["message_chain"] = diagnostic["message_chain"]

    return {
        "level": diagnostic.get("level", "ERROR"),
        "code": diagnostic.get("code", "plugin_diagnostic"),
        "message": diagnostic.get("message", "Plugin diagnostic"),
        "details": details,
    }


def _dump_reply_message_chain(
    event_context: EventContext,
) -> list[dict[str, typing.Any]] | None:
    reply_message_chain = getattr(event_context.event, "reply_message_chain", None)
    if reply_message_chain is None:
        return None
    return reply_message_chain.model_dump()


def _plugin_ref(
    plugin: runtime_plugin_container.PluginContainer,
) -> dict[str, str]:
    return {
        "author": str(plugin.manifest.metadata.author),
        "name": str(plugin.manifest.metadata.name),
    }
