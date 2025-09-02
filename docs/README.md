# LangBot Plugin SDK Documentation

Welcome to the comprehensive documentation for the LangBot Plugin SDK. This documentation will guide you through everything you need to know to develop, test, and deploy plugins for the LangBot platform.

## 📖 Getting Started

- [🚀 Quick Start Guide](quick-start.md) - Get up and running in minutes
- [🔧 Installation](installation.md) - Detailed installation instructions
- [💡 Your First Plugin](examples/basic-plugin.md) - Step-by-step plugin creation tutorial

## 📚 Core Documentation

### API Reference
- [🔌 LangBot API](api-reference/langbot-api.md) - Core LangBot integration APIs
- [💾 Storage API](api-reference/storage-api.md) - Plugin and workspace storage
- [🤖 LLM API](api-reference/llm-api.md) - Language model integration
- [📨 Message API](api-reference/message-api.md) - Message handling and processing
- [🎯 Event API](api-reference/event-api.md) - Event handling system

### CLI Reference
- [💻 CLI Commands](cli-reference.md) - Complete command-line interface reference
- [⚙️ Configuration](cli-reference.md#configuration) - CLI configuration options
- [🔍 Debugging](cli-reference.md#debugging) - CLI debugging tools

### Examples
- [🎯 Basic Examples](examples/) - Simple plugin examples
- [🔗 LLM Integration](examples/llm-integration.md) - Using language models
- [💾 Storage Usage](examples/storage-usage.md) - Working with storage APIs
- [📨 Message Processing](examples/message-processing.md) - Advanced message handling
- [🔄 Event Handling](examples/event-handling.md) - Event system examples

### Development Guide
- [🏗️ Development Setup](development/setup.md) - Setting up your dev environment
- [📝 Best Practices](development/best-practices.md) - Plugin development guidelines
- [🧪 Testing](development/testing.md) - Testing your plugins
- [🐛 Debugging](development/debugging.md) - Debugging techniques
- [🚀 Deployment](development/deployment.md) - Publishing and deployment

## 🌟 Key Features

### 🔥 Async/Await Support
The SDK is built with modern Python async/await patterns for high-performance plugin development.

```python
@register_handler(MessageEvent)
async def handle_message(event: MessageEvent, context: PluginContext):
    # Your async plugin logic here
    await context.send_message("Hello from async world!")
```

### 🤖 Built-in LLM Integration
Direct access to language models with simple, intuitive APIs.

```python
# Easy LLM integration
response = await context.invoke_llm(
    "gpt-3.5-turbo",
    [{"role": "user", "content": "Hello AI!"}]
)
```

### 💾 Persistent Storage
Plugin-specific and workspace-wide storage with automatic serialization.

```python
# Save and retrieve data easily
await context.set_storage("user_prefs", user_data)
prefs = await context.get_storage("user_prefs")
```

### 🌐 Multi-Platform Support
Works across different messaging platforms with unified APIs.

### 📝 Type Safety
Built with Pydantic models for robust type checking and validation.

## 🗺️ Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Your Plugin   │◄──►│   Plugin SDK    │◄──►│  LangBot Core   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
        │                       │                       │
        │                       │                       │
        ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Plugin Logic   │    │  Runtime & CLI  │    │  LLM & Storage  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🚀 Quick Navigation

| I want to... | Go to... |
|---------------|----------|
| Start developing immediately | [Quick Start Guide](quick-start.md) |
| Learn about API methods | [API Reference](api-reference/) |
| See working examples | [Examples](examples/) |
| Use the CLI tools | [CLI Reference](cli-reference.md) |
| Set up development environment | [Development Setup](development/setup.md) |
| Deploy my plugin | [Deployment Guide](development/deployment.md) |

## 🌐 Language Support

This documentation is available in multiple languages:

- [English](README.md) (Current)
- [中文 (Chinese)](README_zh.md)

## 🤝 Contributing to Documentation

Found an error or want to improve the documentation? We welcome contributions!

1. Fork the repository
2. Edit the documentation files
3. Submit a pull request

## 📞 Support

- [GitHub Issues](https://github.com/langbot-app/langbot-plugin-sdk/issues) - Bug reports and feature requests
- [Community Forum](https://community.langbot.app) - General discussions and help
- [Official Documentation](https://docs.langbot.app) - Additional resources

---

**Ready to start?** Head over to the [Quick Start Guide](quick-start.md) to create your first plugin in minutes!