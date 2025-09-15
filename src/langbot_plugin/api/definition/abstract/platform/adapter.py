from __future__ import annotations

# MessageSource的适配器
import typing
import abc
import pydantic

import langbot_plugin.api.entities.builtin.platform.message as platform_message
import langbot_plugin.api.entities.builtin.platform.events as platform_events
import langbot_plugin.api.definition.abstract.platform.event_logger as abstract_platform_logger


class AbstractMessagePlatformAdapter(pydantic.BaseModel, metaclass=abc.ABCMeta):
    """消息平台适配器基类"""

    bot_account_id: str = pydantic.Field(default="")
    """机器人账号ID，需要在初始化时设置"""

    config: dict

    logger: abstract_platform_logger.AbstractEventLogger = pydantic.Field(exclude=True)

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @abc.abstractmethod
    async def send_message(
        self, target_type: str, target_id: str, message: platform_message.MessageChain
    ):
        """主动发送消息

        Args:
            target_type (str): 目标类型，`person`或`group`
            target_id (str): 目标ID
            message (platform.types.MessageChain): 消息链
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def reply_message(
        self,
        message_source: platform_events.MessageEvent,
        message: platform_message.MessageChain,
        quote_origin: bool = False,
    ):
        """回复消息

        Args:
            message_source (platform.types.MessageEvent): 消息源事件
            message (platform.types.MessageChain): 消息链
            quote_origin (bool, optional): 是否引用原消息. Defaults to False.
        """
        raise NotImplementedError

    async def reply_message_chunk(
        self,
        message_source: platform_events.MessageEvent,
        bot_message: dict,
        message: platform_message.MessageChain,
        quote_origin: bool = False,
        is_final: bool = False,
    ):
        """回复消息（流式输出）
        Args:
            message_source (platform.types.MessageEvent): 消息源事件
            message_id (int): 消息ID
            message (platform.types.MessageChain): 消息链
            quote_origin (bool, optional): 是否引用原消息. Defaults to False.
            is_final (bool, optional): 流式是否结束. Defaults to False.
        """
        raise NotImplementedError

    async def create_message_card(
        self, message_id: typing.Type[str, int], event: platform_events.MessageEvent
    ) -> bool:
        """创建卡片消息
        Args:
            message_id (str): 消息ID
            event (platform_events.MessageEvent): 消息源事件
        """
        return False

    async def is_muted(self, group_id: int) -> bool:
        """获取账号是否在指定群被禁言"""
        return False

    @abc.abstractmethod
    def register_listener(
        self,
        event_type: typing.Type[platform_events.Event],
        callback: typing.Callable[
            [platform_events.Event, AbstractMessagePlatformAdapter], None
        ],
    ):
        """注册事件监听器

        Args:
            event_type (typing.Type[platform.types.Event]): 事件类型
            callback (typing.Callable[[platform.types.Event], None]): 回调函数，接收一个参数，为事件
        """
        raise NotImplementedError

    @abc.abstractmethod
    def unregister_listener(
        self,
        event_type: typing.Type[platform_events.Event],
        callback: typing.Callable[
            [platform_events.Event, AbstractMessagePlatformAdapter], None
        ],
    ):
        """注销事件监听器

        Args:
            event_type (typing.Type[platform.types.Event]): 事件类型
            callback (typing.Callable[[platform.types.Event], None]): 回调函数，接收一个参数，为事件
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def run_async(self):
        """异步运行"""
        raise NotImplementedError

    async def is_stream_output_supported(self) -> bool:
        """是否支持流式输出"""
        return False

    @abc.abstractmethod
    async def kill(self) -> bool:
        """关闭适配器

        Returns:
            bool: 是否成功关闭，热重载时若此函数返回False则不会重载MessageSource底层
        """
        raise NotImplementedError


class AbstractMessageConverter:
    """消息链转换器基类"""

    @staticmethod
    def yiri2target(message_chain: platform_message.MessageChain):
        """将源平台消息链转换为目标平台消息链

        Args:
            message_chain (platform.types.MessageChain): 源平台消息链

        Returns:
            typing.Any: 目标平台消息链
        """
        raise NotImplementedError

    @staticmethod
    def target2yiri(message_chain: typing.Any) -> platform_message.MessageChain:
        """将目标平台消息链转换为源平台消息链

        Args:
            message_chain (typing.Any): 目标平台消息链

        Returns:
            platform.types.MessageChain: 源平台消息链
        """
        raise NotImplementedError


class AbstractEventConverter:
    """事件转换器基类"""

    @staticmethod
    def yiri2target(event: typing.Type[platform_events.Event]):
        """将源平台事件转换为目标平台事件

        Args:
            event (typing.Type[platform.types.Event]): 源平台事件

        Returns:
            typing.Any: 目标平台事件
        """
        raise NotImplementedError

    @staticmethod
    def target2yiri(event: typing.Any) -> platform_events.Event:
        """将目标平台事件的调用参数转换为源平台的事件参数对象

        Args:
            event (typing.Any): 目标平台事件

        Returns:
            typing.Type[platform.types.Event]: 源平台事件
        """
        raise NotImplementedError
