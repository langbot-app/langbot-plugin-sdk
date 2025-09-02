# Event API Reference

The Event API is the foundation of LangBot plugin interaction. It provides a comprehensive event-driven architecture for handling various types of platform events, from messages to system notifications.

## Overview

The Event API handles:

- 📨 **Message Events** - Incoming messages from users and groups
- 👥 **Group Events** - Member joins, leaves, and group changes
- 👤 **Friend Events** - Friend requests and relationship changes
- ⚙️ **System Events** - Platform notifications and status updates
- 🔧 **Custom Events** - Plugin-defined events

## Core Concepts

### Event-Driven Architecture

Plugins respond to events using handlers:

```python
from langbot_plugin.api import *

@register_handler(MessageEvent)
async def handle_message(event: MessageEvent, context: PluginContext):
    """Handle any message event"""
    await context.send_message(f"You said: {event.message_chain}")

@register_handler(GroupMessage)
async def handle_group_message(event: GroupMessage, context: PluginContext):
    """Handle group messages specifically"""
    group_name = event.sender.group.name
    await context.send_message(f"Message in {group_name}")
```

### Event Hierarchy

Events follow an inheritance hierarchy:

```
Event (base)
├── MessageEvent (base for all messages)
│   ├── FriendMessage (private messages)
│   └── GroupMessage (group messages)
├── GroupEvent (group-related events)
│   ├── MemberJoin
│   ├── MemberLeave
│   └── GroupInfoChange
├── FriendEvent (friend-related events)
└── SystemEvent (system notifications)
```

## Core Event Types

### Base Event

All events inherit from the base `Event` class:

```python
class Event(pydantic.BaseModel):
    type: str  # Event type identifier
```

**Common Properties:**
- `type`: String identifier for the event type
- Custom properties specific to each event subtype

### MessageEvent

Base class for all message-related events:

```python
class MessageEvent(Event):
    type: str
    message_chain: MessageChain  # The message content
    time: Optional[float]        # Message timestamp
    source_platform_object: Optional[Any]  # Platform-specific data
```

**Example:**
```python
@register_handler(MessageEvent)
async def log_all_messages(event: MessageEvent, context: PluginContext):
    """Log all incoming messages"""
    text = str(event.message_chain)
    timestamp = event.time or "unknown"
    context.logger.info(f"Message at {timestamp}: {text}")
```

## Message Event Types

### FriendMessage

Private messages between users:

```python
class FriendMessage(MessageEvent):
    type: str = "FriendMessage"
    sender: Friend               # Friend who sent the message
    message_chain: MessageChain  # Message content
```

**Properties:**
- `sender`: Friend object with user information
- `message_chain`: The message content

**Example:**
```python
@register_handler(FriendMessage)
async def handle_private_message(event: FriendMessage, context: PluginContext):
    """Handle private messages"""
    user_name = event.sender.nickname
    message_text = str(event.message_chain)
    
    # Respond privately
    response = MessageChain([
        Plain(f"Hi {user_name}! You said: {message_text}")
    ])
    await context.send_message(response)
```

### GroupMessage

Messages in group chats:

```python
class GroupMessage(MessageEvent):
    type: str = "GroupMessage"
    sender: GroupMember          # Group member who sent the message
    message_chain: MessageChain  # Message content
```

**Properties:**
- `sender`: GroupMember object with user and group information
- `message_chain`: The message content
- `group`: Convenience property to access the group (via sender.group)

**Example:**
```python
@register_handler(GroupMessage)
async def handle_group_message(event: GroupMessage, context: PluginContext):
    """Handle group messages"""
    user_name = event.sender.nickname
    group_name = event.group.name
    message_text = str(event.message_chain)
    
    # Only respond to messages mentioning the bot
    if "@bot" in message_text.lower():
        response = MessageChain([
            Plain(f"Hello {user_name} in {group_name}!")
        ])
        await context.send_message(response)
```

## Advanced Event Handling

### Multiple Event Types

Handle multiple event types in one handler:

```python
@register_handler(FriendMessage, GroupMessage)
async def handle_any_message(event: MessageEvent, context: PluginContext):
    """Handle both private and group messages"""
    if isinstance(event, FriendMessage):
        # Handle private message
        await context.send_message("Private message received!")
    elif isinstance(event, GroupMessage):
        # Handle group message
        await context.send_message("Group message received!")
```

### Event Filtering

Use conditions to filter events:

```python
@register_handler(GroupMessage)
async def handle_admin_commands(event: GroupMessage, context: PluginContext):
    """Only handle messages from group admins"""
    
    # Check if sender is admin
    if not event.sender.is_admin:
        return  # Ignore non-admin messages
    
    message_text = str(event.message_chain)
    if message_text.startswith("/admin"):
        await context.send_message("Admin command received!")
```

### Message Content Analysis

Analyze message content to determine response:

```python
@register_handler(MessageEvent)
async def smart_responder(event: MessageEvent, context: PluginContext):
    """Respond based on message content"""
    
    # Extract text from message chain
    text = str(event.message_chain).lower()
    
    # Check for greetings
    greetings = ["hello", "hi", "hey", "greetings"]
    if any(greeting in text for greeting in greetings):
        await context.send_message("Hello there! 👋")
        return
    
    # Check for questions
    if "?" in text or text.startswith(("what", "how", "why", "when", "where")):
        await context.send_message("That's a great question! 🤔")
        return
    
    # Check for mentions of specific topics
    if "weather" in text:
        await context.send_message("I'd love to help with weather info! ☀️")
        return
    
    # Default response
    if isinstance(event, FriendMessage):
        await context.send_message("Thanks for your message!")
```

## Entity Objects

### Friend

Represents a friend/user:

```python
class Friend:
    id: Union[int, str]      # User ID
    nickname: str            # Display name
    # Additional platform-specific fields
```

### GroupMember

Represents a group member:

```python
class GroupMember:
    id: Union[int, str]      # User ID
    nickname: str            # Display name in group
    group: Group             # The group they belong to
    is_admin: bool           # Whether they're a group admin
    # Additional platform-specific fields
```

### Group

Represents a group/chat room:

```python
class Group:
    id: Union[int, str]      # Group ID
    name: str                # Group name
    # Additional platform-specific fields
```

## Practical Examples

### Bot Commands

Create a command system:

```python
@register_handler(MessageEvent)
async def command_handler(event: MessageEvent, context: PluginContext):
    """Handle bot commands"""
    
    text = str(event.message_chain).strip()
    
    # Only process messages that start with '/'
    if not text.startswith('/'):
        return
    
    # Parse command and arguments
    parts = text[1:].split()
    command = parts[0].lower()
    args = parts[1:] if len(parts) > 1 else []
    
    # Handle different commands
    if command == "help":
        help_text = MessageChain([
            Plain("Available commands:\n"),
            Plain("/help - Show this help\n"),
            Plain("/time - Show current time\n"),
            Plain("/weather <city> - Get weather info\n"),
            Plain("/joke - Tell a random joke")
        ])
        await context.send_message(help_text)
        
    elif command == "time":
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await context.send_message(f"Current time: {now}")
        
    elif command == "weather":
        if args:
            city = " ".join(args)
            # In a real implementation, you'd call a weather API
            await context.send_message(f"Weather in {city}: Sunny, 25°C ☀️")
        else:
            await context.send_message("Please specify a city: /weather <city>")
            
    elif command == "joke":
        jokes = [
            "Why don't scientists trust atoms? Because they make up everything!",
            "Why did the math book look so sad? Because it had too many problems!",
            "What do you call a fake noodle? An impasta!"
        ]
        import random
        joke = random.choice(jokes)
        await context.send_message(joke)
        
    else:
        await context.send_message(f"Unknown command: {command}. Use /help for available commands.")
```

### Auto-Moderation

Implement basic moderation features:

```python
@register_handler(GroupMessage)
async def auto_moderator(event: GroupMessage, context: PluginContext):
    """Basic auto-moderation for groups"""
    
    message_text = str(event.message_chain).lower()
    
    # Define banned words (in a real implementation, load from config)
    banned_words = ["spam", "bad_word1", "bad_word2"]
    
    # Check for banned words
    for word in banned_words:
        if word in message_text:
            warning = MessageChain([
                At(target=event.sender.id),
                Plain(" Please watch your language! ⚠️")
            ])
            await context.send_message(warning)
            return
    
    # Check for excessive caps
    caps_ratio = sum(1 for c in message_text if c.isupper()) / len(message_text)
    if caps_ratio > 0.7 and len(message_text) > 10:
        reminder = MessageChain([
            At(target=event.sender.id),
            Plain(" Please don't use excessive caps. 📢")
        ])
        await context.send_message(reminder)
        return
    
    # Check for repeated messages (simple implementation)
    # In a real implementation, you'd store recent messages
    repeated_chars = any(char * 5 in message_text for char in "abcdefghijklmnopqrstuvwxyz")
    if repeated_chars:
        reminder = MessageChain([
            At(target=event.sender.id),
            Plain(" Please avoid spamming characters. 🚫")
        ])
        await context.send_message(reminder)
```

### Welcome Bot

Welcome new members:

```python
# Note: This example assumes GroupEvent types exist
# Actual implementation may vary based on platform

@register_handler(GroupMessage)  # Simplified example using group messages
async def welcome_bot(event: GroupMessage, context: PluginContext):
    """Welcome new members when they first speak"""
    
    # In a real implementation, you'd track if this is the user's first message
    # This is a simplified example
    
    # Store user IDs that have been welcomed
    welcomed_users = getattr(context, 'welcomed_users', set())
    
    user_id = event.sender.id
    if user_id not in welcomed_users:
        # This is the user's first message
        welcome_message = MessageChain([
            Plain("🎉 Welcome "),
            At(target=user_id),
            Plain(f" to {event.group.name}!\n\n"),
            Plain("Please read our rules and enjoy your stay! 📖✨\n"),
            Plain("Type /help to see available commands.")
        ])
        
        await context.send_message(welcome_message)
        
        # Mark user as welcomed
        welcomed_users.add(user_id)
        context.welcomed_users = welcomed_users
```

### AI Chat Integration

Combine events with LLM API:

```python
@register_handler(FriendMessage)
async def ai_chat_friend(event: FriendMessage, context: PluginContext):
    """AI-powered chat for private messages"""
    
    user_message = str(event.message_chain)
    
    # Skip if message is empty or just special characters
    if not user_message.strip() or not any(c.isalnum() for c in user_message):
        return
    
    try:
        # Get available AI models
        models = await context.get_llm_models()
        if not models:
            await context.send_message("Sorry, AI chat is not available right now.")
            return
        
        # Build conversation
        messages = [
            {"role": "system", "content": "You are a helpful and friendly assistant."},
            {"role": "user", "content": user_message}
        ]
        
        # Get AI response
        response = await context.invoke_llm(models[0], messages)
        
        # Send AI response
        ai_response = MessageChain([
            Plain("🤖 "),
            Plain(response.content)
        ])
        await context.send_message(ai_response)
        
    except Exception as e:
        context.logger.error(f"AI chat error: {e}")
        await context.send_message("Sorry, I'm having trouble thinking right now. 🤔")
```

### Message Statistics

Track message statistics:

```python
@register_handler(MessageEvent)
async def message_stats(event: MessageEvent, context: PluginContext):
    """Track message statistics"""
    
    # In a real implementation, use proper storage
    stats = getattr(context, 'message_stats', {
        'total_messages': 0,
        'friend_messages': 0,
        'group_messages': 0,
        'users': set()
    })
    
    # Update statistics
    stats['total_messages'] += 1
    
    if isinstance(event, FriendMessage):
        stats['friend_messages'] += 1
        stats['users'].add(event.sender.id)
    elif isinstance(event, GroupMessage):
        stats['group_messages'] += 1
        stats['users'].add(event.sender.id)
    
    # Store updated stats
    context.message_stats = stats
    
    # Respond to stats command
    message_text = str(event.message_chain)
    if message_text.strip() == "/stats":
        stats_message = MessageChain([
            Plain("📊 Bot Statistics:\n"),
            Plain(f"Total messages: {stats['total_messages']}\n"),
            Plain(f"Private messages: {stats['friend_messages']}\n"),
            Plain(f"Group messages: {stats['group_messages']}\n"),
            Plain(f"Unique users: {len(stats['users'])}")
        ])
        await context.send_message(stats_message)
```

## Event Handler Best Practices

### 1. Handler Registration

```python
# Good: Specific event types
@register_handler(GroupMessage)
async def handle_group(event: GroupMessage, context: PluginContext):
    pass

# Good: Multiple related types
@register_handler(FriendMessage, GroupMessage)
async def handle_messages(event: MessageEvent, context: PluginContext):
    pass

# Avoid: Too broad unless necessary
@register_handler(Event)  # Catches ALL events
async def handle_everything(event: Event, context: PluginContext):
    pass
```

### 2. Error Handling

```python
@register_handler(MessageEvent)
async def safe_handler(event: MessageEvent, context: PluginContext):
    try:
        # Your handler logic here
        message_text = str(event.message_chain)
        # Process message...
        
    except Exception as e:
        # Log error but don't crash
        context.logger.error(f"Handler error: {e}")
        
        # Optionally notify user of error
        await context.send_message("Sorry, something went wrong. 😅")
```

### 3. Performance Considerations

```python
@register_handler(MessageEvent)
async def efficient_handler(event: MessageEvent, context: PluginContext):
    # Quick checks first
    message_text = str(event.message_chain)
    if len(message_text) > 1000:
        return  # Skip very long messages
    
    # Avoid expensive operations in every handler
    if not message_text.startswith('!'):
        return  # Only process commands
    
    # Do expensive work only when needed
    await process_command(message_text, context)
```

### 4. State Management

```python
@register_handler(MessageEvent)
async def stateful_handler(event: MessageEvent, context: PluginContext):
    # Use storage for persistent state
    user_id = getattr(event, 'sender', {}).get('id', 'unknown')
    
    try:
        user_data = await context.get_storage(f"user_{user_id}")
        user_info = json.loads(user_data.decode())
    except:
        user_info = {"message_count": 0, "last_seen": None}
    
    # Update state
    user_info["message_count"] += 1
    user_info["last_seen"] = time.time()
    
    # Save state
    await context.set_storage(
        f"user_{user_id}",
        json.dumps(user_info).encode()
    )
```

## Testing Event Handlers

```python
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_message_handler():
    """Test message handler"""
    
    # Mock context
    context = AsyncMock()
    context.send_message = AsyncMock()
    
    # Create test event
    test_message = MessageChain([Plain("Hello bot!")])
    event = FriendMessage(
        sender={"id": 123, "nickname": "TestUser"},
        message_chain=test_message
    )
    
    # Call handler
    await handle_private_message(event, context)
    
    # Verify response
    context.send_message.assert_called_once()
    # Check the response content...
```

## Related Documentation

- [Message API](message-api.md) - For handling message content
- [LangBot API](langbot-api.md) - For sending responses
- [Storage API](storage-api.md) - For maintaining state
- [Examples](../examples/event-handling.md) - Practical event handling examples
- [Development Guide](../development/) - Advanced event handling patterns