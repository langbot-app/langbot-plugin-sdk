from __future__ import annotations

import glob
import os
import secrets
import shutil
import typing
from typing import AsyncGenerator
import asyncio
import contextlib
from dataclasses import dataclass
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
from langbot_plugin.runtime.security import PLUGIN_REGISTRATION_CAPABILITY_ENV
from langbot_plugin.entities.io.context import (
    InstallationBinding,
    PluginInstallationDesiredState,
    PluginWorkerPolicy,
)
from langbot_plugin.runtime.plugin.artifact import (
    PluginArtifact,
    PluginArtifactStore,
    PluginInstallationPaths,
)
from langbot_plugin.runtime.plugin.dependency_environment import (
    DependencyEnvironmentPreparationError,
    PluginDependencyEnvironment,
    PluginDependencyEnvironmentStore,
)
from langbot_plugin.runtime.plugin.worker_launcher import (
    PluginWorkerLaunchSpec,
    PluginWorkerLauncher,
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


@dataclass(frozen=True, slots=True)
class _PendingPluginRegistration:
    """One launch-scoped capability bound to an installed plugin identity."""

    plugin_author: str
    plugin_name: str
    plugin_path: str
    binding: InstallationBinding | None
    expires_at: float


@dataclass(slots=True)
class PluginInstallationRuntime:
    """Rebuildable runtime state keyed only by its complete binding."""

    binding: InstallationBinding
    artifact: PluginArtifact
    paths: PluginInstallationPaths
    enabled: bool
    dependency_environment: PluginDependencyEnvironment | None = None
    state: str = "disabled"
    error_code: str | None = None
    error_message: str | None = None
    plugin_container: runtime_plugin_container.PluginContainer | None = None
    plugin_handler: runtime_plugin_handler_cls.PluginConnectionHandler | None = None
    launch_task: asyncio.Task | None = None


_REGISTRATION_CAPABILITY_TTL_SECONDS = 300.0

# A plugin process only needs a small subset of the parent environment on
# Windows. In particular, Runtime and Box control-plane credentials must never
# cross this boundary.
_WINDOWS_PLUGIN_ENV_ALLOWLIST = frozenset(
    {
        "ALL_PROXY",
        "APPDATA",
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "NO_PROXY",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "USERPROFILE",
        "WINDIR",
    }
)


class PluginManager:
    """The manager for plugins."""

    context: context_module.RuntimeContext

    plugin_handlers: list[runtime_plugin_handler_cls.PluginConnectionHandler] = []

    plugins: list[runtime_plugin_container.PluginContainer] = []

    plugin_run_tasks: list[asyncio.Task] = []

    def __init__(self, context: context_module.RuntimeContext):
        self.context = context
        self.plugin_handlers = []
        self.plugins = []
        self.plugin_run_tasks = []
        self._pending_registrations: dict[str, _PendingPluginRegistration] = {}
        self._installations: dict[InstallationBinding, PluginInstallationRuntime] = {}
        self._active_binding_by_uuid: dict[str, InstallationBinding] = {}
        self._binding_by_container_id: dict[int, InstallationBinding] = {}
        self.artifact_store = PluginArtifactStore()
        self.dependency_environment_store = PluginDependencyEnvironmentStore(
            self.artifact_store.base_path
        )
        self.worker_launcher = PluginWorkerLauncher()

    @property
    def installation_runtimes(
        self,
    ) -> dict[InstallationBinding, PluginInstallationRuntime]:
        return dict(self._installations)

    def configure_worker_runtime(
        self,
        policy: PluginWorkerPolicy,
        runtime_profile: typing.Literal["oss_dev", "shared"],
    ) -> None:
        self.worker_launcher.configure(policy, runtime_profile)

    @staticmethod
    def _installed_plugin_identity(plugin_path: str) -> tuple[str, str]:
        """Read and validate the identity the Runtime is about to launch."""

        manifest_path = os.path.join(plugin_path, "manifest.yaml")
        try:
            with open(manifest_path, "r", encoding="utf-8") as manifest_file:
                manifest = yaml.safe_load(manifest_file)
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(
                f"Installed plugin manifest is unavailable: {manifest_path}"
            ) from exc

        if not isinstance(manifest, dict) or manifest.get("kind") != "Plugin":
            raise ValueError("Installed plugin manifest must have kind=Plugin")
        metadata = manifest.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("Installed plugin manifest metadata is missing")
        plugin_author = str(metadata.get("author") or "").strip()
        plugin_name = str(metadata.get("name") or "").strip()
        if not plugin_author or not plugin_name:
            raise ValueError("Installed plugin manifest identity is incomplete")

        expected_directory = f"{plugin_author}__{plugin_name}"
        if os.path.basename(os.path.normpath(plugin_path)) != expected_directory:
            raise ValueError(
                "Installed plugin directory does not match its manifest identity"
            )
        return plugin_author, plugin_name

    def _issue_registration_capability(
        self,
        *,
        plugin_author: str,
        plugin_name: str,
        plugin_path: str,
        binding: InstallationBinding | None = None,
    ) -> str:
        """Issue a short-lived, one-use capability for one expected plugin."""

        author = str(plugin_author or "").strip()
        name = str(plugin_name or "").strip()
        if not author or not name:
            raise ValueError("Plugin registration identity is incomplete")
        if (
            getattr(self.context, "runtime_profile", "oss_dev") == "shared"
            and binding is None
        ):
            raise ValueError(
                "Shared plugin registration capability requires InstallationBinding"
            )
        if binding is not None and not self.context.is_current_installation_binding(
            binding
        ):
            raise ValueError("Plugin registration binding is no longer current")

        capability = secrets.token_urlsafe(48)
        self._pending_registrations[capability] = _PendingPluginRegistration(
            plugin_author=author,
            plugin_name=name,
            plugin_path=os.path.abspath(plugin_path),
            binding=binding,
            expires_at=time.monotonic() + _REGISTRATION_CAPABILITY_TTL_SECONDS,
        )
        return capability

    def _find_pending_registration_key(self, capability: str) -> str | None:
        supplied = str(capability or "").strip()
        if not supplied:
            return None
        now = time.monotonic()
        expired = [
            key
            for key, registration in self._pending_registrations.items()
            if registration.expires_at <= now
        ]
        for key in expired:
            self._pending_registrations.pop(key, None)
        for key in self._pending_registrations:
            if secrets.compare_digest(key, supplied):
                return key
        return None

    def is_registration_capability_pending(self, capability: str) -> bool:
        """Check transport admission without consuming the registration."""

        return self._find_pending_registration_key(capability) is not None

    def _consume_registration_capability(
        self,
        capability: str,
        *,
        plugin_author: str,
        plugin_name: str,
    ) -> _PendingPluginRegistration:
        key = self._find_pending_registration_key(capability)
        if key is None:
            raise ValueError(
                "Plugin registration capability is invalid or already used"
            )
        registration = self._pending_registrations.pop(key)
        if (
            registration.plugin_author != plugin_author
            or registration.plugin_name != plugin_name
        ):
            raise ValueError(
                "Plugin manifest identity does not match its registration capability"
            )
        return registration

    def _revoke_registration_capability(self, capability: str) -> None:
        key = self._find_pending_registration_key(capability)
        if key is not None:
            self._pending_registrations.pop(key, None)

    def _revoke_registration_capabilities_for_binding(
        self,
        binding: InstallationBinding,
    ) -> None:
        for key, registration in list(self._pending_registrations.items()):
            if registration.binding == binding:
                self._pending_registrations.pop(key, None)

    @staticmethod
    def _windows_plugin_environment() -> dict[str, str]:
        return {
            key: value
            for key, value in os.environ.items()
            if key.upper() in _WINDOWS_PLUGIN_ENV_ALLOWLIST
        }

    def get_plugin_path(self, plugin_author: str, plugin_name: str) -> str:
        return f"data/plugins/{plugin_author}__{plugin_name}"

    def _current_control_binding(self) -> InstallationBinding | None:
        control_handler = getattr(self.context, "control_handler", None)
        action_context = getattr(control_handler, "current_action_context", None)
        return (
            action_context if isinstance(action_context, InstallationBinding) else None
        )

    def plugins_for_binding(
        self,
        binding: InstallationBinding,
    ) -> list[runtime_plugin_container.PluginContainer]:
        runtime = self._installations.get(binding)
        if runtime is None or runtime.plugin_container is None:
            return []
        return [runtime.plugin_container]

    def _plugins_for_current_scope(
        self,
    ) -> list[runtime_plugin_container.PluginContainer]:
        binding = self._current_control_binding()
        if binding is not None:
            if (
                binding in self._installations
                or getattr(self.context, "runtime_profile", "oss_dev") == "shared"
            ):
                return self.plugins_for_binding(binding)
        return self.plugins

    def plugins_for_current_scope(
        self,
    ) -> list[runtime_plugin_container.PluginContainer]:
        return list(self._plugins_for_current_scope())

    def find_plugin(
        self,
        plugin_author: str,
        plugin_name: str,
        *,
        binding: InstallationBinding | None = None,
    ) -> runtime_plugin_container.PluginContainer | None:
        """Find a plugin by author and name.

        Args:
            plugin_author: The plugin author.
            plugin_name: The plugin name.

        Returns:
            The plugin container if found, otherwise None.
        """
        scoped_plugins = (
            self.plugins_for_binding(binding)
            if binding is not None
            else self._plugins_for_current_scope()
        )
        for plugin in scoped_plugins:
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
                try:
                    (
                        returncode,
                        output,
                    ) = await pkgmgr_helper.install_requirements_isolated(plugin_path)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    output = f"{type(exc).__name__}: {exc}"
                    returncode = 1
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
        # A control socket alone is not enough: LangBot must first fence this
        # Runtime to one Workspace/generation through SET_RUNTIME_CONFIG.
        await self.context.wait_for_workspace_binding()
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
        plugin_author, plugin_name = self._installed_plugin_identity(plugin_path)
        registration_capability = self._issue_registration_capability(
            plugin_author=plugin_author,
            plugin_name=plugin_name,
            plugin_path=plugin_path,
        )

        try:
            if get_platform() == "win32":
                # Due to Windows's lack of supports for both stdio and subprocess:
                # See also: https://docs.python.org/zh-cn/3.13/library/asyncio-platforms.html
                # We have to launch plugin via cmd but communicate via ws.
                python_path = sys.executable

                cmd_args = [
                    python_path,
                    "-m",
                    "langbot_plugin.cli.__init__",
                    "run",
                    "--prod",
                ]

                child_env = self._windows_plugin_environment()
                child_env["RUNTIME_WS_URL"] = (
                    f"ws://localhost:{self.context.ws_debug_port}/plugin/ws"
                )
                child_env[PLUGIN_REGISTRATION_CAPABILITY_ENV] = registration_capability

                process: asyncio.subprocess.Process = (
                    await asyncio.create_subprocess_exec(
                        *cmd_args,
                        env=child_env,
                        cwd=plugin_path,
                    )
                )

                # hold the process
                task = asyncio.create_task(process.wait())

                # the plugin will connect to the runtime via ws automatically

                await task
            else:
                python_path = sys.executable

                args = [
                    "-m",
                    "langbot_plugin.cli.__init__",
                    "run",
                    "-s",
                    "--prod",
                ]

                ctrl = stdio_client_controller.StdioClientController(
                    command=python_path,
                    args=args,
                    env={PLUGIN_REGISTRATION_CAPABILITY_ENV: registration_capability},
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
        finally:
            # A successfully registered capability has already been consumed;
            # this only removes launch failures or processes that never register.
            self._revoke_registration_capability(registration_capability)

    async def apply_plugin_installation(
        self,
        binding: InstallationBinding,
        *,
        artifact_package: bytes | None = None,
        enabled: bool = True,
    ) -> dict[str, typing.Any]:
        """Apply one desired installation and fence an older worker first."""

        binding = self.context.validate_installation_candidate(binding)
        artifact = (
            self.artifact_store.install_package(
                artifact_package,
                binding.artifact_digest,
            )
            if artifact_package is not None
            else self.artifact_store.get_verified(binding.artifact_digest)
        )

        previous = self.context.activate_installation_binding(binding)
        if previous is not None and previous != binding:
            await self._revoke_installation_runtime(previous)
        self._active_binding_by_uuid[binding.installation_uuid] = binding

        if artifact is None:
            self._installations.pop(binding, None)
            return {
                "installation_uuid": binding.installation_uuid,
                "state": "artifact_missing",
            }

        current = self._installations.get(binding)
        if current is None:
            current = PluginInstallationRuntime(
                binding=binding,
                artifact=artifact,
                paths=self.artifact_store.ensure_installation_paths(binding),
                enabled=enabled,
            )
            self._installations[binding] = current
        else:
            current.enabled = enabled

        if enabled:
            current.error_code = None
            current.error_message = None
            if getattr(self.context, "runtime_profile", "oss_dev") == "shared":
                current.dependency_environment = None
                if (
                    self.dependency_environment_store.base_path
                    != self.artifact_store.base_path
                ):
                    # Tests and embedders may replace the artifact store after
                    # construction; dependency state must follow that same
                    # Runtime-owned volume.
                    self.dependency_environment_store = (
                        PluginDependencyEnvironmentStore(self.artifact_store.base_path)
                    )
                try:
                    current.dependency_environment = (
                        await self.worker_launcher.prepare_dependency_environment(
                            self.dependency_environment_store,
                            artifact,
                        )
                    )
                except DependencyEnvironmentPreparationError as exc:
                    await self._stop_installation_worker(current)
                    current.state = "failed"
                    current.error_code = "dependency_prepare_failed"
                    current.error_message = str(exc)
                    logger.error(
                        "Plugin dependency preparation failed for installation %s: %s",
                        binding.installation_uuid,
                        exc,
                    )
                    return self._installation_state_result(current)
                except Exception:
                    await self._stop_installation_worker(current)
                    current.state = "failed"
                    current.error_code = "dependency_prepare_failed"
                    current.error_message = (
                        "Plugin dependency environment preparation failed"
                    )
                    logger.exception(
                        "Unexpected plugin dependency preparation failure for %s",
                        binding.installation_uuid,
                    )
                    return self._installation_state_result(current)

                # A concurrent newer apply/remove can fence this binding while
                # its shared environment is being prepared. Never launch it.
                if self._installations.get(
                    binding
                ) is not current or not self.context.is_current_installation_binding(
                    binding
                ):
                    return {
                        "installation_uuid": binding.installation_uuid,
                        "state": "superseded",
                    }
            current.state = "starting"
            self._schedule_installation_worker(current)
        else:
            current.state = "disabled"
            current.error_code = None
            current.error_message = None
            await self._stop_installation_worker(current)
        return self._installation_state_result(current)

    @staticmethod
    def _installation_state_result(
        runtime: PluginInstallationRuntime,
    ) -> dict[str, typing.Any]:
        result: dict[str, typing.Any] = {
            "installation_uuid": runtime.binding.installation_uuid,
            "state": runtime.state,
            "artifact_path": str(runtime.artifact.code_path),
        }
        if runtime.dependency_environment is not None:
            result["dependency_environment_digest"] = (
                runtime.dependency_environment.digest
            )
        if runtime.error_code is not None:
            result["error_code"] = runtime.error_code
        if runtime.error_message is not None:
            result["message"] = runtime.error_message
        return result

    async def remove_plugin_installation(
        self,
        binding: InstallationBinding,
    ) -> dict[str, typing.Any]:
        """Remove exactly the active desired binding and revoke its worker."""

        binding = self.context.deactivate_installation_binding(binding)
        await self._revoke_installation_runtime(binding)
        self._active_binding_by_uuid.pop(binding.installation_uuid, None)
        return {
            "installation_uuid": binding.installation_uuid,
            "state": "removed",
        }

    async def reconcile_plugin_installations(
        self,
        desired_states: tuple[PluginInstallationDesiredState, ...],
    ) -> dict[str, typing.Any]:
        """Replay the authoritative instance desired state after reconnect."""

        desired_by_uuid = {
            desired.binding.installation_uuid: desired for desired in desired_states
        }
        for desired in desired_states:
            self.context.validate_installation_candidate(desired.binding)

        removed: list[str] = []
        for installation_uuid, current_binding in list(
            self._active_binding_by_uuid.items()
        ):
            desired = desired_by_uuid.get(installation_uuid)
            if desired is None or desired.binding != current_binding:
                if self.context.is_current_installation_binding(current_binding):
                    self.context.deactivate_installation_binding(current_binding)
                await self._revoke_installation_runtime(current_binding)
                self._active_binding_by_uuid.pop(installation_uuid, None)
                removed.append(installation_uuid)

        applied: list[str] = []
        missing_artifacts: list[str] = []
        failed_installations: list[dict[str, str]] = []
        for desired in desired_states:
            result = await self.apply_plugin_installation(
                desired.binding,
                enabled=desired.enabled,
            )
            applied.append(desired.binding.installation_uuid)
            if result["state"] == "artifact_missing":
                missing_artifacts.append(desired.binding.installation_uuid)
            elif result["state"] == "failed":
                failed_installations.append(
                    {
                        "installation_uuid": desired.binding.installation_uuid,
                        "error_code": str(result["error_code"]),
                        "message": str(result["message"]),
                    }
                )

        return {
            "applied": applied,
            "removed": removed,
            "missing_artifacts": missing_artifacts,
            "failed_installations": failed_installations,
        }

    def _schedule_installation_worker(
        self,
        runtime: PluginInstallationRuntime,
    ) -> None:
        if runtime.launch_task is not None and not runtime.launch_task.done():
            return
        runtime.launch_task = asyncio.create_task(
            self.launch_plugin_installation(runtime.binding)
        )
        self.plugin_run_tasks.append(runtime.launch_task)

    async def launch_plugin_installation(
        self,
        binding: InstallationBinding,
    ) -> None:
        runtime = self._installations.get(binding)
        if runtime is None or not runtime.enabled:
            return
        if not self.context.is_current_installation_binding(binding):
            raise ValueError("Plugin installation binding is no longer current")
        if (
            getattr(self.context, "runtime_profile", "oss_dev") == "shared"
            and runtime.dependency_environment is None
        ):
            raise ValueError(
                "Plugin installation dependency environment is unavailable"
            )

        capability = self._issue_registration_capability(
            plugin_author=runtime.artifact.plugin_author,
            plugin_name=runtime.artifact.plugin_name,
            plugin_path=str(runtime.artifact.code_path),
            binding=binding,
        )
        controller = self.worker_launcher.create_controller(
            PluginWorkerLaunchSpec(
                binding=binding,
                artifact=runtime.artifact,
                paths=runtime.paths,
                registration_capability=capability,
                dependency_environment=runtime.dependency_environment,
            )
        )

        async def new_plugin_connection_callback(connection: Connection):
            if not self.context.is_current_installation_binding(binding):
                await connection.close()
                return
            plugin_handler = runtime_plugin_handler_cls.PluginConnectionHandler(
                connection,
                self.context,
                stdio_process=controller.process,
                file_storage_dir=str(runtime.paths.root_path / "rpc-transfer"),
                max_file_bytes=(
                    self.context.worker_policy.max_file_size_mb * 1024 * 1024
                ),
            )
            runtime.plugin_handler = plugin_handler
            await self.add_plugin_handler(plugin_handler)

        try:
            await controller.run(new_plugin_connection_callback)
        except asyncio.CancelledError:
            logger.info(
                "plugin installation worker cancelled: %s",
                binding.installation_uuid,
            )
            raise
        finally:
            self._revoke_registration_capability(capability)

    async def _revoke_installation_runtime(
        self,
        binding: InstallationBinding,
    ) -> None:
        self._revoke_registration_capabilities_for_binding(binding)
        runtime = self._installations.pop(binding, None)
        if runtime is None:
            return
        await self._stop_installation_worker(runtime)

    async def _stop_installation_worker(
        self,
        runtime: PluginInstallationRuntime,
    ) -> None:
        handler = runtime.plugin_handler
        if handler is not None:
            handler.cancel_inflight_messages()
            try:
                await handler.shutdown_plugin()
            except Exception as exc:
                logger.warning("Failed to notify revoked plugin worker: %s", exc)
            await handler.conn.close()
            if handler in self.plugin_handlers:
                self.plugin_handlers.remove(handler)
            process = handler.stdio_process
            if process is not None and process.returncode is None:
                process.kill()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=2)
        runtime.plugin_handler = None
        if runtime.plugin_container is not None:
            self._binding_by_container_id.pop(id(runtime.plugin_container), None)
            runtime.plugin_container = None

        task = runtime.launch_task
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        runtime.launch_task = None

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
        if handler in self.plugin_handlers:
            self.plugin_handlers.remove(handler)
        for runtime in self._installations.values():
            if runtime.plugin_handler is handler:
                if runtime.plugin_container is not None:
                    self._binding_by_container_id.pop(
                        id(runtime.plugin_container),
                        None,
                    )
                runtime.plugin_handler = None
                runtime.plugin_container = None
                return
        for plugin_container in list(self.plugins):
            if plugin_container._runtime_plugin_handler is handler:
                self.plugins.remove(plugin_container)
                return

    async def install_plugin_from_file(
        self, plugin_file: bytes
    ) -> tuple[str, str, str, str]:
        """Validate and extract a package into an isolated staging directory."""
        with zipfile.ZipFile(io.BytesIO(plugin_file), "r") as manifest_file:
            manifest = yaml.safe_load(manifest_file.read("manifest.yaml"))

        plugin_name = manifest["metadata"]["name"]
        plugin_author = manifest["metadata"]["author"]
        plugin_version = manifest["metadata"]["version"]

        self._validate_install_target(plugin_author, plugin_name, plugin_version)

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

    def _validate_install_target(
        self, plugin_author: str, plugin_name: str, plugin_version: str
    ) -> None:
        """Reject a conflicting installed generation for the same plugin."""
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

    def _get_plugin_operation_lock(
        self, plugin_author: str, plugin_name: str
    ) -> asyncio.Lock:
        key = f"{plugin_author}/{plugin_name}"
        lock = self._plugin_operation_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._plugin_operation_locks[key] = lock
        return lock

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
        self._desired_plugin_paths.discard(target_path)
        await self.stop_plugin_supervisor(target_path)
        old_plugin = self.find_plugin(plugin_author, plugin_name)
        if old_plugin is not None:
            await self.shutdown_plugin(old_plugin)

        backup_path: str | None = None
        try:
            if os.path.isdir(target_path):
                backup_path = os.path.join(
                    "data",
                    ".plugin-backups",
                    f"{plugin_author}__{plugin_name}-{uuid.uuid4().hex}",
                )
                os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                os.replace(target_path, backup_path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            os.replace(staging_path, target_path)
        except Exception:
            if backup_path is not None and os.path.isdir(backup_path):
                os.replace(backup_path, target_path)
            if os.path.isdir(target_path) and not self._shutting_down:
                self.start_plugin_supervisor(target_path)
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

        operation_lock = self._get_plugin_operation_lock(plugin_author, plugin_name)
        lock_acquired = False
        backup_path: str | None = None
        activated = False
        try:
            await operation_lock.acquire()
            lock_acquired = True
            self._validate_install_target(plugin_author, plugin_name, plugin_version)
            logger.info("installing isolated plugin dependencies")
            yield {"current_action": "installing dependencies"}
            requirements_file = os.path.join(plugin_path, "requirements.txt")
            if os.path.exists(requirements_file):
                deps = pkgmgr_helper.parse_requirements(requirements_file)
                python_path = await pkgmgr_helper.ensure_plugin_environment(plugin_path)
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
                    (
                        returncode,
                        downloaded,
                        error,
                    ) = await pkgmgr_helper.install_with_retry(
                        dep,
                        max_retries=3,
                        python_executable=python_path,
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
                        "deps_speed": total_downloaded / elapsed if elapsed > 0 else 0,
                    },
                }
                if failures:
                    raise DependencyInstallError(
                        failed=list(failures),
                        plugin=f"{plugin_author}/{plugin_name}",
                        details=failures,
                    )

                (
                    missing,
                    version_mismatch,
                ) = await pkgmgr_helper.classify_requirements_in_environment(
                    python_path, deps
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
        except BaseException:
            if activated:
                await self._rollback_plugin_activation(
                    plugin_author, plugin_name, backup_path
                )
            else:
                shutil.rmtree(plugin_path, ignore_errors=True)
            raise
        finally:
            if lock_acquired:
                operation_lock.release()

    async def register_plugin(
        self,
        handler: runtime_plugin_handler_cls.PluginConnectionHandler,
        container_data: dict[str, typing.Any],
        debug_plugin: bool = False,
        registration_capability: str | None = None,
    ):
        plugin_container = runtime_plugin_container.PluginContainer.from_dict(
            container_data
        )
        plugin_author = str(plugin_container.manifest.metadata.author or "").strip()
        plugin_name = str(plugin_container.manifest.metadata.name or "").strip()
        if not plugin_author or not plugin_name:
            raise ValueError("Plugin manifest identity is incomplete")

        installation_binding: InstallationBinding | None = None
        installation_runtime: PluginInstallationRuntime | None = None
        if debug_plugin:
            if registration_capability:
                raise ValueError(
                    "Debug plugin registration cannot use an installed-plugin capability"
                )
        else:
            registration = self._consume_registration_capability(
                registration_capability or "",
                plugin_author=plugin_author,
                plugin_name=plugin_name,
            )
            # From this point forward, use only the identity captured before the
            # child process was launched, never values supplied by plugin code.
            plugin_author = registration.plugin_author
            plugin_name = registration.plugin_name
            installation_binding = registration.binding
            if installation_binding is not None:
                if not self.context.is_current_installation_binding(
                    installation_binding
                ):
                    raise ValueError(
                        "Plugin registration capability binding is no longer current"
                    )
                installation_runtime = self._installations.get(installation_binding)
                if installation_runtime is None:
                    raise ValueError("Plugin installation desired state is unavailable")
                handler.bind_action_context(installation_binding)
            if (
                self.find_plugin(
                    plugin_author,
                    plugin_name,
                    binding=installation_binding,
                )
                is not None
            ):
                raise ValueError("Installed plugin is already registered")

        try:
            if getattr(self.context, "control_handler", None) is None:
                raise ValueError("Control handler not found")

            # if it's a debug plugin, we need to initialize the plugin settings first
            if debug_plugin:
                # Debug plugins preserve the OSS single-Workspace flow.
                runtime_binding = await self.context.wait_for_workspace_binding()
                await self.context.control_handler.call_action(
                    RuntimeToLangBotAction.INITIALIZE_PLUGIN_SETTINGS,
                    {
                        "plugin_author": plugin_author,
                        "plugin_name": plugin_name,
                        "install_source": PluginInstallSource.DEBUG.value,
                        "install_info": {},
                    },
                )
            elif installation_binding is None:
                # Temporary OSS compatibility for legacy data/plugins launches.
                runtime_binding = await self.context.wait_for_workspace_binding()

            # get plugin settings from LangBot
            plugin_settings = await self.context.control_handler.call_action(
                RuntimeToLangBotAction.GET_PLUGIN_SETTINGS,
                {
                    "plugin_author": plugin_author,
                    "plugin_name": plugin_name,
                },
                **(
                    {"action_context": installation_binding}
                    if installation_binding is not None
                    else {}
                ),
            )
        except Exception as e:
            raise ValueError(
                "Failed to get plugin settings, is LangBot connected?"
            ) from e

        # The installation capability comes from the trusted LangBot settings
        # response, never from REGISTER_PLUGIN data supplied by plugin code.
        installation_uuid = plugin_settings.get("installation_uuid")
        if installation_binding is not None:
            if installation_uuid is not None and (
                not isinstance(installation_uuid, str)
                or installation_uuid.strip() != installation_binding.installation_uuid
            ):
                raise ValueError(
                    "LangBot plugin settings do not match installation binding"
                )
        else:
            if not isinstance(installation_uuid, str) or not installation_uuid.strip():
                raise ValueError(
                    "LangBot did not provide a trusted plugin installation capability"
                )
            handler.bind_action_context(
                runtime_binding.for_installation(installation_uuid.strip())
            )

        # Register the plugin container BEFORE calling initialize_plugin so
        # that storage API calls during initialize() can resolve the owner.
        plugin_container._runtime_plugin_handler = handler
        plugin_container.debug = bool(handler.debug_plugin)
        plugin_container.install_source = plugin_settings.get("install_source", "")
        plugin_container.install_info = plugin_settings.get("install_info", {})
        if installation_binding is not None:
            assert installation_runtime is not None
            installation_runtime.plugin_container = plugin_container
            installation_runtime.plugin_handler = handler
            self._binding_by_container_id[id(plugin_container)] = installation_binding
        else:
            self.plugins.append(plugin_container)

        try:
            # initialize plugin
            await handler.initialize_plugin(plugin_settings)

        # refresh plugin container from plugin (components may have changed)
        plugin_container_data = await handler.get_plugin_container()
        refreshed = runtime_plugin_container.PluginContainer.from_dict(
            plugin_container_data
        )
        refreshed_author = str(refreshed.manifest.metadata.author or "").strip()
        refreshed_name = str(refreshed.manifest.metadata.name or "").strip()
        if (refreshed_author, refreshed_name) != (plugin_author, plugin_name):
            if installation_binding is not None:
                assert installation_runtime is not None
                installation_runtime.plugin_container = None
                installation_runtime.plugin_handler = None
                self._binding_by_container_id.pop(id(plugin_container), None)
            else:
                self.plugins.remove(plugin_container)
            raise ValueError("Plugin changed its manifest identity after registration")
        plugin_container.components = refreshed.components
        plugin_container.manifest = refreshed.manifest
        plugin_container.status = refreshed.status

    async def remove_plugin_container(
        self,
        plugin_container: runtime_plugin_container.PluginContainer,
    ):
        if plugin_container._runtime_plugin_handler is not None:
            await self.remove_plugin_handler(plugin_container._runtime_plugin_handler)

        binding = self._binding_by_container_id.pop(id(plugin_container), None)
        if binding is not None:
            runtime = self._installations.get(binding)
            if runtime is not None:
                runtime.plugin_container = None
                runtime.plugin_handler = None
        elif plugin_container in self.plugins:
            self.plugins.remove(plugin_container)

    async def restart_plugin(
        self,
        plugin_author: str,
        plugin_name: str,
    ):
        operation_lock = self._get_plugin_operation_lock(plugin_author, plugin_name)
        async with operation_lock:
            async for progress in self._restart_plugin_unlocked(
                plugin_author, plugin_name
            ):
                yield progress

    async def _restart_plugin_unlocked(
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
        operation_lock = self._get_plugin_operation_lock(plugin_author, plugin_name)
        async with operation_lock:
            async for progress in self._delete_plugin_unlocked(
                plugin_author, plugin_name
            ):
                yield progress

    async def _delete_plugin_unlocked(
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
        for runtime in list(self._installations.values()):
            await self._stop_installation_worker(runtime)
        for plugin in self.plugins:
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

        for plugin in self._plugins_for_current_scope():
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
            trusted_query_id = event_context.query_id
            trusted_query_uuid = event_context.query_uuid
            resp = await plugin._runtime_plugin_handler.emit_event(
                event_context.model_dump()
            )

            if resp["emitted"]:
                emitted_plugins.append(plugin)

            event_context = EventContext.model_validate(resp["event_context"])
            if event_context.query_id != trusted_query_id:
                raise ValueError("Plugin changed EventContext query_id")
            if trusted_query_uuid is not None:
                if event_context.query_uuid not in (None, trusted_query_uuid):
                    raise ValueError("Plugin changed EventContext query_uuid")
                event_context.query_uuid = trusted_query_uuid
                event_context.event.query_uuid = trusted_query_uuid
            binding = plugin._runtime_plugin_handler.bound_action_context
            if binding is not None:
                event_context.inherit_execution_scope(binding)
                event_context.event.inherit_execution_scope(binding)
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
        self,
        include_plugins: list[str] | None = None,
        *,
        binding: InstallationBinding | None = None,
    ) -> list[ComponentManifest]:
        tools: list[ComponentManifest] = []

        plugins = (
            self.plugins_for_binding(binding)
            if binding is not None
            else self._plugins_for_current_scope()
        )
        for plugin in plugins:
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
        query_uuid: str | None = None,
        binding: InstallationBinding | None = None,
    ) -> dict[str, typing.Any]:
        plugins = (
            self.plugins_for_binding(binding)
            if binding is not None
            else self._plugins_for_current_scope()
        )
        for plugin in plugins:
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

                    if query_uuid is None:
                        resp = await plugin._runtime_plugin_handler.call_tool(
                            tool_name,
                            tool_parameters,
                            session,
                            query_id,
                        )
                    else:
                        resp = await plugin._runtime_plugin_handler.call_tool(
                            tool_name,
                            tool_parameters,
                            session,
                            query_id,
                            query_uuid,
                        )

                    return resp["tool_response"]

        return {}

    async def list_commands(
        self,
        include_plugins: list[str] | None = None,
        *,
        binding: InstallationBinding | None = None,
    ) -> list[ComponentManifest]:
        commands: list[ComponentManifest] = []

        plugins = (
            self.plugins_for_binding(binding)
            if binding is not None
            else self._plugins_for_current_scope()
        )
        for plugin in plugins:
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
        for plugin in self._plugins_for_current_scope():
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

        for plugin in self._plugins_for_current_scope():
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

        for plugin in self._plugins_for_current_scope():
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
