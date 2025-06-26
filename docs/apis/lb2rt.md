# LangBot to Plugin Runtime API Definition

## `list_plugins`

### Request

```json
{}
```

### Response

```json
{
    "plugins": [
        {
            "id": "plugin_id",
            "name": "plugin_name",
            "version": "plugin_version"
        }
    ]
}
```

## `emit_event`

