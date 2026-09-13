from __future__ import annotations

from langbot_plugin.api.definition.components.page import (
    Page,
    PageRequest,
    PageResponse,
)

from components.observability import telemetry


class LangRAGObservabilityPage(Page):
    """Static Page backend exposing LangRAG telemetry."""

    async def handle_api(self, request: PageRequest) -> PageResponse:
        endpoint = (request.endpoint or "").rstrip("/") or "/"
        method = (request.method or "GET").upper()

        if endpoint in ("/", "/snapshot") and method == "GET":
            return PageResponse.ok(telemetry.snapshot())

        if endpoint == "/metrics" and method == "GET":
            return PageResponse.ok(
                {
                    "content_type": "text/plain; version=0.0.4",
                    "body": telemetry.prometheus(),
                }
            )

        if endpoint == "/export" and method == "GET":
            return PageResponse.ok(telemetry.snapshot())

        if endpoint == "/clear" and method in ("POST", "DELETE"):
            telemetry.clear()
            return PageResponse.ok(telemetry.snapshot())

        return PageResponse.fail(f"Unknown endpoint: {method} {endpoint}")
