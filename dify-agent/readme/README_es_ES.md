# Agente Dify

## Descripción general

Ejecuta una aplicación de Dify como LangBot Runner.

## Información del paquete

- **Runner ID**: `plugin:langbot-team/DifyAgent/default`
- **Versión**: `0.1.0`
- **Repositorio**: [https://github.com/langbot-app/langbot-agent-runner](https://github.com/langbot-app/langbot-agent-runner)

## Capacidades principales

- **Activada**: `streaming`, `tool calling`, `knowledge retrieval`, `multimodal input`
- **No declarada**: `interrupt`

## Configuración

| Campo | Tipo | Obligatorio | Valor predeterminado |
| --- | --- | --- | --- |
| `base-url` | `string` | Sí | `https://api.dify.ai/v1` |
| `base-prompt` | `text` | Sí | `When the file content is readable, please read the content of this file. When the file is an image, describe the content of this image.` |
| `app-type` | `select` | Sí | `chat` |
| `api-key` | `secret` | Sí | Vacío |
| `timeout` | `integer` | No | `30` |
| `langbot-assets-enabled` | `boolean` | No | false |
| `langbot-assets-gateway-host` | `string` | No | `0.0.0.0` |
| `langbot-assets-gateway-port` | `integer` | No | `8765` |
| `langbot-assets-gateway-request-timeout` | `integer` | No | `60` |
| `langbot-assets-token-ttl` | `integer` | No | `3600` |
| `langbot-assets-input-name` | `string` | No | `langbot_asset_run_token` |

## Permisos del Host

- **`tools`**: `detail`, `call`
- **`knowledge_bases`**: `retrieve`
- **`history`**: `page`
- **`storage`**: `plugin`

## Instalación y uso

1. Instala el plugin desde el mercado de plugins de LangBot.
2. Selecciona el Runner ID indicado en el selector Runner del Pipeline.
3. Completa la conexión según la tabla y guarda los valores sensibles en campos secret del panel de administración.

## Seguridad y limitaciones

- El runner solo puede usar recursos de LangBot autorizados para la ejecución actual.
- La disponibilidad, las capacidades del modelo y los límites de uso dependen del servicio externo.
- Consulta el README chino de la raíz o README_en_US.md para el comportamiento avanzado y las limitaciones específicas.
