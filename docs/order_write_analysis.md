# Анализ: создание заказа в бескаркасном боте и дублирование с каркасом

Дата: 04.10.2026. Документ описывает только анализ — код не менялся.
Затронутый проект: `agentic_food_order` (бескаркасный бот). FeedMer и graphEditor не изменялись
(`git status` в обоих чист).

---

## 1. Как понято требование

Вопрос «стандартную функцию ты использовал?» и «дублирование кода нам не нужно» — это не про
поиск одинаковых имён функций в трёх репозиториях, а про риск того, что **создание заказа теперь
существует в двух независимых реализациях**: в каркасе (FeedMer) и в бескаркасном боте. Второй
вопрос — каркасные функции я вызвал или написал своё.

Проверяемый факт: **вызвать функции каркаса напрямую нельзя** — это внутренние функции Node-сервиса,
они не экспортированы (ни `module.exports` с `saveOrder`, ни HTTP-эндпоинта «создать заказ»: из 99
регистраций маршрутов в `index.js` ни один не создаёт заказ одним вызовом).

**Уточнение (важно):** отдельного `POST /createOrder` нет, но внешний HTTP-путь к созданию заказа
существует — `POST /webapp/message` (index.js:3544) вызывает `scenarios.mainScenario`, а это
единственный код, доходящий до вставки заказа:

```
POST /webapp/message            index.js:3544   (тело: telegramChatId | initData | vkLaunchParams, text)
  → scenarios.mainScenario      index.js:3601/3611/3622
    → scenarios.saveOrder       scenarios.js:2666 → 5899
      → db.saveOrder            DBlib.js:920/923  — ЕДИНСТВЕННЫЙ INSERT INTO orders во всём каркасе
        → db.addItem            DBlib.js:600     — единственный INSERT INTO items
```

Проверено: `grep -i "insert into orders"` по всему репозиторию даёт только `DBlib.js:923` (+
`orders_payments`), по `items` — только `DBlib.js:600`. Значит любой способ создать заказ проходит
через `mainScenario`.

Как это выглядит как «API»: `/webapp/message` принимает `telegramChatId` **без подписи**
(`resolveOptionalWebappAuthContext`, scenarios.js:812, проверяет `initData`/`vkLaunchParams` только
если их передали), затем прогоняет сценарий шаг за шагом. То есть заказ создаётся не одним вызовом,
а эмуляцией диалога существующего пользователя бота (кнопки/шаги, «Проверить заказ», подтверждение).

Остальные маршруты заказ только читают/меняют: `/api/webapp/cart/*` и `/api/bot_step` (корзина,
шаги), `GET /updateOrder` (правка/удаление), `/order`, `/orders`, `/printOrder`, `/bill*`,
`/finishDelivery` (панель, печать, оплата). Интеграции (`/iikoCallback`, `/headlineCallback`,
`/googleCallback`, `/receiptCallback`, `/service-callback`, `/reline/message`, `/max/webhook`,
`/yandex-pay/v1/webhook`) заказы не вставляют — ценники/меню/оплаты/сообщения.

---

## 2. Что сделано

Подтверждённый заказ агента пишется прямо в общую БД каркаса:

```
OrderAgentTools.submit_order            src/food_order/tools/order_agent_tools.py:482
  → ToolRegistry.create_order           src/food_order/tools/registry.py:72
    → PostgresOrderSink.create_order    src/food_order/adapters/postgres_orders.py:185
      → users + chatids + orders + items (одна транзакция)
```

Номер заказа для клиента = `pk_orders` в общей БД. Выбор хранилища — `ORDER_SINK`
(`postgres` | `telegram` | `both`) в `adapters/orders_factory.py:59`.

---

## 3. Использованные функции

### 3.1 Наши функции (продакшн-путь)

| Функция | Файл:строка | Что делает |
|---|---|---|
| `OrderAgentTools.submit_order` | `tools/order_agent_tools.py:482` | вызов после согласия клиента |
| `ToolRegistry.create_order` | `tools/registry.py:72` | считает итог, делегирует в sink |
| `PostgresOrderSink.create_order` | `adapters/postgres_orders.py:185` | транзакция: юзер, заказ, позиции |
| `PostgresOrderSink._resolve_user` | `adapters/postgres_orders.py:149` | поиск/создание `users` + `chatids` по telegram id |
| `PostgresOrderSink._cafe_id` | `adapters/postgres_orders.py:137` | `cafeId` заказа из точки самовывоза |
| `PostgresOrderSink._cafe_timezone` | `adapters/postgres_orders.py:180` | таймзона кафе для даты заказа |
| `order_date` | `adapters/postgres_orders.py:75` | `strdate`, если время прошло — следующий день |
| `cafe_now` | `adapters/postgres_orders.py:83` | «сейчас» в таймзоне кафе |
| `payway_for` | `adapters/postgres_orders.py:100` | оплата бота → значение enum `payway_type` |
| `build_order_sink` | `adapters/orders_factory.py:59` | сборка sink'ов по `ORDER_SINK` |
| `CompositeOrderSink.create_order` | `adapters/orders_factory.py:29` | БД обязательно, телега админу — best-effort |

### 3.2 Функции каркаса, поведение которых воспроизведено (НЕ вызываются)

| Функция каркаса | Файл:строка | Что берём |
|---|---|---|
| `db.saveOrder` | `DBlib.js:920` | `INSERT INTO orders (…) RETURNING pk_orders` + привязка позиций `UPDATE items SET pk_order` |
| `db.addItem` | `DBlib.js:597` | `INSERT INTO items` (без `id`) |
| `getUserIdByTelegramChatId` / `getUserIdBy…` | `DBlib.js:1842`, `1089-1131` | связь telegram id → `userid` |
| создание пользователя | `DBlib.js:569` | `INSERT INTO users (… step='0' …)` |
| запись `chatids` | `DBlib.js:731` | `userid` ↔ `telegram_chatid`, `last_messanger` |
| `saveOrder` (правила) | `scenarios.js:5899-5981` | `strdate` + перенос на следующий день, `формат DD.MM.YYYY` в таймзоне кафе |
| `calculateDeliverySum` | `helper_modules/deliveryCalculations.js:240` | для самовывоза `deliverysum = 0` |
| `isOrderASAP` | `scenarios.js:8653` | `ASAP = false`, когда время выбрано явно |
| `getDeliveryTimeStart` / `getDeliveryTimeFinish` | `scenarios.js:8671` / `8676` | старт = время заказа, финиш = NULL для самовывоза |
| `addItemsFromAi` / `addItem` | `scenarios.js:4268` / `4341` | **строка на единицу** по цене позиции |
| `collectItemsForUser` | `scenarios.js:8595` | количество считается строками (совместимость корзины/печати) |
| `db.getOrderSum` | `DBlib.js:1877` | `SUM(item_price)` по `pk_order` |
| `payway_type` enum | `migrations:436` | метки `наличными` / `картой при получении` |

Итог: **код каркаса не копировался и не импортируется** (ни `DBlib.js`, ни `scenarios.js`).
Воспроизведён контракт БД: таблицы, колонки, enum, правила заполнения.

Сверка паритета: `scripts/compare_with_feedmer.py` пишет один и тот же заказ дословным SQL каркаса
и нашим sink, затем сравнивает все колонки `orders` и строки `items`.
Последний прогон: позиции идентичны, сумма `getOrderSum` 710 = 710, расхождений по колонкам нет
кроме ожидаемых (`pk_orders`, `timestamp`, `comment`).

---

## 4. Карта дублирования

| # | Что дублируется | Где | Тип | Оценка |
|---|---|---|---|---|
| 1 | SQL-вставки + правила заказа (`strdate`, таймзона, `payway`, строка-на-единицу, `deliverysum=0`, `ASAP`) | `adapters/postgres_orders.py:53,65` ↔ `DBlib.js:920,597`, `scenarios.js:5899` | кросс-проектное, «по контракту БД» | ~40 строк; неизбежно при интеграции через БД, но требует синхронности |
| 2 | Реализации `create_order` внутри бота: `json_fixtures.py:82`, `sheets/client.py:157`, `telegram_orders.py:64`, `postgres_orders.py:185` | наш проект | внутрипроектное, было до правок | каждый сам собирает payload; `order_id` генерится тремя способами (`ORD-{uuid}` ×2, `ORD-%05d`) — наш sink использует `pk_orders` из БД. Кандидат на один `OrderPayloadBuilder` |
| 3 | Запись заказа в Google-таблицу рядом с БД и телегой | `adapters/sheets/client.py:157` | внутрипроектное, было до правок | в `main.py` sink'ом не назначается (используется только как источник меню; в тестах — фикстуры), т.е. фактически не активна. Если включат — у бота будет третье хранилище заказов |
| 4 | Дословный SQL каркаса | `scripts/compare_with_feedmer.py:33,43` | тест/инструмент, осознанно | не продакшн-код; нужен именно для сверки |
| 5 | Два адаптера к одной БД: `FeedMerAdapter.js` (SQL + HTTP для каталогов) и `FeedMerSQLAdapter.js` (SQL) | graphEditor | внутрипроектное, вне нашей задачи | пересечение по `graphs` (5/16), `ai_condition_tools` (12/26), `ai_action_conditions` (12/29) |
| 6 | Чтение графов из БД и из Google-таблиц | FeedMer (`DBlib.js` ↔ `google_sheets_module/`) | вне нашей задачи | наблюдение |

### Чего НЕ дублируется
- graphEditor **не читает и не пишет `orders`/`items`** (0 упоминаний) — с нашими правками не пересекается;
- наш бот не дублирует чтение меню/кафе каркаса: меню берётся из тех же Google-таблиц по `ssBackId`,
  кафе — из `cafes` (read-only, `adapters/postgres_cafes.py`);
- в каркасе создание заказа — одна точка (`mainScenario` → `saveOrder` → `db.saveOrder`), второй
  реализации заказа внутри FeedMer нет.

---

## 5. Варианты снижения дублирования (к обсуждению с Кириллом)

| Вариант | Как | Плюсы | Минусы |
|---|---|---|---|
| 1. Как сейчас: контракт БД | бот пишет в `orders`/`items` | ничего не меняем в каркасе; заказ сразу виден панели; паритет проверен | правила заказа живут в двух местах; при изменении в каркасе надо помнить про бота |
| 2. Единая точка = каркас | либо использовать существующий вход `POST /webapp/message` (он гоняет `mainScenario` и создаёт заказ кодом каркаса), либо попросить у каркаса отдельный эндпоинт создания заказа | ноль дублирования: заказ пишет код каркаса; вариант с `/webapp/message` доступен уже сейчас | `/webapp/message` — это протокол мини-приложения: состояние шагов, корзина в `items`/in-memory, привязка к существующему Telegram/VK-пользователю кафе, без документации и без подписи (любой, кто знает `telegramChatId`, может гнать сценарий) — как контракт интеграции не годится; эндпоинт нужно делать отдельно; появляется сетевая зависимость: каркас лёг — заказ не принят |
| 3. Компромисс: одна функция в БД | правило заполнения заказа в PL/pgSQL-функции, вызывают и каркас, и бот | логика в одном месте, оба writer'а используют её | правки в схеме каркаса и его миграциях; нужен доступ к прод-БД |

Моя оценка: для текущей цели («заказы приходят как обычные») достаточно варианта 1 — он уже
проверен на паритет. Если заказчик считает дублирование правил недопустимым, стратегически верен
вариант 2, но это задача на стороне каркаса; вариант 3 — технический компромисс.

---

## 6. Вопросы Кириллу

1. Есть ли в каркасе штатная точка создания заказа, которую можно вызвать извне, кроме
   `POST /webapp/message` (протокол мини-приложения, гоняет сценарий шагами)? Если нет — имеет ли
   смысл сделать отдельный эндпоинт, чтобы SQL заказа жил в одном месте?
2. Считаем ли мы дублированием воспроизведение контракта БД из другого сервиса (п. 4.1), или
   требование касалось только копирования кода каркаса (которого нет)?
3. Нужно ли чистить внутрипроектное дублирование в боте (п. 4.2 и 4.3) в рамках этой задачи
   или отдельной?

---

## 7. Как воспроизвести проверки

```bash
cd /d/agentic_food_order
./.venv/Scripts/python.exe scripts/compare_with_feedmer.py     # паритет с SQL каркаса
./.venv/Scripts/python.exe scripts/verify_shared_orders.py    # сквозной путь submit_order
./.venv/Scripts/python.exe -m pytest -q --ignore=tests/test_bench_scenarios.py   # 64 теста
```
