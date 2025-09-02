<div align="center">
<img src="https://docs.langbot.app/langbot-plugin-social.png" alt="LangBot Plugin SDK" />
</div>

# LangBot Plugin SDK

[![PyPI version](https://badge.fury.io/py/langbot-plugin.svg)](https://badge.fury.io/py/langbot-plugin)
[![Python version](https://img.shields.io/pypi/pyversions/langbot-plugin.svg)](https://pypi.org/project/langbot-plugin/)
[![License](https://img.shields.io/github/license/langbot-app/langbot-plugin-sdk.svg)](https://github.com/langbot-app/langbot-plugin-sdk/blob/main/LICENSE)

[English](README.md) | **中文**

LangBot 插件开发的官方 SDK、运行时和 CLI 工具。这个包提供了创建、测试和部署 LangBot 平台插件所需的一切。

## ✨ 特性

- 🚀 **简单的插件开发** - 支持 async/await 的综合 SDK
- 🛠️ **CLI 工具** - 完整的插件管理命令行界面
- 🔧 **运行时环境** - 内置的插件托管和测试运行时
- 🤖 **LLM 集成** - 直接访问语言模型和 AI 能力
- 💾 **存储 API** - 插件和工作区存储管理
- 🌐 **多平台支持** - 支持各种消息平台
- 🔄 **消息处理** - 高级消息链处理
- 📝 **类 TypeScript** - 使用 Pydantic 模型确保类型安全

## 🚀 快速开始

### 安装

```bash
pip install langbot-plugin
```

### 创建你的第一个插件

```bash
# 初始化一个新插件
lbp init my-awesome-plugin

# 进入插件目录
cd my-awesome-plugin

# 在开发模式下运行插件
lbp run
```

### 基础插件示例

```python
from langbot_plugin.api import *

@register_handler(MessageEvent)
async def handle_message(event: MessageEvent, context: PluginContext):
    """处理接收到的消息"""
    if event.message.text == "hello":
        await context.send_message("你好！我是你的 LangBot 插件！")

@register_handler(CommandEvent)
async def handle_command(event: CommandEvent, context: PluginContext):
    """处理命令"""
    if event.command == "weather":
        # 使用 LLM 获取天气信息
        llm_response = await context.invoke_llm(
            "gpt-3.5-turbo",
            [{"role": "user", "content": f"{event.args[0]}的天气怎么样？"}]
        )
        await context.send_message(llm_response.content)
```

## 📚 文档

- [📖 完整文档](docs/README.md)
- [⚡ 快速开始指南](docs/quick-start.md)  
- [🔧 安装指南](docs/installation.md)
- [📋 API 参考](docs/api-reference/)
- [💻 CLI 参考](docs/cli-reference.md)
- [🎯 示例](docs/examples/)
- [👩‍💻 开发指南](docs/development/)

## 🛠️ CLI 命令

`lbp` 命令行工具提供全面的插件管理：

```bash
# 插件生命周期
lbp init <plugin-name>    # 创建新插件
lbp run                   # 在开发模式下运行插件  
lbp build                 # 构建插件用于分发
lbp publish               # 发布到 LangBot 市场

# 开发工具
lbp comp <component>      # 生成插件组件
lbp rt                    # 启动运行时环境

# 账户管理  
lbp login                 # 登录 LangBot 账户
lbp logout                # 退出账户
```

## 🔌 核心 API

### LangBot 集成
```python
# 获取 LangBot 版本和机器人信息
version = await api.get_langbot_version()
bots = await api.get_bots()
bot_info = await api.get_bot_info(bot_uuid)

# 发送消息
await api.send_message(bot_uuid, target_type, target_id, message_chain)
```

### LLM 集成
```python
# 访问语言模型
models = await api.get_llm_models()
response = await api.invoke_llm(model_uuid, messages, functions)
```

### 存储管理
```python
# 插件专属存储
await api.set_plugin_storage("key", data)
data = await api.get_plugin_storage("key")

# 工作区共享存储
await api.set_workspace_storage("shared_key", data)
data = await api.get_workspace_storage("shared_key")
```

## 🌐 多语言支持

SDK 支持多种语言：
- 英语 (en_US)
- 简体中文 (zh_Hans)  
- 繁体中文 (zh_Hant)
- 日语 (ja_JP)

## 🤝 贡献

我们欢迎贡献！请查看我们的[开发指南](docs/development/)了解详情：

- 设置开发环境
- 代码风格和约定
- 测试指南
- 提交拉取请求

## 📄 许可证

本项目基于 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 🔗 链接

- [官方网站](https://langbot.app)
- [插件市场](https://marketplace.langbot.app)
- [社区论坛](https://community.langbot.app)
- [问题报告](https://github.com/langbot-app/langbot-plugin-sdk/issues)

---

更多详细信息，请访问我们的[完整文档](docs/README.md)或[官方 LangBot 插件文档](https://docs.langbot.app/zh/plugin/dev/tutor.html)。