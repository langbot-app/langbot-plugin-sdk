# Агент Dify

## Обзор

Запускает приложение Dify как LangBot Runner.

## Информация о пакете

- **Runner ID**: `plugin:langbot-team/DifyAgent/default`
- **Версия**: `0.1.2`
- **Репозиторий**: [https://github.com/langbot-app/langbot-agent-runner](https://github.com/langbot-app/langbot-agent-runner)

## Основные возможности

- **Включено**: `streaming`, `tool calling`, `knowledge retrieval`, `multimodal input`
- **Не заявлено**: `interrupt`

## Настройка

| Поле | Тип | Обязательно | По умолчанию |
| --- | --- | --- | --- |
| `base-url` | `string` | Да | `https://api.dify.ai/v1` |
| `advanced-settings` | `boolean` | Нет | false |
| `base-prompt` | `text` | Да | `When the file content is readable, please read the content of this file. When the file is an image, describe the content of this image.` |
| `app-type` | `select` | Да | `chat` |
| `api-key` | `secret` | Да | Пусто |
| `timeout` | `integer` | Нет | `30` |
| `langbot-assets-enabled` | `boolean` | Нет | false |
| `langbot-assets-gateway-host` | `string` | Нет | `0.0.0.0` |
| `langbot-assets-gateway-port` | `integer` | Нет | `8765` |
| `langbot-assets-gateway-request-timeout` | `integer` | Нет | `60` |
| `langbot-assets-token-ttl` | `integer` | Нет | `3600` |
| `langbot-assets-input-name` | `string` | Нет | `langbot_asset_run_token` |

## Разрешения Host

- **`tools`**: `detail`, `call`
- **`knowledge_bases`**: `retrieve`
- **`history`**: `page`
- **`storage`**: `plugin`

## Установка и использование

1. Установите плагин из магазина плагинов LangBot.
2. Выберите указанный Runner ID в селекторе Runner вашего Pipeline.
3. Заполните параметры подключения по таблице и храните секреты в полях secret панели управления.

## Безопасность и ограничения

- Runner использует только ресурсы LangBot, разрешённые для текущего запуска.
- Доступность, возможности моделей и лимиты запросов зависят от внешнего сервиса.
- Расширенное поведение и ограничения продукта описаны в китайском README в корне и английском README_en_US.md.
