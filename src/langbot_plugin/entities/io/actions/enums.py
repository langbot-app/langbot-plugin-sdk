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

    # ========== APIs for plugin code ==========
    """Event APIs"""
    REPLY_MESSAGE = "reply_message"
    GET_BOT_UUID = "get_bot_uuid"

    """Query APIs"""
    SET_QUERY_VAR = "set_query_var"
    GET_QUERY_VAR = "get_query_var"
    GET_QUERY_VARS = "get_query_vars"

    """LangBot APIs"""
    GET_LANGBOT_VERSION = "get_langbot_version"

    GET_BOTS = "get_bots"
    GET_BOT_INFO = "get_bot_info"
    SEND_MESSAGE = "send_message"

    GET_LLM_MODELS = "get_llm_models"
    GET_LLM_MODEL_INFO = "get_llm_model_info"
    INVOKE_LLM = "invoke_llm"
    INVOKE_LLM_STREAMING = "invoke_llm_streaming"


class RuntimeToPluginAction(ActionType):
    """The action from runtime to plugin."""

    INITIALIZE_PLUGIN = "initialize_plugin"
    GET_PLUGIN_CONTAINER = "get_plugin_container"
    EMIT_EVENT = "emit_event"
    CALL_TOOL = "call_tool"
    EXECUTE_COMMAND = "execute_command"


class LangBotToRuntimeAction(ActionType):
    """The action from langbot to runtime."""

    LIST_PLUGINS = "list_plugins"
    INSTALL_PLUGIN = "install_plugin"
    EMIT_EVENT = "emit_event"
    LIST_TOOLS = "list_tools"
    CALL_TOOL = "call_tool"
    LIST_COMMANDS = "list_commands"
    EXECUTE_COMMAND = "execute_command"


class RuntimeToLangBotAction(ActionType):
    """The action from runtime to langbot."""

    GET_PLUGIN_SETTINGS = "get_plugin_settings"
