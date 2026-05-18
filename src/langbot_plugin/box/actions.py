"""Box-specific action types for the action RPC protocol."""

from __future__ import annotations

from langbot_plugin.entities.io.actions.enums import ActionType


class LangBotToBoxAction(ActionType):
    """Actions sent from LangBot to the Box runtime."""

    INIT = "box_init"  # Initialize with full box config (highest priority)
    HEALTH = "box_health"
    STATUS = "box_status"
    EXEC = "box_exec"
    CREATE_SESSION = "box_create_session"
    GET_SESSION = "box_get_session"
    GET_SESSIONS = "box_get_sessions"
    DELETE_SESSION = "box_delete_session"
    START_MANAGED_PROCESS = "box_start_managed_process"
    GET_MANAGED_PROCESS = "box_get_managed_process"
    STOP_MANAGED_PROCESS = "box_stop_managed_process"
    GET_BACKEND_INFO = "box_get_backend_info"
    LIST_SKILLS = "box_list_skills"
    GET_SKILL = "box_get_skill"
    CREATE_SKILL = "box_create_skill"
    UPDATE_SKILL = "box_update_skill"
    DELETE_SKILL = "box_delete_skill"
    SCAN_SKILL_DIRECTORY = "box_scan_skill_directory"
    LIST_SKILL_FILES = "box_list_skill_files"
    READ_SKILL_FILE = "box_read_skill_file"
    WRITE_SKILL_FILE = "box_write_skill_file"
    PREVIEW_SKILL_ZIP = "box_preview_skill_zip"
    INSTALL_SKILL_ZIP = "box_install_skill_zip"
    SHUTDOWN = "box_shutdown"
