# Basic Plugin Example

This example demonstrates how to create a simple but functional LangBot plugin that responds to messages and commands. It's perfect for beginners who want to understand the fundamental concepts of plugin development.

## What You'll Learn

- Plugin structure and configuration
- Event handling basics
- Message processing
- Command implementation
- Error handling
- Basic debugging

## Prerequisites

- Python 3.10 or higher
- LangBot Plugin SDK installed (`pip install langbot-plugin`)
- Basic Python knowledge

## Plugin Overview

Our basic plugin will:

- 👋 Respond to greetings
- 🔢 Handle a simple math command
- ⏰ Show current time on request
- 📝 Echo messages back to users
- ❓ Provide help information

## Step 1: Initialize the Plugin

```bash
# Create a new plugin
lbp init basic-example-plugin
cd basic-example-plugin
```

## Step 2: Plugin Configuration

Edit `plugin.yaml`:

```yaml
name: basic-example-plugin
version: 1.0.0
description: A basic example plugin for learning LangBot development
author: Your Name
homepage: https://github.com/yourusername/basic-example-plugin
entry: main.py

dependencies:
  - datetime

permissions:
  - send_message
  - receive_message

metadata:
  category: example
  tags: [tutorial, basic, beginner]
  min_langbot_version: "2.0.0"
```

## Step 3: Main Plugin Code

Replace the contents of `main.py`:

```python
"""
Basic LangBot Plugin Example

This plugin demonstrates fundamental concepts of LangBot plugin development:
- Event handling
- Message processing  
- Command implementation
- Error handling
"""

import datetime
import logging
from langbot_plugin.api import *
from langbot_plugin.api.entities.builtin.platform.message import MessageChain, Plain, At

# Plugin metadata
__plugin_meta__ = {
    "name": "basic-example-plugin",
    "version": "1.0.0",
    "description": "A basic example plugin for learning LangBot development",
    "author": "Your Name"
}

# Set up logging
logger = logging.getLogger(__name__)

# Plugin state (in a real plugin, use storage API for persistence)
plugin_stats = {
    "messages_received": 0,
    "commands_executed": 0,
    "users_interacted": set()
}

@register_handler(MessageEvent)
async def handle_message(event: MessageEvent, context: PluginContext):
    """
    Handle all incoming messages
    
    This is the main message handler that processes user messages
    and decides how to respond based on the content.
    """
    try:
        # Update statistics
        plugin_stats["messages_received"] += 1
        
        # Get message text
        message_text = str(event.message_chain).strip()
        
        # Skip empty messages
        if not message_text:
            return
        
        # Track user interaction
        user_id = getattr(event, 'sender', {})
        if hasattr(user_id, 'id'):
            plugin_stats["users_interacted"].add(user_id.id)
        
        # Log the interaction
        logger.info(f"Received message: {message_text}")
        
        # Handle commands (messages starting with /)
        if message_text.startswith('/'):
            await handle_command(message_text, event, context)
            return
        
        # Handle greetings
        greetings = ['hello', 'hi', 'hey', 'greetings', 'good morning', 'good afternoon', 'good evening']
        if any(greeting in message_text.lower() for greeting in greetings):
            await handle_greeting(event, context)
            return
        
        # Handle questions
        if '?' in message_text:
            await handle_question(message_text, event, context)
            return
        
        # Default: Echo the message back
        await handle_echo(message_text, event, context)
        
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await send_error_message(context, "Sorry, I encountered an error processing your message.")

async def handle_command(command_text: str, event: MessageEvent, context: PluginContext):
    """Handle command messages (starting with /)"""
    
    try:
        # Update command statistics
        plugin_stats["commands_executed"] += 1
        
        # Parse command and arguments
        parts = command_text[1:].split()  # Remove '/' and split
        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []
        
        logger.info(f"Executing command: {command} with args: {args}")
        
        # Handle different commands
        if command == "help":
            await send_help_message(context)
            
        elif command == "time":
            await send_time_message(context)
            
        elif command == "math" and len(args) >= 3:
            await handle_math_command(args, context)
            
        elif command == "stats":
            await send_stats_message(context)
            
        elif command == "ping":
            await send_simple_message(context, "🏓 Pong!")
            
        elif command == "about":
            await send_about_message(context)
            
        else:
            await send_unknown_command_message(command, context)
            
    except Exception as e:
        logger.error(f"Error handling command: {e}")
        await send_error_message(context, f"Error executing command: {command}")

async def handle_greeting(event: MessageEvent, context: PluginContext):
    """Handle greeting messages"""
    
    greetings = [
        "Hello there! 👋",
        "Hi! How can I help you today? 😊",
        "Hey! Great to see you! ✨",
        "Greetings! I'm your friendly LangBot plugin! 🤖"
    ]
    
    # Pick a random greeting
    import random
    greeting = random.choice(greetings)
    
    # Add user mention if this is a group message
    if isinstance(event, GroupMessage):
        response = MessageChain([
            At(target=event.sender.id),
            Plain(f" {greeting}")
        ])
    else:
        response = MessageChain([Plain(greeting)])
    
    await context.send_message(response)

async def handle_question(question: str, event: MessageEvent, context: PluginContext):
    """Handle question messages"""
    
    responses = [
        "That's a great question! 🤔",
        "Interesting question! Let me think about that... 💭",
        "I'd love to help answer that! Unfortunately, I'm a basic example plugin. Try asking a more specific question! 😅",
        "Questions are wonderful! This basic plugin doesn't have all the answers, but keep exploring! 🌟"
    ]
    
    import random
    response_text = random.choice(responses)
    
    response = MessageChain([Plain(response_text)])
    await context.send_message(response)

async def handle_echo(message_text: str, event: MessageEvent, context: PluginContext):
    """Echo the message back to the user"""
    
    # Limit echo length to prevent spam
    if len(message_text) > 100:
        echo_text = message_text[:97] + "..."
    else:
        echo_text = message_text
    
    response = MessageChain([
        Plain(f"You said: "),
        Plain(echo_text),
        Plain(" 🔄")
    ])
    
    await context.send_message(response)

async def handle_math_command(args: list, context: PluginContext):
    """Handle basic math operations"""
    
    try:
        # Expected format: /math <number1> <operator> <number2>
        num1 = float(args[0])
        operator = args[1]
        num2 = float(args[2])
        
        result = None
        
        if operator == '+':
            result = num1 + num2
        elif operator == '-':
            result = num1 - num2
        elif operator == '*':
            result = num1 * num2
        elif operator == '/':
            if num2 != 0:
                result = num1 / num2
            else:
                await send_error_message(context, "Cannot divide by zero!")
                return
        else:
            await send_error_message(context, f"Unknown operator: {operator}")
            return
        
        response = MessageChain([
            Plain(f"🧮 {num1} {operator} {num2} = {result}")
        ])
        
        await context.send_message(response)
        
    except ValueError:
        await send_error_message(context, "Invalid numbers provided for math operation")
    except Exception as e:
        await send_error_message(context, f"Math error: {e}")

# Helper functions for sending different types of messages

async def send_help_message(context: PluginContext):
    """Send help information"""
    
    help_text = MessageChain([
        Plain("📚 Basic Plugin Help\n\n"),
        Plain("Available commands:\n"),
        Plain("• /help - Show this help message\n"),
        Plain("• /time - Show current time\n"),
        Plain("• /math <num1> <op> <num2> - Basic calculator\n"),
        Plain("• /stats - Show plugin statistics\n"),
        Plain("• /ping - Test if the plugin is working\n"),
        Plain("• /about - Information about this plugin\n\n"),
        Plain("I also respond to greetings and echo your messages! 😊")
    ])
    
    await context.send_message(help_text)

async def send_time_message(context: PluginContext):
    """Send current time"""
    
    now = datetime.datetime.now()
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    response = MessageChain([
        Plain(f"🕐 Current time: {time_str}")
    ])
    
    await context.send_message(response)

async def send_stats_message(context: PluginContext):
    """Send plugin statistics"""
    
    stats_text = MessageChain([
        Plain("📊 Plugin Statistics\n\n"),
        Plain(f"Messages received: {plugin_stats['messages_received']}\n"),
        Plain(f"Commands executed: {plugin_stats['commands_executed']}\n"),
        Plain(f"Users interacted: {len(plugin_stats['users_interacted'])}")
    ])
    
    await context.send_message(stats_text)

async def send_about_message(context: PluginContext):
    """Send plugin information"""
    
    about_text = MessageChain([
        Plain("ℹ️ About Basic Example Plugin\n\n"),
        Plain(f"Version: {__plugin_meta__['version']}\n"),
        Plain(f"Author: {__plugin_meta__['author']}\n"),
        Plain(f"Description: {__plugin_meta__['description']}\n\n"),
        Plain("This is a tutorial plugin demonstrating basic LangBot functionality.")
    ])
    
    await context.send_message(about_text)

async def send_unknown_command_message(command: str, context: PluginContext):
    """Send unknown command message"""
    
    response = MessageChain([
        Plain(f"❓ Unknown command: /{command}\n"),
        Plain("Type /help to see available commands.")
    ])
    
    await context.send_message(response)

async def send_simple_message(context: PluginContext, text: str):
    """Send a simple text message"""
    
    response = MessageChain([Plain(text)])
    await context.send_message(response)

async def send_error_message(context: PluginContext, error_text: str):
    """Send an error message"""
    
    response = MessageChain([
        Plain(f"❌ {error_text}")
    ])
    
    await context.send_message(response)

# Plugin lifecycle events (optional)

@register_handler(PluginLoadEvent)  # If this event type exists
async def on_plugin_load(event, context: PluginContext):
    """Called when the plugin is loaded"""
    logger.info("Basic example plugin loaded successfully!")

@register_handler(PluginUnloadEvent)  # If this event type exists  
async def on_plugin_unload(event, context: PluginContext):
    """Called when the plugin is unloaded"""
    logger.info("Basic example plugin unloaded")
```

## Step 4: Testing the Plugin

Run your plugin in development mode:

```bash
lbp run --debug
```

## Step 5: Testing Commands

Try these test messages:

### Basic Interactions
- `Hello` → Should respond with a greeting
- `How are you?` → Should respond to question
- `Just chatting` → Should echo the message

### Commands
- `/help` → Shows all available commands
- `/time` → Shows current time
- `/math 10 + 5` → Calculates 10 + 5 = 15
- `/math 20 / 4` → Calculates 20 / 4 = 5
- `/ping` → Responds with "Pong!"
- `/stats` → Shows plugin usage statistics
- `/about` → Shows plugin information

### Error Handling
- `/math 10 / 0` → Should handle division by zero
- `/unknown` → Should show unknown command message
- `/math abc + def` → Should handle invalid numbers

## Understanding the Code

### Event Handling

```python
@register_handler(MessageEvent)
async def handle_message(event: MessageEvent, context: PluginContext):
```

This decorator registers a function to handle `MessageEvent` occurrences. The function receives:
- `event`: Contains message data and metadata
- `context`: Provides access to LangBot APIs

### Message Processing

```python
message_text = str(event.message_chain).strip()
```

Extracts plain text from the message chain, which may contain various components (text, images, mentions, etc.).

### Sending Responses

```python
response = MessageChain([Plain("Hello!")])
await context.send_message(response)
```

Creates a message chain with text content and sends it back to the user.

### Error Handling

```python
try:
    # Plugin logic
except Exception as e:
    logger.error(f"Error: {e}")
    await send_error_message(context, "Something went wrong")
```

Always wrap plugin logic in try-catch blocks to handle errors gracefully.

## Step 6: Adding Features

### 1. Persistent Storage

Add user preferences using the storage API:

```python
@register_handler(CommandEvent)
async def handle_preference(event: CommandEvent, context: PluginContext):
    if event.command == "setname" and event.args:
        name = " ".join(event.args)
        await context.set_storage(f"user_name_{event.user_id}", name.encode())
        await context.send_message(f"I'll remember to call you {name}!")
```

### 2. External API Integration

Add a simple joke command:

```python
import aiohttp

@register_handler(CommandEvent)
async def handle_joke(event: CommandEvent, context: PluginContext):
    if event.command == "joke":
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.chucknorris.io/jokes/random") as response:
                    data = await response.json()
                    joke = data.get("value", "No joke available")
                    await context.send_message(f"😄 {joke}")
        except Exception as e:
            await context.send_message("Sorry, couldn't fetch a joke right now!")
```

### 3. Message Scheduling

Add reminders (simplified example):

```python
import asyncio

async def schedule_reminder(context: PluginContext, delay_seconds: int, message: str):
    """Schedule a reminder message"""
    await asyncio.sleep(delay_seconds)
    await context.send_message(f"⏰ Reminder: {message}")

@register_handler(CommandEvent)
async def handle_remind(event: CommandEvent, context: PluginContext):
    if event.command == "remind" and len(event.args) >= 2:
        try:
            delay = int(event.args[0])  # seconds
            message = " ".join(event.args[1:])
            
            # Start reminder task
            asyncio.create_task(schedule_reminder(context, delay, message))
            
            await context.send_message(f"I'll remind you in {delay} seconds!")
        except ValueError:
            await context.send_message("Invalid time format. Use: /remind <seconds> <message>")
```

## Step 7: Building and Deploying

When you're ready to share your plugin:

```bash
# Build the plugin package
lbp build

# Login to your account
lbp login

# Publish to marketplace
lbp publish
```

## Common Issues and Solutions

### 1. Plugin Won't Start

**Problem**: `ModuleNotFoundError` or import errors

**Solution**: 
- Check `requirements.txt` has all dependencies
- Verify Python path and virtual environment
- Run `lbp run --debug` for detailed error messages

### 2. Messages Not Sending

**Problem**: Plugin receives messages but doesn't respond

**Solution**:
- Check for exceptions in error logs
- Verify message chain creation
- Ensure async/await is used correctly

### 3. Commands Not Working

**Problem**: Commands are not recognized

**Solution**:
- Check command parsing logic
- Verify command starts with '/' character
- Add debug logging to see received messages

## Next Steps

Now that you have a working basic plugin, you can:

1. **Add More Features**: Explore other API capabilities
2. **Learn Advanced Patterns**: Check out other examples
3. **Integrate External Services**: Add weather, news, or other APIs
4. **Improve Error Handling**: Make your plugin more robust
5. **Add Tests**: Write tests for your plugin functionality

## Related Examples

- [Message Processing](message-processing.md) - Advanced message handling
- [LLM Integration](llm-integration.md) - Add AI capabilities
- [Storage Usage](storage-usage.md) - Persistent data patterns
- [Weather Bot](weather-bot.md) - Complete external API example

Congratulations! You've built your first LangBot plugin! 🎉