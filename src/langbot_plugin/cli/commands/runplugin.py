from __future__ import annotations

import os
import asyncio

from langbot_plugin.utils.discover.engine import ComponentDiscoveryEngine
from langbot_plugin.cli.run.controller import PluginRuntimeController


async def arun_plugin_process() -> None:
    
    discovery_engine = ComponentDiscoveryEngine()

    if not os.path.exists("manifest.yaml"):
        print("Plugin manifest not found")
        return

    plugin_manifest = discovery_engine.load_component_manifest(
        path="manifest.yaml",
        owner="builtin",
        no_save=True,
    )

    if plugin_manifest is None:
        print("Plugin manifest not found")
        return

    controller = PluginRuntimeController(plugin_manifest)
    await controller.mount()

    await controller.run()


def run_plugin_process() -> None:
    asyncio.run(arun_plugin_process())
    