# CLI Reference

The LangBot Plugin CLI (`lbp`) is a comprehensive command-line tool for developing, building, and managing LangBot plugins. It provides everything you need for the complete plugin development lifecycle.

## Overview

The CLI provides commands for:

- 🚀 **Plugin Development** - Create, run, and debug plugins
- 🔧 **Component Generation** - Generate boilerplate code and components
- 📦 **Build & Deploy** - Package and publish plugins
- 👤 **Account Management** - Login, logout, and account operations
- 🔍 **Runtime Management** - Control the plugin runtime environment

## Installation & Setup

```bash
# Install the CLI
pip install langbot-plugin

# Verify installation
lbp --version

# Get help
lbp --help
```

## Global Options

All commands support these global options:

```bash
lbp [global-options] <command> [command-options]
```

| Option | Description |
|--------|-------------|
| `--help`, `-h` | Show help information |
| `--version` | Show version information |
| `--verbose`, `-v` | Enable verbose output |
| `--quiet`, `-q` | Suppress non-essential output |

## Commands Reference

### `lbp init` - Initialize Plugin

Create a new plugin project with proper structure and boilerplate code.

```bash
lbp init [plugin-name]
```

**Arguments:**
- `plugin-name` (optional): Name of the plugin. If not provided, you'll be prompted.

**Examples:**
```bash
# Create plugin with interactive prompts
lbp init

# Create plugin with specific name
lbp init my-awesome-plugin

# Create in current directory
lbp init .
```

**Generated Structure:**
```
my-awesome-plugin/
├── plugin.yaml          # Plugin configuration
├── main.py              # Main plugin entry point
├── requirements.txt     # Python dependencies
├── README.md           # Plugin documentation
└── .gitignore          # Git ignore rules
```

**plugin.yaml Example:**
```yaml
name: my-awesome-plugin
version: 1.0.0
description: My awesome LangBot plugin
author: Your Name
homepage: https://github.com/username/my-awesome-plugin
entry: main.py
dependencies:
  - requests>=2.25.0
permissions:
  - send_message
  - storage_read
  - storage_write
```

---

### `lbp comp` - Generate Component

Generate boilerplate code for common plugin components.

```bash
lbp comp <component-type> [options]
```

**Component Types:**

#### `handler`
Generate event handler functions:

```bash
lbp comp handler --event MessageEvent --name handle_message
```

**Options:**
- `--event`: Event type to handle (MessageEvent, GroupMessage, etc.)
- `--name`: Handler function name
- `--async`: Generate async handler (default: true)

**Generated Code:**
```python
@register_handler(MessageEvent)
async def handle_message(event: MessageEvent, context: PluginContext):
    """Handle MessageEvent"""
    # TODO: Implement your handler logic
    pass
```

#### `command`
Generate command handler:

```bash
lbp comp command --name weather --description "Get weather information"
```

**Options:**
- `--name`: Command name
- `--description`: Command description
- `--args`: Command arguments

#### `storage`
Generate storage helper class:

```bash
lbp comp storage --name UserPreferences
```

#### `llm`
Generate LLM integration code:

```bash
lbp comp llm --name ai_responder
```

---

### `lbp run` - Run Plugin

Run the plugin in development mode for testing and debugging.

```bash
lbp run [options]
```

**Options:**
- `--stdio`, `-s`: Use stdio for control connection
- `--debug`: Enable debug mode
- `--port`: Specify port for runtime communication
- `--hot-reload`: Enable hot reloading for development

**Examples:**
```bash
# Basic run
lbp run

# Run with debug output
lbp run --debug

# Run with stdio control
lbp run --stdio

# Run with hot reload
lbp run --hot-reload --debug
```

**Development Features:**
- **Hot Reload**: Automatically restart when files change
- **Debug Mode**: Detailed logging and error reporting
- **Interactive Console**: Direct plugin interaction
- **Breakpoint Support**: Integration with Python debuggers

---

### `lbp build` - Build Plugin

Package the plugin for distribution.

```bash
lbp build [options]
```

**Options:**
- `--output`, `-o`: Output directory (default: `dist`)
- `--format`: Package format (`zip`, `tar.gz`)
- `--include-deps`: Include dependencies in package
- `--minify`: Minify code (remove comments, optimize)

**Examples:**
```bash
# Basic build
lbp build

# Build to specific directory
lbp build --output release

# Build with dependencies included
lbp build --include-deps

# Build optimized package
lbp build --minify
```

**Build Process:**
1. Validates plugin configuration
2. Checks dependencies
3. Runs tests (if present)
4. Packages files into distributable format
5. Generates metadata and checksums

**Output Structure:**
```
dist/
├── my-plugin-1.0.0.zip     # Main package
├── my-plugin-1.0.0.json    # Metadata
└── checksums.txt           # Package verification
```

---

### `lbp publish` - Publish Plugin

Publish the plugin to the LangBot Marketplace.

```bash
lbp publish [options]
```

**Options:**
- `--output`, `-o`: Build output directory (default: `dist`)
- `--tag`: Release tag
- `--message`: Release message
- `--private`: Publish as private plugin
- `--beta`: Publish as beta release

**Prerequisites:**
- Must be logged in (`lbp login`)
- Plugin must be built (`lbp build`)
- Valid plugin configuration

**Examples:**
```bash
# Publish latest build
lbp publish

# Publish with release message
lbp publish --message "Added new features and bug fixes"

# Publish as beta
lbp publish --beta --tag v1.0.0-beta.1

# Publish as private plugin
lbp publish --private
```

**Publishing Process:**
1. Validates plugin package
2. Checks marketplace guidelines
3. Uploads package and metadata
4. Updates marketplace listing
5. Notifies users (if public)

---

### Account Management

#### `lbp login` - Login to Account

Authenticate with your LangBot account.

```bash
lbp login [options]
```

**Options:**
- `--token`: Use API token for authentication
- `--device`: Device name for authentication

**Methods:**
```bash
# Interactive login (opens browser)
lbp login

# Token-based login
lbp login --token YOUR_API_TOKEN

# Login with device name
lbp login --device "My Development Machine"
```

#### `lbp logout` - Logout

Clear authentication credentials.

```bash
lbp logout
```

**Effects:**
- Removes stored authentication tokens
- Clears cached user information
- Disables marketplace operations

---

### `lbp rt` - Runtime Management

Start and manage the plugin runtime environment.

```bash
lbp rt [options]
```

**Options:**
- `--stdio-control`, `-s`: Use stdio for control connection
- `--ws-control-port`: WebSocket control port (default: 5400)
- `--ws-debug-port`: WebSocket debug port (default: 5401)
- `--debug-only`: Only run debug server
- `--host`: Bind host address
- `--config`: Runtime configuration file

**Examples:**
```bash
# Start runtime with defaults
lbp rt

# Start with custom ports
lbp rt --ws-control-port 6000 --ws-debug-port 6001

# Start debug-only mode
lbp rt --debug-only

# Start with stdio control
lbp rt --stdio-control
```

**Runtime Features:**
- **Plugin Hosting**: Runs multiple plugins simultaneously
- **Hot Reloading**: Supports development workflow
- **Debug Interface**: WebSocket-based debugging
- **Health Monitoring**: Runtime status and metrics

---

### Utility Commands

#### `lbp help` - Show Help

Display help information for commands.

```bash
lbp help [command]
```

**Examples:**
```bash
# General help
lbp help

# Command-specific help
lbp help init
lbp help build
```

#### `lbp ver` - Show Version

Display version information.

```bash
lbp ver
```

**Output:**
```
LangBot Plugin SDK v0.1.1-beta.6
Python 3.11.0
Platform: Linux-5.4.0-x86_64
```

---

## Configuration

### Global Configuration

CLI configuration is stored in `~/.langbot/config.yaml`:

```yaml
# Default configuration
defaults:
  editor: code
  build_format: zip
  debug_mode: false
  auto_reload: true

# User preferences
user:
  name: "Your Name"
  email: "your.email@example.com"
  
# Development settings
development:
  hot_reload: true
  debug_port: 5401
  log_level: info

# Marketplace settings
marketplace:
  auto_publish: false
  private_by_default: false
```

### Project Configuration

Each plugin can have local configuration in `.lbp/config.yaml`:

```yaml
# Project-specific settings
project:
  name: my-awesome-plugin
  version: 1.0.0
  
# Development overrides
development:
  port: 5402
  debug: true
  
# Build settings
build:
  output_dir: dist
  include_tests: false
  minify: true
```

### Environment Variables

The CLI respects these environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `LBP_HOME` | CLI home directory | `~/.langbot` |
| `LBP_DEBUG` | Enable debug mode | `false` |
| `LBP_LOG_LEVEL` | Logging level | `info` |
| `LBP_RUNTIME_PORT` | Default runtime port | `5400` |
| `LBP_API_URL` | Marketplace API URL | Official API |

## Workflows

### Development Workflow

```bash
# 1. Create new plugin
lbp init my-plugin
cd my-plugin

# 2. Generate components as needed
lbp comp handler --event MessageEvent --name handle_message
lbp comp command --name weather

# 3. Develop with hot reload
lbp run --hot-reload --debug

# 4. Test and iterate
# ... make changes to your code ...

# 5. Build when ready
lbp build

# 6. Publish to marketplace
lbp login
lbp publish
```

### CI/CD Integration

```yaml
# GitHub Actions example
name: Build and Publish Plugin

on:
  push:
    tags: ['v*']

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
          
      - name: Install CLI
        run: pip install langbot-plugin
        
      - name: Build plugin
        run: lbp build
        
      - name: Login to marketplace
        run: lbp login --token ${{ secrets.LBP_TOKEN }}
        
      - name: Publish plugin
        run: lbp publish --tag ${{ github.ref_name }}
```

## Debugging

### Debug Mode

Enable debug mode for detailed output:

```bash
# Debug specific command
lbp --verbose build

# Debug runtime
lbp run --debug

# Debug with breakpoints
lbp run --debug --port 5401
# Then connect debugger to localhost:5401
```

### Common Issues

#### Plugin Won't Start

```bash
# Check plugin configuration
lbp validate

# Check dependencies
lbp check-deps

# Run with debug output
lbp run --debug --verbose
```

#### Build Failures

```bash
# Validate plugin before building
lbp validate

# Check build output
lbp build --verbose

# Clean and rebuild
lbp clean
lbp build
```

#### Authentication Issues

```bash
# Check login status
lbp status

# Re-authenticate
lbp logout
lbp login

# Use token authentication
lbp login --token YOUR_TOKEN
```

## Advanced Usage

### Custom Templates

Create custom templates for `lbp init`:

```bash
# Create template directory
mkdir ~/.langbot/templates/my-template

# Use custom template
lbp init my-plugin --template my-template
```

### Plugin Development Scripts

Create development scripts in `package.json` style:

```yaml
# plugin.yaml
scripts:
  dev: lbp run --hot-reload --debug
  build: lbp build --minify
  test: python -m pytest tests/
  lint: python -m ruff check .
  deploy: lbp build && lbp publish
```

```bash
# Run scripts
lbp run-script dev
lbp run-script test
lbp run-script deploy
```

### Plugin Validation

```bash
# Validate plugin configuration
lbp validate

# Check for common issues
lbp lint

# Run security checks
lbp security-check

# Performance analysis
lbp profile
```

## Related Documentation

- [Quick Start Guide](quick-start.md) - Get started with CLI
- [Installation Guide](installation.md) - CLI installation details
- [API Reference](api-reference/) - Plugin API documentation
- [Examples](examples/) - Example projects and usage
- [Development Guide](development/) - Advanced development topics