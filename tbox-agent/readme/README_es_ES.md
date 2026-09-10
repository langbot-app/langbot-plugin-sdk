# Agente Tbox

## Descripción general

Ejecuta una aplicación Ant Tbox como LangBot Runner.

## Información del paquete

- **Runner ID**: `plugin:langbot-team/TboxAgent/default`
- **Versión**: `0.1.0`
- **Repositorio**: [https://github.com/langbot-app/langbot-agent-runner](https://github.com/langbot-app/langbot-agent-runner)

## Capacidades principales

- **Activada**: `streaming`, `multimodal input`
- **No declarada**: `tool calling`, `knowledge retrieval`, `interrupt`

## Configuración

| Campo | Tipo | Obligatorio | Valor predeterminado |
| --- | --- | --- | --- |
| `api-key` | `secret` | Sí | Vacío |
| `app-id` | `string` | Sí | Vacío |
| `timeout` | `number` | No | `120` |

## Permisos del Host

- **`storage`**: `plugin`

## Instalación y uso

1. Instala el plugin desde el mercado de plugins de LangBot.
2. Selecciona el Runner ID indicado en el selector Runner del Pipeline.
3. Completa la conexión según la tabla y guarda los valores sensibles en campos secret del panel de administración.

## Seguridad y limitaciones

- El runner solo puede usar recursos de LangBot autorizados para la ejecución actual.
- La disponibilidad, las capacidades del modelo y los límites de uso dependen del servicio externo.
- Consulta el README chino de la raíz o README_en_US.md para el comportamiento avanzado y las limitaciones específicas.
