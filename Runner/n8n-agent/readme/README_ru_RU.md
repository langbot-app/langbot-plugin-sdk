# Агент рабочих процессов n8n

## Обзор

Запускает webhook рабочего процесса n8n как LangBot Runner.

## Информация о пакете

- **Runner ID**: `plugin:langbot-team/N8nAgent/default`
- **Версия**: `0.1.2`
- **Репозиторий**: [https://github.com/langbot-app/langbot-plugins/tree/main/Runner/n8n-agent](https://github.com/langbot-app/langbot-plugins/tree/main/Runner/n8n-agent)

## Основные возможности

- **Включено**: `streaming`, `tool calling`, `knowledge retrieval`
- **Не заявлено**: `multimodal input`, `interrupt`

## Настройка

| Поле | Тип | Обязательно | По умолчанию |
| --- | --- | --- | --- |
| `webhook-url` | `string` | Да | Пусто |
| `auth-type` | `select` | Да | `none` |
| `basic-username` | `string` | Нет | Пусто |
| `basic-password` | `secret` | Нет | Пусто |
| `jwt-secret` | `secret` | Нет | Пусто |
| `jwt-algorithm` | `string` | Нет | `HS256` |
| `header-name` | `string` | Нет | Пусто |
| `header-value` | `secret` | Нет | Пусто |
| `advanced-settings` | `boolean` | Нет | false |
| `timeout` | `integer` | Нет | `120` |
| `output-key` | `string` | Нет | `response` |
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
