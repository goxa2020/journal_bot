# Разработка и эксплуатация

**Дата:** 18.11.2026 · Дополняет [ARCHITECTURE.md](ARCHITECTURE.md) и [ROADMAP.md](ROADMAP.md).

## 1. Требования

| Компонент | Версия | Зачем |
|---|---|---|
| Docker + Docker Compose | Compose v2.33+ | основной способ запуска: бот, БД, Redis, админка, мониторинг |
| Python | 3.11–3.13 (в образе 3.13) | локальный запуск, линтеры, миграции |
| [uv](https://docs.astral.sh/uv/) | 0.5+ | зависимости и запуск команд |
| PostgreSQL | 14 | база (в compose — сервис `postgres`) |
| Redis | 7 | FSM, кеш, брокер Celery |
| Git | — | версии, pre-commit |

Аккаунт edu-tpi и токен бота от [@BotFather](https://t.me/botfather) — обязательны.

## 2. Первый запуск

```bash
git clone https://github.com/goxa2020/journal_bot.git
cd journal_bot

cp .env.example .env          # затем заполнить BOT_TOKEN и ENCRYPTION_KEY

docker compose up -d --build
docker compose logs -f bot
```

`migrator` применяет миграции автоматически и завершается — это нормально.
Приложение доступно: бот в Telegram, админка на `http://localhost:${ADMIN_PORT}`,
Prometheus `:9090`, Grafana `:3000`.

Быстрые проверки после старта:

```bash
docker compose ps                       # все сервисы healthy, кроме migrator (exited 0)
docker compose exec redis redis-cli ping
docker compose exec bot alembic current
```

### Обязательные переменные

| Переменная | Пример | Комментарий |
|---|---|---|
| `BOT_TOKEN` | `123456:AA...` | от @BotFather |
| `ENCRYPTION_KEY` | `kZ3...=` (44 символа) | **Fernet-ключ**; без него или с невалидным ключом бот не стартует (фаза 0) |
| `DB_*` | `postgres/postgres/postgres` | для compose имена хостов — имена сервисов |
| `REDIS_*` | `redis/6379` | |

Сгенерировать ключ:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> **Важно:** смена `ENCRYPTION_KEY` делает ранее сохранённые пароли нерасшифровываемыми —
> все пользователи должны войти заново. Ключ храните отдельно от бэкапа БД (менеджер секретов
> или защищённая папка) и никогда — в git.
>
> **Если ключ пуст или невалиден**, бот падает на старте с сообщением `ConfigError`:
> что это за ключ и как его сгенерировать. Случайный ключ больше не подставляется — иначе
> после рестарта сохранённые пароли переставали расшифровываться.

### Если VPN работает только на хосте

Docker не наследует системный прокси Windows: контейнер ходит в интернет напрямую, поэтому
`api.telegram.org` может быть недоступен, хотя на хосте Telegram открывается. Решение — указать
боту прокси хоста в `.env`:

```dotenv
TELEGRAM_PROXY=http://host.docker.internal:10809
```

`10809` — HTTP-прокси VPN-клиента (v2rayN, Happ и т.п.; SOCKS-порт 10808 тоже подойдёт).
В Docker Desktop `host.docker.internal` указывает на хост. Проверка доступности из контейнера:

```bash
docker exec tgbot-bot python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('host.docker.internal',10809)); print('proxy ok')"
```

Прокси применяется только к Bot API; запросы к edu-tpi идут напрямую. Зависимость
`aiohttp-socks` (требование aiogram для прокси) уже есть в группе `bot`, поэтому после
изменения `.env` нужен только перезапуск: `docker compose up -d bot`.

Остальные переменные (`ADMIN_*`, `SENTRY_DSN`, `AMPLITUDE_API_KEY`, `PROMETHEUS_PORT`,
`GRAFANA_*`, `CELERY_*`) — смотри [.env.example](../.env.example).

### Две конфигурации compose: локально и на сервере

`docker-compose.yml` — общая база: сервисы, образы, healthcheck'и, сети и тома. Портов на хост
в ней нет намеренно: списки в override только дополняются, поэтому «отменить» публикацию
наследованием из базового файла нельзя.

| Файл | Где | Что добавляет |
|---|---|---|
| `docker-compose.override.yml` | локальная машина (подхватывается сам) | порты на хост, `docker compose watch`, bind-mount `./admin` |
| `docker-compose.prod.yml` | сервер (указывается явно) | админка на `127.0.0.1`, лимиты памяти, мониторинг за профилем `monitoring` |

```bash
# локально — как раньше
docker compose up -d --build

# на сервере
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

На сервере `bot` и `worker` ходят в Telegram через прокси (`TELEGRAM_PROXY`), потому что там
он нужен не из-за VPN на хосте, а из-за блокировки провайдера; установка и обновление прокси,
деплой и особенности сервера — [deploy/README.md](../deploy/README.md).

Для локальной разработки прод-стек поднимать целиком нельзя: два процесса с одним токеном
конфликтуют (`409 Conflict`). Достаточно инфраструктуры:

```bash
docker compose up -d postgres pgbouncer redis
```

## 3. Локальный запуск (без Docker)

Подходит для отладки кода на локальной машине. На Windows есть ограничение — см. §8.

```bash
uv sync --frozen --all-groups
uv run alembic upgrade head        # нужен доступный PostgreSQL
uv run python -m bot               # polling по умолчанию
```

Для админки отдельно:

```bash
uv run gunicorn -c admin/gunicorn_conf.py
```

При локальном запуске в `.env` поставьте `DB_HOST=localhost`, `REDIS_HOST=localhost`.

### Быстрая итерация: как не пересобирать образ

Три режима, от самого быстрого:

| Способ | Команда | Время цикла | Когда использовать |
|---|---|---|---|
| Локальный запуск с автоперезапуском | `just dev` | ~3–5 с (правка → рестарт процесса) | основной режим разработки |
| Синхронизация в контейнер | `just watch` | ~10–14 с (`sync+restart`, без пересборки) | когда нужен именно контейнер: alpine, права, окружение |
| Пересборка образа | `docker compose up -d --build bot` | ~7 с при правке кода; ~2 мин только при смене `pyproject.toml`/`uv.lock` | проверка образа перед коммитом |

Первый запуск `just watch` делает полный `up` и может пересоздать сервисы (если менялся
`docker-compose.yml`); дальше правки `bot/` только перезапускают контейнер бота.

`just dev` читает `.env.local` (через `ENV_FILE`) — в нём хосты `127.0.0.1` и порты, опубликованные
compose: `6432` — pgbouncer, `6433` — postgres, `6380` — redis. Host-порты вынесены в отдельные
переменные (`PGBOUNCER_HOST_PORT`, `POSTGRES_HOST_PORT`, `REDIS_HOST_PORT`), потому что на машине
может быть свой PostgreSQL на 5432/5433.

Минимальный `.env.local` (копия `.env` с правками, файл не в git):

```dotenv
DB_HOST=127.0.0.1
DB_PORT=6432
REDIS_HOST=127.0.0.1
REDIS_PORT=6380
TELEGRAM_PROXY=http://127.0.0.1:10809
DEBUG=False
```

`just dev` — это `watchfiles` + `python -m bot`: процесс перезапускается при сохранении файла
в `bot/`. Изменения в локалях требуют `just babel-compile` (`.mo` не пересобирается сам).

**Важно:** локальный и контейнерный бот одновременно не работают — Telegram отдаёт апдейты
только одному поллеру. Перед `just dev`: `docker compose stop bot`; после: `docker compose up -d bot`.

Что дало ускорение сборки:

- зависимости копируются и ставятся **до** `COPY . .`, поэтому правка кода не переустанавливает пакеты;
- `COPY --chown` вместо `chown -R` по каталогу с `.venv` — это было ~80 с на каждую сборку;
- `logs/` создаётся в образе заранее и принадлежит `appuser`.

## 4. Команды

Проект использует `just` (и дублирующий `Makefile`).

| Команда | Что делает |
|---|---|
| `just deps` | `uv sync --frozen` |
| `just compose-up` / `compose-down` | поднять/остановить окружение |
| `just logs bot` | логи сервиса |
| `just compose-exec bot <cmd>` | выполнить команду в контейнере |
| `just dev` | локальный запуск с автоперезапуском (`.env.local`, `watchfiles`) |
| `just dev-worker` | локальный Celery-воркер без Docker (`.env.local`, `--pool=solo` на Windows) |
| `just worker` / `just beat` | поднять Celery worker / beat в Docker |
| `just worker-logs` | логи `worker` и `beat` |
| `just celery-ping` | `celery inspect ping` из контейнера воркера (должен ответить `pong`) |
| `just watch` | `docker compose watch`: правки `bot/` синхронизируются и перезапускают контейнер |
| `docker compose --profile host-metrics up -d` | добавить `node-exporter` (только Linux-хост) |
| `just mm "message"` | новая миграция (autogenerate) |
| `just migrate` | применить миграции |
| `just downgrade <rev>` | откатить |
| `just check` | `ruff check` + `ruff format --check` |
| `just format` | автоисправление форматирования |
| `just mypy` | проверка типов `bot/` |
| `just pre` | pre-commit по всем файлам |
| `just babel` | извлечь и обновить переводы |
| `just babel-compile` | скомпилировать `.po` → `.mo` |
| `just backup` | legacy-скрипт `scripts/postgres/backup` (в текущем образе не работает — см. §13) |

Прямые команды без `just`:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy bot/
uv run pytest -q
```

### pre-commit и кэши

`just pre` держит кэш pre-commit и `TEMP` внутри проекта (`.pre-commit-cache/`), потому что
python из `.venv` в песочнице DSH (и при некоторых политиках машины) не может писать
в `C:\Users\<user>\.cache` — иначе pre-commit падает с `attempt to write a readonly database`.

Git-хуки подключены на [.githooks/pre-commit](../.githooks/pre-commit)
(`git config --local core.hooksPath .githooks`): обёртка выставляет те же переменные, поэтому
обычный `git commit` работает. Если раньше делали `pre-commit install`, путь `.git/hooks/`
перекрывает этот — вернуть `git config --local core.hooksPath .githooks`.
Каталог кэша в репозиторий не попадает (он в `.gitignore`).

`ruff` больше не пишет кэш в `/tmp` (на Windows это `C:\tmp` и отказ доступа) — используется
`.ruff_cache` в проекте.

## 5. Миграции

Голова — `2026_11_21_grades_v2` (фаза 2: суррогатный PK `grades`, `hour_number`,
`edu_lesson_id`, уникальный ключ урока).

```bash
# создать (в контейнере — чтобы совпадали зависимости)
docker compose exec bot alembic revision --autogenerate -m "add hour_number to grades"

# применить
docker compose exec bot alembic upgrade head

# откатить на шаг
docker compose exec bot alembic downgrade -1
```

Правила:

- `alembic/env.py` берёт URL из `settings.database_url` (asyncpg), `NullPool` — можно гонять
  параллельно с ботом;
- таблицы админки (`admin`, `role`, `roles_admins`) создаются `db.create_all()` и в миграции
  не попадают — перед `--autogenerate` убедитесь, что они не «предлагаются к удалению»;
- `downgrade` обязателен: миграция без рабочего отката не принимается;
- на непустой таблице новый `NOT NULL` столбец добавляется с `server_default`, иначе деплой
  падает (так было с `users.is_authenticated`).

## 6. Локализация

Тексты — gettext: `_()` для строк в момент вызова, `n_()` для отложенных (в списках, дефолтах).

```bash
just babel            # extract + update (обновит bot/locales/**/messages.po)
just babel-compile    # .po → .mo
```

Порядок при добавлении строки:

1. В коде — `_("ключ")` или `n_("ключ")`.
2. `just babel` — строка попадает в `.pot` и в `.po` с пустым `msgstr`.
3. Заполнить `msgstr` в `ru` и `en`.
4. `just babel-compile` и закоммитить `.po` — `.mo` в git не попадает (`.gitignore`), его
   компилирует Dockerfile и CI отдельным шагом.
5. Проверить в Telegram оба языка (язык берётся из `users.language_code`, по умолчанию `ru`).

Новая локаль: `pybabel init -i bot/locales/messages.pot -d bot/locales -D messages -l <код>`,
добавить код в `users_commands` в [bot/keyboards/default_commands.py](../bot/keyboards/default_commands.py).

## 7. Тесты

Каркас появился в фазе 0 (задачи 0.7 и 0.10). Структура и правила:

```
tests/
├── conftest.py              # env для Settings, fakeredis, русская локаль, стабы
├── fakes.py                 # стаб aiohttp.ClientSession и фикстуры edu-tpi
├── fixtures/edu_tpi/        # обезличенные ответы API
├── unit/                    # TTL, шифрование, кеш, вход, синхронизация, форматтеры
└── integration/             # сценарии Celery eager — фаза 1
```

На фазе 2 добавлены тесты клиента edu-tpi, кеша/подгрупп, токена и переавторизации,
дифа оценок, задач `sync_user_*`, `/sync`, `/grades`, `/logout` и форматтера таблицы.
Всего 150 тестов.

```bash
just babel-compile                  # .mo не в git, а тесты проверяют русские тексты
uv run pytest -q                    # всё
uv run pytest tests/unit -q         # быстро
uv run pytest -k token_ttl -vv      # один срез
```

Правила:

- сеть в тестах запрещена: HTTP-слой edu-tpi подменяется стабом `aiohttp.ClientSession`
  (в `tests/unit/test_auth_service.py`), Redis — `fakeredis`, БД — заглушкой сессии.
  `respx` установлен для будущих httpx-клиентов: с `aiohttp` он не работает;
- в фикстурах API **нет реальных ФИО и оценок** — только обезличенные фрагменты;
- `tests/conftest.py` выставляет `BOT_TOKEN` и тестовый `ENCRYPTION_KEY` до импорта `bot.*`;
  это тестовые значения, не секреты;
- парсер и диф оценок тестируются на каждое изменение — это самое хрупкое место;
- CI (job «Run tests») ставит зависимости, компилирует локали и запускает `pytest -q`.

## 8. Windows

| Проблема | Причина | Решение |
|---|---|---|
| `ModuleNotFoundError: No module named 'uvloop'` | `uvloop` не поддерживает Windows, а `bot/__main__.py` импортирует его безусловно | запускать в Docker или WSL; после задачи 0.8 будет автоматический откат на стандартный loop |
| `just` не установлен | — | `winget install casey.just` или использовать `make`/прямые команды |
| Скрипты `scripts/postgres/*` | bash, нужен `pg_dump`, которого нет в образе | не использовать; бэкапы — сервис `pgbackup` (см. §13) |

Остальное (Python, uv, Docker) работает штатно.

## 9. Типовые проблемы

| Симптом | Причина | Что делать |
|---|---|---|
| `BOT_TOKEN Field required` | `.env` не найден | запускать из корня проекта, либо задать переменные окружения |
| `InvalidToken` при расшифровке пароля | сменился/потерян `ENCRYPTION_KEY` | вернуть прежний ключ; иначе попросить пользователей войти заново |
| `Target database is not up to date` | не применены миграции | `just migrate` |
| `prepared statement "__asyncpg_..." already exists` | pgbouncer в transaction-режиме | `POOL_MODE=session` в compose (уже выставлен), уникальные имена в `CConnection` |
| `Connection refused` к Redis/Postgres | локальный запуск с docker-хостами | в `.env`: `DB_HOST=localhost`, `REDIS_HOST=localhost` |
| Тексты в боте не меняются | не скомпилированы `.mo` | `just babel-compile`, перезапуск бота |
| Кнопки меню отвечают «🚧 В разработке» | обработчиков ещё нет, стоит заглушка (`callback/stubs.py`) | это ожидаемо; экраны появятся в ROADMAP 2.7–2.9, 3.3 |
| `401` в логах синхронизации | истёк токен | переавторизация по сохранённым данным; если не помогла — `/logout` и вход заново |
| `ZoneInfoNotFoundError: 'Europe/Moscow'` | нет базы часовых поясов: Windows и alpine-образ без `tzdata` | до задачи 0.2: `uv add tzdata` (плюс `apk add tzdata` в Dockerfile) или запускать в Docker с установленным `tzdata` |
| `TelegramNetworkError: ClientConnectorError ... api.telegram.org` | VPN работает только на хосте, Docker не видит системный прокси | задать `TELEGRAM_PROXY=http://host.docker.internal:10809` в `.env`, перезапустить бота (см. §2) |
| `RuntimeError: ... install aiohttp-socks` | в образе нет зависимости для прокси | `uv sync`, пересобрать образ: `docker compose up -d --build bot` |
| `node-exporter` падает с `Exited (2)` | сервис читает `/proc` и `/sys` Linux-хоста, в Docker Desktop на Windows он бесполезен | по умолчанию выключен (профиль `host-metrics`), на Windows не включать |
| `invalid role "tgbot"` / пустая схема при локальном запуске | подключились к локальному Postgres, а не к контейнеру | `DB_HOST=127.0.0.1`, `DB_PORT=6432` (pgbouncer) или `6433` (postgres) в `.env.local` |
| `relation "users" does not exist` | в томе пустая БД (новый том после пересоздания контейнера) | `docker compose run --rm migrator` |
| `409 Conflict` в логах Telegram | два поллера с одним токеном (локальный и контейнерный) | остановить один: `docker compose stop bot` |
| `Error 11001 connecting to redis:6379` у воркера | воркер запущен локально, но читает `.env` с docker-хостами | локально — `just dev-worker` (`ENV_FILE=.env.local`); вручную: `ENV_FILE=.env.local uv run celery -A bot.celery_app worker ...` |
| `/healthz` не отвечает, `curl` висит | бот поднят в webhook-режиме или порт занят | в polling `/healthz` поднимает `bot/core/health.py` на `WEBHOOK_HOST:WEBHOOK_PORT`; проверить `docker compose port bot ${WEBHOOK_PORT}` и логи `health server` |
| Порт занят | локальный сервис на 5433/6379/8080/3000 | изменить в `.env` или остановить локальный сервис |

Логи: `logs/telegram_bot.log` в контейнере бота (в проде — `docker compose logs`), у воркера
будет `logs/worker.log`. В контейнере логи смотрите через `just logs`, файлы — только при
локальном запуске.

## 10. Отладка фоновых задач

Фаза 1 подняла Celery: приложение — [bot/celery_app.py](../bot/celery_app.py), задачи — `bot/tasks/`,
воркер и beat — сервисы compose. Очереди: `sync`, `notify`, `maintenance`; один воркер слушает
все три (`celery -A bot.celery_app worker -Q sync,notify,maintenance`).

```bash
docker compose up -d worker beat              # поднять отдельно
docker compose ps                             # worker healthy, beat Up
docker compose logs -f worker                 # выполнение задач (stdout)
docker compose logs -f beat                   # расписание
docker compose exec worker celery -A bot.celery_app inspect ping
docker compose exec worker celery -A bot.celery_app inspect active
docker compose exec worker celery -A bot.celery_app inspect registered
docker compose stop worker beat               # останавливает только их
```

Запуск задачи руками (нужен доступ к тому же Redis, что у воркера):

```bash
docker compose exec worker python -c \
  "from bot.tasks.service import ping; print(ping.delay().get(timeout=10))"
```

Синхронизация конкретного пользователя (id — Telegram user id из `users.id`):

```bash
docker compose exec worker python -c \
  "from bot.tasks.sync import sync_user_manual; sync_user_manual.delay(USER_ID)"
docker compose logs -f worker        # сводка и sync_logs видны здесь
```

Smoke-задача `bot.tasks.service.ping` не пишет в БД и не ходит в Telegram: если она не отвечает
`pong`, проблема в брокере или воркере, а не в задаче.

Локальный воркер без Docker (нужен `.env.local`):

```bash
just dev-worker        # ENV_FILE=.env.local, --pool=solo (Windows), concurrency 1
```

`just dev-worker` дополнительно убирает из окружения переменные, которые `just` экспортировал
из `.env`: `set dotenv-load` + `set export` в justfile перекрывают `.env.local` (pydantic-settings
ставит переменные окружения выше env-файла), и воркер пошёл бы на `redis:6379` вместо
опубликованного `127.0.0.1:6380`. С `just dev` (бот) та же ловушка — см. ROADMAP, «замечено
вне фазы 1».

Отладка без брокера — `CELERY_TASK_ALWAYS_EAGER=True`: задача выполняется в вызывающем процессе,
`.delay()` не пишет в Redis. Так работают smoke-тесты (`tests/integration/test_celery_smoke.py`).
В бою флаг должен быть `False` (иначе `.delay()` выполняет задачу прямо в боте).

Куда смотреть, когда задача упала:

| Симптом | Что это | Что делать |
|---|---|---|
| `retry #N` в логе, задача повторяется | `RetryableError`: сеть, 5xx, 429 | ретраи идут сами (backoff до 240 с, максимум 3 повтора). Не помогает — проверить доступность edu-tpi/Telegram, это не баг задачи |
| `permanent error`, повторов нет | `PermanentError`: неверные данные или схема ответа | разбирать данные/парсер: повтор не поможет |
| `skipped: locked key=...` | по этому объекту уже работает другая задача | норма: lock `SET NX EX` живёт 300 с, повтор пропускается без ошибки |
| `inspect ping` не отвечает | воркер не подключился к брокеру | `docker compose logs worker`: адрес Redis; подключение повторяется автоматически |
| задача «есть», но результата нет | смотреть `result_expires` (24 ч) | результат в Redis живёт сутки, тело задачи — в логе воркера |

Логи: `docker compose logs` (stdout) и файл `/usr/src/app/logs/worker.log` в контейнере
(ротация 100 КБ, как у бота; посмотреть — `docker compose exec worker tail -n 100 logs/worker.log`).
Flower и celery-exporter появятся в фазе 8: до этого метрики задач (`celery_tasks_total`,
`celery_task_failures_total`, `celery_task_duration_seconds`) живут только в процессе воркера.

## 11. Структура проекта

```
journal_bot/
├── bot/                 код бота (handlers, services, integrations, database, locales)
├── admin/               Flask-Admin: шаблоны, вьюхи, gunicorn
├── docs/                документация: архитектура, план, API, разработка
│   └── archive/         старые документы (не актуальны)
├── migrations/          Alembic
├── configs/             prometheus, grafana
├── scripts/             бэкапы, вспомогательные скрипты
├── tests/               появится в фазе 0
├── docker-compose.yml   окружение
├── justfile / Makefile  команды
└── pyproject.toml       зависимости, ruff, mypy
```

## 12. Соглашения

- **Ветки:** `main` — рабочая; задачи — короткоживущие ветки, PR с описанием и чек-листом DoD.
- **Коммиты:** Conventional Commits — `feat(sync): …`, `fix(auth): …`, `docs: …`, `test: …`,
  `build(deps): …`. Один коммит — одна задача.
- **Код:** Python 3.13, типы обязательны, `ruff` с `select = ALL` и `line-length = 120`,
  `mypy` в строгом режиме для `bot/`.
- **Ошибки:** свои исключения из `bot/core/errors.py`; не глотать `Exception`.
- **Секреты:** никогда в коде, логах, тестах и фикстурах; только `.env`.
- **Документация:** изменение поведения — правка `docs/` в том же PR; статусы задач в
  [ROADMAP.md](ROADMAP.md) обновляются сразу.

## 13. Бэкапы и восстановление

Основной механизм — сервис `pgbackup` (образ `prodrigestivill/postgres-backup-local`):
дампы каждые 30 минут в volume `backups-data`, глубина 7 дней / 4 недели / 6 месяцев.

```bash
# разовый бэкап
docker compose exec pgbackup /backup.sh

# что есть
docker compose exec pgbackup ls -la /backups/last

# забрать файл на хост
docker compose cp pgbackup:/backups/last/<file> ./

# восстановить (ПЕРЕЗАПИСЫВАЕТ текущую БД)
docker compose exec pgbackup /restore.sh <file>
```

Проверка восстановления — раз в месяц на отдельной БД: бэкап без проверки восстановления
бэкапом не считается.

> **Легаси:** `scripts/postgres/backup` и `restore` рассчитаны на образ с `pg_dump` и базу
> с именем `app`; в текущем контейнере бота (alpine, без postgresql-client) они не работают.
> Не использовать; починить или удалить — задача 8.7 в [ROADMAP.md](ROADMAP.md).

## 14. Что делать перед PR

```bash
just format      # ruff + format
just mypy        # типы
just check       # финальная проверка
uv run pytest -q
```

И пройтись по Definition of Done в [ROADMAP.md](ROADMAP.md#12-порядок-работы-и-definition-of-done).
