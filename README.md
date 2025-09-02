<div align="center">
<img src="https://docs.langbot.app/langbot-plugin-social.png" alt="LangBot Plugin SDK" />
</div>

# LangBot Plugin SDK

[![PyPI version](https://badge.fury.io/py/langbot-plugin.svg)](https://badge.fury.io/py/langbot-plugin)
[![Python version](https://img.shields.io/pypi/pyversions/langbot-plugin.svg)](https://pypi.org/project/langbot-plugin/)
[![License](https://img.shields.io/github/license/langbot-app/langbot-plugin-sdk.svg)](https://github.com/langbot-app/langbot-plugin-sdk/blob/main/LICENSE)

**English** | [中文](README_zh.md)

The official SDK, Runtime, and CLI tools for developing LangBot plugins. This package provides everything you need to create, test, and deploy plugins for the LangBot platform.

## ✨ Features

- 🚀 **Easy Plugin Development** - Comprehensive SDK with async/await support
- 🛠️ **CLI Tools** - Complete command-line interface for plugin management
- 🔧 **Runtime Environment** - Built-in runtime for hosting and testing plugins
- 🤖 **LLM Integration** - Direct access to language models and AI capabilities
- 💾 **Storage APIs** - Plugin and workspace storage management
- 🌐 **Multi-platform** - Support for various messaging platforms
- 🔄 **Message Processing** - Advanced message chain handling
- 📝 **TypeScript-like** - Pydantic models for type safety

## 🚀 Quick Start

### Installation

```bash
pip install langbot-plugin
```

### Create Your First Plugin

```bash
# Initialize a new plugin
lbp init my-awesome-plugin

# Navigate to the plugin directory
cd my-awesome-plugin

# Run the plugin in development mode
lbp run
```

### Basic Plugin Example

```python
from langbot_plugin.api import *

@register_handler(MessageEvent)
async def handle_message(event: MessageEvent, context: PluginContext):
    """Handle incoming messages"""
    if event.message.text == "hello":
        await context.send_message("Hello! I'm your LangBot plugin!")

@register_handler(CommandEvent)
async def handle_command(event: CommandEvent, context: PluginContext):
    """Handle commands"""
    if event.command == "weather":
        # Get weather information using LLM
        llm_response = await context.invoke_llm(
            "gpt-3.5-turbo",
            [{"role": "user", "content": f"What's the weather like in {event.args[0]}?"}]
        )
        await context.send_message(llm_response.content)
```

## 📚 Documentation

- [📖 Full Documentation](docs/README.md)
- [⚡ Quick Start Guide](docs/quick-start.md)  
- [🔧 Installation Guide](docs/installation.md)
- [📋 API Reference](docs/api-reference/)
- [💻 CLI Reference](docs/cli-reference.md)
- [🎯 Examples](docs/examples/)
- [👩‍💻 Development Guide](docs/development/)

## 🛠️ CLI Commands

The `lbp` command-line tool provides comprehensive plugin management:

```bash
# Plugin lifecycle
lbp init <plugin-name>    # Create a new plugin
lbp run                   # Run plugin in development mode  
lbp build                 # Build plugin for distribution
lbp publish               # Publish to LangBot Marketplace

# Development tools
lbp comp <component>      # Generate plugin components
lbp rt                    # Start the runtime environment

# Account management  
lbp login                 # Login to LangBot account
lbp logout                # Logout from account
```

## 🔌 Core APIs

### LangBot Integration
```python
# Get LangBot version and bot information
version = await api.get_langbot_version()
bots = await api.get_bots()
bot_info = await api.get_bot_info(bot_uuid)

# Send messages
await api.send_message(bot_uuid, target_type, target_id, message_chain)
```

### LLM Integration
```python
# Access language models
models = await api.get_llm_models()
response = await api.invoke_llm(model_uuid, messages, functions)
```

### Storage Management
```python
# Plugin-specific storage
await api.set_plugin_storage("key", data)
data = await api.get_plugin_storage("key")

# Workspace-wide storage
await api.set_workspace_storage("shared_key", data)
data = await api.get_workspace_storage("shared_key")
```

## 🌐 Multi-language Support

The SDK supports multiple languages:
- English (en_US)
- Simplified Chinese (zh_Hans)  
- Traditional Chinese (zh_Hant)
- Japanese (ja_JP)

## 🤝 Contributing

We welcome contributions! Please see our [Development Guide](docs/development/) for details on:

- Setting up the development environment
- Code style and conventions
- Testing guidelines
- Submitting pull requests

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🔗 Links

- [Official Website](https://langbot.app)
- [Plugin Marketplace](https://marketplace.langbot.app)
- [Community Forum](https://community.langbot.app)
- [Bug Reports](https://github.com/langbot-app/langbot-plugin-sdk/issues)

---

For more detailed information, please visit our [complete documentation](docs/README.md) or the [official LangBot Plugin Documentation](https://docs.langbot.app/zh/plugin/dev/tutor.html).