from __future__ import annotations

import os
import asyncio
import dotenv
import logging

from langbot_plugin.utils.discover.engine import ComponentDiscoveryEngine
from langbot_plugin.cli.run.controller import PluginRuntimeController
from langbot_plugin.cli.i18n import cli_print


async def arun_plugin_process(stdio: bool = False, prod_mode: bool = False) -> None:
    # read .env file
    dotenv.load_dotenv(".env")

    discovery_engine = ComponentDiscoveryEngine()

    if not os.path.exists("manifest.yaml"):
        cli_print("manifest_not_found")
        return

    plugin_manifest = discovery_engine.load_component_manifest(
        path="manifest.yaml",
        owner="builtin",
        no_save=True,
    )

    if plugin_manifest is None:
        cli_print("manifest_not_found")
        return

    ws_debug_url = ""

    if not stdio:
        ws_debug_url = os.getenv("DEBUG_RUNTIME_WS_URL", os.getenv("RUNTIME_WS_URL", ""))
        if ws_debug_url == "":
            cli_print("debug_url_not_set")
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
        prod_mode,
    )

    controller_run_task = asyncio.create_task(controller.run())
    await controller.mount()

    await controller_run_task


def run_plugin_process(stdio: bool = False, prod_mode: bool = False) -> None:
    # Configure logging for plugin process
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s.%(msecs)03d] (PluginProcess) %(filename)s (%(lineno)d) - [%(levelname)s] : %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    try:
        asyncio.run(arun_plugin_process(stdio, prod_mode))
    except asyncio.CancelledError:
        cli_print("plugin_process_cancelled")
        return
    except KeyboardInterrupt:
        cli_print("keyboard_interrupt")
        return
