from __future__ import annotations

import typing
import pydantic

from langbot_plugin.api.entities.builtin.platform import message as platform_message


class FunctionCall(pydantic.BaseModel):
    name: str

    arguments: str


class ToolCall(pydantic.BaseModel):
    id: str

    type: str

    function: FunctionCall


class ImageURLContentObject(pydantic.BaseModel):
    url: str

    def __str__(self):
        return self.url[:128] + ("..." if len(self.url) > 128 else "")


class ContentElement(pydantic.BaseModel):
    type: str
    """Type of the content"""

    text: typing.Optional[str] = None

    image_url: typing.Optional[ImageURLContentObject] = None

    image_base64: typing.Optional[str] = None

    def __str__(self):
        if self.type == "text":
            return self.text
        elif self.type == "image_url":
            return f"[Image]({self.image_url})"
        else:
            return "Unknown content"

    @classmethod
    def from_text(cls, text: str):
        return cls(type="text", text=text)

    @classmethod
    def from_image_url(cls, image_url: str):
        return cls(type="image_url", image_url=ImageURLContentObject(url=image_url))

    @classmethod
    def from_image_base64(cls, image_base64: str):
        return cls(type="image_base64", image_base64=image_base64)


class Message(pydantic.BaseModel):
    """Message for AI"""

    role: str  # user, system, assistant, tool, command, plugin
    """Role of the message"""

    name: typing.Optional[str] = None
    """Name of the message, only set when function call is returned"""

    content: typing.Optional[list[ContentElement]] | typing.Optional[str] = None
    """Content of the message"""

    tool_calls: typing.Optional[list[ToolCall]] = None
    """Tool calls"""

    tool_call_id: typing.Optional[str] = None

    def readable_str(self) -> str:
        if self.content is not None:
            return (
                str(self.role) + ": " + str(self.get_content_platform_message_chain())
            )
        elif self.tool_calls is not None:
            return f"Call tool: {self.tool_calls[0].id}"
        else:
            return "Unknown message"

    def get_content_platform_message_chain(
        self, prefix_text: str = ""
    ) -> platform_message.MessageChain | None:
        """Convert the content to a platform message MessageChain object

        Args:
            prefix_text (str): The prefix text of the first text component
        """

        if self.content is None:
            return None
        elif isinstance(self.content, str):
            return platform_message.MessageChain(
                [platform_message.Plain(text=(prefix_text + self.content))]
            )
        elif isinstance(self.content, list):
            mc: list[platform_message.MessageComponent] = []
            for ce in self.content:
                if ce.type == "text":
                    if ce.text is not None:
                        mc.append(platform_message.Plain(text=ce.text))
                elif ce.type == "image_url":
                    assert ce.image_url is not None
                    if ce.image_url.url.startswith("http"):
                        mc.append(platform_message.Image(url=ce.image_url.url))
                    else:  # base64
                        b64_str = ce.image_url.url

                        if b64_str.startswith("data:"):
                            b64_str = b64_str.split(",")[1]

                        mc.append(platform_message.Image(base64=b64_str))

            # find the first text component
            if prefix_text:
                for i, c in enumerate(mc):
                    if isinstance(c, platform_message.Plain):
                        mc[i] = platform_message.Plain(text=(prefix_text + c.text))
                        break
                else:
                    mc.insert(0, platform_message.Plain(text=prefix_text))

            return platform_message.MessageChain(mc)
