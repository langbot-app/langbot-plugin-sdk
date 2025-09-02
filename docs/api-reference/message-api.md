# Message API Reference

The Message API provides powerful tools for handling and creating messages in LangBot plugins. It includes support for rich message components, message chains, and cross-platform message formatting.

## Overview

The Message API handles:

- 📝 **Message Components** - Text, images, mentions, files, and more
- 🔗 **Message Chains** - Sequences of message components
- 🌐 **Cross-Platform** - Unified API across different messaging platforms
- 🎨 **Rich Content** - Images, files, links, and special platform features

## Core Concepts

### Message Components

Message components are the building blocks of messages. Each component represents a specific type of content:

```python
from langbot_plugin.api.entities.builtin.platform.message import *

# Text component
text = Plain("Hello world!")

# Mention component  
mention = At(target=12345, display="Alice")

# Image component
image = Image(url="https://example.com/image.jpg")
```

### Message Chains

Message chains combine multiple components into a single message:

```python
# Create a complex message
chain = MessageChain([
    Plain("Hello "),
    At(target=12345),
    Plain("! Check out this image: "),
    Image(url="https://example.com/pic.jpg")
])
```

## Message Components Reference

### Plain Text

Basic text content.

```python
class Plain(MessageComponent):
    type: str = "Plain"
    text: str
```

**Example:**
```python
# Simple text
plain = Plain(text="Hello world!")

# Multi-line text
multiline = Plain(text="Line 1\nLine 2\nLine 3")

# Text with special characters
special = Plain(text="Symbols: ★ ♠ ♣ ♥ ♦")
```

### Mentions

#### At (Mention User)

Mention a specific user.

```python
class At(MessageComponent):
    type: str = "At"
    target: Union[int, str]  # User ID
    display: Optional[str]   # Display name (optional)
```

**Example:**
```python
# Mention by ID
mention = At(target=123456)

# Mention with custom display
mention_named = At(target=123456, display="Alice")

# Use in message chain
chain = MessageChain([
    Plain("Hey "),
    At(target=123456),
    Plain(", how are you?")
])
```

#### AtAll (Mention Everyone)

Mention all users in a group.

```python
class AtAll(MessageComponent):
    type: str = "AtAll"
```

**Example:**
```python
# Mention everyone
at_all = AtAll()

# Announcement message
announcement = MessageChain([
    AtAll(),
    Plain(" Important announcement: Server maintenance tonight!")
])
```

### Media Components

#### Image

Send images via URL, local path, or base64.

```python
class Image(MessageComponent):
    type: str = "Image"
    image_id: Optional[str]  # Platform-specific image ID
    url: Optional[str]       # Image URL
    path: Optional[str]      # Local file path
    base64: Optional[str]    # Base64 encoded image
```

**Example:**
```python
# Image from URL
url_image = Image(url="https://example.com/image.jpg")

# Local image file
local_image = Image(path="/path/to/image.png")

# Base64 encoded image
import base64
with open("image.jpg", "rb") as f:
    encoded = base64.b64encode(f.read()).decode()
b64_image = Image(base64=encoded)

# Image with message
message = MessageChain([
    Plain("Check out this cool image:"),
    Image(url="https://example.com/cool.jpg")
])
```

#### Voice

Send voice messages.

```python
class Voice(MessageComponent):
    type: str = "Voice"
    voice_id: Optional[str]
    url: Optional[str]
    path: Optional[str]
    base64: Optional[str]
```

#### File

Send file attachments.

```python
class File(MessageComponent):
    type: str = "File"
    file_id: Optional[str]
    name: str
    size: Optional[int]
```

### Special Components

#### Quote

Quote/reply to another message.

```python
class Quote(MessageComponent):
    type: str = "Quote"
    id: Optional[int]                    # Original message ID
    group_id: Optional[Union[int, str]]  # Group ID (if group message)
    sender_id: Optional[Union[int, str]] # Original sender ID
    target_id: Optional[Union[int, str]] # Original target ID
    origin: MessageChain                 # Original message content
```

**Example:**
```python
# Quote a previous message
quote = Quote(
    id=12345,
    group_id=67890,
    sender_id=11111,
    origin=MessageChain([Plain("Original message")])
)

# Reply with quote
reply = MessageChain([
    quote,
    Plain("Thanks for the info!")
])
```

#### Source

Message metadata (automatically added by platform).

```python
class Source(MessageComponent):
    type: str = "Source"
    id: Union[int, str]  # Message ID
    time: datetime       # Message timestamp
```

#### Forward

Forward another message.

```python
class Forward(MessageComponent):
    type: str = "Forward"
    display: str              # Display text
    message_chain: MessageChain  # Forwarded content
```

## MessageChain API

### Creation

```python
# Empty chain
chain = MessageChain([])

# Chain with components
chain = MessageChain([
    Plain("Hello"),
    At(target=123),
    Plain("!")
])

# From existing components
components = [Plain("Text"), Image(url="pic.jpg")]
chain = MessageChain(components)
```

### Access and Modification

```python
# Access by index
first = chain[0]        # Get first component
last = chain[-1]        # Get last component

# Modify by index
chain[0] = Plain("Hi")  # Replace first component

# Length
count = len(chain)

# Iteration
for component in chain:
    print(type(component), component)

# Check if contains component type
has_images = Image in chain
has_mentions = At in chain
```

### List Operations

```python
# Add components
chain.append(Plain("More text"))
chain.insert(0, AtAll())  # Insert at beginning
chain.extend([Image(url="pic.jpg"), Plain("End")])

# Remove components
removed = chain.pop()      # Remove last
chain.remove(at_component) # Remove specific component
del chain[0]              # Remove by index
chain.clear()             # Remove all

# Combine chains
chain1 = MessageChain([Plain("Hello")])
chain2 = MessageChain([Plain("World")])
combined = chain1 + chain2  # New combined chain
chain1 += chain2           # Modify chain1 in place
```

### Utility Methods

```python
# Get first component of specific type
first_image = chain.get_first(Image)
first_mention = chain.get_first(At)

# Get message source info
source = chain.source
message_id = chain.message_id

# Convert to string (text content only)
text_content = str(chain)

# Check equality
are_equal = chain1 == chain2
```

## Practical Examples

### Building Rich Messages

```python
@register_handler(CommandEvent)
async def rich_message_example(event: CommandEvent, context: PluginContext):
    if event.command == "rich":
        # Build a complex message
        message = MessageChain([
            Plain("📢 "),
            AtAll(),
            Plain("\n\n🎉 Welcome to our server!\n\n"),
            Plain("📸 Here's our logo: "),
            Image(url="https://example.com/logo.png"),
            Plain("\n\n💬 Reply to this message: "),
            Quote(
                id=event.message_id,
                origin=MessageChain([Plain("Original command")])
            ),
            Plain("\n\n👤 Mentioned user: "),
            At(target=event.user_id),
            Plain("\n\nThanks for using our bot! ⭐")
        ])
        
        await context.send_message(message)
```

### Message Processing

```python
@register_handler(MessageEvent)
async def process_message(event: MessageEvent, context: PluginContext):
    chain = event.message_chain
    
    # Extract text content
    text_parts = []
    for component in chain:
        if isinstance(component, Plain):
            text_parts.append(component.text)
    full_text = "".join(text_parts)
    
    # Find mentions
    mentions = []
    for component in chain:
        if isinstance(component, At):
            mentions.append(component.target)
    
    # Check for images
    images = []
    for component in chain:
        if isinstance(component, Image):
            images.append(component.url or component.path)
    
    # Build response
    response_parts = [Plain(f"You sent: {full_text}")]
    
    if mentions:
        response_parts.extend([
            Plain(f"\nYou mentioned: "),
            *[At(target=uid) for uid in mentions]
        ])
    
    if images:
        response_parts.append(Plain(f"\nYou sent {len(images)} image(s)"))
    
    response = MessageChain(response_parts)
    await context.send_message(response)
```

### Message Templates

```python
class MessageTemplates:
    @staticmethod
    def welcome_message(user_id: str, group_name: str) -> MessageChain:
        """Welcome message template"""
        return MessageChain([
            Plain("🎉 Welcome "),
            At(target=user_id),
            Plain(f" to {group_name}!\n\n"),
            Plain("Please read our rules and enjoy your stay! 📖✨")
        ])
    
    @staticmethod
    def error_message(error_msg: str) -> MessageChain:
        """Error message template"""
        return MessageChain([
            Plain("❌ Error: "),
            Plain(error_msg)
        ])
    
    @staticmethod
    def info_card(title: str, content: str, image_url: str = None) -> MessageChain:
        """Info card template"""
        components = [
            Plain(f"ℹ️ {title}\n\n"),
            Plain(content)
        ]
        
        if image_url:
            components.extend([
                Plain("\n\n"),
                Image(url=image_url)
            ])
        
        return MessageChain(components)

# Usage
@register_handler(CommandEvent)
async def template_example(event: CommandEvent, context: PluginContext):
    if event.command == "welcome":
        message = MessageTemplates.welcome_message(
            event.user_id, 
            "Awesome Group"
        )
        await context.send_message(message)
```

### Image Handling

```python
import asyncio
import aiohttp
import base64

async def download_and_send_image(context: PluginContext, url: str):
    """Download an image and send it"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    image_data = await response.read()
                    
                    # Option 1: Send as base64
                    encoded = base64.b64encode(image_data).decode()
                    message = MessageChain([
                        Plain("Here's your image:"),
                        Image(base64=encoded)
                    ])
                    
                    # Option 2: Send as URL (if accessible)
                    # message = MessageChain([
                    #     Plain("Here's your image:"),
                    #     Image(url=url)
                    # ])
                    
                    await context.send_message(message)
                else:
                    error_msg = MessageChain([
                        Plain(f"❌ Failed to download image: HTTP {response.status}")
                    ])
                    await context.send_message(error_msg)
                    
    except Exception as e:
        error_msg = MessageChain([
            Plain(f"❌ Error downloading image: {e}")
        ])
        await context.send_message(error_msg)
```

### Message Parsing Utilities

```python
class MessageParser:
    @staticmethod
    def extract_text(chain: MessageChain) -> str:
        """Extract all text content from a message chain"""
        text_parts = []
        for component in chain:
            if isinstance(component, Plain):
                text_parts.append(component.text)
        return "".join(text_parts)
    
    @staticmethod
    def extract_mentions(chain: MessageChain) -> list[str]:
        """Extract all mentioned user IDs"""
        mentions = []
        for component in chain:
            if isinstance(component, At):
                mentions.append(str(component.target))
        return mentions
    
    @staticmethod
    def extract_images(chain: MessageChain) -> list[dict]:
        """Extract image information"""
        images = []
        for component in chain:
            if isinstance(component, Image):
                images.append({
                    "url": component.url,
                    "path": component.path,
                    "image_id": component.image_id,
                    "has_base64": bool(component.base64)
                })
        return images
    
    @staticmethod
    def has_component_type(chain: MessageChain, component_type: type) -> bool:
        """Check if chain contains specific component type"""
        return component_type in chain
    
    @staticmethod
    def count_component_type(chain: MessageChain, component_type: type) -> int:
        """Count occurrences of component type"""
        return sum(1 for c in chain if isinstance(c, component_type))

# Usage
@register_handler(MessageEvent)
async def analyze_message(event: MessageEvent, context: PluginContext):
    chain = event.message_chain
    
    text = MessageParser.extract_text(chain)
    mentions = MessageParser.extract_mentions(chain)
    images = MessageParser.extract_images(chain)
    
    analysis = MessageChain([
        Plain(f"📊 Message Analysis:\n"),
        Plain(f"📝 Text: {text[:50]}...\n"),
        Plain(f"👥 Mentions: {len(mentions)}\n"),
        Plain(f"🖼️ Images: {len(images)}\n"),
        Plain(f"🧩 Components: {len(chain)}")
    ])
    
    await context.send_message(analysis)
```

## Platform-Specific Components

### WeChat Components

For WeChat-specific features:

```python
# WeChat Mini Program
class WeChatMiniPrograms(MessageComponent):
    type: str = "WeChatMiniPrograms"
    # WeChat-specific fields...

# WeChat Emoji
class WeChatEmoji(MessageComponent):
    type: str = "WeChatEmoji"
    # WeChat-specific fields...

# WeChat Link
class WeChatLink(MessageComponent):
    type: str = "WeChatLink"
    # WeChat-specific fields...
```

## Best Practices

1. **Validation**: Always validate message components before sending
2. **Error Handling**: Handle cases where components might not be supported
3. **Performance**: Use appropriate image formats and sizes
4. **Platform Compatibility**: Test messages across different platforms
5. **User Experience**: Keep messages readable and well-formatted
6. **Security**: Validate URLs and file paths before using

## Error Handling

```python
@register_handler(MessageEvent)
async def safe_message_handling(event: MessageEvent, context: PluginContext):
    try:
        # Process message safely
        chain = event.message_chain
        
        # Validate chain
        if not chain or len(chain) == 0:
            await context.send_message("Empty message received")
            return
        
        # Safe component access
        first_component = chain[0] if len(chain) > 0 else None
        
        # Safe type checking
        if isinstance(first_component, Plain):
            text = first_component.text
            # Process text...
        
        # Build response with error handling
        try:
            response = MessageChain([Plain("Processed your message!")])
            await context.send_message(response)
        except Exception as send_error:
            context.logger.error(f"Failed to send response: {send_error}")
            
    except Exception as e:
        context.logger.error(f"Message handling error: {e}")
        # Send error message to user
        error_chain = MessageChain([Plain("Sorry, I couldn't process your message.")])
        await context.send_message(error_chain)
```

## Related Documentation

- [Event API](event-api.md) - For handling message events
- [LangBot API](langbot-api.md) - For sending messages
- [Examples](../examples/message-processing.md) - Practical message examples
- [Development Guide](../development/) - Advanced message handling patterns