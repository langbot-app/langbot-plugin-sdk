# Агент Tbox

## Обзор

Запускает приложение Ant Tbox как LangBot Runner.

## Информация о пакете

- **Runner ID**: `plugin:langbot-team/TboxAgent/default`
- **Версия**: `0.1.0`
- **Репозиторий**: [https://github.com/langbot-app/langbot-plugins/tree/main/Runner/tbox-agent](https://github.com/langbot-app/langbot-plugins/tree/main/Runner/tbox-agent)

## Основные возможности

- **Включено**: `streaming`, `multimodal input`
- **Не заявлено**: `tool calling`, `knowledge retrieval`, `interrupt`

## Настройка

| Поле | Тип | Обязательно | По умолчанию |
| --- | --- | --- | --- |
| `api-key` | `secret` | Да | Пусто |
| `app-id` | `string` | Да | Пусто |
| `timeout` | `number` | Нет | `120` |

## Разрешения Host

- **`storage`**: `plugin`

## Установка и использование

1. Установите плагин из магазина плагинов LangBot.
2. Выберите указанный Runner ID в селекторе Runner вашего Pipeline.
3. Заполните параметры подключения по таблице и храните секреты в полях secret панели управления.

## Безопасность и ограничения

- Runner использует только ресурсы LangBot, разрешённые для текущего запуска.
- Доступность, возможности моделей и лимиты запросов зависят от внешнего сервиса.
- Расширенное поведение и ограничения продукта описаны в китайском README в корне и английском README_en_US.md.
