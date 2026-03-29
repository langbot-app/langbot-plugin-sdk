from __future__ import annotations

import time

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


async def download_plugin_streaming(
    plugin_author: str, plugin_name: str, plugin_version: str
) -> typing.AsyncGenerator[dict[str, typing.Any], None]:
    """Download plugin with streaming progress.

    Yields dicts with keys: downloaded, total, speed, done, data (only when done=True).
    """
    cloud_service_url = runtime_settings.cloud_service_url
    url = f"{cloud_service_url}/api/v1/marketplace/plugins/download/{plugin_author}/{plugin_name}/{plugin_version}"

    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        async with client.stream("GET", url) as response:
            assert response.status_code == 200, (
                f"Failed to download plugin: HTTP {response.status_code}"
            )

            total = int(response.headers.get("content-length", 0))
            downloaded = 0
            chunks: list[bytes] = []
            start_time = time.time()

            async for chunk in response.aiter_bytes(chunk_size=8192):
                chunks.append(chunk)
                downloaded += len(chunk)
                elapsed = time.time() - start_time
                speed = downloaded / elapsed if elapsed > 0 else 0

                yield {
                    "downloaded": downloaded,
                    "total": total,
                    "speed": speed,
                    "done": False,
                }

        yield {
            "downloaded": downloaded,
            "total": total if total > 0 else downloaded,
            "speed": 0,
            "done": True,
            "data": b"".join(chunks),
        }


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
