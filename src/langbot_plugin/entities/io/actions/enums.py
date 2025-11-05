from __future__ import annotations

from enum import Enum


class ActionType(Enum):
    pass


class CommonAction(ActionType):
    """The common action."""

    PING = "ping"
    HEARTBEAT = "heartbeat"
    FILE_CHUNK = "__file_chunk"


class PluginToRuntimeAction(ActionType):
    """The action from plugin to runtime."""

    REGISTER_PLUGIN = "register_plugin"

    # ========== APIs for plugin code ==========

    """Query-based APIs"""
    REPLY_MESSAGE = "reply_message"
    GET_BOT_UUID = "get_bot_uuid"
    SET_QUERY_VAR = "set_query_var"
    GET_QUERY_VAR = "get_query_var"
    GET_QUERY_VARS = "get_query_vars"
    CREATE_NEW_CONVERSATION = "create_new_conversation"

    """LangBot APIs"""
    GET_LANGBOT_VERSION = "get_langbot_version"

    GET_BOTS = "get_bots"
    GET_BOT_INFO = "get_bot_info"
    SEND_MESSAGE = "send_message"

    GET_LLM_MODELS = "get_llm_models"
    # GET_LLM_MODEL_INFO = "get_llm_model_info"
    INVOKE_LLM = "invoke_llm"
    # INVOKE_LLM_STREAMING = "invoke_llm_streaming"

    SET_PLUGIN_STORAGE = "set_plugin_storage"
    GET_PLUGIN_STORAGE = "get_plugin_storage"
    GET_PLUGIN_STORAGE_KEYS = "get_plugin_storage_keys"
    DELETE_PLUGIN_STORAGE = "delete_plugin_storage"

    SET_WORKSPACE_STORAGE = "set_workspace_storage"
    GET_WORKSPACE_STORAGE = "get_workspace_storage"
    GET_WORKSPACE_STORAGE_KEYS = "get_workspace_storage_keys"
    DELETE_WORKSPACE_STORAGE = "delete_workspace_storage"

    GET_CONFIG_FILE = "get_config_file"

    LIST_PLUGINS_MANIFEST = "list_plugins_manifest"
    LIST_COMMANDS = "list_commands"
    LIST_TOOLS = "list_tools"


class RuntimeToPluginAction(ActionType):
    """The action from runtime to plugin."""

    INITIALIZE_PLUGIN = "initialize_plugin"
    GET_PLUGIN_CONTAINER = "get_plugin_container"
    GET_PLUGIN_ICON = "get_plugin_icon"
    EMIT_EVENT = "emit_event"
    CALL_TOOL = "call_tool"
    EXECUTE_COMMAND = "execute_command"


class LangBotToRuntimeAction(ActionType):
    """The action from langbot to runtime."""

    LIST_PLUGINS = "list_plugins"
    GET_PLUGIN_INFO = "get_plugin_info"
    GET_PLUGIN_ICON = "get_plugin_icon"
    INSTALL_PLUGIN = "install_plugin"
    RESTART_PLUGIN = "restart_plugin"
    DELETE_PLUGIN = "delete_plugin"
    UPGRADE_PLUGIN = "upgrade_plugin"
    EMIT_EVENT = "emit_event"
    LIST_TOOLS = "list_tools"
    CALL_TOOL = "call_tool"
    LIST_COMMANDS = "list_commands"
    EXECUTE_COMMAND = "execute_command"


class RuntimeToLangBotAction(ActionType):
    """The action from runtime to langbot."""

    INITIALIZE_PLUGIN_SETTINGS = "initialize_plugin_settings"
    GET_PLUGIN_SETTINGS = "get_plugin_settings"

    SET_BINARY_STORAGE = "set_binary_storage"
    GET_BINARY_STORAGE = "get_binary_storage"
    GET_BINARY_STORAGE_KEYS = "get_binary_storage_keys"
    DELETE_BINARY_STORAGE = "delete_binary_storage"

    GET_CONFIG_FILE = "get_config_file"
