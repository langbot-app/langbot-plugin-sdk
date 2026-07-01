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

## `install_plugin`

### Request

```json
```

### Response

```json
```

## `emit_event`

### Request

```json
{
    "event_context": {},
    "include_plugins": ["author/name"]
}
```

### Response

```json
{
    "emitted_plugins": [],
    "response_sources": [
        {
            "kind": "reply_message_chain",
            "plugin": {
                "author": "plugin_author",
                "name": "plugin_name"
            }
        }
    ],
    "event_context": {}
}
```

`emitted_plugins` contains plugins whose event handlers ran. `response_sources`
contains plugins that changed a deferred response field on the event context, such
as `reply_message_chain`.

## `list_tools`

### Request

```json
```

### Response

```json
```

## `call_tool`

### Request

```json
```

### Response

```json
```
