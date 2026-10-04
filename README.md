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
- `ADMIN_TELEGRAM_ID` — куда слать новые заказы (нужен при `ORDER_SINK=telegram` или `both`)

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
| `ORDER_SINK` | Куда уходит подтверждённый заказ: `postgres` (общая БД FeedMer), `telegram` (чат админа) или `both` |
| `ORDERS_DATABASE_URL` | Отдельная БД для заказов (по умолчанию `DATABASE_URL`) |
| `ORDERS_DEFAULT_CAFE_ID` | `cafeId`, если точка самовывоза не числовой FeedMer cafeId |
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

## Куда уходят заказы

По умолчанию (`ORDER_SINK=postgres`) подтверждённый заказ пишется прямо в общую БД FeedMer —
`public.orders` + `public.items` — в том же формате, что и заказы каркасного бота: панель,
курьерские маршруты и отчёты видят его без доработок.

- клиент Telegram → `public.users` + `public.chatids` (создаются один раз, дальше переиспользуются);
- `orders.strdate` = дата самовывоза **в таймзоне кафе** (`cafes.timezone`), если время уже прошло — следующий день;
- `deliveryTimeStart` = время, `deliveryTimeFinish`/`addr`/`formaladdr` = NULL, `isDelivery = false`,
  `deliverysum = printedDeliverySum = 0`, `ASAP = false`, `payway` = `наличными` / `картой при получении`;
- позиции — в `public.items`: **строка на единицу** по цене позиции, как в корзине каркаса
  (`collectItemsForUser` считает количество по строкам, `getOrderSum` = `SUM(item_price)`);
- номер заказа в диалоге с клиентом = `pk_orders` в общей БД;
- `comment` = `Заказ агентного бота (agentic)` — по нему видно, что заказ пришёл не из каркаса.

Сверка с каркасом (пишет один и тот же заказ SQL-ом FeedMer и нашим sink, затем сравнивает строки
по всем колонкам):

```bash
.venv/Scripts/python.exe scripts/compare_with_feedmer.py
```

id заказа (`orders.pk_orders`) и строк позиций (`items.id`) выдаёт сама БД — ровно как для
каркасных заказов: в миграциях FeedMer `items.id` объявлен `GENERATED ALWAYS AS IDENTITY`, а
`orders.pk_orders` — sequence-default, и `DBlib.saveOrder` вставляет заказ без id, забирая его через
`RETURNING pk_orders`. Если база собрана копией таблиц без ключей и последовательностей (в `testing`
было именно так: ни PK, ни FK, ни identity — из-за этого упал бы и сам каркас), нужно один раз прогнать:

```bash
psql -h localhost -U postgres -d testing -f scripts/fix_shared_orders_schema.sql
```

Скрипт идемпотентный, правит только эту БД и ничего не меняет в FeedMer/graphEditor.

`ORDER_SINK=both` дополнительно шлёт заказ админу в Telegram: падение уведомления не отменяет
заказ, он остаётся в БД. `ORDER_SINK=telegram` возвращает прежнее поведение.

Проверка сквозной записи:

```bash
.venv/Scripts/python.exe scripts/verify_shared_orders.py
```

## Как устроен заказ

1. Клиент пишет в бот → `OrderAgent` вызывает tools (`get_menu`, `set_items`, точки, время, оплата, телефон).
2. Когда все поля заполнены — агент показывает сводку и ждёт подтверждения.
3. По согласию вызывается `submit_order` → заказ пишется в общую БД (`ORDER_SINK=postgres`) и/или уходит админу в Telegram.
4. `/cancel` или явная отмена сбрасывает черновик.
