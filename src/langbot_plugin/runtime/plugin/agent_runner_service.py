from __future__ import annotations

import asyncio
import logging
import typing

from langbot_plugin.api.definition.components.agent_runner.runner import AgentRunner
from langbot_plugin.api.entities.builtin.agent_runner.manifest import (
    AgentRunnerManifest,
)
from langbot_plugin.api.entities.builtin.agent_runner.result import AgentRunResult
from langbot_plugin.entities.io.actions.enums import RuntimeToPluginAction
from langbot_plugin.entities.io.errors import ActionCallTimeoutError
from langbot_plugin.runtime.plugin import container as runtime_plugin_container
from langbot_plugin.utils.deadline import (
    anext_with_deadline,
    remaining_deadline_seconds,
)

logger = logging.getLogger(__name__)


def _remaining_deadline_seconds(context: dict[str, typing.Any]) -> float | None:
    return remaining_deadline_seconds((context.get("runtime") or {}).get("deadline_at"))


def _runner_action_timeout(context: dict[str, typing.Any]) -> float:
    remaining = _remaining_deadline_seconds(context)
    if remaining is None:
        return 300
    if remaining <= 0:
        return 0.001
    return max(remaining + 1.0, 0.001)


def _ensure_result_sequence(
    result_data: dict[str, typing.Any],
    sequence: int,
) -> dict[str, typing.Any]:
    if not isinstance(result_data, dict):
        return result_data
    result_data = dict(result_data)
    result_data["sequence"] = sequence
    return result_data


class AgentRunnerRuntimeService:
    """Discovers AgentRunner components and forwards Host runs to plugin processes."""

    def __init__(
        self,
        *,
        plugins: typing.Callable[
            [], typing.Iterable[runtime_plugin_container.PluginContainer]
        ],
        find_plugin: typing.Callable[
            [str, str], runtime_plugin_container.PluginContainer | None
        ],
    ):
        self._plugins = plugins
        self._find_plugin = find_plugin

    async def list_agent_runners(
        self, include_plugins: list[str] | None = None
    ) -> list[dict[str, typing.Any]]:
        """List available AgentRunner components using Protocol v1 transport shape."""
        runners: list[dict[str, typing.Any]] = []

        for plugin in self._plugins():
            if not self._is_plugin_ready(plugin):
                continue

            if (
                include_plugins is not None
                and self._plugin_id(plugin) not in include_plugins
            ):
                continue

            for component in plugin.components:
                if component.manifest.kind != AgentRunner.__kind__:
                    continue

                runner_entry = self._build_runner_entry(plugin, component)
                if runner_entry is not None:
                    runners.append(runner_entry)

        return runners

    async def run_agent(
        self,
        plugin_author: str,
        plugin_name: str,
        runner_name: str,
        context: dict[str, typing.Any],
    ) -> typing.AsyncGenerator[dict[str, typing.Any], None]:
        """Forward a Host AgentRunner run to the selected plugin process."""
        run_id = context.get("run_id", "unknown")
        target_plugin = self._find_plugin(plugin_author, plugin_name)

        if target_plugin is None:
            yield self._run_failed(
                run_id=run_id,
                error=f"Plugin {plugin_author}/{plugin_name} not found",
                code="runner.plugin_not_found",
            )
            return

        if not target_plugin.enabled:
            yield self._run_failed(
                run_id=run_id,
                error=f"Plugin {plugin_author}/{plugin_name} is disabled",
                code="runner.plugin_disabled",
            )
            return

        if (
            target_plugin.status
            != runtime_plugin_container.RuntimeContainerStatus.INITIALIZED
        ):
            yield self._run_failed(
                run_id=run_id,
                error=f"Plugin {plugin_author}/{plugin_name} is not initialized",
                code="runner.plugin_not_initialized",
            )
            return

        if self._find_runner_component(target_plugin, runner_name) is None:
            yield self._run_failed(
                run_id=run_id,
                error=f"AgentRunner {runner_name} not found in plugin {plugin_author}/{plugin_name}",
                code="runner.not_found",
            )
            return

        if target_plugin._runtime_plugin_handler is None:
            yield self._run_failed(
                run_id=run_id,
                error=f"Plugin {plugin_author}/{plugin_name} has no runtime handler",
                code="runner.handler_not_found",
            )
            return

        sequence = 0
        try:
            gen = target_plugin._runtime_plugin_handler.call_action_generator(
                RuntimeToPluginAction.RUN_AGENT,
                {
                    "runner_name": runner_name,
                    "context": context,
                },
                timeout=_runner_action_timeout(context),
            )

            while True:
                try:
                    result_data = await anext_with_deadline(
                        gen,
                        (context.get("runtime") or {}).get("deadline_at"),
                    )
                except StopAsyncIteration:
                    break
                sequence += 1
                yield _ensure_result_sequence(result_data, sequence)

        except (asyncio.TimeoutError, ActionCallTimeoutError):
            yield self._run_failed(
                run_id=run_id,
                error="Agent runner timed out",
                code="runner.timeout",
                retryable=True,
                sequence=sequence + 1,
            )
        except Exception as e:
            logger.exception(
                "Error forwarding AgentRunner %s/%s:%s",
                plugin_author,
                plugin_name,
                runner_name,
            )
            yield self._run_failed(
                run_id=run_id,
                error=f"Error forwarding to plugin: {e}",
                code="runner.forward_exception",
                sequence=sequence + 1,
            )

    def _build_runner_entry(
        self,
        plugin: runtime_plugin_container.PluginContainer,
        component: runtime_plugin_container.ComponentContainer,
    ) -> dict[str, typing.Any] | None:
        spec = component.manifest.spec or {}
        runner_cls = (
            type(component.component_instance)
            if isinstance(component.component_instance, AgentRunner)
            else AgentRunner
        )
        config_schema = spec.get("config") or runner_cls.get_config_schema()
        runner_name = component.manifest.metadata.name
        runner_id = (
            "plugin:"
            f"{plugin.manifest.metadata.author}/"
            f"{plugin.manifest.metadata.name}/"
            f"{runner_name}"
        )

        try:
            runner_manifest = AgentRunnerManifest(
                id=runner_id,
                name=runner_name,
                label=component.manifest.metadata.label.to_dict(),
                description=component.manifest.metadata.description.to_dict()
                if component.manifest.metadata.description is not None
                else None,
                capabilities=spec.get("capabilities") or {},
                permissions=spec.get("permissions") or {},
                config_schema=config_schema,
                metadata={
                    "plugin_author": plugin.manifest.metadata.author,
                    "plugin_name": plugin.manifest.metadata.name,
                    "runner_name": runner_name,
                },
            )
        except Exception as exc:
            logger.warning(
                "Skipping invalid AgentRunner manifest %s/%s/%s: %s",
                plugin.manifest.metadata.author,
                plugin.manifest.metadata.name,
                runner_name,
                exc,
            )
            return None

        manifest_data = runner_manifest.model_dump(mode="json")
        return {
            "plugin_author": plugin.manifest.metadata.author,
            "plugin_name": plugin.manifest.metadata.name,
            "runner_name": runner_name,
            "runner_description": manifest_data["description"],
            "manifest": manifest_data,
            "capabilities": manifest_data["capabilities"],
            "permissions": manifest_data["permissions"],
            "config": config_schema,
        }

    def _find_runner_component(
        self,
        plugin: runtime_plugin_container.PluginContainer,
        runner_name: str,
    ) -> runtime_plugin_container.ComponentContainer | None:
        for component in plugin.components:
            if (
                component.manifest.kind == AgentRunner.__kind__
                and component.manifest.metadata.name == runner_name
            ):
                return component
        return None

    @staticmethod
    def _is_plugin_ready(
        plugin: runtime_plugin_container.PluginContainer,
    ) -> bool:
        return (
            plugin.enabled
            and plugin.status
            == runtime_plugin_container.RuntimeContainerStatus.INITIALIZED
        )

    @staticmethod
    def _plugin_id(plugin: runtime_plugin_container.PluginContainer) -> str:
        return f"{plugin.manifest.metadata.author}/{plugin.manifest.metadata.name}"

    @staticmethod
    def _run_failed(
        *,
        run_id: str,
        error: str,
        code: str,
        retryable: bool = False,
        sequence: int = 1,
    ) -> dict[str, typing.Any]:
        return AgentRunResult.run_failed(
            run_id=run_id,
            error=error,
            code=code,
            retryable=retryable,
            sequence=sequence,
        ).model_dump(mode="json")
