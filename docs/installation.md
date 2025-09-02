# Installation Guide

This guide covers different ways to install and set up the LangBot Plugin SDK for development.

## System Requirements

- **Python**: 3.10 or higher
- **Operating System**: Windows, macOS, or Linux
- **Memory**: At least 512MB RAM available
- **Storage**: 100MB free disk space

## Quick Installation

### Using pip (Recommended)

```bash
pip install langbot-plugin
```

Verify the installation:
```bash
lbp --version
```

### Using pipx (Isolated Installation)

For isolated installation that doesn't affect your system Python:

```bash
# Install pipx if you haven't already
pip install pipx

# Install langbot-plugin with pipx
pipx install langbot-plugin

# Verify
lbp --version
```

## Development Installation

If you want to contribute to the SDK or need the latest development features:

### From Source

```bash
# Clone the repository
git clone https://github.com/langbot-app/langbot-plugin-sdk.git
cd langbot-plugin-sdk

# Install in development mode
pip install -e .

# Install development dependencies
pip install -e ".[dev]"
```

### Using Poetry (Alternative)

```bash
# Clone the repository
git clone https://github.com/langbot-app/langbot-plugin-sdk.git
cd langbot-plugin-sdk

# Install poetry if you haven't already
pip install poetry

# Install dependencies
poetry install

# Activate the virtual environment
poetry shell
```

## Virtual Environment Setup

It's recommended to use a virtual environment for plugin development:

### Using venv

```bash
# Create a virtual environment
python -m venv langbot-env

# Activate it
# On Windows:
langbot-env\Scripts\activate
# On macOS/Linux:
source langbot-env/bin/activate

# Install the SDK
pip install langbot-plugin
```

### Using conda

```bash
# Create a conda environment
conda create -n langbot python=3.11

# Activate it
conda activate langbot

# Install the SDK
pip install langbot-plugin
```

## Configuration

### Initial Setup

After installation, you may want to configure the CLI:

```bash
# Check current configuration
lbp config

# Set default settings (optional)
lbp config --editor code  # Set default editor
lbp config --debug true   # Enable debug mode
```

### Account Setup

To publish plugins to the marketplace, you'll need to login:

```bash
lbp login
```

This will open a web browser for authentication with your LangBot account.

## Verification

Test your installation with these commands:

```bash
# Check version
lbp --version

# Check available commands
lbp --help

# Test plugin creation
lbp init test-plugin
cd test-plugin
lbp run --help
```

## Platform-Specific Instructions

### Windows

#### Using Windows Subsystem for Linux (WSL)

For the best development experience on Windows, consider using WSL:

```bash
# Install WSL (if not already installed)
wsl --install

# Open WSL terminal and install Python
sudo apt update
sudo apt install python3 python3-pip

# Install the SDK
pip3 install langbot-plugin
```

#### Native Windows Installation

```bash
# Using PowerShell or Command Prompt
pip install langbot-plugin

# Add Python Scripts to PATH if needed
# The installer usually does this automatically
```

### macOS

#### Using Homebrew

```bash
# Install Python (if not already installed)
brew install python

# Install the SDK
pip3 install langbot-plugin
```

#### Using pyenv (Recommended for version management)

```bash
# Install pyenv
brew install pyenv

# Install Python 3.11
pyenv install 3.11.0
pyenv global 3.11.0

# Install the SDK
pip install langbot-plugin
```

### Linux

#### Ubuntu/Debian

```bash
# Update package list
sudo apt update

# Install Python and pip
sudo apt install python3 python3-pip

# Install the SDK
pip3 install langbot-plugin

# Add to PATH if needed
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

#### CentOS/RHEL/Fedora

```bash
# Install Python and pip
sudo dnf install python3 python3-pip  # Fedora
# OR
sudo yum install python3 python3-pip  # CentOS/RHEL

# Install the SDK
pip3 install langbot-plugin
```

#### Arch Linux

```bash
# Install Python and pip
sudo pacman -S python python-pip

# Install the SDK
pip install langbot-plugin
```

## Docker Installation

For containerized development:

### Using Official Docker Image

```bash
# Pull the official image (when available)
docker pull langbot/plugin-sdk:latest

# Run interactive container
docker run -it langbot/plugin-sdk:latest bash
```

### Building Custom Image

Create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install LangBot Plugin SDK
RUN pip install langbot-plugin

# Set working directory
WORKDIR /workspace

# Default command
CMD ["lbp", "--help"]
```

Build and run:

```bash
# Build the image
docker build -t my-langbot-dev .

# Run container with volume mount
docker run -it -v $(pwd):/workspace my-langbot-dev bash
```

## IDE Setup

### Visual Studio Code

Recommended extensions for LangBot plugin development:

1. **Python** - Python language support
2. **Pylance** - Enhanced Python intellisense
3. **Python Type Checker** - Type checking support

Create `.vscode/settings.json`:

```json
{
    "python.defaultInterpreterPath": "./venv/bin/python",
    "python.linting.enabled": true,
    "python.linting.pylintEnabled": true,
    "python.formatting.provider": "black"
}
```

### PyCharm

1. Create a new Python project
2. Set Python interpreter to your virtual environment
3. Install the LangBot Plugin SDK in the project interpreter
4. Configure code style to match the project standards

## Troubleshooting

### Common Issues

#### Permission Errors

```bash
# If you get permission errors on Linux/macOS
pip install --user langbot-plugin

# Or use sudo (not recommended)
sudo pip install langbot-plugin
```

#### Python Version Issues

```bash
# Check Python version
python --version

# If using multiple Python versions
python3.11 -m pip install langbot-plugin
```

#### PATH Issues

If `lbp` command is not found:

```bash
# Find where pip installed the package
pip show -f langbot-plugin

# Add the Scripts/bin directory to your PATH
# On Windows: Add to Environment Variables
# On Linux/macOS: Add to ~/.bashrc or ~/.zshrc
export PATH="$HOME/.local/bin:$PATH"
```

#### Network Issues

```bash
# Use a different index if PyPI is slow
pip install -i https://pypi.douban.com/simple/ langbot-plugin

# Or use a proxy
pip install --proxy http://proxy.server:port langbot-plugin
```

### Getting Help

If you encounter issues:

1. Check the [GitHub Issues](https://github.com/langbot-app/langbot-plugin-sdk/issues)
2. Search the [Community Forum](https://community.langbot.app)
3. Create a new issue with:
   - Your operating system and version
   - Python version (`python --version`)
   - Error messages or logs
   - Steps to reproduce the issue

## Next Steps

After successful installation:

1. 📚 Read the [Quick Start Guide](quick-start.md)
2. 🔧 Explore [CLI Commands](cli-reference.md)
3. 📖 Check out [Examples](examples/)
4. 👩‍💻 Set up your [Development Environment](development/setup.md)

## Keeping Updated

To update to the latest version:

```bash
# Update the SDK
pip install --upgrade langbot-plugin

# Check the new version
lbp --version
```

To get notifications about updates, consider:
- ⭐ Starring the [GitHub repository](https://github.com/langbot-app/langbot-plugin-sdk)
- 📢 Following [@LangBotApp](https://twitter.com/langbotapp) on Twitter
- 📧 Subscribing to the [newsletter](https://langbot.app/newsletter)