from __future__ import annotations

import asyncio
from typing import Any, Literal

from langbot_plugin.runtime.io.controllers.stdio import (
    server as stdio_controller_server,
)
from langbot_plugin.runtime.io.controllers.ws import server as ws_controller_server
from langbot_plugin.runtime.io.handlers import control as control_handler_cls
from langbot_plugin.runtime.plugin import mgr as plugin_mgr_cls
from langbot_plugin.entities.io.context import (
    ActionContext,
    InstallationBinding,
    PluginWorkerPolicy,
    RuntimeIdentity,
)
from langbot_plugin.runtime.security import WorkspaceDebugTokenStore


class RuntimeContext:
    """This class stores the shared context of langbot plugin runtime, for resolving recursive dependencies.

    This module (should) not depend on any other implementation modules.
    """

    stdio_server: stdio_controller_server.StdioServerController | None = (
        None  # stdio control server
    )
    ws_control_server: ws_controller_server.WebSocketServerController | None = (
        None  # ws control
    )
    ws_debug_server: ws_controller_server.WebSocketServerController | None = (
        None  # ws debug server
    )

    control_handler: control_handler_cls.ControlConnectionHandler | None

    plugin_mgr: plugin_mgr_cls.PluginManager

    ws_debug_port: int = 5401  # Default debug port

    def __init__(self):
        self.control_handler = None
        self.blocking_executor: Any | None = None
        self.event_loop_monitor: Any | None = None
        self.runtime_identity: RuntimeIdentity | None = None
        self.worker_policy: PluginWorkerPolicy | None = None
        self.runtime_profile: Literal["oss_dev", "shared"] | None = None
        self._runtime_configuration_ready = asyncio.Event()

        # Compatibility fence for the still-global PluginManager. It is not
        # the control connection identity and is never populated by the
        # instance-scoped handshake. The first authorized tenant action pins
        # this legacy manager to one Workspace/generation; another Workspace
        # fails closed until manager dispatch is installation-scoped.
        self._legacy_workspace_binding: ActionContext | None = None
        self._workspace_binding_ready = asyncio.Event()
        self._installation_bindings: dict[str, InstallationBinding] = {}
        self._installation_watermarks: dict[str, InstallationBinding] = {}
        self.workspace_debug_tokens = WorkspaceDebugTokenStore()

    def get_runtime_resource_stats(self) -> dict[str, Any]:
        """Return aggregate O(1) counters safe for public health probes."""

        plugin_manager = self.plugin_mgr
        handlers = getattr(
            plugin_manager,
            "plugin_handlers",
            getattr(plugin_manager, "handlers", ()),
        )
        event_loop_monitor = self.event_loop_monitor
        return {
            "event_loop": (
                event_loop_monitor.snapshot() if event_loop_monitor is not None else {}
            ),
            "blocking_executor": (
                self.blocking_executor.snapshot()
                if self.blocking_executor is not None
                else {}
            ),
            "plugin_handlers": len(handlers),
            "legacy_supervisors": len(
                getattr(plugin_manager, "_plugin_supervisors", ())
            ),
            "installation_runtimes": len(getattr(plugin_manager, "_installations", ())),
            "pending_registrations": len(
                getattr(plugin_manager, "_pending_registrations", ())
            ),
            "restart_coordinator": (
                plugin_manager.restart_coordinator.snapshot()
                if hasattr(plugin_manager, "restart_coordinator")
                else {"configured": False}
            ),
        }

    @property
    def workspace_binding(self) -> ActionContext | None:
        """Legacy single-Workspace manager fence (not Runtime identity)."""

        return self._legacy_workspace_binding

    def activate_control_handler(
        self,
        handler: control_handler_cls.ControlConnectionHandler,
    ) -> control_handler_cls.ControlConnectionHandler | None:
        """Make ``handler`` authoritative and atomically fence its predecessor."""

        previous = self.control_handler
        self.control_handler = handler
        return previous

    def is_active_control_handler(
        self,
        handler: control_handler_cls.ControlConnectionHandler,
    ) -> bool:
        return self.control_handler is handler

    def bind_runtime(
        self,
        runtime_identity: RuntimeIdentity | dict,
        worker_policy: PluginWorkerPolicy | dict,
        runtime_profile: Literal["oss_dev", "shared"] = "oss_dev",
    ) -> tuple[RuntimeIdentity, PluginWorkerPolicy]:
        """Bind this process once to an instance identity and worker policy."""

        identity = RuntimeIdentity.model_validate(runtime_identity)
        policy = PluginWorkerPolicy.model_validate(worker_policy)

        if self.runtime_identity is not None and self.runtime_identity != identity:
            raise ValueError("Plugin Runtime identity cannot be rebound")
        if self.worker_policy is not None and self.worker_policy != policy:
            raise ValueError("Plugin worker policy cannot be changed at runtime")
        if self.runtime_profile is not None and self.runtime_profile != runtime_profile:
            raise ValueError("Plugin Runtime profile cannot be changed at runtime")

        self.runtime_identity = identity
        self.worker_policy = policy
        self.runtime_profile = runtime_profile
        self._runtime_configuration_ready.set()
        return identity, policy

    async def wait_for_runtime_configuration(
        self,
    ) -> tuple[RuntimeIdentity, PluginWorkerPolicy]:
        """Wait for the instance-scoped control handshake."""

        await self._runtime_configuration_ready.wait()
        if self.runtime_identity is None or self.worker_policy is None:
            raise RuntimeError("Plugin Runtime configuration is unavailable")
        return self.runtime_identity, self.worker_policy

    def bind_workspace(
        self,
        action_context: ActionContext | dict,
    ) -> ActionContext:
        """Pin the legacy global manager to one Workspace/generation.

        New control handshakes must not call this method. It remains only for
        the pre-installation-scoped manager and is intentionally fail-closed.
        """

        binding = ActionContext.model_validate(action_context).without_installation()
        if (
            self.runtime_identity is not None
            and binding.instance_uuid != self.runtime_identity.instance_uuid
        ):
            raise ValueError("Workspace binding does not match Runtime instance")
        if (
            self._legacy_workspace_binding is not None
            and self._legacy_workspace_binding != binding
        ):
            raise ValueError(
                "Legacy PluginManager cannot dispatch another Workspace safely"
            )
        self._legacy_workspace_binding = binding
        self._workspace_binding_ready.set()
        return binding

    def authorize_installation_binding(
        self,
        action_context: InstallationBinding | dict,
    ) -> InstallationBinding:
        """Authorize one explicit tenant action against immutable fences.

        This first slice deliberately keeps the existing manager constrained to
        one Workspace. Multiple installations in that Workspace are accepted,
        but each installation UUID is permanently pinned to its complete tuple.
        """

        binding = InstallationBinding.model_validate(action_context)
        if self.runtime_identity is None or self.worker_policy is None:
            raise ValueError("SET_RUNTIME_CONFIG must complete before tenant actions")
        if binding.instance_uuid != self.runtime_identity.instance_uuid:
            raise ValueError("Installation binding does not match Runtime instance")

        existing = self._installation_bindings.get(binding.installation_uuid)
        if existing is not None and not existing.same_installation(binding):
            raise ValueError(
                "Plugin installation binding cannot change generation, revision, or artifact"
            )
        if existing is None:
            if self.runtime_profile != "oss_dev":
                raise ValueError("Plugin installation is not present in desired state")
            # Compatibility for the legacy OSS manager only. Shared profile
            # installations must arrive through apply/reconcile first.
            self.bind_workspace(binding)
            self._installation_bindings[binding.installation_uuid] = binding
        return binding

    def validate_installation_candidate(
        self,
        action_context: InstallationBinding | dict,
    ) -> InstallationBinding:
        """Validate a trusted desired-state transition without applying it."""

        binding = InstallationBinding.model_validate(action_context)
        if self.runtime_identity is None or self.worker_policy is None:
            raise ValueError("SET_RUNTIME_CONFIG must complete before desired state")
        if binding.instance_uuid != self.runtime_identity.instance_uuid:
            raise ValueError("Installation binding does not match Runtime instance")

        current = self._installation_bindings.get(binding.installation_uuid)
        if current == binding:
            return binding
        baseline = current or self._installation_watermarks.get(
            binding.installation_uuid
        )
        if baseline is None:
            assert self.worker_policy is not None
            if (
                len(self._installation_watermarks)
                >= self.worker_policy.max_installations
            ):
                raise ValueError(
                    "Plugin installation fence capacity reached; "
                    "refusing an unbounded desired-state allocation"
                )
            return binding
        if baseline.workspace_uuid != binding.workspace_uuid:
            raise ValueError("Plugin installation cannot move to another Workspace")
        is_new_generation = binding.placement_generation > baseline.placement_generation
        is_new_revision = (
            binding.placement_generation == baseline.placement_generation
            and binding.runtime_revision > baseline.runtime_revision
        )
        if not is_new_generation and not is_new_revision:
            raise ValueError("Plugin installation desired state is stale")
        return binding

    def activate_installation_binding(
        self,
        action_context: InstallationBinding | dict,
    ) -> InstallationBinding | None:
        """Install a newer desired binding and immediately fence its predecessor."""

        binding = self.validate_installation_candidate(action_context)
        previous = self._installation_bindings.get(binding.installation_uuid)
        if (
            previous is None
            and binding.installation_uuid not in self._installation_watermarks
        ):
            assert self.worker_policy is not None
            if (
                len(self._installation_watermarks)
                >= self.worker_policy.max_installations
            ):
                raise ValueError(
                    "Plugin installation fence capacity reached; "
                    "refusing an unbounded desired-state allocation"
                )
        self._installation_bindings[binding.installation_uuid] = binding
        self._installation_watermarks[binding.installation_uuid] = binding
        return previous

    def deactivate_installation_binding(
        self,
        action_context: InstallationBinding | dict,
    ) -> InstallationBinding:
        """Remove exactly the current binding; stale removals fail closed."""

        binding = InstallationBinding.model_validate(action_context)
        current = self._installation_bindings.get(binding.installation_uuid)
        if current != binding:
            raise ValueError("Plugin installation removal binding is stale")
        del self._installation_bindings[binding.installation_uuid]
        self._installation_watermarks[binding.installation_uuid] = binding
        return binding

    def is_current_installation_binding(
        self,
        action_context: InstallationBinding | dict,
    ) -> bool:
        binding = InstallationBinding.model_validate(action_context)
        return self._installation_bindings.get(binding.installation_uuid) == binding

    async def wait_for_workspace_binding(self) -> ActionContext:
        """Wait until LangBot has supplied the trusted Runtime binding."""

        await self._workspace_binding_ready.wait()
        if self._legacy_workspace_binding is None:  # pragma: no cover - Event invariant
            raise RuntimeError("Plugin Runtime Workspace binding is unavailable")
        return self._legacy_workspace_binding
