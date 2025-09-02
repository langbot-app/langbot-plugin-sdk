# LangBot API Reference

The LangBot API provides core integration with the LangBot platform, allowing your plugin to interact with bots, send messages, and access LangBot services.

## Overview

The `LangBotAPIProxy` class is the main interface for interacting with LangBot. It provides methods for:

- 🤖 **Bot Management** - Get information about bots and their capabilities
- 📨 **Message Sending** - Send messages to users and groups
- 🔍 **System Information** - Get LangBot version and system details

## Getting Started

The LangBot API is available through the plugin context:

```python
from langbot_plugin.api import *

@register_handler(MessageEvent)
async def my_handler(event: MessageEvent, context: PluginContext):
    # Access LangBot API through context
    version = await context.get_langbot_version()
    bots = await context.get_bots()
```

## Methods

### System Information

#### `get_langbot_version()`

Get the current version of the LangBot platform.

```python
async def get_langbot_version() -> str
```

**Returns:**
- `str`: The LangBot version string (e.g., "2.1.0")

**Example:**
```python
@register_handler(CommandEvent)
async def version_command(event: CommandEvent, context: PluginContext):
    if event.command == "version":
        version = await context.get_langbot_version()
        await context.send_message(f"LangBot version: {version}")
```

---

### Bot Management

#### `get_bots()`

Get a list of all available bots.

```python
async def get_bots() -> list[str]
```

**Returns:**
- `list[str]`: List of bot UUIDs

**Example:**
```python
@register_handler(CommandEvent)
async def list_bots(event: CommandEvent, context: PluginContext):
    if event.command == "bots":
        bots = await context.get_bots()
        bot_list = "\n".join([f"- {bot}" for bot in bots])
        await context.send_message(f"Available bots:\n{bot_list}")
```

#### `get_bot_info(bot_uuid)`

Get detailed information about a specific bot.

```python
async def get_bot_info(bot_uuid: str) -> dict[str, Any]
```

**Parameters:**
- `bot_uuid` (str): The UUID of the bot to query

**Returns:**
- `dict[str, Any]`: Bot information including name, capabilities, and status

**Example:**
```python
@register_handler(CommandEvent)
async def bot_info(event: CommandEvent, context: PluginContext):
    if event.command == "botinfo" and event.args:
        bot_uuid = event.args[0]
        try:
            info = await context.get_bot_info(bot_uuid)
            await context.send_message(f"Bot info: {info}")
        except Exception as e:
            await context.send_message(f"Error getting bot info: {e}")
```

---

### Message Sending

#### `send_message(bot_uuid, target_type, target_id, message_chain)`

Send a message through a specific bot to a target.

```python
async def send_message(
    bot_uuid: str,
    target_type: str,
    target_id: str,
    message_chain: MessageChain
) -> None
```

**Parameters:**
- `bot_uuid` (str): The UUID of the bot to send through
- `target_type` (str): Type of target ("group" or "person")
- `target_id` (str): ID of the target (group ID or user ID)
- `message_chain` (MessageChain): The message to send

**Example:**
```python
from langbot_plugin.api.entities.builtin.platform.message import MessageChain, Plain

@register_handler(CommandEvent)
async def broadcast(event: CommandEvent, context: PluginContext):
    if event.command == "broadcast" and event.args:
        message_text = " ".join(event.args)
        message_chain = MessageChain([Plain(message_text)])
        
        bots = await context.get_bots()
        if bots:
            await context.send_message(
                bots[0],  # Use first available bot
                "group",  # Send to a group
                "123456", # Group ID
                message_chain
            )
```

**Target Types:**
- `"group"`: Send to a group chat
- `"person"`: Send to a private chat

**Message Chain:**
The `message_chain` parameter accepts a `MessageChain` object containing various message components:

```python
from langbot_plugin.api.entities.builtin.platform.message import (
    MessageChain, Plain, At, Image
)

# Text message
simple_message = MessageChain([Plain("Hello world!")])

# Message with @mention
mention_message = MessageChain([
    Plain("Hello "),
    At(user_id=12345),
    Plain("!")
])

# Message with image
image_message = MessageChain([
    Plain("Check out this image:"),
    Image(image_id="img123", url="https://example.com/image.jpg")
])
```

## Error Handling

All API methods can raise exceptions. It's recommended to wrap calls in try-catch blocks:

```python
@register_handler(CommandEvent)
async def safe_api_call(event: CommandEvent, context: PluginContext):
    try:
        version = await context.get_langbot_version()
        await context.send_message(f"Version: {version}")
    except Exception as e:
        await context.send_message(f"API call failed: {e}")
        # Log the error for debugging
        context.logger.error(f"LangBot API error: {e}")
```

## Common Patterns

### Bot Selection

Choose an appropriate bot for your operations:

```python
async def get_preferred_bot(context: PluginContext) -> str:
    """Get the best available bot for operations"""
    bots = await context.get_bots()
    if not bots:
        raise RuntimeError("No bots available")
    
    # Use first bot, or implement your selection logic
    return bots[0]
```

### Message Broadcasting

Send messages to multiple targets:

```python
async def broadcast_to_groups(context: PluginContext, group_ids: list[str], message: str):
    """Broadcast a message to multiple groups"""
    bot_uuid = await get_preferred_bot(context)
    message_chain = MessageChain([Plain(message)])
    
    for group_id in group_ids:
        try:
            await context.send_message(bot_uuid, "group", group_id, message_chain)
        except Exception as e:
            context.logger.error(f"Failed to send to group {group_id}: {e}")
```

### Conditional Bot Operations

Check bot capabilities before operations:

```python
async def smart_send_message(context: PluginContext, message: str):
    """Send message using the best available bot"""
    bots = await context.get_bots()
    
    for bot_uuid in bots:
        try:
            bot_info = await context.get_bot_info(bot_uuid)
            # Check if bot supports required features
            if bot_info.get("supports_images", False):
                # Use this bot for image-capable messages
                message_chain = MessageChain([Plain(message)])
                await context.send_message(bot_uuid, "group", "target", message_chain)
                break
        except Exception:
            continue  # Try next bot
```

## Best Practices

1. **Error Handling**: Always wrap API calls in try-catch blocks
2. **Bot Selection**: Check available bots before sending messages
3. **Resource Cleanup**: The SDK handles connection cleanup automatically
4. **Rate Limiting**: Be mindful of message sending frequency
5. **Logging**: Use the context logger for debugging API issues

## Related Documentation

- [Storage API](storage-api.md) - For persistent data storage
- [LLM API](llm-api.md) - For AI model integration
- [Message API](message-api.md) - For advanced message handling
- [Examples](../examples/) - Practical usage examples