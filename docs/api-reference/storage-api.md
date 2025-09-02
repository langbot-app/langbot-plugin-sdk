# Storage API Reference

The Storage API provides persistent data storage for your plugins. It offers two types of storage:

- 🔒 **Plugin Storage** - Private to your plugin instance
- 🌐 **Workspace Storage** - Shared across all plugins in a workspace

## Overview

The storage system uses key-value pairs and handles automatic serialization/deserialization. All data is stored as bytes internally but the SDK provides convenience methods for common data types.

## Getting Started

Storage is accessed through the plugin context:

```python
from langbot_plugin.api import *

@register_handler(MessageEvent)
async def my_handler(event: MessageEvent, context: PluginContext):
    # Plugin-specific storage
    await context.set_storage("user_count", 42)
    count = await context.get_storage("user_count")
    
    # Workspace-wide storage  
    await context.set_workspace_storage("shared_config", {"theme": "dark"})
    config = await context.get_workspace_storage("shared_config")
```

## Plugin Storage

Plugin storage is private to your specific plugin instance. Data stored here is only accessible by your plugin.

### `set_plugin_storage(key, value)`

Store data for your plugin.

```python
async def set_plugin_storage(key: str, value: bytes) -> None
```

**Parameters:**
- `key` (str): Storage key (must be unique within your plugin)
- `value` (bytes): Data to store (raw bytes)

**Example:**
```python
import json

@register_handler(CommandEvent)
async def save_user_preference(event: CommandEvent, context: PluginContext):
    if event.command == "setpref" and len(event.args) >= 2:
        key = event.args[0]
        value = event.args[1]
        
        # Store as JSON
        data = json.dumps({"user_id": event.user_id, "value": value})
        await context.set_plugin_storage(f"pref_{key}", data.encode('utf-8'))
        
        await context.send_message(f"Preference '{key}' saved!")
```

### `get_plugin_storage(key)`

Retrieve data from your plugin storage.

```python
async def get_plugin_storage(key: str) -> bytes
```

**Parameters:**
- `key` (str): Storage key to retrieve

**Returns:**
- `bytes`: The stored data

**Raises:**
- `KeyError`: If the key doesn't exist

**Example:**
```python
import json

@register_handler(CommandEvent)
async def get_user_preference(event: CommandEvent, context: PluginContext):
    if event.command == "getpref" and event.args:
        key = event.args[0]
        
        try:
            data = await context.get_plugin_storage(f"pref_{key}")
            pref = json.loads(data.decode('utf-8'))
            await context.send_message(f"Preference '{key}': {pref['value']}")
        except KeyError:
            await context.send_message(f"Preference '{key}' not found")
        except Exception as e:
            await context.send_message(f"Error: {e}")
```

### `get_plugin_storage_keys()`

Get all storage keys for your plugin.

```python
async def get_plugin_storage_keys() -> list[str]
```

**Returns:**
- `list[str]`: List of all storage keys

**Example:**
```python
@register_handler(CommandEvent)
async def list_preferences(event: CommandEvent, context: PluginContext):
    if event.command == "listprefs":
        keys = await context.get_plugin_storage_keys()
        pref_keys = [k for k in keys if k.startswith("pref_")]
        
        if pref_keys:
            key_list = "\n".join([f"- {k[5:]}" for k in pref_keys])  # Remove "pref_" prefix
            await context.send_message(f"Your preferences:\n{key_list}")
        else:
            await context.send_message("No preferences saved")
```

### `delete_plugin_storage(key)`

Delete data from your plugin storage.

```python
async def delete_plugin_storage(key: str) -> None
```

**Parameters:**
- `key` (str): Storage key to delete

**Example:**
```python
@register_handler(CommandEvent)
async def delete_preference(event: CommandEvent, context: PluginContext):
    if event.command == "delpref" and event.args:
        key = event.args[0]
        
        try:
            await context.delete_plugin_storage(f"pref_{key}")
            await context.send_message(f"Preference '{key}' deleted")
        except KeyError:
            await context.send_message(f"Preference '{key}' not found")
```

## Workspace Storage

Workspace storage is shared across all plugins in the same workspace. Use this for data that needs to be accessible by multiple plugins.

### `set_workspace_storage(key, value)`

Store data in the workspace.

```python
async def set_workspace_storage(key: str, value: bytes) -> None
```

**Parameters:**
- `key` (str): Storage key (shared across workspace)
- `value` (bytes): Data to store

**Example:**
```python
import json

@register_handler(CommandEvent)
async def set_global_config(event: CommandEvent, context: PluginContext):
    if event.command == "setglobal" and len(event.args) >= 2:
        key = event.args[0]
        value = event.args[1]
        
        config = {"value": value, "set_by": "my_plugin", "timestamp": time.time()}
        data = json.dumps(config)
        
        await context.set_workspace_storage(f"global_{key}", data.encode('utf-8'))
        await context.send_message(f"Global setting '{key}' updated")
```

### `get_workspace_storage(key)`

Retrieve data from workspace storage.

```python
async def get_workspace_storage(key: str) -> bytes
```

**Parameters:**
- `key` (str): Storage key to retrieve

**Returns:**
- `bytes`: The stored data

**Example:**
```python
@register_handler(CommandEvent)
async def get_global_config(event: CommandEvent, context: PluginContext):
    if event.command == "getglobal" and event.args:
        key = event.args[0]
        
        try:
            data = await context.get_workspace_storage(f"global_{key}")
            config = json.loads(data.decode('utf-8'))
            await context.send_message(f"Global '{key}': {config['value']}")
        except KeyError:
            await context.send_message(f"Global setting '{key}' not found")
```

### `get_workspace_storage_keys()`

Get all workspace storage keys.

```python
async def get_workspace_storage_keys() -> list[str]
```

**Returns:**
- `list[str]`: List of all workspace storage keys

### `delete_workspace_storage(key)`

Delete data from workspace storage.

```python
async def delete_workspace_storage(key: str) -> None
```

**Parameters:**
- `key` (str): Storage key to delete

## Data Serialization Helpers

While the raw storage API uses bytes, you can create helper functions for common data types:

### JSON Helper

```python
import json
from typing import Any

class StorageHelper:
    def __init__(self, context: PluginContext):
        self.context = context
    
    async def set_json(self, key: str, data: Any, workspace: bool = False) -> None:
        """Store JSON-serializable data"""
        json_data = json.dumps(data).encode('utf-8')
        if workspace:
            await self.context.set_workspace_storage(key, json_data)
        else:
            await self.context.set_plugin_storage(key, json_data)
    
    async def get_json(self, key: str, workspace: bool = False) -> Any:
        """Retrieve JSON data"""
        if workspace:
            data = await self.context.get_workspace_storage(key)
        else:
            data = await self.context.get_plugin_storage(key)
        return json.loads(data.decode('utf-8'))

# Usage
@register_handler(CommandEvent)
async def use_helper(event: CommandEvent, context: PluginContext):
    helper = StorageHelper(context)
    
    # Store complex data
    user_data = {
        "name": "Alice",
        "preferences": {"theme": "dark", "language": "en"},
        "scores": [100, 85, 92]
    }
    await helper.set_json("user_123", user_data)
    
    # Retrieve complex data
    retrieved = await helper.get_json("user_123")
    print(retrieved["name"])  # "Alice"
```

### Pickle Helper (Advanced)

```python
import pickle
from typing import Any

class PickleStorageHelper:
    def __init__(self, context: PluginContext):
        self.context = context
    
    async def set_object(self, key: str, obj: Any, workspace: bool = False) -> None:
        """Store any Python object"""
        data = pickle.dumps(obj)
        if workspace:
            await self.context.set_workspace_storage(key, data)
        else:
            await self.context.set_plugin_storage(key, data)
    
    async def get_object(self, key: str, workspace: bool = False) -> Any:
        """Retrieve Python object"""
        if workspace:
            data = await self.context.get_workspace_storage(key)
        else:
            data = await self.context.get_plugin_storage(key)
        return pickle.loads(data)

# Usage with custom classes
class UserProfile:
    def __init__(self, name: str, level: int):
        self.name = name
        self.level = level

helper = PickleStorageHelper(context)
profile = UserProfile("Bob", 5)
await helper.set_object("profile_bob", profile)
```

## Common Patterns

### User-Specific Data

```python
async def save_user_data(context: PluginContext, user_id: str, data: dict):
    """Save data specific to a user"""
    key = f"user_{user_id}"
    json_data = json.dumps(data).encode('utf-8')
    await context.set_plugin_storage(key, json_data)

async def get_user_data(context: PluginContext, user_id: str) -> dict:
    """Get data for a specific user"""
    key = f"user_{user_id}"
    try:
        data = await context.get_plugin_storage(key)
        return json.loads(data.decode('utf-8'))
    except KeyError:
        return {}  # Return empty dict if no data
```

### Configuration Management

```python
class ConfigManager:
    def __init__(self, context: PluginContext):
        self.context = context
        self.config_key = "plugin_config"
    
    async def get_config(self) -> dict:
        """Get plugin configuration"""
        try:
            data = await self.context.get_plugin_storage(self.config_key)
            return json.loads(data.decode('utf-8'))
        except KeyError:
            return self._default_config()
    
    async def set_config(self, config: dict) -> None:
        """Save plugin configuration"""
        data = json.dumps(config).encode('utf-8')
        await self.context.set_plugin_storage(self.config_key, data)
    
    async def update_config(self, updates: dict) -> None:
        """Update specific configuration values"""
        config = await self.get_config()
        config.update(updates)
        await self.set_config(config)
    
    def _default_config(self) -> dict:
        return {
            "enabled": True,
            "debug_mode": False,
            "max_retries": 3
        }
```

### Data Migration

```python
async def migrate_storage_v1_to_v2(context: PluginContext):
    """Example storage migration"""
    version_key = "storage_version"
    
    try:
        version_data = await context.get_plugin_storage(version_key)
        version = int(version_data.decode('utf-8'))
    except KeyError:
        version = 1  # Default to version 1
    
    if version == 1:
        # Migrate from v1 to v2
        keys = await context.get_plugin_storage_keys()
        for key in keys:
            if key.startswith("old_format_"):
                # Get old data
                old_data = await context.get_plugin_storage(key)
                old_obj = json.loads(old_data.decode('utf-8'))
                
                # Convert to new format
                new_key = key.replace("old_format_", "new_format_")
                new_obj = {"version": 2, "data": old_obj}
                new_data = json.dumps(new_obj).encode('utf-8')
                
                # Save new data and delete old
                await context.set_plugin_storage(new_key, new_data)
                await context.delete_plugin_storage(key)
        
        # Update version
        await context.set_plugin_storage(version_key, "2".encode('utf-8'))
```

## Error Handling

```python
async def safe_storage_operation(context: PluginContext):
    try:
        # Storage operation
        data = await context.get_plugin_storage("some_key")
        result = json.loads(data.decode('utf-8'))
        return result
        
    except KeyError:
        # Key doesn't exist
        return None
        
    except json.JSONDecodeError as e:
        # Invalid JSON data
        context.logger.error(f"Invalid JSON in storage: {e}")
        return None
        
    except Exception as e:
        # Other errors
        context.logger.error(f"Storage error: {e}")
        return None
```

## Best Practices

1. **Key Naming**: Use descriptive, prefixed keys (e.g., "user_123", "config_main")
2. **Data Format**: Use JSON for simple data, pickle for complex objects
3. **Error Handling**: Always handle KeyError for missing data
4. **Data Validation**: Validate data after retrieval
5. **Cleanup**: Remove unused keys to avoid storage bloat
6. **Security**: Don't store sensitive data in workspace storage
7. **Versioning**: Consider data format versioning for migrations

## Limitations

- Storage keys must be strings
- Data is limited by available disk space
- No atomic transactions across multiple keys
- No query/search capabilities (you must know the key)

## Related Documentation

- [LangBot API](langbot-api.md) - Core LangBot integration
- [Examples](../examples/storage-usage.md) - Practical storage examples
- [Development Guide](../development/) - Advanced usage patterns