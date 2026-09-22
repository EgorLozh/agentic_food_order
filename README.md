# food-order

Telegram-бот для заказов еды на самовывоз. Клиент общается естественным языком; LLM-агент собирает слоты заказа (позиции, точка, время, оплата, телефон) через tools и отправляет подтверждённый заказ админу.

## Возможности

- Диалог в Telegram (aiogram 3)
- LLM-агент заказа (OpenAI API, DeepSeek API или локальный Ollama)
- Меню и цены из Google Sheets (FeedMer) либо из JSON-фикстур
- Точки самовывоза из PostgreSQL или `config/cafes.yaml`
- Уведомление админу в Telegram после подтверждения заказа
- E2E-бенчмарк диалогов через Telethon (`food-order-bench`)

## Требования

- Python 3.11+
- Токен Telegram-бота
- LLM: ключ OpenAI / DeepSeek **или** запущенный Ollama
- `ADMIN_TELEGRAM_ID` — куда слать новые заказы

Опционально: Google Sheets (меню), PostgreSQL (кафе), Telethon (бенч).

## Быстрый старт

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env
# заполни BOT_TOKEN, ADMIN_TELEGRAM_ID и настройки LLM

food-order-bot
```

Без credentials Google Sheets бот берёт меню из `config/fixtures/`. Без `DATABASE_URL` — точки из `config/cafes.yaml`.

## Конфигурация

Скопируй `.env.example` → `.env`. Основные переменные:

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | Токен бота |
| `ADMIN_TELEGRAM_ID` | Telegram ID получателя заказов |
| `LLM_PROVIDER` | `openai`, `ollama` или `deepseek` |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | При `LLM_PROVIDER=openai` |
| `OLLAMA_*` | При `LLM_PROVIDER=ollama` |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | При `LLM_PROVIDER=deepseek` |
| `DATABASE_URL` | PostgreSQL с кафе (иначе YAML) |
| `SPREADSHEET_ID` + Google credentials | Меню из Sheets (иначе фикстуры) |
| `ORDER_SCHEMA_PATH` | Схема обязательных полей заказа |
| `DIALOG_HISTORY_LIMIT` | Сколько реплик держать в контексте LLM |

Схема заказа: `config/order_schema.yaml`. Алиасы меню: `config/menu_aliases.yaml`.

## Команды

```bash
food-order-bot              # polling бота
pytest                      # юнит-тесты
pip install -e ".[eval]"    # зависимости для бенча
food-order-bench run ...    # E2E-сценарии через Telegram
```

Подробности по бенчу и сценариям: [config/scenarios/README.md](config/scenarios/README.md).

## Структура

```
config/           # схема заказа, кафе, алиасы, фикстуры, E2E-сценарии
src/food_order/
  bot/            # Telegram handlers
  llm/            # клиент LLM и OrderAgent
  orchestration/  # оркестрация диалога
  adapters/       # Sheets, Postgres, фикстуры, sink заказов
  tools/          # tools агента (меню, слоты, submit)
  storage/        # сессии и история диалога
  bench/          # E2E runner (Telethon)
tests/
```

## Как устроен заказ

1. Клиент пишет в бот → `OrderAgent` вызывает tools (`get_menu`, `set_items`, точки, время, оплата, телефон).
2. Когда все поля заполнены — агент показывает сводку и ждёт подтверждения.
3. По согласию вызывается `submit_order` → сообщение админу в Telegram.
4. `/cancel` или явная отмена сбрасывает черновик.
