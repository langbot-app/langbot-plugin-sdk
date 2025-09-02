# Development Environment Setup

This guide will help you set up a complete development environment for LangBot plugin development, from basic installation to advanced IDE configuration.

## System Requirements

### Minimum Requirements
- **Operating System**: Windows 10+, macOS 10.14+, or Linux (Ubuntu 18.04+)
- **Python**: 3.10 or higher
- **Memory**: 4GB RAM
- **Storage**: 1GB free space
- **Network**: Internet connection for package downloads

### Recommended Requirements
- **Python**: 3.11 or 3.12 (latest stable)
- **Memory**: 8GB+ RAM for comfortable development
- **Storage**: 5GB+ free space for dependencies and projects
- **IDE**: VS Code, PyCharm, or similar modern editor

## Quick Setup

For experienced developers who want to get started immediately:

```bash
# 1. Install Python 3.11+
python --version  # Should be 3.10+

# 2. Create virtual environment
python -m venv langbot-dev
source langbot-dev/bin/activate  # On Windows: langbot-dev\Scripts\activate

# 3. Install the SDK
pip install langbot-plugin

# 4. Verify installation
lbp --version

# 5. Create your first plugin
lbp init my-plugin
cd my-plugin
lbp run --debug
```

## Detailed Setup Instructions

### Step 1: Python Installation

#### Windows

**Option 1: From python.org (Recommended)**
1. Download Python from [python.org](https://www.python.org/downloads/)
2. Run installer with "Add to PATH" checked
3. Verify: `python --version`

**Option 2: Using Windows Package Manager**
```powershell
# Install Python using winget
winget install Python.Python.3.11

# Or using Chocolatey
choco install python
```

**Option 3: Using Microsoft Store**
1. Open Microsoft Store
2. Search for "Python 3.11"
3. Install the official Python package

#### macOS

**Option 1: Using Homebrew (Recommended)**
```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python
brew install python@3.11

# Verify installation
python3 --version
```

**Option 2: Using pyenv**
```bash
# Install pyenv
curl https://pyenv.run | bash

# Install Python 3.11
pyenv install 3.11.0
pyenv global 3.11.0
```

#### Linux (Ubuntu/Debian)

```bash
# Update package list
sudo apt update

# Install Python 3.11
sudo apt install python3.11 python3.11-pip python3.11-venv

# Install development tools
sudo apt install python3.11-dev build-essential

# Verify installation
python3.11 --version
```

#### Linux (CentOS/RHEL/Fedora)

```bash
# For Fedora
sudo dnf install python3.11 python3.11-pip

# For CentOS/RHEL (enable EPEL first)
sudo yum install epel-release
sudo yum install python311 python311-pip
```

### Step 2: Virtual Environment Setup

Virtual environments isolate your project dependencies:

#### Using venv (Built-in)

```bash
# Create virtual environment
python -m venv langbot-dev

# Activate virtual environment
# On Windows:
langbot-dev\Scripts\activate
# On macOS/Linux:
source langbot-dev/bin/activate

# Verify activation (should show virtual env path)
which python

# Upgrade pip
python -m pip install --upgrade pip
```

#### Using conda

```bash
# Install Miniconda or Anaconda first
# Then create environment
conda create -n langbot-dev python=3.11
conda activate langbot-dev

# Install pip in conda environment
conda install pip
```

#### Using poetry

```bash
# Install poetry
curl -sSL https://install.python-poetry.org | python3 -

# Create new project with poetry
poetry new my-langbot-plugin
cd my-langbot-plugin

# Add LangBot SDK
poetry add langbot-plugin

# Activate shell
poetry shell
```

### Step 3: Install LangBot Plugin SDK

```bash
# Basic installation
pip install langbot-plugin

# Development installation (with extra tools)
pip install langbot-plugin[dev]

# From source (for contributing)
git clone https://github.com/langbot-app/langbot-plugin-sdk.git
cd langbot-plugin-sdk
pip install -e .

# Verify installation
lbp --version
lbp --help
```

### Step 4: IDE Configuration

#### Visual Studio Code

**Install VS Code**
- Download from [code.visualstudio.com](https://code.visualstudio.com/)
- Install the Python extension pack

**Essential Extensions**
```bash
# Install via command line
code --install-extension ms-python.python
code --install-extension ms-python.pylance
code --install-extension ms-python.flake8
code --install-extension ms-python.black-formatter
```

**VS Code Settings** (`.vscode/settings.json`):
```json
{
    "python.defaultInterpreterPath": "./langbot-dev/bin/python",
    "python.linting.enabled": true,
    "python.linting.pylintEnabled": true,
    "python.formatting.provider": "black",
    "python.formatting.blackArgs": ["--line-length", "88"],
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": ["tests"],
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
        "source.organizeImports": true
    },
    "files.exclude": {
        "**/__pycache__": true,
        "**/*.pyc": true,
        ".pytest_cache": true
    }
}
```

**Launch Configuration** (`.vscode/launch.json`):
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Run Plugin",
            "type": "python",
            "request": "launch",
            "program": "${workspaceFolder}/main.py",
            "console": "integratedTerminal",
            "env": {
                "PYTHONPATH": "${workspaceFolder}"
            }
        },
        {
            "name": "Debug Plugin with LBP",
            "type": "python",
            "request": "launch",
            "module": "langbot_plugin.cli",
            "args": ["run", "--debug"],
            "console": "integratedTerminal",
            "cwd": "${workspaceFolder}"
        }
    ]
}
```

#### PyCharm

**Installation**
- Download from [jetbrains.com/pycharm](https://www.jetbrains.com/pycharm/)
- Use Community Edition (free) or Professional Edition

**Configuration Steps**
1. Open PyCharm
2. Create new project or open existing
3. Configure Python interpreter:
   - File → Settings → Project → Python Interpreter
   - Add interpreter → Existing environment
   - Select your virtual environment's Python executable

**Recommended Plugins**
- Python Community Edition (built-in)
- Markdown support
- .ignore
- Rainbow Brackets

#### Other Editors

**Vim/Neovim**
```vim
" Essential plugins for Python development
Plug 'neoclide/coc.nvim', {'branch': 'release'}
Plug 'psf/black', { 'branch': 'stable' }
Plug 'nvie/vim-flake8'
```

**Sublime Text**
- Install Package Control
- Install packages: Python 3, SublimeLinter, SublimeLinter-flake8

### Step 5: Development Tools

#### Code Quality Tools

```bash
# Install development dependencies
pip install black flake8 mypy pytest pytest-asyncio

# Or using requirements-dev.txt
echo "black>=22.0.0
flake8>=4.0.0
mypy>=0.910
pytest>=6.0.0
pytest-asyncio>=0.18.0
pytest-cov>=3.0.0" > requirements-dev.txt

pip install -r requirements-dev.txt
```

#### Pre-commit Hooks

```bash
# Install pre-commit
pip install pre-commit

# Create .pre-commit-config.yaml
cat > .pre-commit-config.yaml << EOF
repos:
  - repo: https://github.com/psf/black
    rev: 22.12.0
    hooks:
      - id: black
        language_version: python3

  - repo: https://github.com/pycqa/flake8
    rev: 6.0.0
    hooks:
      - id: flake8

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v0.991
    hooks:
      - id: mypy
        additional_dependencies: [types-all]
EOF

# Install the hooks
pre-commit install
```

#### Testing Setup

```bash
# Create test directory structure
mkdir -p tests/{unit,integration,fixtures}
touch tests/__init__.py

# Create pytest configuration
cat > pytest.ini << EOF
[tool:pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = 
    --verbose
    --tb=short
    --cov=src
    --cov-report=html
    --cov-report=term-missing
asyncio_mode = auto
EOF
```

### Step 6: Project Structure

#### Standard Project Layout

```bash
# Create project structure
mkdir my-langbot-plugin
cd my-langbot-plugin

# Create directories
mkdir -p {src,tests/{unit,integration},docs,scripts}

# Create files
touch {README.md,requirements.txt,requirements-dev.txt}
touch {main.py,plugin.yaml,.gitignore}
touch tests/{__init__.py,conftest.py}

# Initialize git
git init
git add .
git commit -m "Initial project structure"
```

#### Template Files

**plugin.yaml**
```yaml
name: my-langbot-plugin
version: 0.1.0
description: My awesome LangBot plugin
author: Your Name
homepage: https://github.com/yourusername/my-langbot-plugin
entry: main.py

dependencies:
  - httpx>=0.24.0
  - pydantic>=2.0.0

permissions:
  - send_message
  - receive_message
  - storage_read
  - storage_write

metadata:
  category: utility
  tags: [example, tutorial]
  min_langbot_version: "2.0.0"
```

**requirements.txt**
```
langbot-plugin>=0.1.0
httpx>=0.24.0
pydantic>=2.0.0
```

**requirements-dev.txt**
```
-r requirements.txt
black>=22.0.0
flake8>=4.0.0
mypy>=0.910
pytest>=6.0.0
pytest-asyncio>=0.18.0
pytest-cov>=3.0.0
pre-commit>=2.20.0
```

**.gitignore**
```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/
env.bak/
venv.bak/

# Testing
.pytest_cache/
.coverage
htmlcov/
.tox/

# IDE
.vscode/
.idea/
*.swp
*.swo

# LangBot
.lbp/
dist/
*.log

# OS
.DS_Store
Thumbs.db
```

### Step 7: Environment Variables

#### Development Configuration

```bash
# Create .env file for development
cat > .env << EOF
# Development settings
LBP_DEBUG=true
LBP_LOG_LEVEL=debug
LBP_RUNTIME_PORT=5400

# API Configuration
LANGBOT_API_URL=https://api.langbot.app
LANGBOT_API_TOKEN=your_dev_token_here

# Plugin Configuration
PLUGIN_DEBUG_MODE=true
PLUGIN_HOT_RELOAD=true
EOF

# Add .env to .gitignore
echo ".env" >> .gitignore
```

#### Loading Environment Variables

```python
# In your plugin code
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Use environment variables
DEBUG_MODE = os.getenv('PLUGIN_DEBUG_MODE', 'false').lower() == 'true'
API_TOKEN = os.getenv('LANGBOT_API_TOKEN')
```

### Step 8: Verification

#### Test Your Setup

```bash
# 1. Verify Python and virtual environment
python --version  # Should show 3.10+
which python      # Should show virtual environment path

# 2. Verify LangBot CLI
lbp --version
lbp --help

# 3. Create and run a test plugin
lbp init test-plugin
cd test-plugin
lbp run --debug

# 4. Run tests (if any)
pytest

# 5. Check code quality
black --check .
flake8 .
mypy .
```

#### Common Issues and Solutions

**Issue**: `lbp: command not found`
```bash
# Solution: Ensure virtual environment is activated and pip installed correctly
source langbot-dev/bin/activate  # Activate venv
pip install --upgrade pip
pip install langbot-plugin
```

**Issue**: Python version conflicts
```bash
# Solution: Use explicit Python version
python3.11 -m venv langbot-dev
source langbot-dev/bin/activate
python -m pip install langbot-plugin
```

**Issue**: Permission errors on Windows
```bash
# Solution: Run as administrator or use --user flag
pip install --user langbot-plugin
```

## Advanced Setup

### Docker Development Environment

```dockerfile
# Dockerfile for development
FROM python:3.11-slim

WORKDIR /workspace

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt

# Install LangBot CLI
RUN pip install langbot-plugin

VOLUME ["/workspace"]
CMD ["bash"]
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  langbot-dev:
    build: .
    volumes:
      - .:/workspace
    ports:
      - "5400:5400"  # Runtime port
      - "5401:5401"  # Debug port
    environment:
      - LBP_DEBUG=true
```

### Remote Development

#### VS Code Remote Development

1. Install "Remote - Containers" extension
2. Create `.devcontainer/devcontainer.json`:

```json
{
    "name": "LangBot Plugin Development",
    "dockerFile": "../Dockerfile",
    "forwardPorts": [5400, 5401],
    "postCreateCommand": "pip install -e .",
    "customizations": {
        "vscode": {
            "extensions": [
                "ms-python.python",
                "ms-python.pylance"
            ]
        }
    }
}
```

#### GitHub Codespaces

Create `.devcontainer/devcontainer.json` in your repository for one-click development environment setup.

### Continuous Integration Setup

#### GitHub Actions

```yaml
# .github/workflows/test.yml
name: Test Plugin

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.10, 3.11, 3.12]

    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements-dev.txt
    
    - name: Lint with flake8
      run: flake8 .
    
    - name: Check formatting with black
      run: black --check .
    
    - name: Type check with mypy
      run: mypy .
    
    - name: Test with pytest
      run: pytest
```

## Next Steps

After setting up your development environment:

1. **Read the Documentation**: Familiarize yourself with the [API Reference](../api-reference/)
2. **Try Examples**: Work through the [Examples](../examples/)
3. **Follow Best Practices**: Review [Best Practices](best-practices.md)
4. **Start Building**: Create your first plugin!

## Getting Help

If you encounter issues during setup:

1. **Check the Documentation**: Most common issues are covered here
2. **Search GitHub Issues**: Someone may have already solved your problem
3. **Ask on Discord**: Join our community for real-time help
4. **Create an Issue**: Report bugs or request help on GitHub

---

Your development environment is now ready! Start building amazing LangBot plugins! 🚀