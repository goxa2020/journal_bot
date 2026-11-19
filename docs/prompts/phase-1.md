# Промпт для новой сессии: полностью выполнить Фазу 1 (Celery)

> Скопируй всё, что ниже разделителя, в новую сессию DSH.
> Промпт самодостаточен: он не требует прошлого диалога, но опирается на документы в репозитории.
> Фаза 0 закрыта и влита в `main`; её результат считается данным.

---

Ты — единственный агент в сессии. Работаешь над проектом `C:\Users\User\Projects\journal_bot`:
Telegram-бот электронного журнала edu-tpi (Python 3.11–3.13, aiogram 3.32, SQLAlchemy 2.1 async,
PostgreSQL 14, Redis 7, Docker Compose). Архитектура и план уже написаны — твоя задача
не проектировать заново, а **полностью закрыть Фазу 1 (Celery)** из плана: каркас фоновой
обработки, в котором задачи уже можно писать и отлаживать.

## Перед началом (обязательно)

1. Прочитай:
   - `docs/ROADMAP.md` — §1 «Текущее состояние», §3 «Фаза 1 — Celery», §11 «Сводка»,
     §12 «Порядок работы и Definition of Done»;
   - `docs/ARCHITECTURE.md` — §3 (слои), §6.1–6.6 (приложение, очереди, задачи, beat,
     мост sync/async, идемпотентность), §9 (ошибки), §11 (наблюдаемость), §13 (риски);
   - `docs/DEVELOPMENT.md` — §2–4 (запуск, команды, pre-commit и кэши), §7 (тесты),
     §9 (типовые проблемы), §10 (отладка фоновых задач), §14 (перед PR);
   - `bot/core/config.py` (`CelerySettings`), `bot/database/database.py`, `bot/core/loader.py`,
     `.env.example`, `docker-compose.yml`, `justfile`.
2. Проверь состояние: `git status` (чисто), `git log --oneline -5`, `git branch --show-current`.
   Ожидается `main` на `e50f27d` или новее, CI зелёный.
3. Заведи todo-лист через `todo_write` по задачам 1.1–1.7 и веди его по ходу работы.

## Что уже сделано (не переделывать)

- **Фаза 0 закрыта:** обязательный `ENCRYPTION_KEY` (`bot/core/encryption.py`, `bot/core/errors.py`),
  кеш `is_authorized`, удалён мёртвый код и reply-клавиатура, реальная последняя оценка в меню,
  заглушки кнопок меню, 42 unit-теста, job «Run tests» в CI.
- `CelerySettings` уже содержит broker (`/1`), backend (`/2`), timezone, сериализаторы, лимиты;
  в `.env`/`.env.example` есть все `CELERY_*`.
- `bot/database/database.py`: `get_engine()` (QueuePool, `pool_size=0`) и глобальный `sessionmaker` —
  только для процесса бота. Для задач нужен **свой** engine с `NullPool` (см. §6.5).
- `redis_client` и `bot` в `bot/core/loader.py` — глобальные объекты процесса бота. В задачах их
  переиспользовать **нельзя**: соединения привязаны к event loop, а `asyncio.run` создаёт новый
  loop на каждую задачу.
- `/metrics` сейчас поднимается только в webhook-режиме; `/healthz` нет. Задача 1.6.
- `bot/core/errors.py` содержит только `AppError`/`ConfigError`; edu-ошибки пока живут в
  `bot/services/api_client.py` (их перенос — фаза 2, не трогай).

## Состояние окружения

- `main` на `e50f27d`; CI зелёный: «Run tests», «Run Linters» 3.11/3.12/3.13, «Docker Image CI».
- Версии: aiogram 3.32.0, SQLAlchemy 2.1.8 (`sqlalchemy[asyncio]`, greenlet 3.5.6),
  pydantic-settings 2.16.3, Redis-клиент 8.x.
- Тесты: pytest 9.2, pytest-asyncio 1.5 (`asyncio_mode=auto`), `fakeredis`, `respx` (мокает
  **только httpx**; для aiohttp в `tests/unit/test_auth_service.py` свой стаб `ClientSession`).
  42 теста. Перед `pytest` нужен `just babel-compile` (`.mo` не в git; тесты проверяют ru-тексты).
- Docker-стек поднят: `bot`, `admin`, `postgres`, `pgbouncer`, `pgbackup`, `redis`, `migrator`,
  `prometheus`, `grafana`. Сервисов `worker`/`beat`/`flower` нет. Бот работает в polling.
- **Один токен бота = один поллер.** Worker не вызывает `getUpdates`, поэтому может работать
  рядом с ботом; второй `python -m bot` запускать нельзя (`409 Conflict`).
- PostgreSQL: данные лежат в томе `tgbot_postgres-data` (`PGDATA` исправлен в фазе 0). **Не**
  запускай `docker compose down -v`. Бэкапы — в томе `tgbot_backups-data`; последнее
  восстановление было 19.11.2026, в БД 1 пользователь и 1 админ.
- VPN на хосте работает как прокси `127.0.0.1:10809`:
  - для `uv add/lock/sync` нужен `$env:HTTPS_PROXY='http://127.0.0.1:10809'`, иначе PyPI не резолвится;
  - Docker не наследует прокси хоста: при сборке с новыми зависимостями передавай
    `--build-arg HTTP_PROXY=http://host.docker.internal:10809 --build-arg HTTPS_PROXY=http://host.docker.internal:10809`;
  - Telegram из контейнера идёт через `TELEGRAM_PROXY` из `.env`.
- Если работаешь в новом worktree: `.env` и `.env.local` не в git — скопируй их из
  `C:\Users\User\Projects\journal_bot` (не печатай и не коммить). Если git-хук/pre-commit падает с
  `MSYS ... NtCreateDirectoryObject ... 0xC0000022`, скопируй `.pre-commit-cache` из main —
  в фазе 0 это было рабочим обходом.
- Тесты на этой Windows-машине медленно импортируют aiogram (~15–20 с) — это окружение, а не
  тесты; не пытайся «оптимизировать» тесты под 5 секунд.
- Секреты: не печатать значения из `.env`/`.env.local`, не коммитить их.

## Задачи Фазы 1 (в этом порядке)

### 1.1. Приложение Celery

- Добавь в группу `bot` зависимость `celery[redis]` (5.x), обнови `uv.lock`
  (`uv add --group bot "celery[redis]>=5.5,<6"` с прокси). `Dockerfile` менять не нужно: он
  ставит группу `bot`.
- `bot/celery_config.py`: константы из `CelerySettings`, а не числа в коде:
  имя приложения `journal_bot`, broker `/1`, backend `/2`, JSON-сериализаторы,
  `accept_content=["json"]`, `timezone=Europe/Moscow`, `enable_utc=True`,
  `task_acks_late=True`, `task_reject_on_worker_lost=True`,
  `worker_prefetch_multiplier=1`, `task_time_limit=300`, `task_soft_time_limit=250`,
  `worker_max_tasks_per_child=1000`, `broker_connection_retry_on_startup=True`,
  `task_default_queue="maintenance"`, `task_queue_max_priority=10`, `result_expires`.
- `bot/celery_app.py`: `celery_app = Celery(...)`, `config_from_object`, `include=["bot.tasks.service"]`,
  `task_routes` (см. 1.2). `beat_schedule` пока **пустой** (или только smoke-задача):
  задачи синхронизации/уведомлений появятся в фазах 2–5, не создавай их сейчас.
- Добавь `CELERY_TASK_ALWAYS_EAGER: bool = False` в `CelerySettings` и `.env.example` — пригодится
  тестам и локальной отладке.

**Критерий:** `uv run python -c "from bot.celery_app import celery_app; print(celery_app.conf.task_default_queue)"`
печатает `maintenance` и **не подключается** к Redis; `just mypy` зелёный.

### 1.2. Очереди и маршрутизация

- Очереди по [ARCHITECTURE.md](docs/ARCHITECTURE.md) §6.2: `sync`, `notify`, `maintenance`.
- `task_routes` — по именам задач (`bot.tasks.sync.*` → `sync`, `bot.tasks.notify.*` → `notify`,
  остальное → `maintenance`), а не по объектам; smoke-задача — в `maintenance`.
- Приоритеты внутри очереди не включай (для MVP достаточно разделения по очередям).

**Критерий:** тест на `celery_app.amqp.router.route({}, "bot.tasks.service.ping")` даёт очередь
`maintenance`; маршрут `bot.tasks.sync.sync_user_manual` — `sync` (даже если самой задачи ещё нет).

### 1.3. Мост sync/async и ресурсы задачи

- `bot/tasks/__init__.py`, `bot/tasks/base.py`:
  - `run_async(coro)` — `asyncio.run(coro)`; понятная ошибка, если вызван внутри работающего loop;
  - `task_session()` — async context manager: свой `create_async_engine(settings.database_url,
    poolclass=NullPool)` + `get_sessionmaker()`, в `finally` — `await engine.dispose()`;
  - `task_redis()` — свой `Redis`-клиент внутри loop задачи (не `bot.core.loader.redis_client`),
    закрывается после задачи;
  - `send_telegram_message(chat_id, text, reply_markup=None)` — `Bot` с тем же `TELEGRAM_PROXY`,
    `DefaultBotProperties(parse_mode=HTML)`, создаётся и закрывается внутри вызова
    (`async with Bot(...)`), без polling-методов.
- Никаких глобальных engine/session/redis/bot в задачах; импорт `bot.core.loader` в `bot/tasks/*`
  не использовать.

**Критерий:** unit-тесты: `run_async` возвращает результат; `task_session` закрывает engine
(проверить `dispose` на моке); `task_redis` закрывается; в тестах нет сети/брокера.

### 1.4. Базовый класс задачи

- В `bot/core/errors.py` добавь `RetryableError(AppError)` и `PermanentError(AppError)`.
- `BaseTask(celery.Task)` в `bot/tasks/base.py`:
  - `autoretry_for=(RetryableError,)`, `max_retries=3`, `retry_backoff=True`,
    `retry_backoff_max=240`, `retry_jitter=True`;
  - `PermanentError` не ретраится: лог `ERROR` с именем задачи/id/аргументами (только id, без ПДн);
  - `on_failure`/`on_success` с логом и метриками; логи в `logs/worker.log` (ротация, как в боте)
    плюс stdout для `docker compose logs`.
- Lock для задач, работающих с одним пользователем: `task_lock(key, ttl=300)` на
  `SET NX EX`; не взяли — задача выходит **без ошибки** с логом `skipped: locked`.
  (Реальное использование — фаза 2, здесь только рабочий хелпер + тест.)
- Метрики задач через `prometheus_client`: `celery_tasks_total{task,status}`,
  `celery_task_failures_total{task}`, `celery_task_duration_seconds{task}`.
  HTTP-эндпоинт для них не делай — экспортёр/Flower в фазе 8.

**Критерий:** тесты: `RetryableError` → `self.retry` вызван; `PermanentError` → ретрая нет и
исключение залогировано; при занятом lock задача завершается без исключения.

### 1.5. Worker и beat в compose

- Добавь в `docker-compose.yml` сервисы:
  - `worker`: тот же образ, `command: celery -A bot.celery_app worker -l INFO
    -Q sync,notify,maintenance -c ${CELERY_WORKER_CONCURRENCY:-2}`; `env_file: .env`;
    `depends_on` redis/postgres/pgbouncer с `condition: service_healthy`; сеть `app`;
    `restart: always`; healthcheck `celery -A bot.celery_app inspect ping -d celery@$$HOSTNAME`
    (в compose `$$`, чтобы shell не съел переменную);
  - `beat`: `command: celery -A bot.celery_app beat -l INFO --schedule=/tmp/celerybeat-schedule`;
    зависимость от redis; `restart: always`.
- Профили: `worker`/`beat` должны подниматься обычным `docker compose up -d` (MVP-чек-лист
  требует полный стек на чистой машине); отдельные воркеры под очереди — не в этой фазе.
- `justfile`: команды `worker`, `beat`, `worker-logs`, `celery-ping`, `dev-worker`
  (локально: `ENV_FILE=.env.local`, тот же worker, без Docker). Дублируй в `Makefile`, если
  он ещё поддерживается.
- `.env.example`: `CELERY_WORKER_CONCURRENCY` уже есть; добавь `CELERY_TASK_ALWAYS_EAGER=False`.

**Критерий:** `docker compose up -d --build worker beat` — оба контейнера `Up`, у worker
healthcheck зелёный; `docker compose exec worker celery -A bot.celery_app inspect ping` отвечает
`pong`; в логах нет трейсбеков; `docker compose stop worker beat` останавливает только их.

### 1.6. Telegram из воркера и `/healthz` в polling

- `send_telegram_message` из 1.3 должен работать в контейнере worker через `TELEGRAM_PROXY`.
  Проверь отправку на admin chat из БД (или себе, если знаешь chat_id). Если проверить нечем —
  честно напиши это в отчёте.
- В polling-режиме (`not settings.USE_WEBHOOK`) подними aiohttp-сервер на
  `WEBHOOK_HOST:WEBHOOK_PORT` (порт уже опубликован в compose) с:
  - `GET /healthz` → `200 {"status": "ok", "service": "bot"}`;
  - `GET /metrics` → `prometheus_client.generate_latest()` с корректным content-type.
  Webhook-режим не ломай. Сервер корректно останавливается в `on_shutdown`.
- Добавь `healthcheck` боту в compose: `wget -qO- http://localhost:${WEBHOOK_PORT}/healthz`
  (в alpine есть busybox wget) или python-однострочник, если wget недоступен.

**Критерий:** `curl http://localhost:8080/healthz` → 200/json; `curl http://localhost:8080/metrics`
отдаёт метрики; бот по-прежнему пишет `bot started` и не конфликтует по `getUpdates`.

### 1.7. Smoke-тест и документация

- `bot/tasks/service.py`: задача `ping` (`BaseTask`, без БД и Telegram) → `"pong"`. Она же —
  smoke для очереди и ручных проверок.
- `tests/integration/test_celery_smoke.py`: `task_always_eager=True` + `task_eager_propagates=True`,
  `ping.apply().get() == "pong"` **без брокера и сети**; тест маршрутизации; тест, что
  `PermanentError` не ретраится (если не покрыт в 1.4).
- `docs/DEVELOPMENT.md` §10: команды отладки worker/beat (`inspect active`, `inspect ping`,
  `logs worker`, запуск задачи руками, `task_always_eager`), куда смотреть при `RetryableError`.
- `docs/ROADMAP.md`: статусы 1.1–1.7, итог фазы, готовность MVP; `README.md` — «что работает
  сейчас» (worker/beat/healthz) и «что в плане».

**Критерий:** `uv run pytest -q` зелёный (старые 42 + новые), в тестах нет обращений к
Redis/Postgres/Telegram; `docker compose exec worker python -c "from bot.tasks.service import ping;
print(ping.delay().get(timeout=10))"` → `pong`.

## Ограничения

- **Только Фаза 1.** Не писать синхронизацию, диф оценок, уведомления, экраны оценок/статистики,
  Flower/celery-exporter — это фазы 2, 3, 8.
- **Не менять схему БД и миграции.** Если покажется, что нужна миграция, — стоп и вопрос
  пользователю: это фаза 2.
- Не менять `docs/ARCHITECTURE.md` без причины: архитектурные решения зафиксированы. Если
  решение реально меняется — обоснуй и обнови документ в том же коммите.
- Не переиспользовать в задачах глобальные `engine`, `sessionmaker`, `redis_client`, `Bot` —
  это главная ловушка Celery + asyncio (см. §6.5). `asyncio.run` на каждую задачу, `NullPool`,
  `dispose()`, свой Redis-клиент, свой `Bot`.
- `task_acks_late=True` означает возможные повторы: задачи должны быть идемпотентны; не
  подтверждай задачу вручную, не глуши исключения.
- i18n: новых пользовательских строк в этой фазе быть не должно; если появились — `_()`/`n_()`,
  обе локали, `just babel-compile`.
- Секреты: не печатать значения из `.env`/`.env.local`, не коммитить их; в логах задач — только id.
- Коммиты — Conventional Commits, один коммит на задачу или логическую пару
  (`feat(celery): add app and routing`, `feat(tasks): add async bridge and base task`).
  Хуки через `.githooks`; **не** использовать `--no-verify`; если хук упал — разобраться.
- Не запускать бота одновременно в контейнере и локально. Worker запускать можно.
- Merge в `main` и push делать только по явной просьбе пользователя (в фазе 0 это была
  отдельная команда).

## Проверка перед отчётом (Definition of Done)

1. `just pre` — зелёный (ruff, ruff-format, pre-commit).
2. `just mypy` — зелёный.
3. `uv run pytest -q` — зелёный, старые 42 теста не сломаны, новые покрывают 1.3/1.4/1.7.
4. `docker compose up -d --build worker beat` — оба сервиса работают, worker healthy;
   `docker compose exec worker celery -A bot.celery_app inspect ping` → `pong`; логи без ошибок.
5. `docker compose exec worker python -c "from bot.tasks.service import ping; print(ping.delay().get(timeout=10))"`
   → `pong`; beat пишет `beat: Starting...`.
6. `curl http://localhost:8080/healthz` → 200; `/metrics` отдаёт метрики; бот пишет `bot started`
   и не падает с `409 Conflict`.
7. `docker compose up -d` (весь стек) — поднимается без ошибок; `git status` — чисто;
   ROADMAP обновлён.
8. Если разрешат push — CI «Run tests», «Run Linters» (3.11–3.13) и «Docker Image CI» зелёные.

## Отчёт в конце

1. Что сделано по каждой задаче 1.1–1.7 (файлы, коммиты).
2. Чем проверено: команды и результат, какие тесты добавлены и что они ловят; отдельно —
   результат `inspect ping`, ручного `ping.delay()`, `/healthz`, `/metrics`.
3. Что не удалось проверить и почему (например, отправка в Telegram без admin chat_id).
4. Замеченные проблемы вне фазы 1 (не исправлять, но записать в ROADMAP/отчёт): например,
   поведение `pgbackup` с `pg_dump` 17 при сервере 14, `build_key` с хвостовым двоеточием,
   отсутствие экспортёра метрик Celery (фаза 8), ограничения `respx` с aiohttp.
5. Готовность к фазе 2: что уже можно использовать (base task, lock, task_session, send helper,
   очереди), что нужно знать следующему агенту, где лежат логи worker/beat.
