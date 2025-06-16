import itertools
import logging
import typing
from datetime import datetime
from pathlib import Path
import base64

import aiofiles
import httpx
import pydantic
from pydantic import RootModel

from langbot_plugin.api.entities.builtin.platform.base import (
    PlatformIndexedMetaclass,
    PlatformIndexedModel,
    PlatformBaseModel,
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


class MessageChain(RootModel[typing.List[MessageComponent]]):
    """Message chain.

    An example of constructing a message chain:
    ```py
    message_chain = MessageChain([
        AtAll(),
        Plain("Hello World!"),
    ])
    ```

    `Plain` can be omitted:
    ```py
    message_chain = MessageChain([
        AtAll(),
        "Hello World!",
    ])
    ```

    When calling an API, the parameter that requires `MessageChain` can also be replaced with `List[MessageComponent]`.
    For example, the following two methods are equivalent:
    ```py
    await bot.send_friend_message(12345678, [
        Plain("Hello World!")
    ])
    ```
    ```py
    await bot.send_friend_message(12345678, MessageChain([
        Plain("Hello World!")
    ]))
    ```

    You can use the `in` operation to check the message chain:
    1. Whether there is a message component.
    2. Whether there is a message component of a certain type.

    ```py
    if AtAll in message_chain:
        print('AtAll')

    if At(bot.qq) in message_chain:
        print('At Me')
    ```

    """

    @staticmethod
    def _parse_message_chain(msg_chain: typing.Iterable):
        result = []
        for msg in msg_chain:
            if isinstance(msg, dict):
                result.append(MessageComponent.parse_subtype(msg))
            elif isinstance(msg, MessageComponent):
                result.append(msg)
            elif isinstance(msg, str):
                result.append(Plain(msg))
            else:
                raise TypeError(
                    f"The element in the message chain must be dict, str, or MessageComponent, current type: {type(msg)}"
                )
        return result

    @pydantic.validator("__root__", always=True, pre=True, check_fields=False)
    def _parse_component(cls, msg_chain):
        if isinstance(msg_chain, (str, MessageComponent)):
            msg_chain = [msg_chain]
        if not msg_chain:
            msg_chain = []
        return cls._parse_message_chain(msg_chain)

    @classmethod
    def parse_obj(cls, msg_chain: typing.Iterable):
        """Construct the corresponding `MessageChain` object through a list of message chains.

        Args:
            msg_chain: A list of message chains.
        """
        result = cls._parse_message_chain(msg_chain)
        return cls(result)

    def __str__(self):
        return "".join(str(component) for component in self.root)

    def __repr__(self):
        return f"{self.__class__.__name__}({self.root})"

    def __len__(self):
        return len(self.root)

    def __iter__(self):
        return iter(self.root)

    def get_first(
        self, t: typing.Type[TMessageComponent]
    ) -> typing.Optional[TMessageComponent]:
        """Get the first message component that matches the type in the message chain."""
        for component in self.root:
            if isinstance(component, t):
                return component
        return None

    @typing.overload
    def __getitem__(self, index: int) -> MessageComponent: ...

    @typing.overload
    def __getitem__(self, index: slice) -> typing.List[MessageComponent]: ...

    @typing.overload
    def __getitem__(
        self, index: typing.Type[TMessageComponent]
    ) -> typing.List[TMessageComponent]: ...

    @typing.overload
    def __getitem__(
        self, index: typing.Tuple[typing.Type[TMessageComponent], int]
    ) -> typing.List[TMessageComponent]: ...

    def __getitem__(
        self,
        index: typing.Union[
            int,
            slice,
            typing.Type[TMessageComponent],
            typing.Tuple[typing.Type[TMessageComponent], int],
        ],
    ) -> typing.Union[
        MessageComponent, typing.List[MessageComponent], typing.List[TMessageComponent]
    ]:
        if isinstance(index, type):
            return [c for c in self.root if isinstance(c, index)]
        if isinstance(index, tuple):
            t, i = index
            return [c for c in self.root if isinstance(c, t)][i]
        return self.root[index]

    def __setitem__(
        self,
        key: typing.Union[int, slice],
        value: typing.Union[
            MessageComponent, str, typing.Iterable[typing.Union[MessageComponent, str]]
        ],
    ):
        # 如果 value 是 str，直接转为 Plain
        if isinstance(value, str):
            value = Plain(value)
        # 如果 key 是 int，value 应该是 MessageComponent
        if isinstance(key, int):
            if isinstance(value, MessageComponent):
                self.root[key] = value
            else:
                raise TypeError("Value must be MessageComponent when key is int.")
        # 如果 key 是 slice，value 应该是可迭代对象
        elif isinstance(key, slice):
            # 明确只接受 list/tuple，不接受 dict_items 等
            if isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes)):
                value_list = [Plain(c) if isinstance(c, str) else c for c in value]
                self.root[key] = value_list
            else:
                raise TypeError("Value must be list/tuple of MessageComponent or str when key is slice.")
        else:
            raise TypeError("Key must be int or slice.")

    def __delitem__(self, key: typing.Union[int, slice]):
        del self.root[key]

    def has(
        self,
        sub: typing.Union[
            MessageComponent, typing.Type[MessageComponent], "MessageChain", str
        ],
    ) -> bool:
        """Check if the message chain:
        1. Whether there is a message component.
        2. Whether there is a message component of a certain type.

        Args:
            sub (`Union[MessageComponent, Type[MessageComponent], 'MessageChain', str]`):
                If it is `MessageComponent`, check if the component is in the message chain.
                If it is `Type[MessageComponent]`, check if the component type is in the message chain.

        Returns:
            bool: Whether it is found.
        """
        if isinstance(sub, type):
            return any(isinstance(i, sub) for i in self.root)
        if isinstance(sub, MessageComponent):
            return any(i == sub for i in self.root)
        raise TypeError(f"Type mismatch, current type: {type(sub)}")

    def __contains__(self, sub) -> bool:
        return self.has(sub)

    def __ge__(self, other):
        return other in self

    def __add__(
        self, other: typing.Union["MessageChain", MessageComponent, str]
    ) -> "MessageChain":
        if isinstance(other, MessageChain):
            return self.__class__(self.root + other.root)
        if isinstance(other, str):
            return self.__class__(self.root + [Plain(other)])
        if isinstance(other, MessageComponent):
            return self.__class__(self.root + [other])
        return NotImplemented

    def __radd__(self, other: typing.Union[MessageComponent, str]) -> "MessageChain":
        if isinstance(other, MessageComponent):
            return self.__class__([other] + self.root)
        if isinstance(other, str):
            return self.__class__([Plain(other)] + self.root)
        return NotImplemented

    def __mul__(self, other: int):
        if isinstance(other, int):
            return self.__class__(self.root * other)
        return NotImplemented

    def __rmul__(self, other: int):
        return self.__mul__(other)

    def index(
        self,
        x: typing.Union[MessageComponent, typing.Type[MessageComponent]],
        i: int = 0,
        j: int = -1,
    ) -> int:
        """Return the index of the first occurrence of x in the message chain (the index is between i and j).

        Args:
            x (`Union[MessageComponent, Type[MessageComponent]]`):
                The message element or message element type to find.
            i: The position to start searching from.
            j: The position to end searching at.

        Returns:
            int: If found, return the index.

        Raises:
            ValueError: Not found.
            TypeError: Type mismatch.
        """
        if isinstance(x, type):
            l = len(self.root)
            if i < 0:
                i += l
            if i < 0:
                i = 0
            if j < 0:
                j += l
            if j > l:
                j = l
            for index in range(i, j):
                if isinstance(self.root[index], x):
                    return index
            raise ValueError(
                "The message chain does not contain the component of this type."
            )
        if isinstance(x, MessageComponent):
            return self.root.index(x, i, j)
        raise TypeError(f"Type mismatch, current type: {type(x)}")

    def count(
        self, x: typing.Union[MessageComponent, typing.Type[MessageComponent]]
    ) -> int:
        """Return the number of occurrences of x in the message chain.

        Args:
            x (`Union[MessageComponent, Type[MessageComponent]]`):
                The message element or message element type to find.

        Returns:
            int: The number of occurrences.
        """
        if isinstance(x, type):
            return sum(1 for i in self.root if isinstance(i, x))
        if isinstance(x, MessageComponent):
            return self.root.count(x)
        raise TypeError(f"Type mismatch, current type: {type(x)}")

    def extend(self, x: typing.Iterable[typing.Union[MessageComponent, str]]):
        """Add the elements of another message chain to the end of the message chain.

        Args:
            x: Another message chain, or a sequence of message elements or string elements.
        """
        self.root.extend(Plain(c) if isinstance(c, str) else c for c in x)

    def append(self, x: typing.Union[MessageComponent, str]):
        """Add a message element or string element to the end of the message chain.

        Args:
            x: A message element or string element.
        """
        self.root.append(Plain(x) if isinstance(x, str) else x)

    def insert(self, i: int, x: typing.Union[MessageComponent, str]):
        """Add a message element or string to the message chain at the specified position.

        Args:
            i: The insertion position.
            x: A message element or string element.
        """
        self.root.insert(i, Plain(x) if isinstance(x, str) else x)

    def pop(self, i: int = -1) -> MessageComponent:
        """Remove and return the element at the specified position from the message chain.

        Args:
            i: The position to remove. The default is the last position.

        Returns:
            MessageComponent: The removed element.
        """
        return self.root.pop(i)

    def remove(self, x: typing.Union[MessageComponent, typing.Type[MessageComponent]]):
        """Remove the specified element or the element of the specified type from the message chain.

        Args:
            x: The specified element or element type.
        """
        if isinstance(x, type):
            self.root.pop(self.index(x))
        if isinstance(x, MessageComponent):
            self.root.remove(x)

    def exclude(
        self,
        x: typing.Union[MessageComponent, typing.Type[MessageComponent]],
        count: int = -1,
    ) -> "MessageChain":
        """Return the message chain after removing the specified element or the element of the specified type.

        Args:
            x: The specified element or element type.
            count: The maximum number of elements to remove. The default is to remove all.

        Returns:
            MessageChain: The remaining message chain.
        """

        def _exclude():
            nonlocal count
            x_is_type = isinstance(x, type)
            for c in self.root:
                if (count != 0) and ((x_is_type and isinstance(c, x)) or c == x):
                    if count > 0:
                        count -= 1
                    continue
                yield c

        return self.__class__(_exclude())

    def reverse(self):
        """Reverse the message chain in place."""
        self.root.reverse()

    @property
    def source(self) -> typing.Optional["Source"]:
        """Get the `Source` object in the message chain."""
        return self.get_first(Source)

    @property
    def message_id(self) -> typing.Union[int, str]:
        """Get the message_id of the message chain, if it cannot be obtained, return -1."""
        source = self.source
        return source.id if source else -1


class Source(MessageComponent):
    """Source. Contains basic information about the message."""

    type: str = "Source"
    """Message component type."""
    id: typing.Union[int, str]
    """The identification number of the message, used for reference reply (the Source type is always the first element of MessageChain)."""
    time: datetime
    """Message time."""


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
    time: typing.Optional[datetime] = None
    """The time of the message."""

    @pydantic.validator("message_chain", check_fields=False)
    def _validate_message_chain(cls, value: typing.Union[MessageChain, list]):
        if isinstance(value, list):
            return MessageChain.parse_obj(value)
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