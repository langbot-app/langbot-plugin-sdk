# Plugin Dependency Management

## Problem

When users update their LangBot containers (by pulling new images and rebuilding), the Python environment is fresh but the `data/plugins/` directory persists as a mounted volume. This causes plugin dependencies to be lost, leading to plugin failures.

## Solution

The runtime now automatically tracks and reinstalls plugin dependencies when needed using a dependency state tracking system.

### How It Works

1. **Dependency State Tracking**: Each plugin directory contains a `.deps_state.json` file that tracks:
   - SHA256 hash of the `requirements.txt` file
   - Other metadata about installed dependencies

2. **Automatic Dependency Check**: When the runtime starts and launches plugins:
   - It checks each plugin's `requirements.txt` against the stored hash
   - If the hash doesn't match (or doesn't exist), dependencies are reinstalled
   - If the hash matches, dependencies are assumed to be installed and the plugin launches immediately

3. **Installation Tracking**: When a new plugin is installed:
   - Dependencies are installed as usual
   - The dependency state is recorded in `.deps_state.json`

### Implementation Details

- **New Module**: `src/langbot_plugin/runtime/helper/depsmgr.py`
  - Contains the `DependencyManager` class
  - Provides methods for checking, installing, and tracking dependencies

- **Modified Module**: `src/langbot_plugin/runtime/plugin/mgr.py`
  - `launch_all_plugins()`: Added dependency check before launching each plugin
  - `install_plugin()`: Added dependency state tracking after installation

### Benefits

1. **Automatic Recovery**: No manual intervention needed after container updates
2. **Efficient**: Only reinstalls dependencies when `requirements.txt` changes
3. **Backward Compatible**: Works with existing plugins without modification
4. **Robust**: Handles edge cases like missing or empty requirements files

### State File Format

The `.deps_state.json` file in each plugin directory contains:

```json
{
  "requirements_hash": "764ab607b6484a34..."
}
```

This file is automatically managed by the runtime and should not be manually edited.

### Testing

Comprehensive unit tests are provided in `tests/runtime/test_depsmgr.py` covering:
- Hash computation
- State file reading/writing
- Dependency checking logic
- Change detection
- Edge cases (missing files, empty requirements, etc.)
