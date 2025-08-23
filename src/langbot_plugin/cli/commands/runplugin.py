from __future__ import annotations

import os
import asyncio
import dotenv

from langbot_plugin.utils.discover.engine import ComponentDiscoveryEngine
from langbot_plugin.cli.run.controller import PluginRuntimeController


async def arun_plugin_process(stdio: bool = False) -> None:
    # read .env file
    dotenv.load_dotenv(".env")

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

    ws_debug_url = ""

    if not stdio:
        ws_debug_url = os.getenv("DEBUG_RUNTIME_WS_URL", "")
        if ws_debug_url == "":
            print("DEBUG_RUNTIME_WS_URL is not set in .env file")
            return

    # discover components
    component_manifests = []

    for comp_group in plugin_manifest.spec["components"].values():
        manifests = discovery_engine.load_blueprint_comp_group(
            comp_group, owner="builtin", no_save=True
        )
        component_manifests.extend(manifests)

    controller = PluginRuntimeController(
        plugin_manifest,
        component_manifests,
        stdio,
        ws_debug_url,
    )

    controller_run_task = asyncio.create_task(controller.run())
    await controller.mount()

    await controller_run_task


def run_plugin_process(stdio: bool = False) -> None:

    try:
        asyncio.run(arun_plugin_process(stdio))
    except asyncio.CancelledError:
        print("Plugin process cancelled")
        return
    except KeyboardInterrupt:
        print("Keyboard interrupt, exiting...")
        return