import itertools
import logging
import typing
from datetime import datetime
from pathlib import Path
import base64

import aiofiles
import httpx
import pydantic

from langbot_plugin.api.entities.builtin.platform.base import (
    PlatformIndexedMetaclass,
    PlatformIndexedModel,
)
from langbot_plugin.api.entities.builtin.platform import entities as platform_entities

logger = logging.getLogger(__name__)


class MessageComponentMetaclass(PlatformIndexedMetaclass):
    """Message component metaclass."""

    __message_component__: typing.Type["MessageComponent"] | None = None

    def __new__(cls, name, bases, attrs, **kwargs):
        new_cls = super().__new__(cls, name, bases, attrs, **kwargs)
        if name == "MessageComponent":
            cls.__message_component__ = new_cls

        if not cls.__message_component__:
            return new_cls

        for base in bases:
            if issubclass(base, cls.__message_component__):
                # 获取字段名
                if hasattr(new_cls, "__fields__"):
                    # 忽略 type 字段
                    new_cls.__parameter_names__ = list(new_cls.__fields__)[1:]
                else:
                    new_cls.__parameter_names__ = []
                break

        return new_cls


class MessageComponent(PlatformIndexedModel, metaclass=MessageComponentMetaclass):
    """Message component."""

    type: str
    """Type of the message component."""

    def __str__(self):
        return ""

    def __repr__(self):
        return (
            self.__class__.__name__
            + "("
            + ", ".join(
                (
                    f"{k}={repr(v)}"
                    for k, v in self.__dict__.items()
                    if k != "type" and v
                )
            )
            + ")"
        )

    def __init__(self, *args, **kwargs):
        if args:
            # parse the parameter list, convert positional parameters to named parameters
            parameter_names = self.__parameter_names__
            if len(args) > len(parameter_names):
                raise TypeError(
                    f"`{self.type}` needs {len(parameter_names)} parameters, but {len(args)} were passed."
                )
            for name, value in zip(parameter_names, args):
                if name in kwargs:
                    raise TypeError(
                        f"In `{self.type}`, the named parameter `{name}` conflicts with the positional parameter."
                    )
                kwargs[name] = value
        super().__init__(**kwargs)


TMessageComponent = typing.TypeVar("TMessageComponent", bound=MessageComponent)


class MessageChain:
    """消息链。
    
    一个简单的消息组件列表包装器，支持基本的列表操作和序列化。
    
    示例:
        ```python
        chain = MessageChain([Plain("Hello"), At(123456)])
        ```
    """
    
    def __init__(self, components: typing.List[MessageComponent]):
        """初始化消息链。
        
        Args:
            components: 消息组件列表
            
        Raises:
            TypeError: 如果输入不是 MessageComponent 列表
        """
        self._components = []  # 先初始化，避免异常时 repr 报错
        if not isinstance(components, list):
            raise TypeError("MessageChain 只能从 MessageComponent 列表创建")
        if not all(isinstance(item, MessageComponent) for item in components):
            raise TypeError("列表中的所有元素必须是 MessageComponent 类型")
        self._components = components
    
    def __str__(self) -> str:
        """返回消息链的字符串表示。"""
        return "".join(str(component) for component in self._components)
    
    def __repr__(self) -> str:
        """返回消息链的代码表示。"""
        return f"{self.__class__.__name__}({self._components})"
    
    def __len__(self) -> int:
        """返回消息链的长度。"""
        return len(self._components)
    
    def __iter__(self) -> typing.Iterator[MessageComponent]:
        """返回消息链的迭代器。"""
        return iter(self._components)
    
    def __getitem__(self, index: int | slice) -> MessageComponent | typing.List[MessageComponent]:
        """获取指定位置的消息组件。"""
        return self._components[index]
    
    def __setitem__(self, index: int | slice, value: MessageComponent | typing.List[MessageComponent]) -> None:
        """设置指定位置的消息组件。"""
        if isinstance(index, int):
            if not isinstance(value, MessageComponent):
                raise TypeError("值必须是 MessageComponent 类型")
            self._components[index] = value
        elif isinstance(index, slice):
            if not isinstance(value, list) or not all(isinstance(item, MessageComponent) for item in value):
                raise TypeError("值必须是 MessageComponent 列表")
            self._components[index] = value
    
    def __delitem__(self, index: int | slice) -> None:
        """删除指定位置的消息组件。"""
        del self._components[index]
    
    def append(self, component: MessageComponent) -> None:
        """在消息链末尾添加一个消息组件。"""
        if not isinstance(component, MessageComponent):
            raise TypeError("只能添加 MessageComponent 类型的组件")
        self._components.append(component)
    
    def insert(self, index: int, component: MessageComponent) -> None:
        """在指定位置插入一个消息组件。"""
        if not isinstance(component, MessageComponent):
            raise TypeError("只能插入 MessageComponent 类型的组件")
        self._components.insert(index, component)
    
    def extend(self, components: typing.List[MessageComponent]) -> None:
        """在消息链末尾添加多个消息组件。"""
        if not isinstance(components, list) or not all(isinstance(item, MessageComponent) for item in components):
            raise TypeError("只能添加 MessageComponent 列表")
        self._components.extend(components)
    
    def pop(self, index: int = -1) -> MessageComponent:
        """移除并返回指定位置的消息组件。"""
        return self._components.pop(index)
    
    def remove(self, component: MessageComponent) -> None:
        """移除指定的消息组件。"""
        self._components.remove(component)
    
    def clear(self) -> None:
        """清空消息链。"""
        self._components.clear()
    
    def __add__(self, other: "MessageChain") -> "MessageChain":
        """连接两个消息链。"""
        if not isinstance(other, MessageChain):
            raise TypeError("只能与 MessageChain 类型进行连接")
        return self.__class__(self._components + other._components)
    
    def __iadd__(self, other: "MessageChain") -> "MessageChain":
        """原地连接两个消息链。"""
        if not isinstance(other, MessageChain):
            raise TypeError("只能与 MessageChain 类型进行连接")
        self._components.extend(other._components)
        return self
    
    def model_dump(self, **kwargs) -> typing.List[typing.Dict[str, typing.Any]]:
        """序列化消息链。"""
        return [component.model_dump(**kwargs) for component in self._components]
    
    @classmethod
    def model_validate(cls, obj: typing.List[typing.Dict[str, typing.Any]]) -> "MessageChain":
        """反序列化消息链。"""
        components = [MessageComponent.parse_subtype(item) for item in obj]
        return cls(typing.cast(typing.List[MessageComponent], components))
    
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: typing.Any,
        _handler: typing.Callable[[typing.Any], typing.Any],
    ) -> typing.Any:
        """为 Pydantic 提供序列化支持。"""
        from pydantic_core import core_schema
        
        def validate_message_chain(value: typing.Any) -> "MessageChain":
            if isinstance(value, MessageChain):
                return value
            if isinstance(value, list):
                return cls(value)
            raise ValueError("Invalid MessageChain")
        
        return core_schema.json_or_python_schema(
            json_schema=core_schema.list_schema(
                core_schema.union_schema([
                    core_schema.is_instance_schema(MessageComponent),
                    core_schema.dict_schema()
                ])
            ),
            python_schema=core_schema.union_schema([
                core_schema.is_instance_schema(MessageChain),
                core_schema.list_schema(
                    core_schema.union_schema([
                        core_schema.is_instance_schema(MessageComponent),
                        core_schema.dict_schema()
                    ])
                )
            ]),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda x: x.model_dump(),
                return_schema=core_schema.list_schema(),
                when_used='json'
            )
        )

    def count(self, x: type | MessageComponent) -> int:
        """返回消息链中某类型或某组件的出现次数。"""
        if isinstance(x, type):
            return sum(1 for i in self._components if isinstance(i, x))
        if isinstance(x, MessageComponent):
            return self._components.count(x)
        raise TypeError(f"Type mismatch, current type: {type(x)}")

    def get_first(self, t: type) -> MessageComponent | None:
        """获取第一个指定类型的消息组件。"""
        for component in self._components:
            if isinstance(component, t):
                return component
        return None

    @property
    def source(self):
        """获取消息链中的 Source 组件。"""
        return self.get_first(Source)

    def has(self, sub: type | MessageComponent) -> bool:
        """判断消息链中是否包含某类型或某组件。"""
        if isinstance(sub, type):
            return any(isinstance(i, sub) for i in self._components)
        if isinstance(sub, MessageComponent):
            return any(i == sub for i in self._components)
        raise TypeError(f"Type mismatch, current type: {type(sub)}")

    def __contains__(self, sub) -> bool:
        return self.has(sub)

    @classmethod
    def parse_obj(cls, obj):
        """兼容老代码，等价于 MessageChain(list(obj))。"""
        if isinstance(obj, MessageChain):
            return obj
        if not isinstance(obj, list):
            raise TypeError("MessageChain.parse_obj 只接受 list")
        return cls(obj)

    def index(self, x: type | MessageComponent, i: int = 0, j: int = -1) -> int:
        """返回 x 在消息链中的索引。"""
        l = len(self._components)
        if i < 0:
            i += l
        if i < 0:
            i = 0
        if j < 0:
            j += l
        if j > l:
            j = l
        if isinstance(x, type):
            for idx in range(i, j):
                if isinstance(self._components[idx], x):
                    return idx
            raise ValueError("The message chain does not contain the component of this type.")
        if isinstance(x, MessageComponent):
            return self._components.index(x, i, j)
        raise TypeError(f"Type mismatch, current type: {type(x)}")

    @property
    def message_id(self):
        """获取消息链的 message_id，如果没有 source 返回 -1。"""
        src = self.source
        return src.id if src else -1

    def exclude(self, x: type | MessageComponent, count: int = -1) -> "MessageChain":
        """返回排除指定类型或组件后的新消息链。"""
        def _exclude():
            nonlocal count
            x_is_type = isinstance(x, type)
            for c in self._components:
                if (count != 0) and ((x_is_type and isinstance(c, x)) or c == x):
                    if count > 0:
                        count -= 1
                    continue
                yield c
        return MessageChain(list(_exclude()))


class Source(MessageComponent):
    """Source. Contains basic information about the message."""

    type: str = "Source"
    """Message component type."""
    id: typing.Union[int, str]
    """The identification number of the message, used for reference reply (the Source type is always the first element of MessageChain)."""
    time: datetime
    """Message time."""

    def model_dump(self, **kwargs):
        return {
            "type": self.type,
            "id": self.id,
            "time": self.time.timestamp(),
        }


class Plain(MessageComponent):
    """Plain text."""

    type: str = "Plain"
    """Message component type."""
    text: str
    """Text message."""

    def __str__(self):
        return self.text

    def __repr__(self):
        return f"Plain({self.text!r})"


class Quote(MessageComponent):
    """Quote."""

    type: str = "Quote"
    """Message component type."""
    id: typing.Optional[int] = None
    """The message_id of the original message to be quoted."""
    group_id: typing.Optional[typing.Union[int, str]] = None
    """The group number of the original message to be quoted, 0 when it is a friend message."""
    sender_id: typing.Optional[typing.Union[int, str]] = None
    """The ID of the sender of the original message to be quoted."""
    target_id: typing.Optional[typing.Union[int, str]] = None
    """The ID or group ID of the receiver of the original message to be quoted."""
    origin: MessageChain
    """The message chain object of the original message to be quoted."""

    @pydantic.validator("origin", always=True, pre=True)
    def origin_formater(cls, v):
        return MessageChain.parse_obj(v)


class At(MessageComponent):
    """At someone."""

    type: str = "At"
    """Message component type."""
    target: typing.Union[int, str]
    """Group member ID."""
    display: typing.Optional[str] = None
    """The text displayed when At, invalid when sending messages, automatically using the group nickname."""

    def __eq__(self, other):
        return isinstance(other, At) and self.target == other.target

    def __str__(self):
        return f"@{self.display or self.target}"


class AtAll(MessageComponent):
    """At all."""

    type: str = "AtAll"
    """Message component type."""

    def __str__(self):
        return "@All"


class Image(MessageComponent):
    """Image."""

    type: str = "Image"
    """Message component type."""
    image_id: typing.Optional[str] = None
    """The image_id of the image, if not empty, the url attribute will be ignored."""
    url: typing.Optional[pydantic.HttpUrl] = None
    """The URL of the image, can be used as a network image link when sending; when receiving, it is the link of the image, which can be used for image download."""
    path: typing.Union[str, Path, None] = None
    """The path of the image, send local image."""
    base64: typing.Optional[str] = None
    """The Base64 encoding of the image."""

    def __eq__(self, other):
        return (
            isinstance(other, Image)
            and self.type == other.type
            and self.uuid == other.uuid
        )

    def __str__(self):
        return "[Image]"

    @pydantic.validator("path")
    def validate_path(cls, path: typing.Union[str, Path, None]):
        """Fix the behavior of the path parameter, making it relative to the LangBot startup path."""
        if path:
            try:
                return str(Path(path).resolve(strict=True))
            except FileNotFoundError:
                raise ValueError(f"Invalid path: {path}")
        else:
            return path

    @property
    def uuid(self):
        image_id = self.image_id
        if image_id[0] == "{":  # Group image
            image_id = image_id[1:37]
        elif image_id[0] == "/":  # Friend image
            image_id = image_id[1:]
        return image_id

    async def get_bytes(self) -> typing.Tuple[bytes, str]:
        """Get the bytes and mime type of the image"""
        if self.url:
            async with httpx.AsyncClient() as client:
                response = await client.get(str(self.url))
                response.raise_for_status()
                return response.content, response.headers.get("Content-Type")
        elif self.base64:
            mime_type = "image/jpeg"

            split_index = self.base64.find(";base64,")
            if split_index == -1:
                raise ValueError("Invalid base64 string")

            mime_type = self.base64[5:split_index]
            base64_data = self.base64[split_index + 8 :]

            return base64.b64decode(base64_data), mime_type
        elif self.path:
            async with aiofiles.open(self.path, "rb") as f:
                return await f.read(), "image/jpeg"
        else:
            raise ValueError("Can not get bytes from image")

    @classmethod
    async def from_local(
        cls,
        filename: typing.Union[str, Path, None] = None,
        content: typing.Optional[bytes] = None,
    ) -> "Image":
        """Load the image from the local file path, passed in the form of base64.

        Args:
            filename: Load the image from the local file path, one of `content` and `filename`.
            content: Load the image from the local file content, one of `content` and `filename`.

        Returns:
            Image: The image object.
        """
        if content:
            pass
        elif filename:
            path = Path(filename)
            import aiofiles

            async with aiofiles.open(path, "rb") as f:
                content = await f.read()
        else:
            raise ValueError("Please specify the image path or image content!")
        import base64

        img = cls(base64=base64.b64encode(content).decode())
        return img

    @classmethod
    def from_unsafe_path(cls, path: typing.Union[str, Path]) -> "Image":
        """Load the image from the unsafe path.

        Args:
            path: Load the image from the unsafe path.

        Returns:
            Image: The image object.
        """
        return cls.construct(path=str(path))


class Unknown(MessageComponent):
    """Unknown."""

    type: str = "Unknown"
    """Message component type."""
    text: str
    """Text."""

    def __str__(self):
        return f"Unknown Message: {self.text}"


class Voice(MessageComponent):
    """Voice."""

    type: str = "Voice"
    """Message component type."""
    voice_id: typing.Optional[str] = None
    """The voice_id of the voice, if not empty, the url attribute will be ignored."""
    url: typing.Optional[str] = None
    """The URL of the voice, can be used as a network voice link when sending; when receiving, it is the link of the voice file, which can be used for voice download."""
    path: typing.Optional[str] = None
    """The path of the voice, send local voice."""
    base64: typing.Optional[str] = None
    """The Base64 encoding of the voice."""
    length: typing.Optional[int] = None
    """The length of the voice, in seconds."""

    @pydantic.validator("path")
    def validate_path(cls, path: typing.Optional[str]):
        """Fix the behavior of the path parameter, making it relative to the LangBot startup path."""
        if path:
            try:
                return str(Path(path).resolve(strict=True))
            except FileNotFoundError:
                raise ValueError(f"Invalid path: {path}")
        else:
            return path

    def __str__(self):
        return "[Voice]"

    async def download(
        self,
        filename: typing.Union[str, Path, None] = None,
        directory: typing.Union[str, Path, None] = None,
    ):
        """Download the voice to the local.

        Args:
            filename: The path to download the voice to the local. One of `filename` and `directory`.
            directory: The path to download the voice to the local. One of `filename` and `directory`.
        """
        if not self.url:
            logger.warning(
                f"Voice `{self.voice_id}` has no url parameter, download failed."
            )
            return

        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.get(self.url)
            response.raise_for_status()
            content = response.content

            if filename:
                path = Path(filename)
                path.parent.mkdir(parents=True, exist_ok=True)
            elif directory:
                path = Path(directory)
                path.mkdir(parents=True, exist_ok=True)
                path = path / f"{self.voice_id}.silk"
            else:
                raise ValueError("Please specify the file path or directory path!")

            import aiofiles

            async with aiofiles.open(path, "wb") as f:
                await f.write(content)

    @classmethod
    async def from_local(
        cls,
        filename: typing.Union[str, Path, None] = None,
        content: typing.Optional[bytes] = None,
    ) -> "Voice":
        """Load the voice from the local file path, passed in the form of base64.

        Args:
            filename: Load the voice from the local file path, one of `content` and `filename`.
            content: Load the voice from the local file content, one of `content` and `filename`.
        """
        if content:
            pass
        if filename:
            path = Path(filename)
            import aiofiles

            async with aiofiles.open(path, "rb") as f:
                content = await f.read()
        else:
            raise ValueError("Please specify the voice path or voice content!")
        import base64

        img = cls(base64=base64.b64encode(content).decode())
        return img


class ForwardMessageNode(pydantic.BaseModel):
    """A message in a merged forward."""

    sender_id: typing.Optional[typing.Union[int, str]] = None
    """Sender ID."""
    sender_name: typing.Optional[str] = None
    """Display name."""
    message_chain: typing.Optional[MessageChain] = None
    """Message content."""
    message_id: typing.Optional[int] = None
    """The message_id of the message."""

    @pydantic.validator("message_chain", check_fields=False)
    def _validate_message_chain(cls, value: typing.Union[MessageChain, list]):
        if isinstance(value, list):
            return MessageChain(value)
        return value

    @classmethod
    def create(
        cls,
        sender: typing.Union[platform_entities.Friend, platform_entities.GroupMember],
        message: MessageChain,
    ) -> "ForwardMessageNode":
        """Generate a merged forward message from a message chain.

        Args:
            sender: The sender of the message.
            message: The message content.

        Returns:
            ForwardMessageNode: A message in a merged forward.
        """
        return ForwardMessageNode(
            sender_id=sender.id, sender_name=sender.get_name(), message_chain=message
        )

    def model_dump(self, **kwargs):
        return {
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "message_chain": self.message_chain.model_dump(),
            "message_id": self.message_id,
        }

class ForwardMessageDiaplay(pydantic.BaseModel):
    title: str = "Chat history of the group"
    brief: str = "[Chat history]"
    source: str = "Chat history"
    preview: typing.List[str] = []
    summary: str = "View x forwarded messages"


class Forward(MessageComponent):
    """Merged forward."""

    type: str = "Forward"
    """Message component type."""
    display: ForwardMessageDiaplay
    """Display information"""
    node_list: typing.List[ForwardMessageNode]
    """List of forwarded message nodes."""

    def __init__(self, *args, **kwargs):
        if len(args) == 1:
            self.node_list = args[0]
            super().__init__(**kwargs)
        super().__init__(*args, **kwargs)

    def __str__(self):
        return "[Chat history]"


class File(MessageComponent):
    """File."""

    type: str = "File"
    """Message component type."""
    id: str
    """File recognition ID."""
    name: str
    """File name."""
    size: int
    """File size."""

    def __str__(self):
        return f"[File]{self.name}"


# ================ 个人微信专用组件 ================


class WeChatMiniPrograms(MessageComponent):
    """Mini program. Personal WeChat only."""

    type: str = "WeChatMiniPrograms"
    """Mini program ID"""
    mini_app_id: str
    """Mini program owner ID"""
    user_name: str
    """Mini program name"""
    display_name: typing.Optional[str] = ""
    """Open address"""
    page_path: typing.Optional[str] = ""
    """Mini program title"""
    title: typing.Optional[str] = ""
    """Home page image"""
    image_url: typing.Optional[str] = ""


class WeChatForwardMiniPrograms(MessageComponent):
    """Forward mini program. Personal WeChat only."""

    type: str = "WeChatForwardMiniPrograms"
    """xml data"""
    xml_data: str
    """Home page image"""
    image_url: typing.Optional[str] = None

    def __str__(self):
        return self.xml_data


class WeChatEmoji(MessageComponent):
    """Emoji. Personal WeChat only."""

    type: str = "WeChatEmoji"
    """emojimd5"""
    emoji_md5: str
    """Emoji size"""
    emoji_size: int


class WeChatLink(MessageComponent):
    """Send link. Personal WeChat only."""

    type: str = "WeChatLink"
    """Title"""
    link_title: str = ""
    """Link description"""
    link_desc: str = ""
    """Link address"""
    link_url: str = ""
    """Link thumbnail"""
    link_thumb_url: str = ""


class WeChatForwardLink(MessageComponent):
    """Forward link. Personal WeChat only."""

    type: str = "WeChatForwardLink"
    """xml data"""
    xml_data: str

    def __str__(self):
        return self.xml_data


class WeChatForwardImage(MessageComponent):
    """Forward image. Personal WeChat only."""

    type: str = "WeChatForwardImage"
    """xml data"""
    xml_data: str

    def __str__(self):
        return self.xml_data


class WeChatForwardFile(MessageComponent):
    """Forward file. Personal WeChat only."""

    type: str = "WeChatForwardFile"
    """xml data"""
    xml_data: str

    def __str__(self):
        return self.xml_data


class WeChatAppMsg(MessageComponent):
    """Send appmsg. Personal WeChat only."""

    type: str = "WeChatAppMsg"
    """xml data"""
    app_msg: str

    def __str__(self):
        return self.app_msg


class WeChatForwardQuote(MessageComponent):
    """Forward quoted message. Personal WeChat only."""

    type: str = "WeChatForwardQuote"
    """xml data"""
    app_msg: str

    def __str__(self):
        return self.app_msg


class WeChatFile(MessageComponent):
    """文件。"""

    type: str = 'File'
    """消息组件类型。"""
    file_id: str = ''
    """文件识别 ID。"""
    file_name: str = ''
    """文件名称。"""
    file_size: int = 0
    """文件大小。"""
    file_path: str = ''
    """文件地址"""
    file_base64: str = ''
    """base64"""
    def __str__(self):
        return f'[文件]{self.file_name}'