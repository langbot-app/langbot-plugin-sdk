from __future__ import annotations

from typing import Any

import pydantic

from langbot_plugin.api.entities.builtin.platform import message as platform_message
from langbot_plugin.api.entities.events import BaseEventModel
import langbot_plugin.api.entities.events as events_module


global_eid_index = 0

cached_event_contexts: dict[int, EventContext] = {}


class EventContext(pydantic.BaseModel):
    """事件上下文, 保存此次事件运行的信息"""

    query_id: int
    """请求ID"""

    eid: int = 0
    """事件编号"""

    event_name: str
    """事件名称"""

    event: pydantic.SerializeAsAny[BaseEventModel]
    """此次事件的对象，具体类型为handler注册时指定监听的类型，可查看events.py中的定义"""

    is_prevent_default: bool = False
    """是否阻止默认行为"""

    is_prevent_postorder: bool = False
    """是否阻止后续插件的执行"""

    # ========== APIs for plugins ==========

    ## ========= Query-based APIs =========

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

    ## ========= Event-based APIs from plugin to use =========

    def prevent_default(self):
        """Prevent default behavior"""
        self.is_prevent_default = True

    def prevent_postorder(self):
        """Prevent subsequent plugin execution"""
        self.is_prevent_postorder = True

    # ========== The following methods are reserved for internal use, and plugins should not call them directly ==========

    def is_prevented_default(self):
        """Whether to prevent default behavior"""
        return self.is_prevent_default

    def is_prevented_postorder(self):
        """Whether to prevent subsequent plugin execution"""
        return self.is_prevent_postorder

    @classmethod
    def from_event(cls, event: BaseEventModel) -> EventContext:
        global global_eid_index
        query_id = event.query.query_id
        eid = global_eid_index
        event = event
        event_name = event.__class__.__name__
        is_prevent_default = False
        is_prevent_postorder = False

        obj = cls(
            query_id=query_id,
            eid=eid,
            event_name=event_name,
            event=event,
            is_prevent_default=is_prevent_default,
            is_prevent_postorder=is_prevent_postorder,
        )

        cached_event_contexts[eid] = obj

        global_eid_index += 1

        return obj

    @pydantic.field_validator("event", mode="before")
    def validate_event(cls, v):
        if isinstance(v, BaseEventModel):
            return v

        event_name = v["event_name"]
        event_class = getattr(events_module, event_name)
        event = event_class.model_validate(v)
        return event
