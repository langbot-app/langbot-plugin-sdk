"""Fail early when CI selects an SDK older than LocalAgent's reasoning API."""

from __future__ import annotations

import inspect

import pytest
from langbot_plugin.api.proxies.langbot_api import LangBotAPIProxy
from langbot_plugin.api.proxies.runner.resources import AgentRunResourceAPIMixin


@pytest.mark.parametrize(
    ("proxy", "method"),
    [(AgentRunResourceAPIMixin, "count_tokens")]
    + [
        (proxy, method)
        for proxy in (LangBotAPIProxy, AgentRunResourceAPIMixin)
        for method in ("invoke_llm", "invoke_llm_with_usage", "invoke_llm_stream", "invoke_llm_stream_events")
    ],
)
def test_sdk_accepts_optional_per_call_reasoning(proxy, method):
    signature = inspect.signature(getattr(proxy, method))
    assert "reasoning_level" in signature.parameters, f"{proxy.__name__}.{method} requires the reasoning-aware SDK"
    parameter = signature.parameters["reasoning_level"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is None
