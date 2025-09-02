# Quick Start Guide

Get your first LangBot plugin up and running in just a few minutes!

## Prerequisites

- Python 3.10 or higher
- pip package manager

## Step 1: Install the SDK

```bash
pip install langbot-plugin
```

Verify the installation:
```bash
lbp --help
```

## Step 2: Create Your First Plugin

```bash
lbp init my-first-plugin
cd my-first-plugin
```

This creates a new plugin project with the following structure:
```
my-first-plugin/
├── plugin.yaml          # Plugin configuration
├── main.py              # Main plugin entry point
├── requirements.txt     # Python dependencies
└── README.md           # Plugin documentation
```

## Step 3: Understand the Plugin Structure

Let's examine the generated `main.py`:

```python
from langbot_plugin.api import *

# Plugin metadata
__plugin_meta__ = {
    "name": "my-first-plugin",
    "version": "1.0.0",
    "description": "My first LangBot plugin"
}

@register_handler(MessageEvent)
async def handle_message(event: MessageEvent, context: PluginContext):
    """Handle incoming messages"""
    # Echo the received message
    await context.send_message(f"You said: {event.message.text}")

@register_handler(CommandEvent) 
async def handle_command(event: CommandEvent, context: PluginContext):
    """Handle commands"""
    if event.command == "hello":
        await context.send_message("Hello! I'm your LangBot plugin!")
    elif event.command == "time":
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await context.send_message(f"Current time: {now}")
```

## Step 4: Run Your Plugin

Start the plugin in development mode:

```bash
lbp run
```

Your plugin is now running and ready to receive events from LangBot!

## Step 5: Test Your Plugin

You can test your plugin by sending messages or commands through the LangBot interface. The plugin will:

- Echo any text message you send
- Respond to the `/hello` command with a greeting  
- Respond to the `/time` command with the current time

## Step 6: Add LLM Integration

Let's enhance your plugin with AI capabilities. Update your `main.py`:

```python
from langbot_plugin.api import *

__plugin_meta__ = {
    "name": "my-first-plugin",
    "version": "1.0.0", 
    "description": "My first LangBot plugin with AI"
}

@register_handler(MessageEvent)
async def handle_message(event: MessageEvent, context: PluginContext):
    """Handle incoming messages with AI"""
    if "?" in event.message.text:
        # Use AI to answer questions
        try:
            models = await context.get_llm_models()
            if models:
                response = await context.invoke_llm(
                    models[0],  # Use first available model
                    [{"role": "user", "content": event.message.text}]
                )
                await context.send_message(response.content)
            else:
                await context.send_message("No AI models available")
        except Exception as e:
            await context.send_message(f"AI error: {str(e)}")
    else:
        # Simple echo for statements
        await context.send_message(f"You said: {event.message.text}")

@register_handler(CommandEvent)
async def handle_command(event: CommandEvent, context: PluginContext):
    """Handle commands"""
    if event.command == "ask" and event.args:
        # AI-powered Q&A command
        question = " ".join(event.args)
        try:
            models = await context.get_llm_models()
            if models:
                response = await context.invoke_llm(
                    models[0],
                    [{"role": "user", "content": question}]
                )
                await context.send_message(f"AI says: {response.content}")
        except Exception as e:
            await context.send_message(f"Error: {str(e)}")
    elif event.command == "hello":
        await context.send_message("Hello! I'm your AI-powered LangBot plugin!")
```

## Step 7: Add Storage

Let's add user preferences storage:

```python
@register_handler(CommandEvent)
async def handle_command(event: CommandEvent, context: PluginContext):
    """Handle commands with storage"""
    if event.command == "setname" and event.args:
        # Store user's preferred name
        name = " ".join(event.args)
        await context.set_storage(f"user_name_{event.user_id}", name)
        await context.send_message(f"I'll remember to call you {name}!")
        
    elif event.command == "greet":
        # Greet user with stored name
        try:
            name = await context.get_storage(f"user_name_{event.user_id}")
            await context.send_message(f"Hello {name}! Nice to see you again!")
        except:
            await context.send_message("Hello! Use /setname <name> first so I know what to call you.")
```

## Step 8: Build and Deploy

When you're ready to share your plugin:

```bash
# Build the plugin package
lbp build

# Login to your LangBot account (if you haven't already)
lbp login

# Publish to the marketplace
lbp publish
```

## Next Steps

Congratulations! You've created your first LangBot plugin. Here's what to explore next:

### 📚 Learn More
- [API Reference](api-reference/) - Complete API documentation
- [Examples](examples/) - More advanced plugin examples
- [Message Processing](examples/message-processing.md) - Handle complex message types

### 🔧 Development Tools
- [CLI Reference](cli-reference.md) - All CLI commands and options
- [Development Guide](development/) - Best practices and advanced topics
- [Debugging](development/debugging.md) - Debug your plugins effectively

### 🚀 Advanced Features
- [Event Handling](examples/event-handling.md) - Handle various event types
- [Storage Usage](examples/storage-usage.md) - Advanced storage patterns  
- [LLM Integration](examples/llm-integration.md) - Deep dive into AI features

## Common Issues

### Plugin won't start?
- Check Python version: `python --version` (needs 3.10+)
- Verify installation: `lbp --help`
- Check plugin syntax: Look for Python syntax errors in `main.py`

### LLM not working?
- Ensure you're connected to LangBot with available LLM models
- Check your LangBot account has LLM access
- Verify network connectivity

### Storage errors?
- Storage keys must be strings
- Data is automatically serialized, but ensure it's JSON-compatible
- Check for proper error handling in your code

## Help & Support

- [GitHub Issues](https://github.com/langbot-app/langbot-plugin-sdk/issues) - Bug reports
- [Community Forum](https://community.langbot.app) - Get help from other developers
- [Documentation](README.md) - Complete reference materials

Happy plugin development! 🎉