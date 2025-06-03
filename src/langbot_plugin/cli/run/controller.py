from __future__ import annotations

import typing

from langbot_plugin.api.definition.components.manifest import ComponentManifest
from langbot_plugin.runtime.plugin.container import PluginContainer, RuntimeContainerStatus


class PluginRuntimeController:
    """The controller for running plugins."""

    plugin_container: PluginContainer

    def __init__(self, plugin_manifest: ComponentManifest) -> None:
        self.plugin_container = PluginContainer(
            manifest=plugin_manifest,
            plugin_instance=None,
            enabled=True,
            priority=0,
            plugin_config={},
            status=RuntimeContainerStatus.UNMOUNTED,
            components=[],
        )

    async def mount(self) -> None:
        pass

    async def run(self) -> None:
        pass