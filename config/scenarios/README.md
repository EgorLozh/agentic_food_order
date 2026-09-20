# E2E сценарии для `food-order-bench`

Прогоняет диалоги **через реальный Telegram**: user-клиент (Telethon) пишет живому боту.

## Важно

- Используй **отдельный тестовый** Telegram-аккаунт, не личный.
- Сценарии рассчитаны на **live** меню/точки (Google Sheets + Postgres, точки Raketa), не на `config/fixtures`.
- Часть сценариев делает **submit** («да»). Чтобы в том же чате увидеть админку `Новый заказ …`, поставь `ADMIN_TELEGRAM_ID` = id тестового аккаунта.
- Бот должен быть запущен (`food-order-bot`) с нужным `LLM_PROVIDER`.

## ADMIN = тестовый аккаунт (для submit)

```bash
food-order-bench whoami
# скопируй id=… → ADMIN_TELEGRAM_ID в .env
# рестарт food-order-bot
```

Без этого expect `Новый заказ` / `ORD-` на turn «да» не сработает (уведомление уйдёт другому chat_id).

## Каталог сценариев

| id | Что проверяет |
|---|---|
| `happy_shaurma` | Полный заказ + submit (клиент + админ «Новый заказ») |
| `stepwise_slots` | Слоты по очереди + submit |
| `cancel_flow` | Отмена mid-dialog |
| `unknown_item` | Нет в меню |
| `ambiguous_item` | «Шаурма» без вида/размера → уточнение |
| `ambiguous_pickup` | «На Ракете» → обе точки |
| `vague_time` | «Вечером» → нужна HH:MM |
| `replace_item` | Замена на Свиную Биг + submit |
| `edit_after_summary` | Сдвиг времени после сводки + submit |

## Установка

```bash
pip install -e ".[eval]"
```

## Настройка

1. На https://my.telegram.org создай приложение (с тестового аккаунта) → `api_id` / `api_hash`.
2. В `.env` добавь:

```env
TG_API_ID=12345
TG_API_HASH=your_api_hash
TG_SESSION=bench.session
BOT_USERNAME=your_bot_username
ADMIN_TELEGRAM_ID=123456789   # food-order-bench whoami
```

3. Первый `run` / `whoami` запросит код входа — вводи номер **тестового** аккаунта.

## Запуск

```bash
food-order-bench whoami

# бот уже polling
food-order-bench run --scenarios config/scenarios --label openai/gpt-5.1-mini

# один сценарий
food-order-bench run --scenarios config/scenarios --id happy_shaurma --label ollama

# сравнить два прогона (после смены LLM_PROVIDER и рестарта бота)
food-order-bench compare reports/openai_gpt-5_1-mini.json reports/ollama.json
```

Флаги: `--delay`, `--timeout` (секунды **на каждый ответ** бота; в логе будет `per-reply timeout Ns`), `-o path.json`, `--quiet`.

Если в YAML указан `timeout_s`, он действует только если **больше** `--timeout` (CLI — минимум).
