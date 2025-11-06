# Plugin Dependency Management

## Problem

When users update their LangBot containers (by pulling new images and rebuilding), the Python environment is fresh but the `data/plugins/` directory persists as a mounted volume. This causes plugin dependencies to be lost, leading to plugin failures.

## Solution

The runtime now **automatically reinstalls all plugin dependencies on every startup**. This is a simple and straightforward approach that ensures dependencies are always available.

### How It Works

When the runtime starts and launches plugins (in `launch_all_plugins()`):
1. For each plugin directory in `data/plugins/`
2. Check if a `requirements.txt` file exists
3. If it exists, run `pip install -r requirements.txt`
4. Then launch the plugin

This happens **every time** the runtime starts, ensuring that:
- After container rebuild, all dependencies are reinstalled
- After requirements.txt changes, new dependencies are installed
- No state tracking or complexity needed

### Implementation

Modified `src/langbot_plugin/runtime/plugin/mgr.py`:
- `launch_all_plugins()`: Added `pip install -r requirements.txt` before launching each plugin

### Benefits

1. **Simple**: No complex state tracking or hash computation
2. **Reliable**: Dependencies always installed, regardless of container state
3. **Automatic**: Works automatically after container rebuild
4. **Backward Compatible**: Works with existing plugins without modification
5. **Robust**: Handles all edge cases (pip handles already-installed packages efficiently)

### Performance Considerations

- `pip` is smart enough to skip reinstalling packages that are already installed at the correct version
- The startup time will increase slightly due to pip checking installed packages
- For most plugins with few dependencies, this overhead is minimal
