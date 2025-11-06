# AGENTS.md

This file is for guiding code agents (like Claude Code, GitHub Copilot, OpenAI Codex, etc.) to work in the langbot-plugin-sdk project.

**IMPORTANT**: This document may contain outdated information and may differ from the actual content. Please refer to the actual situation for accuracy.

## Project Overview

LangBot Plugin SDK is the infrastructure for LangBot's plugin system, providing:
- **Plugin SDK**: Python APIs and interfaces for plugin development
- **Plugin Runtime**: Execution environment managing plugin lifecycle
- **CLI Tools**: `lbp` command for scaffolding, building, and debugging plugins
- **Communication Protocol**: Bidirectional action-based protocol (stdio/WebSocket)

The SDK enables developers to extend LangBot with custom:
- **Commands**: User-triggered actions (e.g., `!weather tokyo`)
- **Tools**: LLM-callable functions for AI agents (e.g., web search, database queries)
- **Event Listeners**: Handlers for message events (e.g., auto-reply, content filtering)

## Technology Stack

- **Language**: Python 3.10+
- **Async Framework**: asyncio with async/await
- **Data Validation**: Pydantic v2 with type hints
- **Communication**: WebSockets, stdio
- **CLI**: argparse with Jinja2 templates
- **Package Manager**: uv (recommended) or pip

## Project Structure

```
langbot-plugin-sdk/
├── src/langbot_plugin/
│   ├── api/                     # SDK APIs for plugin developers
│   │   ├── definition/          # Base classes
│   │   │   ├── plugin.py        # BasePlugin
│   │   │   └── components/      # Component base classes
│   │   │       ├── base.py      # BaseComponent
│   │   │       ├── command/     # Command component
│   │   │       ├── tool/        # Tool component
│   │   │       └── common/      # EventListener
│   │   ├── entities/            # Data models
│   │   │   ├── context.py       # ExecuteContext, EventContext
│   │   │   ├── events.py        # Event types
│   │   │   └── builtin/         # Platform entities
│   │   │       ├── platform/    # MessageChain, components
│   │   │       ├── command/     # CommandReturn
│   │   │       └── provider/    # Session, Conversation
│   │   └── proxies/             # API proxy classes
│   │       ├── langbot_api.py   # LangBotAPIProxy
│   │       └── query_based.py   # QueryBasedAPIProxy
│   ├── runtime/                 # Plugin runtime system
│   │   ├── plugin/              # Plugin management
│   │   │   ├── mgr.py           # PluginManager
│   │   │   ├── container.py     # PluginContainer
│   │   │   └── installer.py    # Plugin installation
│   │   ├── io/                  # Communication layer
│   │   │   ├── handler.py       # Action handler
│   │   │   ├── stdio.py         # Stdio transport
│   │   │   └── websocket.py    # WebSocket transport
│   │   └── event/               # Event dispatching
│   ├── cli/                     # Command-line tools
│   │   ├── main.py              # lbp entrypoint
│   │   ├── init.py              # Plugin initialization
│   │   ├── gen/                 # Component generation
│   │   └── run.py               # Plugin debugging
│   ├── entities/                # Internal data structures
│   │   ├── io/                  # Communication protocol
│   │   └── plugin/              # Plugin metadata
│   └── utils/                   # Utilities
│       ├── discover/            # Component discovery
│       └── network/             # Network helpers
├── docs/                        # Documentation
├── pyproject.toml               # Python project config
└── README.md
```

## Plugin System Architecture

### Communication Model

```
┌─────────────────┐         ┌──────────────────┐
│    LangBot      │         │  Plugin Process  │
│                 │◄───────►│                  │
│  Plugin Runtime │ stdio/  │  BasePlugin      │
│                 │ WebSocket│  Components      │
└─────────────────┘         └──────────────────┘
```

**Transport Modes**:
1. **Stdio Mode** (default):
   - Plugin runs as subprocess of LangBot
   - Communication via stdin/stdout
   - Used in personal/lightweight deployments

2. **WebSocket Mode**:
   - Plugin connects to Runtime via WebSocket
   - Used in containerized/production environments
   - Enables remote plugin debugging

### Plugin Lifecycle

1. **Discovery**: Runtime scans plugin directories, reads manifests
2. **Installation**: Download from GitHub/marketplace, install dependencies
3. **Loading**: Import plugin module, instantiate `BasePlugin` class
4. **Initialization**: Call `async initialize()`, send config
5. **Registration**: Register components (Commands, Tools, EventListeners)
6. **Ready**: Plugin accepts events and requests
7. **Termination**: Cleanup and shutdown

### Component Architecture

```
BasePlugin
  ├── Command (1+ per plugin)
  │   └── Subcommand handlers
  ├── Tool (0+ per plugin)
  │   └── call() method
  └── EventListener (1 per plugin)
      └── Event handlers
```

## SDK Development

### Setup Environment

```bash
# Install dependencies
uv sync --dev
# Or with pip
pip install -e .

# Run CLI
uv run lbp --help
# Or
python -m langbot_plugin.cli.main --help
```

### Plugin Development Workflow

#### 1. Initialize Plugin

```bash
lbp init MyPlugin
cd MyPlugin
```

Creates:
- `manifest.yaml`: Plugin metadata and configuration
- `main.py`: Plugin class skeleton
- `components/`: Component directories
- `assets/`: Icon and resources

#### 2. Add Components

**Add Command**:
```bash
lbp comp Command
# Enter command name: weather
```

Creates:
- `components/commands/weather.py`
- `components/commands/weather.yaml`

**Add Tool**:
```bash
lbp comp Tool
# Enter tool name: search_web
```

Creates:
- `components/tools/search_web.py`
- `components/tools/search_web.yaml`

**Add Event Listener**:
```bash
lbp comp EventListener
# Enter listener name: message_filter
```

Creates:
- `components/event_listener/message_filter.py`
- `components/event_listener/message_filter.yaml`

#### 3. Implement Components

See "Plugin Development Patterns" section below.

#### 4. Test Plugin

```bash
# Start LangBot instance first
cd /path/to/LangBot
uv run main.py

# In another terminal, run plugin
cd MyPlugin
lbp run
```

Plugin connects to running LangBot for testing.

#### 5. Build & Publish

```bash
lbp build
lbp publish
```

## Plugin Development Patterns

### Base Plugin Class

```python
from langbot_plugin.api.definition.plugin import BasePlugin

class MyPlugin(BasePlugin):
    """
    Main plugin class.
    Must inherit from BasePlugin.
    """

    def __init__(self):
        super().__init__()
        # Initialize data structures
        self.custom_data = {}

    async def initialize(self) -> None:
        """
        Called when plugin is launching.
        Use for async initialization (DB connections, API clients, etc.)
        """
        # Access plugin configuration
        config = self.get_config()
        api_key = config.get('api_key')

        # Load file configuration
        file_config = config.get('file_input')
        if file_config:
            file_key = file_config['file_key']
            file_bytes = await self.get_config_file(file_key)
            # Process file_bytes

    def __del__(self):
        """
        Optional cleanup when plugin terminates.
        """
        pass
```

**Available APIs** (inherited from `LangBotAPIProxy`):

```python
# Bot management
await self.get_langbot_version() -> str
await self.get_bots() -> list[Bot]
await self.get_bot_info(bot_uuid: str) -> Bot

# Messaging
await self.send_message(
    bot_uuid: str,
    target_type: str,  # "person" or "group"
    target_id: Union[int, str],
    message_chain: MessageChain
)

# LLM integration
await self.get_llm_models() -> list[LLMModel]
await self.invoke_llm(
    llm_model_uuid: str,
    messages: list[dict],
    funcs: list[dict],
    extra_args: dict
) -> dict

# Storage (persistent data)
await self.set_plugin_storage(key: str, value: bytes)
await self.get_plugin_storage(key: str) -> bytes
await self.get_plugin_storage_keys() -> list[str]
await self.delete_plugin_storage(key: str)

# Workspace-level storage
await self.set_workspace_storage(key: str, value: bytes)
await self.get_workspace_storage(key: str) -> bytes
# ... similar methods

# Metadata
await self.list_plugins_manifest() -> list[dict]
await self.list_commands() -> list[dict]
await self.list_tools() -> list[dict]
```

### Command Component

**Manifest** (`components/commands/info.yaml`):
```yaml
apiVersion: v1
kind: Command
metadata:
  name: info
  label:
    en_US: Info
    zh_Hans: 信息
  description:
    en_US: Show information
    zh_Hans: 显示信息
execution:
  python:
    path: info.py
    attr: Info
```

**Implementation** (`components/commands/info.py`):
```python
from langbot_plugin.api.definition.components.command.command import Command
from langbot_plugin.api.entities.builtin.command.context import ExecuteContext, CommandReturn
from langbot_plugin.api.entities.builtin.platform import message as pm
from typing import AsyncGenerator

class Info(Command):
    """
    Command component.
    Triggered by: !info [subcommand] [args...]
    """

    async def initialize(self):
        await super().initialize()

        # Root command handler (matches !info with no subcommand)
        @self.subcommand(
            name="",                    # Empty = root
            help="Show information",
            usage="!info",
            aliases=["i"]               # !i also works
        )
        async def root(self, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
            """
            Root command handler.
            Yields CommandReturn objects for response.
            """
            # Access context
            query_id = context.query_id              # Request ID
            session = context.session                # Session info
            command_text = context.command_text      # Full command text
            command = context.command                # Command name
            params = context.params                  # All parameters
            crt_params = context.crt_params          # Current level params
            privilege = context.privilege            # User privilege level

            # Build response
            text = f"Query ID: {query_id}\n"
            text += f"Command: {command}\n"
            text += f"Params: {params}\n"

            # Yield response (can yield multiple times)
            yield CommandReturn(text=text)

        # Subcommand handler (matches !info version)
        @self.subcommand(
            name="version",
            help="Show LangBot version",
            usage="!info version"
        )
        async def version_handler(self, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
            # Access plugin APIs
            version = await self.plugin.get_langbot_version()
            yield CommandReturn(text=f"LangBot version: {version}")

        # Nested subcommand (matches !info user <username>)
        @self.subcommand(
            name="user",
            help="Show user info",
            usage="!info user <username>"
        )
        async def user_handler(self, context: ExecuteContext) -> AsyncGenerator[CommandReturn, None]:
            if len(context.crt_params) < 1:
                yield CommandReturn(text="Usage: !info user <username>")
                return

            username = context.crt_params[0]
            # Do something with username
            yield CommandReturn(text=f"User: {username}")
```

**ExecuteContext APIs**:
```python
# Reply to message
await context.reply(message_chain: MessageChain, quote_origin: bool = True)

# Get current bot UUID
bot_uuid = await context.get_bot_uuid()

# Query-scoped variables (persist during query lifecycle)
await context.set_query_var(key: str, value: Any)
value = await context.get_query_var(key: str) -> Any

# Create new conversation (reset context)
await context.create_new_conversation()

# Navigate subcommands
sub_context = context.shift()  # Move to next subcommand level
```

**CommandReturn Types**:
```python
# Text response
yield CommandReturn(text="Hello world")

# Image (base64)
yield CommandReturn(
    text="Here's an image:",
    image_base64="data:image/png;base64,..."
)

# Image (URL)
yield CommandReturn(image_url="https://example.com/image.png")

# File
yield CommandReturn(
    file_url="https://example.com/file.pdf",
    file_name="document.pdf"
)
```

### Tool Component

**Manifest** (`components/tools/get_weather.yaml`):
```yaml
apiVersion: v1
kind: Tool
metadata:
  name: get_weather
  label:
    en_US: GetWeather
    zh_Hans: 获取天气
  description:
    en_US: Get weather information for a city
    zh_Hans: 获取城市天气信息

spec:
  parameters:
    type: object
    properties:
      city:
        type: string
        description: City name (e.g., "Tokyo", "New York")
      unit:
        type: string
        enum: ["celsius", "fahrenheit"]
        description: Temperature unit
    required:
      - city

  llm_prompt: |
    Get current weather information for a specified city.
    Use this tool when users ask about weather conditions.

    Parameters:
    - city: Name of the city (required)
    - unit: Temperature unit, "celsius" or "fahrenheit" (optional, default: celsius)

    Returns:
    - temperature: Current temperature
    - condition: Weather condition (e.g., "sunny", "rainy")
    - humidity: Humidity percentage

execution:
  python:
    path: get_weather.py
    attr: GetWeather
```

**Implementation** (`components/tools/get_weather.py`):
```python
from langbot_plugin.api.definition.components.tool.tool import Tool
from typing import Any
import httpx

class GetWeather(Tool):
    """
    Tool component.
    Called by LLM during Agent execution.
    """

    async def call(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Tool execution method.

        Args:
            params: Parameters from LLM (validated against JSON schema)

        Returns:
            Tool result (must be JSON-serializable)
        """
        # Extract parameters
        city = params.get('city')
        unit = params.get('unit', 'celsius')

        # Access plugin configuration
        config = self.plugin.get_config()
        api_key = config.get('weather_api_key')

        # Call external API
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.weather.com/v1/current",
                params={'city': city, 'unit': unit, 'key': api_key}
            )
            data = response.json()

        # Return structured result
        return {
            'temperature': data['temp'],
            'condition': data['condition'],
            'humidity': data['humidity'],
            'unit': unit
        }
```

**Important Notes**:
- All tool methods are async
- Parameters must match JSON schema in manifest
- Return values must be JSON-serializable
- LLM uses `llm_prompt` to decide when/how to call tool
- Access plugin config via `self.plugin.get_config()`

### Event Listener Component

**Manifest** (`components/event_listener/message_handler.yaml`):
```yaml
apiVersion: v1
kind: EventListener
metadata:
  name: message_handler
  label:
    en_US: MessageHandler
    zh_Hans: 消息处理器
  description:
    en_US: Handle incoming messages
    zh_Hans: 处理收到的消息
execution:
  python:
    path: message_handler.py
    attr: MessageHandler
```

**Implementation** (`components/event_listener/message_handler.py`):
```python
from langbot_plugin.api.definition.components.common.event_listener import EventListener
from langbot_plugin.api.entities import events, context
from langbot_plugin.api.entities.builtin.platform import message as pm

class MessageHandler(EventListener):
    """
    Event listener component.
    Handles events from LangBot pipeline.
    """

    def __init__(self):
        super().__init__()

        # Register handler for person normal messages
        @self.handler(events.PersonNormalMessageReceived)
        async def on_person_message(event_context: context.EventContext):
            """
            Triggered when user sends a normal message (not command).
            """
            # Access event data
            event = event_context.event
            query_id = event_context.query_id

            # Prevent default processing (stops LLM response)
            # event_context.prevent_default()

            # Prevent other plugins from handling this event
            # event_context.prevent_postorder()

            # Reply to message
            reply_chain = pm.MessageChain([
                pm.Plain(text="Hello! I received your message."),
                pm.Image(url="https://example.com/image.png")
            ])

            await event_context.reply(reply_chain, quote_origin=True)

        # Register handler for group messages
        @self.handler(events.GroupNormalMessageReceived)
        async def on_group_message(event_context: context.EventContext):
            """
            Triggered when group message is received.
            """
            event = event_context.event
            # Process group message
            pass

        # Register handler for prompt pre-processing
        @self.handler(events.PromptPreProcessing)
        async def on_prompt_preprocess(event_context: context.EventContext):
            """
            Triggered before sending message to LLM.
            Can modify prompt or context.
            """
            # Access/modify query variables
            await event_context.set_query_var('custom_key', 'custom_value')
            value = await event_context.get_query_var('custom_key')
```

**Event Types**:
- `PersonMessageReceived`: Any private message
- `GroupMessageReceived`: Any group message
- `PersonNormalMessageReceived`: Normal private message (after command processing)
- `GroupNormalMessageReceived`: Normal group message (after command processing)
- `PersonCommandSent`: Command in private chat
- `GroupCommandSent`: Command in group chat
- `NormalMessageResponded`: After AI responds
- `PromptPreProcessing`: Before sending to LLM

**EventContext APIs**:
```python
# Reply to message
await event_context.reply(message_chain: MessageChain, quote_origin: bool = True)

# Get bot UUID
bot_uuid = await event_context.get_bot_uuid()

# Query variables
await event_context.set_query_var(key: str, value: Any)
value = await event_context.get_query_var(key: str) -> Any

# Control flow
event_context.prevent_default()      # Stop default processing
event_context.prevent_postorder()    # Block subsequent plugins
```

### Message Chain System

**MessageChain** is a flexible container for rich message content:

```python
from langbot_plugin.api.entities.builtin.platform import message as pm

# Create message chain
chain = pm.MessageChain([
    pm.Plain(text="Hello, "),
    pm.At(target=12345),              # @ mention user
    pm.Plain(text="!\n"),
    pm.Image(url="https://example.com/image.png"),
    pm.Image(base64="data:image/png;base64,..."),
    pm.Voice(url="https://example.com/audio.mp3"),
    pm.File(url="https://example.com/doc.pdf", name="document.pdf"),
])

# Operations
chain.append(pm.Plain(text=" More text"))
first_plain = chain.get_first(pm.Plain)
text_only = str(chain)                # Plain text representation

# Serialization
data = chain.model_dump()             # To dict
loaded = pm.MessageChain.model_validate(data)  # From dict
```

**Message Component Types**:
- `Plain(text: str)`: Text content
- `At(target: int|str)`: @ mention user
- `AtAll()`: @ mention all
- `Image(url: str)` or `Image(base64: str)` or `Image(path: str)`: Images
- `Voice(url: str)`: Audio/voice
- `File(url: str, name: str)`: File attachments
- `Quote(origin: MessageChain)`: Reply to previous message
- `Forward(messages: list[MessageChain])`: Merged forwarded messages
- `Source(id: str, time: int)`: Message metadata

## Plugin Manifest

**Plugin Manifest** (`manifest.yaml`):
```yaml
apiVersion: v1
kind: Plugin
metadata:
  author: YourName
  name: PluginName
  repository: https://github.com/yourname/plugin
  version: 0.1.0
  description:
    en_US: English description
    zh_Hans: Chinese description
  label:
    en_US: Display Name
    zh_Hans: 显示名称
  icon: assets/icon.svg

spec:
  config:
    - name: api_key
      type: string
      label:
        en_US: API Key
        zh_Hans: API 密钥
      description:
        en_US: Your API key for external service
        zh_Hans: 外部服务的 API 密钥
      required: true

    - name: text_input
      type: text
      label:
        en_US: Text Input
        zh_Hans: 文本输入
      default: "Default value"

    - name: file_input
      type: file
      label:
        en_US: Configuration File
        zh_Hans: 配置文件
      accept: "application/json"
      required: false

    - name: file_array
      type: array[file]
      label:
        en_US: Multiple Files
        zh_Hans: 多个文件

    - name: selection
      type: select
      label:
        en_US: Select Option
        zh_Hans: 选择选项
      options:
        - value: option1
          label:
            en_US: Option 1
            zh_Hans: 选项 1
        - value: option2
          label:
            en_US: Option 2
            zh_Hans: 选项 2

    - name: bot_selection
      type: bot-selector
      label:
        en_US: Select Bot
        zh_Hans: 选择机器人

  components:
    Command:
      fromDirs:
        - path: components/commands/
    Tool:
      fromDirs:
        - path: components/tools/
    EventListener:
      fromDirs:
        - path: components/event_listener/

execution:
  python:
    path: main.py
    attr: PluginName
```

**Configuration Types**:
- `string`: Simple text input
- `text`: Multi-line text input
- `integer`: Integer number
- `float`: Floating-point number
- `boolean`: True/false checkbox
- `select`: Dropdown selection
- `array[string]`: Multiple string values
- `file`: Single file upload
- `array[file]`: Multiple file upload
- `bot-selector`: Select bot from LangBot
- `llm-model-selector`: Select LLM model
- `prompt-editor`: Prompt template editor

## Runtime System Architecture

### Plugin Manager (`runtime/plugin/mgr.py`)

Responsibilities:
- Discover plugins in directories
- Install plugins from GitHub/marketplace
- Manage plugin dependencies (requirements.txt)
- Launch plugin processes
- Monitor plugin health

Key Methods:
```python
async def discover_plugins() -> list[PluginContainer]
async def install_plugin(source: str) -> PluginContainer
async def start_plugin(container: PluginContainer)
async def stop_plugin(container: PluginContainer)
```

### Plugin Container (`runtime/plugin/container.py`)

Encapsulates plugin instance with:
- Plugin metadata (manifest)
- Component containers (Commands, Tools, EventListeners)
- Runtime status (UNMOUNTED, MOUNTED, INITIALIZED)
- Communication handler

### Communication Protocol (`runtime/io/`)

**Action-Based Protocol**:
- Bidirectional JSON messages
- Request-response with sequence IDs
- Streaming support via chunk status
- File transfer (16KB chunks)

**Action Structure**:
```json
{
  "action": "action_name",
  "seq": 12345,
  "data": {...},
  "chunk_status": "start|continue|end"
}
```

**Response Structure**:
```json
{
  "seq": 12345,
  "ok": true,
  "data": {...}
}
```

**Transport Implementations**:
- `StdioHandler`: stdin/stdout communication
- `WebSocketHandler`: WebSocket client/server

## CLI Tools

### lbp Commands

```bash
# Initialize new plugin
lbp init [plugin_name]

# Generate component
lbp comp [Command|Tool|EventListener]

# Run plugin locally (requires running LangBot)
lbp run [-s]

# Build plugin for distribution
lbp build

# Publish to marketplace
lbp publish

# Start runtime (for WebSocket mode)
lbp rt
```

### Template System (`cli/gen/`)

- Jinja2-based templates in `assets/templates/`
- Variables: plugin_name, plugin_author, component_name
- Generates boilerplate code and manifests

## Testing & Debugging

### Local Testing

1. Start LangBot:
```bash
cd /path/to/LangBot
uv run main.py
```

2. Run plugin:
```bash
cd /path/to/your-plugin
lbp run
```

Plugin connects to LangBot via stdio for testing.

### Debugging Tips

- Use `print()` statements (output to stderr for visibility)
- Check LangBot logs for plugin errors
- Test components individually
- Validate manifest YAML syntax
- Use type hints for Pydantic validation errors

## Integration with LangBot

### Plugin Discovery

LangBot scans `data/plugins/` directory:
```
data/plugins/
├── PluginA/
│   ├── manifest.yaml
│   ├── main.py
│   └── components/
└── PluginB/
    ├── manifest.yaml
    └── ...
```

### Plugin Execution

1. LangBot starts Plugin Runtime
2. Runtime discovers and loads plugins
3. Each plugin runs in separate process
4. Runtime routes events to plugins
5. Plugins process and respond

## Important File References

### SDK Core
- Plugin base: `src/langbot_plugin/api/definition/plugin.py`
- Command base: `src/langbot_plugin/api/definition/components/command/command.py`
- Tool base: `src/langbot_plugin/api/definition/components/tool/tool.py`
- EventListener base: `src/langbot_plugin/api/definition/components/common/event_listener.py`

### Entities
- ExecuteContext: `src/langbot_plugin/api/entities/builtin/command/context.py`
- EventContext: `src/langbot_plugin/api/entities/context.py`
- Events: `src/langbot_plugin/api/entities/events.py`
- MessageChain: `src/langbot_plugin/api/entities/builtin/platform/message.py`

### Runtime
- PluginManager: `src/langbot_plugin/runtime/plugin/mgr.py`
- PluginContainer: `src/langbot_plugin/runtime/plugin/container.py`
- Handler: `src/langbot_plugin/runtime/io/handler.py`

### CLI
- Main: `src/langbot_plugin/cli/main.py`
- Init: `src/langbot_plugin/cli/init.py`
- Gen: `src/langbot_plugin/cli/gen/`

### Examples
- See `../langbot-plugin-demo/` for complete examples

## Best Practices

### Code Style
- Use async/await for all I/O operations
- Type hints with Pydantic models
- English comments and docstrings
- Follow PEP 8 conventions

### Error Handling
- Try/catch in component methods
- Return meaningful error messages
- Log errors for debugging
- Don't crash on invalid input

### Configuration
- Validate config in `initialize()`
- Provide sensible defaults
- Support i18n for labels and descriptions
- Document configuration options

### Testing
- Write unit tests for business logic
- Test with real LangBot instance
- Validate manifest YAML
- Test edge cases

### Performance
- Use async for concurrent operations
- Cache expensive computations
- Avoid blocking operations
- Release resources properly

### Security
- Validate user input
- Sanitize external data
- Don't log sensitive information
- Follow principle of least privilege

## Platform Compatibility

### Windows
- Native Windows: Plugin system has limitations (Asyncio ProactorEventLoop)
- Recommended: Use WSL2 or Docker
- Future: WebSocket mode will fully support Windows

### Linux/macOS
- Full support for stdio and WebSocket modes
- Recommended for development and production

## Some Development Tips and Standards

- All user-facing text must support i18n (en_US, zh_Hans at minimum)
- All code comments and docstrings in English
- Use Pydantic for data validation
- Async/await everywhere for I/O
- Follow type hints strictly
- Write comprehensive docstrings
- Test components independently
- Keep components focused and single-purpose

## Some Principles

- Keep it simple, stupid.
- Entities should not be multiplied unnecessarily
- 八荣八耻

    以瞎猜接口为耻，以认真查询为荣。
    以模糊执行为耻，以寻求确认为荣。
    以臆想业务为耻，以人类确认为荣。
    以创造接口为耻，以复用现有为荣。
    以跳过验证为耻，以主动测试为荣。
    以破坏架构为耻，以遵循规范为荣。
    以假装理解为耻，以诚实无知为荣。
    以盲目修改为耻，以谨慎重构为荣。
