from __future__ import annotations

from enum import Enum


class ActionType(Enum):
    pass


class CommonAction(ActionType):
    """The common action."""

    PING = "ping"
    HEARTBEAT = "heartbeat"


class PluginToRuntimeAction(ActionType):
    """The action from plugin to runtime."""

    REGISTER_PLUGIN = "register_plugin"


class RuntimeToPluginAction(ActionType):
    """The action from runtime to plugin."""

    INITIALIZE_PLUGIN = "initialize_plugin"
    GET_PLUGIN_CONTAINER = "get_plugin_container"
    EMIT_EVENT = "emit_event"
    CALL_TOOL = "call_tool"


class LangBotToRuntimeAction(ActionType):
    """The action from langbot to runtime."""

    LIST_PLUGINS = "list_plugins"
    INSTALL_PLUGIN = "install_plugin"
    EMIT_EVENT = "emit_event"
    LIST_TOOLS = "list_tools"
    CALL_TOOL = "call_tool"


class RuntimeToLangBotAction(ActionType):
    """The action from runtime to langbot."""

    GET_PLUGIN_SETTINGS = "get_plugin_settings"
