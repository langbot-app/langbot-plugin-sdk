from __future__ import annotations

from typing import Any
import typing

import pydantic

import langbot_plugin.api.entities.builtin.provider.session as provider_session
from langbot_plugin.api.entities.builtin.command import errors
import langbot_plugin.api.entities.builtin.platform.message as platform_message


class CommandReturn(pydantic.BaseModel):
    """命令返回值"""

    text: typing.Optional[str] = None
    """文本
    """

    image_base64: typing.Optional[str] = None
    """图片Base64"""

    image_url: typing.Optional[str] = None
    """图片链接
    """

    file_url: typing.Optional[str] = None
    """文件链接
    """

    file_name: typing.Optional[str] = None
    """文件名称
    """

    error: typing.Optional[errors.CommandError] = None
    """错误，保留供系统使用，插件逻辑报错请自行使用 text 传递
    """

    class Config:
        arbitrary_types_allowed = True


class ExecuteContext(pydantic.BaseModel):
    """单次命令执行上下文"""

    query_id: int
    """请求ID"""

    session: provider_session.Session
    """本次消息所属的会话对象"""

    command_text: str
    """命令完整文本（删除命令触发前缀）"""

    full_command_text: str
    """命令完整文本"""

    command: str
    """命令名称"""

    crt_command: str
    """当前命令
    
    多级命令中crt_command为当前命令，command为根命令。
    例如：!plugin on Webwlkr
    处理到plugin时，command为plugin，crt_command为plugin
    处理到on时，command为plugin，crt_command为on
    """

    params: list[str]
    """命令参数
    
    整个命令以空格分割后的参数列表
    """

    crt_params: list[str]
    """当前命令参数

    多级命令中crt_params为当前命令参数，params为根命令参数。
    例如：!plugin on Webwlkr
    处理到plugin时，params为['on', 'Webwlkr']，crt_params为['on', 'Webwlkr']
    处理到on时，params为['on', 'Webwlkr']，crt_params为['Webwlkr']
    """

    privilege: int
    """发起人权限"""

    def shift(self) -> ExecuteContext:
        """Shift the command context."""
        self.crt_command = self.crt_params[0] if len(self.crt_params) > 0 else ""
        self.crt_params = self.crt_params[1:] if len(self.crt_params) > 0 else []
        return self

    # ========== 插件可调用的 API ==========
    async def reply(
        self, message_chain: platform_message.MessageChain, quote_origin: bool = False
    ):
        """Reply to the message request

        Args:
            message_chain (platform.types.MessageChain): LangBot message chain
            quote_origin (bool): Whether to quote the original message
        """

    async def get_bot_uuid(self) -> str:
        """Get the bot uuid"""

    async def set_query_var(self, key: str, value: Any):
        """Set a query variable"""

    async def get_query_var(self, key: str) -> Any:
        """Get a query variable"""

    async def get_query_vars(self) -> dict[str, Any]:
        """Get all query variables"""

    async def create_new_conversation(self) -> dict[str, Any]:
        """Create a new conversation"""
