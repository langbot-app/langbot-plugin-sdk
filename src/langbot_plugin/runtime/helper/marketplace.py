from __future__ import annotations

import httpx
from langbot_plugin.runtime.settings import settings as runtime_settings
import typing
from langbot_plugin.entities import marketplace as entities_marketplace


async def get_plugin_info(
    plugin_author: str, plugin_name: str
) -> entities_marketplace.PluginInfo:
    cloud_service_url = runtime_settings.cloud_service_url
    url = (
        f"{cloud_service_url}/api/v1/marketplace/plugins/{plugin_author}/{plugin_name}"
    )
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        assert response.status_code == 200, (
            f"Failed to get plugin info: {response.text}"
        )
        assert response.json()["code"] == 0, (
            f"Failed to get plugin info: {response.json()['msg']}"
        )
        return entities_marketplace.PluginInfo.model_validate(
            response.json()["data"]["plugin"]
        )


async def download_plugin(
    plugin_author: str, plugin_name: str, plugin_version: str
) -> bytes:
    cloud_service_url = runtime_settings.cloud_service_url
    url = f"{cloud_service_url}/api/v1/marketplace/plugins/download/{plugin_author}/{plugin_name}/{plugin_version}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        assert response.status_code == 200, (
            f"Failed to download plugin: {response.text}"
        )
        return response.content


async def list_plugins() -> list[entities_marketplace.PluginInfo]:
    cloud_service_url = runtime_settings.cloud_service_url
    url = f"{cloud_service_url}/api/v1/marketplace/plugins"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        assert response.status_code == 200, f"Failed to list plugins: {response.text}"
        assert response.json()["code"] == 0, (
            f"Failed to list plugins: {response.json()['msg']}"
        )
        return [
            entities_marketplace.PluginInfo.model_validate(plugin)
            for plugin in response.json()["data"]["plugins"]
        ]
