# План разработки

**Версия:** 2.0 · **Дата:** 18.11.2026 · **Предыдущий план:** [archive/dev-plan.md](archive/dev-plan.md)
**Архитектура:** [ARCHITECTURE.md](ARCHITECTURE.md) · **API:** [API.md](API.md) · **Разработка:** [DEVELOPMENT.md](DEVELOPMENT.md)

План описывает путь от текущего состояния к рабочей версии (MVP) и далее. Задачи идут в порядке
выполнения: каждая следующая фаза опирается на предыдущую.

## Обозначения

| Знак | Статус |
|---|---|
| ✅ | Сделано и проверено |
| 🟡 | Есть частично, требует доработки |
| ⬜ | Не начато |

Оценка — в часах чистой работы, без ревью и ожидания CI. «Файлы» — что создаётся или меняется.

---

## 1. Текущее состояние

Кратко: инфраструктура, схема данных, вход в edu-tpi, синхронизация оценок, экран
`/grades`, уведомления и автоматическая синхронизация по расписанию — есть (фазы 0–4).
MVP закрыт по коду: остались режим ожидания (фаза 5), статистика (`/stats`, фаза 6),
экспорт и дайджест (фаза 7), эксплуатация (фаза 8). Без них бот уже приносит оценки,
уведомляет о новых и обновляет их сам каждые 6 часов.

| Блок | Статус | Что есть | Чего нет |
|---|---|---|---|
| Инфраструктура | ✅ | compose (бот, воркер, beat, админка, postgres, pgbouncer, redis, миграции, бэкапы, prometheus, grafana, celery-exporter, node-exporter), Dockerfile ×2, CI, pre-commit, `just`/`make` | Flower (не обязателен: метрики Celery идут через celery-exporter) |
| Схема БД | ✅ | `users`, `journals`, `grades` (суррогатный PK, `hour_number`, уникальный ключ урока), `sync_logs`, `student_journal`, 6 миграций | — |
| Каркас бота | ✅ | polling/webhook, FSM в Redis, middlewares, i18n ru/en, меню, аналитика, Sentry, логи, `/healthz` и `/metrics` в обоих режимах | обработчик `/stats` |
| Вход в edu-tpi | ✅ | FSM логин→пароль в одном сообщении, кнопки «Ещё раз»/«Сменить данные»/«Отмена», обязательный `ENCRYPTION_KEY`, токен в Redis, `users` обновляется, «сервис недоступен» отличается от неверных данных | — |
| Клиент журнала | ✅ | `bot/integrations/edu_tpi.py`: типизированные ответы, ошибки, таймаут 60 с, лимиты 1 req/s на журнал и 5 req/s суммарно; групповой кеш и подгруппы | — |
| Синхронизация | ✅ | `GradeSyncService`, диф `(date, hour_number)`, upsert оценок, `journals`, `student_journal`, `sync_logs`, сводка; задачи `sync_user_manual` и `sync_user_after_login`; `GroupSyncService` и `sync_all_users` по расписанию (один запрос на группу/подгруппу, подгруппы через `unprocessed`), оппортунистическая синхронизация за флагом `SYNC_OPPORTUNISTIC` | — |
| Уведомления | ✅ | `NotificationService` (политика день/ночь, дедупликация), задачи `send_grade_notification`/`send_night_batch`, ночная очередь в Redis, экран `/settings`, метрики и события аналитики; из батча — только `send_grade_notification.delay` | дайджест (фаза 7) |
| Экраны оценок | 🟡 | `/grades` (список журналов, таблица, средний балл), `/sync` и кнопка «Обновить», `/logout`, `/settings` | `/stats` |
| Celery | ✅ | приложение `journal_bot`, очереди `sync`/`notify`/`maintenance`, `BaseTask` (ретраи, lock, логи, метрики), задачи синхронизации и уведомлений, расписание beat (`sync_all_users` каждые 6 часов), сервисы `worker`/`beat` в compose, HTTP-метрики воркера `:9108` и celery-exporter | — |
| Админка | 🟡 | вход, роли, пользователи, дашборд | журналы, оценки, логи синхронизаций |
| Тесты | ✅ | pytest + pytest-asyncio, `fakeredis`, HTTP-стаб edu-tpi, фикстуры журнала, **282 теста** (Celery в eager-режиме, диф оценок, политика уведомлений, экран настроек, групповая синхронизация и «один запрос на журнал», батч-лок, метрики и алерт, маппинг id журнала, метрики/healthz воркера, display-width таблиц) | тестов статистики и экспорта (фазы 6–7) |

**Готовность MVP: ~95%** (фазы 0–4 закрыты: инфраструктура, вход, клиент, кеш,
синхронизация, экран оценок, уведомления и автосинхронизация; технический долг фаз 0–4
закрыт 22.11.2026 пакетами W1–W5 — см. §12; остались проверка на чистой машине и статистика
`/stats` — уже за пределами MVP-кода).


### Что сделано ранее (для истории)

- ✅ каркас репозитория и CI: ruff (ALL, строгий), mypy, pre-commit, Dependabot, CodeQL, Hadolint;
- ✅ Docker Compose на 10 сервисов с healthcheck'ами и бэкапами PostgreSQL;
- ✅ 5 миграций Alembic: `users`, `journals`, `grades`, `sync_logs`, `student_journal`;
- ✅ aiogram 3: FSM-хранилище в Redis, миграция с polling на webhook, i18n (gettext), меню;
- ✅ middlewares: логирование, троттлинг, сессия БД, авто-регистрация, i18n;
- ✅ вход по edu-tpi: fingerprint → `tokenauth` → `GET tokenauth`, Fernet-шифрование пароля;
- ✅ авторизация в боте доведена до рабочего состояния: падение `ValidationError` из-за
  reply-клавиатуры в `edit_message_text` устранено (inline-отмена), исправлены
  `accessToken`/`expiresIn`, добавлена ошибка «сервис недоступен»;
- ✅ `JournalParser`: журналы по семестрам, `journalInfo`, уроки студента;
- ✅ Flask-Admin: Flask-Security, роли, экран пользователей, дашборд;
- ✅ HTTP-метрики aiohttp и `/metrics` в webhook-режиме, Sentry, аналитика Amplitude/PostHog/GA
  (по ключу); бизнес-метрик (синхронизации, уведомления) пока нет;
- ✅ экспорт пользователей в CSV для админа;
- ✅ документация v2 (18.11.2026): `docs/ARCHITECTURE.md`, `ROADMAP.md`, `API.md`, `DEVELOPMENT.md`;
- ✅ запуск в Docker при VPN на хосте: `TELEGRAM_PROXY` + `aiohttp-socks`; починены healthcheck'и
  `grafana`/`pgbackup`, `node-exporter` вынесен в профиль `host-metrics`;
- ✅ скорость разработки: зависимости в Dockerfile ставятся до копирования кода, `COPY --chown`
  вместо `chown -R` (сборка после правки кода ~7 с вместо ~90–105 с); `just dev` (локальный
  запуск с автоперезапуском и `.env.local`), `just watch` (`docker compose watch`); host-порты
  БД/Redis разведены с локальным Postgres (`6432`/`6433`/`6380`);
- ✅ рефакторинг авторизации в сервисный слой (`fix(auth)`): `AuthService`-функции в
  `bot/services/auth.py`, inline-отмена, различение «неверные данные» и «сервис недоступен»;
- ✅ фаза 0 закрыта (19.11.2026): обязательный `ENCRYPTION_KEY` и `encryption.py`, кеш
  `is_authorized`, удаление мёртвого кода, реальная последняя оценка в меню, заглушки кнопок,
  каркас pytest и 42 unit-теста, job «Run tests» в CI.

---

## 2. Фаза 0 — фундамент (перед Celery)

Цель: убрать ошибки, которые гарантированно всплывут в синхронизации, и подготовить тесты.
Без этой фазы фаза 2 упрётся в баги, а не в архитектуру.

| № | Задача | Статус | Ч | Файлы |
|---|---|---|---|---|
| 0.1 | Ключ токена: `accessToken` вместо `access_token`, `expiresIn` из **минут** в секунды (TTL = `expiresIn*60 − 300`), резервный TTL при отсутствии поля | ✅ | 1 | [bot/services/auth.py](../bot/services/auth.py) |
| 0.2 | Конфигурация на старте: `ENCRYPTION_KEY` обязателен (валидация Fernet, `Fernet.generate_key()` убран), шифрование вынесено в [bot/core/encryption.py](../bot/core/encryption.py), понятная ошибка запуска без ключа. `tzdata` для `ZoneInfo` уже добавлен (Windows/alpine), `uvloop` ставится только на Linux | ✅ | 2 | [bot/core/config.py](../bot/core/config.py), [bot/core/encryption.py](../bot/core/encryption.py), [bot/core/errors.py](../bot/core/errors.py) |
| 0.3 | Кеш `is_authorized` (проверка идёт на каждом апдейте) и согласованный сброс: `set_user_data`, `set_language_code`, `set_edu_credentials`, `set_is_admin`, `add_user`. `clear_cache` строит тот же ключ, что `@cached`; `get_all_users` больше не кеширует ORM-объекты | ✅ | 2 | [bot/services/users.py](../bot/services/users.py), [bot/cache/redis.py](../bot/cache/redis.py) |
| 0.4 | Удалён мёртвый код: `services/journals.py`, `services/sync_logs.py` (старая схема «предметов»), `scripts/test_parser.py`, `keyboards/reply/`, `utils/command.py`, `filters/number.py`; убраны писатели в несуществующие колонки `last_sync`/`notifications_enabled`. Нужное вернётся на фазе 2 | ✅ | 1 | `bot/services/`, `bot/keyboards/`, `bot/utils/`, `bot/filters/`, `scripts/` |
| 0.5 | Реальная последняя оценка в главном меню: `GradesService.get_last_grade` (join с `journals`), форматтер `ДД.ММ.ГГГГ` в [bot/utils/formatters.py](../bot/utils/formatters.py), «Оценки не найдены» при пустой таблице | ✅ | 1 | [bot/services/grades.py](../bot/services/grades.py), [bot/utils/formatters.py](../bot/utils/formatters.py), [bot/utils/main_menu.py](../bot/utils/main_menu.py) |
| 0.6 | Авторизация без reply-клавиатуры (осталась только inline-отмена и `/cancel`); кнопки меню без обработчиков отвечают `callback.answer()` «🚧 В разработке» | ✅ | 2 | [bot/handlers/message/auth.py](../bot/handlers/message/auth.py), [bot/handlers/callback/stubs.py](../bot/handlers/callback/stubs.py), [bot/keyboards/inline/auth.py](../bot/keyboards/inline/auth.py) |
| 0.7 | Каркас тестов: `pytest`, `pytest-asyncio`, `respx`, `fakeredis`, конфиг в `pyproject.toml`, `tests/conftest.py`, job «Run tests» в CI, `pythonpath` и per-file-ignores для `tests/` | ✅ | 4 | `tests/`, [pyproject.toml](../pyproject.toml), [.github/workflows/linters.yml](../.github/workflows/linters.yml) |
| 0.8 | `uvloop` только на Linux: опциональный импорт, на Windows — обычный loop; локальный запуск работает | ✅ | 1 | [bot/__main__.py](../bot/__main__.py) |
| 0.9 | `.env.example`: плейсхолдеры вместо похожих на настоящие секретов, комментарии, генерация ключа, backend Redis `/2` | ✅ | 1 | [.env.example](../.env.example) |
| 0.10 | Первые настоящие тесты (42): TTL токена, inline-клавиатура отмены и регрессия `EditMessageText`, ошибки входа (неверные данные / сеть / 5xx), шифрование, кеш `is_authorized` с `fakeredis`, форматтер и пустое меню | ✅ | 3 | `tests/unit/` |

**Итог фазы: ~18 ч, все задачи закрыты.** Фаза 0 проверена: `ruff`, `ruff format`, `mypy`,
`pytest` (42 теста), сборка и запуск контейнера. Критерий входа на реальном edu-tpi
проверяется вручную по [DEVELOPMENT.md](DEVELOPMENT.md) §9; в этой сессии тестового аккаунта
не было.

---

## 3. Фаза 1 — Celery

Цель: каркас фоновой обработки, в котором задачи уже можно писать и отлаживать.

| № | Задача | Статус | Ч | Файлы |
|---|---|---|---|---|
| 1.1 | `celery_app.py`: приложение, брокер `/1`, backend `/2`, JSON, timezone, `acks_late`, timeouts; `celery_config.py` с константами из `CelerySettings` | ✅ | 3 | [bot/celery_app.py](../bot/celery_app.py), [bot/celery_config.py](../bot/celery_config.py) |
| 1.2 | Очереди `sync`/`notify`/`maintenance`: маршрутизация по именам задач (`bot.tasks.sync.*` → `sync` и т.д.), `maintenance` по умолчанию | ✅ | 2 | [bot/celery_config.py](../bot/celery_config.py) |
| 1.3 | Мост sync/async: `run_async`, `task_session()` с `NullPool` и `dispose`, `task_redis()`, `send_telegram_message()` со своим `Bot` и `TELEGRAM_PROXY` | ✅ | 3 | [bot/tasks/base.py](../bot/tasks/base.py) |
| 1.4 | Базовый класс задачи: `RetryableError`/`PermanentError`, autoretry с backoff, lock `SET NX EX`, логи в stdout и `logs/worker.log`, метрики `celery_tasks_total`/`celery_task_failures_total`/`celery_task_duration_seconds` | ✅ | 3 | [bot/tasks/base.py](../bot/tasks/base.py), [bot/core/errors.py](../bot/core/errors.py) |
| 1.5 | `worker`, `beat` в compose (один воркер на три очереди, healthcheck `celery inspect ping`, `restart: always`); команды `worker`, `beat`, `worker-logs`, `celery-ping`, `dev-worker` в `justfile`/`Makefile` | ✅ | 3 | [docker-compose.yml](../docker-compose.yml), [justfile](../justfile), [Makefile](../Makefile) |
| 1.6 | Экземпляр `Bot` в воркере (с тем же `TELEGRAM_PROXY`) и хелпер отправки; `/healthz` и `/metrics` у бота в polling-режиме, healthcheck бота в compose | ✅ | 3 | [bot/tasks/base.py](../bot/tasks/base.py), [bot/core/health.py](../bot/core/health.py), [bot/__main__.py](../bot/__main__.py) |
| 1.7 | Smoke-задача `ping`, тесты в `task_always_eager` (без брокера и сети), `celery inspect ping` в чек-листе, отладка в DEVELOPMENT §10 | ✅ | 2 | [bot/tasks/service.py](../bot/tasks/service.py), [tests/integration/](../tests/integration/), [tests/unit/test_tasks_base.py](../tests/unit/test_tasks_base.py), [docs/DEVELOPMENT.md](DEVELOPMENT.md) |

**Итог фазы: ~19 ч, все задачи закрыты (19.11.2026).** Проверено: `ruff`, `ruff format`, `mypy`,
`pytest` (63 теста), `docker compose up -d` (весь стек), `worker` healthy, `beat` пишет
`beat: Starting...`, `celery inspect ping` → `pong`, `ping.delay().get()` → `pong`,
`curl /healthz` → `{"status": "ok", "service": "bot"}`, `/metrics` отдаёт метрики.
Отправка из воркера проверена вызовом `send_telegram_message` из контейнера `worker` на
admin-чат из БД: запрос прошёл без ошибок (`admins: 1 sent: 1`); факт доставки подтверждается
только в самом Telegram — со стороны агента это не проверить. Задач синхронизации и уведомлений
нет — это фазы 2–3; расписание beat пустое до фазы 4.

---

## 4. Фаза 2 — синхронизация и оценки (ядро MVP)

Цель: пользователь видит свои оценки, полученные из журнала, и может обновить их вручную.

| № | Задача | Статус | Ч | Файлы |
|---|---|---|---|---|
| 2.1 | Миграция `grades`: суррогатный PK, `edu_lesson_id`, `hour_number`, `UNIQUE(user_id, journal_id, date, hour_number)` | ✅ | 2 | [2026-11-21_grades_lesson_key.py](../migrations/versions/2026-11-21_grades_lesson_key.py), [grade.py](../bot/database/models/grade.py) |
| 2.2 | Слить `api_client` и `journal_parser` в `integrations/edu_tpi.py`: типизированные ответы, ошибки, таймауты | ✅ | 4 | [edu_tpi.py](../bot/integrations/edu_tpi.py), [models.py](../bot/integrations/models.py), [errors.py](../bot/core/errors.py) |
| 2.3 | Кеш журналов и алгоритм подгрупп (`student_ids`, `isSubGroup`, ключи `journal:*`) | ✅ | 5 | [journal_cache.py](../bot/integrations/journal_cache.py) |
| 2.4 | Кеш токена в Redis, повторная авторизация по сохранённым данным, обработка 401 | ✅ | 3 | [auth.py](../bot/services/auth.py) |
| 2.5 | `GradeSyncService.sync_user`: диф, upsert, `sync_logs`, возврат сводки | ✅ | 6 | [grade_sync.py](../bot/services/grade_sync.py), [sync_logs.py](../bot/services/sync_logs.py) |
| 2.6 | Задачи `sync_user_manual`, `sync_user_after_login` + сообщение пользователю | ✅ | 3 | [tasks/sync.py](../bot/tasks/sync.py) |
| 2.7 | `/sync` и кнопка «Обновить»: постановка задачи, «⏳ запущено», результат, обработка «уже идёт» | ✅ | 3 | [message/sync.py](../bot/handlers/message/sync.py), [callback/sync.py](../bot/handlers/callback/sync.py) |
| 2.8 | Экран `/grades`: таблица по журналам, выбор журнала, кнопки «Назад/Обновить» | ✅ | 5 | [message/grades.py](../bot/handlers/message/grades.py), [callback/grades.py](../bot/handlers/callback/grades.py), [inline/grades.py](../bot/keyboards/inline/grades.py) |
| 2.9 | Форматирование таблицы оценок (ширина 86, обрезка названий, легенда) + тесты | ✅ | 3 | [formatters.py](../bot/utils/formatters.py) |
| 2.10 | `/logout`: сброс токена, удаление шифрованных данных, `is_authenticated=False` | ✅ | 2 | [message/auth.py](../bot/handlers/message/auth.py), [users.py](../bot/services/users.py) |
| 2.11 | `journals` upsert при синхронизации (имя, преподаватель, тип) | ✅ | 2 | [services/journals.py](../bot/services/journals.py) |

**Итог фазы: ~38 ч, все задачи закрыты (21.11.2026).** Проверено:

- `ruff check .`, `ruff format --check .`, `mypy bot/` — зелёные;
- `pytest -q` — 153 теста (было 64), включая маппинг кодов edu-tpi, кеш/подгруппы,
  переавторизацию, диф оценок, задачи в eager-режиме, форматтер таблицы, `/logout`;
- миграция на PostgreSQL 14: `upgrade head` → `downgrade -1` → `upgrade head`;
  `\d grades` показывает `BIGSERIAL`, `hour_number SMALLINT NOT NULL`, `UNIQUE
  (user_id, journal_id, date, hour_number)`, индексы `(user_id, journal_id, date)` и
  `(journal_id)`; `alembic check` не находит расхождений по `grades` (таблицы админки и
  `journals.id` — известный старый дрейф, см. «Замечено вне фазы 2»);
- реальная синхронизация на проде: 30 журналов, 150 оценок, 29 журналов в `journals` и
  `student_journal`; один архивный журнал (`state: -2, data: null`) корректно пропущен;
  повторная синхронизация — `new=0, updated=0, errors=0`, дубликатов нет;
- переавторизация на проде: после удаления `auth:token:*` синхронизация сама вошла по
  сохранённым credentials и записала новый токен;
- `docker compose up -d` (dev-конфигурация) поднимает стек; локальный бот стартует и
  отвечает `/healthz`; на сервере после деплоя `bot`/`worker` healthy;
- ручной сценарий в Telegram (нажатия «Обновить»/`/grades`/`/logout` от лица студента)
  агентом не выполнялся — UI-слой проверен тестами и рендером реальных строк из БД; см.
  отчёт сессии.

Критерий приёмки фазы выполнен, кроме пункта «два пользователя одной группы — один запрос
на журнал»: это задача 4.5 (групповая синхронизация), в фазе 2 кеш уже групповой.

**Уточнения после приёмки (21.11.2026):** запрашивается только текущий семестр (следующий
ещё не начался); в `/grades` попадают все журналы с любыми непустыми записями (оценки и
отметки `Н/У/Б/О`); скрываются только журналы, где все клетки пустые («присутствовал»);
список отсортирован по дате последней записи; названия лекций/практик помечаются «Л»/«П»;
строки таблиц ограничены 50 символами; в конкретном журнале нет предмета, номера пары и
легенды, оценка и посещение — одна колонка; кнопка «Главное меню» переименована и стоит
перед «К списку». Пустой журнал чужой подгруппы кешируется отрицательно на 15 минут и не
считается ошибкой.


---

## 5. Фаза 3 — уведомления (финиш MVP)

| № | Задача | Статус | Ч | Файлы |
|---|---|---|---|---|
| 3.1 | `NotificationService`: немедленное уведомление, форматирование, проверка настроек | ✅ | 3 | `bot/services/notifications.py`, [grade_sync.py](../bot/services/grade_sync.py), [users.py](../bot/services/users.py), [formatters.py](../bot/utils/formatters.py) |
| 3.2 | Ночное накопление в Redis + `send_night_batch` с `eta` на утро пользователя | ✅ | 4 | [tasks/notify.py](../bot/tasks/notify.py), [celery_app.py](../bot/celery_app.py) |
| 3.3 | Экран `/settings`: уведомления вкл/выкл, «копить ночью», время утра | ✅ | 4 | [message/settings.py](../bot/handlers/message/settings.py), [callback/settings.py](../bot/handlers/callback/settings.py), [inline/settings.py](../bot/keyboards/inline/settings.py) |
| 3.4 | Дедупликация (`notify:sent:*`), обработка `TelegramForbidden`/`RetryAfter` | ✅ | 2 | [tasks/notify.py](../bot/tasks/notify.py), [services/notifications.py](../bot/services/notifications.py) |
| 3.5 | Метрики и события аналитики: `notifications_total`, `sync_new_grades` | ✅ | 2 | [core/metrics.py](../bot/core/metrics.py), [tasks/sync.py](../bot/tasks/sync.py), [services/analytics.py](../bot/services/analytics.py) |
| 3.6 | Тесты политики: день/ночь, дубликаты, выключенные уведомления | ✅ | 3 | [test_notifications.py](../tests/unit/test_notifications.py), [test_notify_tasks.py](../tests/unit/test_notify_tasks.py), [test_settings.py](../tests/unit/test_settings.py) |

**Итог фазы: ~18 ч, все задачи закрыты (22.11.2026).** Критерий приёмки:

- новая оценка днём приходит одним сообщением в течение минуты после синхронизации —
  `sync_user_manual` отправляет список вместо счётчика, повторной сводки нет;
- оценка в 23:00 не будит, а приходит утром одним списком в указанное время — ночная
  очередь `notifications:night:{user_id}` и одна задача `send_night_batch` на утро;
- повторный запуск задачи не отправляет то же уведомление дважды — маркеры
  `notify:sent:*` (7 дней) и атомарное чтение ночного списка;
- пользователь, заблокировавший бота, не ломает очередь — `notification_enabled=False`,
  остальные пользователи и задачи продолжают работать.

Проверено:

- `pytest -q` — 219 тестов (было 153): политика день/ночь, дедупликация, ночная очередь,
  ошибки Telegram, метрики, экран `/settings`, `new_notices` в дифе;
- `ruff check`, `ruff format --check`, `mypy bot/` — зелёные; pre-commit чистый;
- на проде: `docker compose … up -d` → `bot`/`worker` healthy, задачи
  `send_grade_notification`/`send_night_batch` зарегистрированы в воркере, миграции не
  менялись (`2026_11_21_grades_v2`);
- ручная проверка на реальном Telegram-аккаунте: `notify_new_grades(manual=True)` отправил
  одно сообщение, повтор вернул `skipped` (маркер `notify:sent` стоял), маркер снят;
- ночная политика на проде: при подменённом времени 23:00 решение `night`, `morning_at`
  = 08:00 следующего дня, Redis TTL 11 ч, очередь и ключ постановки создаются и чистятся;
- `send_night_batch` с пустой очередью в воркере — `skipped`, сообщения нет.

### 🎯 MVP готов, когда

- [x] вход, оценки, ручная синхронизация и уведомления работают на реальных данных;
- [ ] `docker compose up -d` на чистой машине поднимает всё, включая воркер и beat
      (на сервере стек поднимался; чистая машина в этой сессии не проверялась);
- [x] `pytest` и `mypy` зелёные в CI;
- [x] в логах нет паролей и токенов;
- [x] README и ROADMAP отражают фактическое состояние.

**Оценка MVP: ~93 ч** (фазы 0–3). При 8–10 ч/неделю — около 2,5 месяцев.

---

## 6. Фаза 4 — автоматическая синхронизация

| № | Задача | Статус | Ч | Файлы |
|---|---|---|---|---|
| 4.1 | `sync_all_users`: группировка по `group_id`, обход подгрупп через `unprocessed_students` | ✅ | 4 | [group_sync.py](../bot/services/group_sync.py), [sync.py](../bot/tasks/sync.py), [users.py](../bot/services/users.py), [grade_sync.py](../bot/services/grade_sync.py) |
| 4.2 | Оппортунистическая синхронизация участников группы (флаг `SYNC_OPPORTUNISTIC`) | ✅ | 3 | [grade_sync.py](../bot/services/grade_sync.py), [config.py](../bot/core/config.py) |
| 4.3 | Расписание beat: 6 часов, блокировка пересекающихся запусков | ✅ | 2 | [celery_app.py](../bot/celery_app.py), [celery_config.py](../bot/celery_config.py), [base.py](../bot/tasks/base.py) |
| 4.4 | Метрики массовой синхронизации, алерт при массовых ошибках | ✅ | 2 | [metrics.py](../bot/core/metrics.py), [sync.py](../bot/tasks/sync.py), [locales/](../bot/locales/) |
| 4.5 | Тест: два пользователя одной группы — один запрос на журнал | ✅ | 2 | [test_group_sync.py](../tests/integration/test_group_sync.py) |

**Итог фазы: ~13 ч, все задачи закрыты (22.11.2026).** Критерий приёмки:

- `sync_all_users` обходит авторизованных пользователей по группам: список журналов берётся
  **один раз на группу** (при ошибке авторизации первого токена — следующим участником), а
  `JournalCache.get_journal` обслуживает всю группу/подгруппу одним запросом к edu-tpi;
  подгруппы добираются повторами прохода по `unprocessed`, диф не дублируется — он вынесен
  в `GradeSyncService.apply_payload` и используется и ручной, и групповой синхронизацией;
- два пользователя одной группы и один журнал — ровно **1** запрос (`test_group_sync`),
  две подгруппы — по одному на подгруппу, пустой журнал чужой подгруппы — пропуск без ошибки;
- ошибка авторизации одного участника не останавливает остальных, `ParseError` журнала не
  валит другие журналы, `EduUnavailableError`/`EduRateLimitError` — ошибка прогона; если
  список журналов не получен ни для одной группы, задача падает в `RetryableError` и
  повторяется целиком (батч идемпотентен);
- пересекающиеся прогоны не идут параллельно: батч-лок `sync:all:lock` (TTL 3600) даёт
  `{"status": "skipped", "reason": "locked"}` без ошибки, per-user `sync:lock:{user_id}`
  берётся на время дифа и снимается сразу (`release=True`), задача ограничена
  `expires=3600`, `soft_time_limit=1800`, `time_limit=1900`;
- beat ставит `sync-all-users` по `crontab(minute=0, hour="*/6")` (00/06/12/18 МСК) с
  `options={"expires": 3600}`; точный маршрут задачи — `maintenance` (правило стоит до
  wildcard `bot.tasks.sync.*`), очередь `sync` не занимается;
- метрики `sync_batch_users{status=success|failed|skipped}`, `sync_batch_duration_seconds`,
  `sync_new_grades{type=auto}`; при `users ≥ SYNC_ALERT_MIN_USERS` и доле `failed ≥
  SYNC_ALERT_FAILURE_RATIO` админам уходит **одно** сообщение (`sync.batch_alert`, только
  числа), ошибка Telegram алерт не роняет батч;
- фоновая синхронизация молчит, кроме новых оценок: уведомления ставятся
  `send_grade_notification.delay` после коммита журнала, сводок и счётчиков нет.

Проверено:

- `ruff check`, `ruff format --check`, `mypy bot/` — зелёные; pre-commit чистый;
- `pytest -q` — **249 тестов** (было 219): групповой прогон на `fakeredis` и словаре-хранилище
  (один запрос на журнал, подгруппы, пустой журнал, ошибка авторизации одного участника,
  идемпотентность, занятый per-user lock, отсутствие прогресса), батч-лок и лимиты задачи,
  инкременты метрик через `prometheus_client.REGISTRY`, алерт по порогу и без него, падение
  Telegram при алерте, маршрут и расписание beat, флаг `SYNC_OPPORTUNISTIC` (включён/выключен,
  первичный импорт молчит, занятый lock участника);
- на проде: `sync_all_users.delay().get()` → `{"status": "success", "groups": 1, "users": 1,
  "success": 1, "failed": 0, "new_grades": 0, "updated_grades": 0, "errors": [], ...}`,
  13.9–15.1 с (15 журналов, из них 14 с данными этого студента, архивный `32053` пуст);
  повторный прогон — те же числа, `grades` остались 150, дубликатов нет; `sync_logs` пишет
  `sync_type=auto`, `status=success`, `journals=14 errors=0`; сообщений пользователю нет
  (`notification sent` в логах — 0);
- занятый `sync:all:lock` (выставлен вручную в Redis) → `skipped: locked`, батч не пошёл;
- `celery_app.amqp.router.route({}, "bot.tasks.sync.sync_all_users")` → `maintenance`;
  `beat_schedule` в контейнере `beat` содержит `sync-all-users` с `crontab 0 */6 * * *` и
  `expires: 3600`; `beat` после деплоя стартует без ошибок, `worker` регистрирует задачу;
  в `docker compose logs worker` нет трейсбеков;
- локальный dev-стек (`docker compose up -d`, без второго поллера на время проверки):
  `bot` healthy, `worker`/`beat` up, та же запись расписания; после проверки прод-бот поднят
  обратно, стек healthy.

Найдено и исправлено по ходу (коммиты `fix(sync)`):

- `users.edu_user_id` из `tokenauth` может **не совпадать** с id строки `journalData`
  (на проде `-22069`): ручная синхронизация находила студента по ФИО, а групповой проход
  считал, что его нет ни в одном журнале, и помечал `failed` (`unprocessed`). Групповая
  синхронизация теперь использует то же правило (`id`, затем ФИО);
- диф шёл только по `unprocessed`, поэтому после первого журнала участник выходил из набора
  и остальные журналы ему не обновлялись (`journals=1` вместо 14 в `sync_logs`). Теперь
  `unprocessed` решает только, нужен ли ещё проход с токеном другой подгруппы, а диф идёт по
  всем участникам группы из `payload`; набор `applied` не даёт обработать пару повторно.

Не проверено на проде: «два реальных пользователя одной группы — один запрос» (в БД один
авторизованный пользователь; сценарий закрыт тестом), плановый запуск в 06:00/12:00/18:00
(ждать до 6 часов) и реальный алерт админам (проверен тестом, на проде не провоцировался).

---

## 7. Фаза 5 — режим ожидания

| № | Задача | Статус | Ч | Файлы |
|---|---|---|---|---|
| 5.1 | Включение/выключение режима, `watch_mode_expires_at`, Redis-множество | ⬜ | 3 | `bot/handlers/callback/watch.py` |
| 5.2 | Задача `sync_watch_mode_users` каждые 5 минут | ⬜ | 3 | `bot/tasks/sync.py` |
| 5.3 | Очистка истёкших, отображение остатка времени, продление | ⬜ | 3 | `bot/tasks/service.py` |
| 5.4 | Тесты: истечение, отсутствие дублей, лимит 30 минут | ⬜ | 2 | `tests/unit/` |

**Итог: ~11 ч.**

---

## 8. Фаза 6 — статистика

| № | Задача | Статус | Ч | Файлы |
|---|---|---|---|---|
| 6.1 | `StatisticsService`: средний балл, посещаемость, динамика по месяцам, лучшие/проблемные журналы | ⬜ | 5 | `bot/services/statistics.py` |
| 6.2 | Экран `/stats` с разделами и навигацией | ⬜ | 4 | `bot/handlers/message/stats.py` |
| 6.3 | Посещаемость: `Н`/`О`/`У`/`Б`, проценты, серии пропусков | ⬜ | 3 | `bot/services/statistics.py` |
| 6.4 | Тесты на фикстурах с граничными случаями (нет оценок, только пропуски) | ⬜ | 3 | `tests/unit/` |

**Итог: ~15 ч.**

---

## 9. Фаза 7 — экспорт и дайджест

| № | Задача | Статус | Ч | Файлы |
|---|---|---|---|---|
| 7.1 | Экспорт в XLSX (журналы, оценки, средние, посещаемость) | ⬜ | 4 | `bot/services/export.py` |
| 7.2 | Кнопка «Экспорт» и отправка документа с понятными ошибками по размеру | ⬜ | 2 | `bot/handlers/callback/export.py` |
| 7.3 | Месячный дайджест: сборка, текст, кнопки, расписание | ⬜ | 4 | `bot/tasks/notify.py`, `bot/services/statistics.py` |
| 7.4 | Тесты экспорта и дайджеста | ⬜ | 2 | `tests/unit/` |

**Итог: ~12 ч.**

---

## 10. Фаза 8 — эксплуатация, админка, наблюдаемость

| № | Задача | Статус | Ч | Файлы |
|---|---|---|---|---|
| 8.1 | Админка: журналы, оценки, логи синхронизаций, действия «пересинхронизировать» | ⬜ | 4 | [admin/views/](../admin/views/) |
| 8.2 | Таблицы админки в миграции; принудительная смена дефолтного пароля | ⬜ | 3 | `admin/`, `migrations/` |
| 8.3 | `celery-exporter` + дашборд Grafana «Celery», панель синхронизаций | ✅ | 4 | [docker-compose.yml](../docker-compose.yml), [configs/grafana/](../configs/grafana/) |
| 8.4 | Нагрузочный прогон (200 пользователей), настройка concurrency и лимитов | ⬜ | 3 | — |
| 8.5 | Runbook: что делать при 401 у всех, бане API, переполнении очереди | ⬜ | 2 | `docs/RUNBOOK.md` |
| 8.6 | `docs/UI.md`: экраны и тексты (перенос из архива), сверка README с кодом | ⬜ | 3 | `docs/` |
| 8.7 | Починить или удалить `scripts/postgres/*` (ссылаются на несуществующую БД `app`, нет `pg_dump` в образе) | ⬜ | 1 | [scripts/postgres/](../scripts/postgres/) |

**Итог: ~20 ч.**

**Вне фаз закрыто:** 8.3 (`celery-exporter`, `/metrics` воркера, дашборд Grafana) — пакет W2
технического долга, 22.11.2026; 8.7 (легаси `scripts/postgres/*`) остаётся открытым.

---

## 11. Сводка

| Фаза | Содержание | Часы | Статус |
|---|---|---|---|
| 0 | Фундамент и исправления | 18 | ✅ |
| 1 | Celery | 19 | ✅ |
| 2 | Синхронизация и оценки | 38 | ✅ |
| 3 | Уведомления | 18 | ✅ |
| **MVP** | **0–3** | **~93** | **🟡 ~95% (код закрыт, осталась проверка на чистой машине)** |
| 4 | Автосинхронизация | 13 | ✅ |
| 5 | Режим ожидания | 11 | ⬜ |
| 6 | Статистика | 15 | ⬜ |
| 7 | Экспорт и дайджест | 12 | ⬜ |
| 8 | Эксплуатация и админка | 20 | ⬜ |
| **Итого** | | **~164** | |

Календарно при 8–10 ч/неделю: MVP — ~10–11 недель, весь план — ~18–20 недель.

---

## 12. Порядок работы и Definition of Done

### Правила

1. Одна задача — один осмысленный коммит (Conventional Commits: `feat(sync): …`,
   `fix(auth): …`, `docs: …`, `test: …`).
2. Новая бизнес-логика — с тестом. Без теста задача не закрывается, если это парсер, диф,
   политика уведомлений или статистика.
3. Параметр, который может измениться, — в `settings`, а не числом в коде.
4. Пользовательские строки — только через `_()`/`n_()`, обе локали обновлены.
5. Схема БД меняется только миграцией, с рабочим `downgrade`.
6. Долгая операция не выполняется в хендлере — только задача Celery.
7. Секреты — только в `.env`; в логах и Sentry нет паролей и токенов.

### Definition of Done задачи

- [ ] код соответствует [ARCHITECTURE.md](ARCHITECTURE.md) (слои, ошибки, метрики);
- [ ] `ruff check`, `ruff format --check`, `mypy bot/` зелёные;
- [ ] тесты покрывают новую логику, `pytest` зелёный;
- [ ] проверено руками в Telegram (для пользовательских сценариев);
- [ ] обновлены `ROADMAP.md` (статус) и, при необходимости, `ARCHITECTURE.md`/`API.md`;
- [ ] в задаче нет `TODO` без ссылки на номер задачи.

### Замечено вне фазы 0 — закрыто техническим долгом (22.11.2026)

Пункты ниже не переносились в фазы 5–8, а закрыты в пакетах W1–W5. Доказательство —
тест, команда или документ рядом с пунктом.

- ~~`respx` (0.23) не мокает `aiohttp`~~ — **закрыто решением (W1.6)**: зависимость удалена
  из `pyproject.toml` и `uv.lock`, HTTP-тесты используют собственный стаб `tests/fakes.py`.
  Задел «на случай httpx» не нужен: при переходе стаб заменится вместе с клиентом.
- ~~`bot/services/auth.py` содержит мёртвый `edit_bot_message`~~ — **проверено (W1.2):
  пункт устарел, код не мёртвый.** Функция вызывается в 4 хендлерах (19 обращений:
  `message/auth.py`, `callback/auth.py`, `callback/grades.py`, `callback/settings.py`);
  удаление ломало вход и экраны. Пункт снят, поведение не менялось.
- ~~`get_edu_credentials` возвращает `(None, None)` при повреждении~~ — **закрыто тестом
  (W1.3)**: повреждённая любая часть Fernet-пары → `EduAuthError`, `is_authenticated=False`,
  в лог пишется только `user_id` и факт повреждения (без токена, пароля и ФИО);
  `tests/unit/test_token_service.py::test_corrupted_credentials_raise_auth_error_without_leaking_token`.
- ~~Комментарии `#:` в `.po` ссылаются на удалённые файлы~~ — **проверено (W1.4)**:
  `grep` по `services/journals`, `api_client`, `journal_parser`, `keyboards/reply`,
  `utils/command`, `filters/number`, `test_parser` в `bot/locales/**/messages.po` пуст;
  перегенерация не требуется.
- ~~`.mo` не в git: перед `pytest` нужен `just babel-compile`~~ — **закрыто (W1.5)**:
  `tests/conftest.py` компилирует `.po` → `.mo`, если `.mo` нет или он старше `.po`.
  Проверено удалением обоих `.mo` → `pytest` зелёный. `.mo` остаётся в `.gitignore`,
  CI компилирует локали отдельным шагом, `just test` делает то же.
- ~~`uv add`/`uv lock` только через прокси~~ — **ограничение среды (W1.16)**, не код:
  `HTTPS_PROXY=http://127.0.0.1:10809`.
- ~~`pgbackup` снимает дампы клиентом `pg_dump` 17~~ — исправлено ранее: образ закреплён на
  `prodrigestivill/postgres-backup-local:14-alpine`; восстановление проверено и в W5.2.

### Замечено вне фазы 1 — закрыто техническим долгом (22.11.2026)

- ~~**`just dev` не читает `.env.local`**~~ — **закрыто (W1.1)**: `set dotenv-load := false`;
  `dev`/`dev-worker` задают `ENV_FILE=.env.local` явно, переменные `.env` больше не
  экспортируются и не перекрывают файл. `just dev-check` печатает
  `DB 127.0.0.1:6432`, `REDIS 127.0.0.1:6380`. Compose-рецепты не затронуты: `docker compose`
  читает `.env` из корня сам. См. [DEVELOPMENT.md](DEVELOPMENT.md) §2/§9.
- ~~**Метрики задач Celery не экспортируются по HTTP**~~ — **закрыто (W2.1)**: у воркера
  HTTP-сервер `:9108` (multiprocess `prometheus_client`) с `/metrics` и `/healthz`; в
  Prometheus добавлены job'ы `worker` и `celery-exporter`; дашборд Grafana `Celery / sync`.
  Проверено: `sync_batch_users_total`, `sync_new_grades_total`, `notifications_total`,
  `celery_tasks_total`, `celery_task_duration_seconds`, targets `worker`/`celery-exporter` —
  `up`. См. [ARCHITECTURE.md](ARCHITECTURE.md) §11.
- ~~**`.env` не содержал `CELERY_*`**~~ — закрыто в фазе 1; **W1.7** проверил, что все поля
  `CelerySettings` есть в `.env.example` с комментариями.
- ~~**Celery не поставляет типы**~~ — **внешнее ограничение (W1.8)**: Celery 5.7.0 без
  `py.typed`; три `# type: ignore` оставлены с комментариями, стабы не выдумываются.
  См. «Замечено вне фазы 5».
- ~~**`worker` healthcheck через `celery inspect ping`**~~ — **закрыто (W2.2)**: healthcheck
  ходит в `/healthz` на `:9108`, `timeout: 5s`, `interval: 30s`, `start_period: 60s`,
  Celery CLI не запускается. `docker compose ps` — `worker healthy`.
- ~~**Медленный импорт на Windows + Docker Desktop**~~ — **ограничение среды (W1.16)**:
  aiogram по-прежнему импортируется локально в `send_telegram_message`; это не код проекта.
- ~~**Ротация `logs/worker.log` не мультипроцессная**~~ — **закрыто (W2.3)**: файл на процесс
  `logs/worker-<pid>.log` (`worker_log_path(pid)`), ротация у каждого писателя своя; тест
  `tests/unit/test_worker_metrics.py::test_worker_log_path_is_per_pid`.

### Исправлено по ходу вне фазы 0

- **[docker-compose.yml](../docker-compose.yml): `PGDATA` был в кавычках.** Compose передаёт
  значение вместе с ними, поэтому кластер создавался в слое контейнера, а не в томе
  `tgbot_postgres-data`; любое пересоздание `postgres` теряло БД. Кавычки убраны, том теперь
  используется по назначению. Данные после пересоздания восстановлены из `pgbackup`
  (последний дамп — 19.11.2026 02:13); изменения за 02:13–05:14, если они были, потеряны —
  проверить при следующем входе.
- **Compose разделён на две конфигурации.** `docker-compose.yml` — общая база без опубликованных
  портов; `docker-compose.override.yml` — то, что нужно только машине разработчика (порты,
  `compose watch`, bind-mount `./admin`); `docker-compose.prod.yml` — сервер (админка на
  `127.0.0.1`, лимиты памяти, мониторинг за профилем). Порты из базы убраны, потому что списки
  в override только дополняются и «отменить» публикацию наследованием нельзя.
- **`.dockerignore` не пропускал `admin/`.** Вайтлист содержал `!/bot/`, но не `!/admin/`,
  поэтому образ админки никогда не содержал свой код и работал только благодаря bind-mount
  `./admin` — в проде без монтирования gunicorn падал с `admin/gunicorn_conf.py doesn't exist`.
- **Админка падала с `ModuleNotFoundError: psycopg`.** SQLAlchemy 2.1 перевёл умолчание для
  `postgresql://` на драйвер psycopg3, а в зависимостях `psycopg2`. В `admin/config.py` драйвер
  указан явно: `postgresql+psycopg2://`.
- **Диалог входа больше не плодит сообщения.** «Войти» правит меню на месте, «Отмена»
  возвращает меню в то же сообщение, успешный вход заменяет его на «успех» + меню. На сбое
  edu-tpi появились «Ещё раз» (повтор с теми же данными), «Сменить данные» и «Отмена»; пароль
  для повтора хранится в FSM только как Fernet-токен.

### Замечено вне фазы 2 — закрыто техническим долгом (22.11.2026)

- ~~**`alembic check` не чист из-за старого дрейфа**~~ — **закрыто (W3)**: у `journals.id`
  убран `unique=True` (PK уже уникален), в `migrations/env.py` добавлен `include_object`,
  исключающий таблицы админки (`admin`, `role`, `roles_admins`, документированный
  компромисс A11). `alembic check` → «No new upgrade operations detected»; локально
  `downgrade -1` → `upgrade head` проходит, голова `2026_11_21_grades_v2` не менялась.
- ~~**`respx` по-прежнему не мокает `aiohttp`**~~ — W1.6: зависимость удалена.
- ~~**Метрики Celery не экспортируются по HTTP**~~ — W2.1: `/metrics` воркера и celery-exporter.
- ~~**`deploy.ps1` собирает образ на сервере**~~ — **закрыто (W5.1)**: режимы `-ImageFile`
  и `-DeliverImage` (локальная сборка → `docker save` → gzip → `scp` → `docker load` →
  `up -d --no-build`); сеть BuildKit сервера не нужна. Проверено end-to-end 22.11.2026.
- ~~**Пустой журнал edu-tpi**~~ — **не баг (W1.10)**: `EduEmptyJournalError`, пропуск без
  ошибки; тесты `test_get_journal_without_data_raises_empty_error` и
  `test_empty_journal_is_skipped_without_error`.
- ~~**Ключи Redis с хвостовым двоеточием**~~ — **проверено на проде (W1.11)**:
  `redis-cli --scan --pattern 'auth:token:*:'` пуст; живой ключ — `auth:token:775171777`
  (без хвоста). Удалять нечего.
- ~~**Ручной сценарий Telegram агентом не проверялся**~~ — ограничение, W6.1.
- ~~**Ширина таблицы считается по `len()`**~~ — **закрыто (W1.13)**: `wcwidth` — прямая
  зависимость, `display_width()` используется в `_truncate`/`_fit` и в обрезке списка
  журналов; тесты с эмодзи и CJK, оценки и `Н/У/Б/О` не сломаны.
- ~~**`GET /api/tokenauth` не проверяется на `state`**~~ — **закрыто (W1.12)**:
  `state != 1` → `EduAuthError` (данные входа отозваны), `state: 1` без `data` → `ParseError`;
  успешный ответ не задет. Тесты в `tests/unit/test_edu_tpi_client.py`.

### Замечено вне фазы 3 — закрыто техническим долгом (22.11.2026)

- ~~**Метрики воркера не экспортируются по HTTP**~~ — **закрыто (W2.1)**: `notifications_total`,
  `sync_new_grades_total`, `sync_batch_users_total`, `sync_batch_duration_seconds` видны в
  `/metrics` воркера на `:9108`; Prometheus job `worker`, дашборд Grafana `Celery / sync`.
- ~~**`respx` так и не мокает `aiohttp`**~~ — W1.6: удалён.
- ~~**`pgbackup` пишет только на тот же SSD**~~ — **закрыто (W5.2)**: `deploy/backup-pull.ps1`
  забирает последний дамп на машину разработчика, проверяет gzip, печатает UTC и МСК и с
  `-RestoreCheck` восстанавливает в отдельную БД. Проверено 22.11.2026: дамп
  `bot_db-20261122-002956.sql.gz` (03:29 МСК), 9 таблиц, 1 пользователь.
  Автоматическое расписание pull — решение владельца (см. фазу 5).
- ~~**Серверный BuildKit не резолвит `ghcr.io`**~~ — **закрыто (W5.1)**: доставка готового
  образа `-ImageFile`/`-DeliverImage`, BuildKit на сервере не участвует.
- ~~**Ручные нажатия в Telegram агентом не выполнялись**~~ — ограничение, W6.1.
- ~~**`sync_new_grades` экспонируется как `sync_new_grades_total`**~~ — **учтено в
  документации (W1.9)**: имя зафиксировано в [ARCHITECTURE.md](ARCHITECTURE.md) §11 и в
  дашборде `configs/grafana/celery-sync.json`.

### Замечено вне фазы 4 — закрыто техническим долгом (22.11.2026)

- ~~**`users.edu_user_id` не всегда равен id строки `journalData`**~~ — **закрыто (W4)**:
  Redis-маппинг `journal:student:{edu_user_id}` → id строки журнала, TTL 30 дней. Заполняется
  только при однозначном совпадении по ФИО; `JournalCache` ищет по маппингу → `edu_user_id` →
  ФИО, `GroupSyncService` и `GradeSyncService` используют то же правило. Тесты:
  `test_redirected_student_id_is_mapped_and_gives_cache_hit`,
  `test_ambiguous_full_name_does_not_create_mapping`,
  `test_member_is_matched_by_full_name_when_edu_id_differs` (повторный прогон — cache hit,
  HTTP-запросов не прибавилось). На проде: маппинг `journal:student:-22069` → `22069`,
  первый `sync_all_users` — 15.3 с, повторный — 1.4 с, `new=0`, ошибок нет.
- ~~**Метрики воркера не экспортируются по HTTP**~~ — W2.1.
- ~~**Алерт админам на проде не провоцировался**~~ — ограничение, W6.2 (логика покрыта
  `tests/unit/test_sync_batch.py`).
- ~~**Плановый запуск 06:00/12:00/18:00 МСК не наблюдался**~~ — расписание проверено в beat;
  фактический плановый прогон — внешнее ограничение сессии (W6.3).
- ~~**`respx` не мокает `aiohttp`**~~ — W1.6.
- ~~**`pgbackup` пишет только на тот же SSD**~~ — W5.2.
- ~~**Серверная сборка зависит от локального стора `ghcr.io`**~~ — W5.1.
- ~~**pre-commit в песочнице требует доступа вне её**~~ — **компенсировано (W1.15)**: job
  `pre-commit` в `.github/workflows/linters.yml` (`pre-commit run --all-files`); локально —
  `just pre` с расширенным доступом (ограничение среды).
- ~~**У одного пользователя батч длится ~14–15 с**~~ — **лимиты вынесены в настройки
  (W1.14)**: `EDU_MIN_JOURNAL_INTERVAL=1.0`, `EDU_MAX_RPS=5`, defaults не изменены; подбор
  под нагрузку — фаза 8 (нагрузочный прогон), не технический долг.

### Замечено вне фазы 5 (открыто, 22.11.2026)

Технический долг фаз 0–4 закрыт; здесь только то, что нельзя закрыть кодом в этой сессии или
что требует решения владельца.

- **Ручные проверки в Telegram** (W6.1). У агента нет клиента Telegram: нажатия `/settings`,
  `/sync`, `/grades`, `/logout` в реальном клиенте не выполнялись. Экраны и обработчики
  покрыты тестами и рендером реальных строк из БД; серверная часть синхронизации проверена
  на проде.
- **Реальный алерт админам на проде не провоцировался** (W6.2): он ушёл бы владельцу. Логика
  покрыта `tests/unit/test_sync_batch.py` (порог, доля, одно сообщение на админа, падение
  Telegram).
- **Плановый запуск 06:00/12:00/18:00 МСК** (W6.3): расписание проверено в контейнере `beat`,
  ручной `sync_all_users` выполнен на проде; фактический плановый прогон в этой сессии не
  наблюдался (до ближайшей границы — часы). Первый плановый прогон пишет
  `sync batch started/finished` в `docker compose logs worker`.
- **Два реальных пользователя одной группы на проде** (W6.4): в БД один авторизованный
  пользователь; фейковых не добавляли. Сценарий «один запрос на журнал/подгруппу и один диф
  на участника» закрыт `tests/integration/test_group_sync.py`.
- **Автоматическое расписание pull-бэкапа** (W5.2): скрипт `deploy/backup-pull.ps1` есть и
  проверен, но запускается вручную; второе место хранения (S3/другой хост) не выбрано.
  Вопрос владельцу: нужен ли ежедневный pull по расписанию и/или S3-хранилище?
- **Monitoring на проде не включён**: конфиги (`configs/prometheus`, `configs/grafana`,
  compose-профиль `monitoring`) готовы и проверены локально (targets `worker` и
  `celery-exporter` — `up`, дашборд `Celery / sync` открывается). Включение требует скачать
  образы `prom/prometheus`, `grafana/grafana`, `danihodovic/celery-exporter` на сервер и
  выделить ~1.1 ГиБ памяти. Решение владельца.
- **Celery 5.7.0 не поставляет `py.typed`** (W1.8): три `# type: ignore` в `bot/tasks/base.py`,
  `bot/tasks/sync.py`, `bot/celery_app.py`; снимутся с типизированным релизом Celery.
- **pre-commit в песочнице** (W1.15): `.githooks/pre-commit` запускает MSYS git, которому
  песочница запрещает создавать signal pipe; CI-job `pre-commit` закрывает проверку, локально
  `just pre`/`git commit` требуют расширенного доступа.
- **Медленный импорт aiogram и Docker Desktop на Windows** (W1.16): окружение, не код;
  таймауты импорта компенсированы локальным импортом в `send_telegram_message`.
- **`uv add`/`uv lock` только через прокси** (W1.16): `HTTPS_PROXY=http://127.0.0.1:10809`.
- **Счётчики задач переработанного дочернего процесса воркера обнуляются**: multiprocess
  `prometheus_client` удаляет mmap-файлы процесса по `mark_process_dead`, поэтому после
  `worker_max_tasks_per_child` (1000) ряд `celery_tasks_total` начинается заново. Для
  дашбордов это нормально (`increase`/`rate` переживают сброс), но сумма «за всё время» по
  воркеру не накапливается — историю хранит Prometheus, а не процесс.

### Чек-лист перед production (после MVP)

- [ ] `docker compose up -d --build` на чистой машине поднимает бота, воркер, beat, админку;
- [x] миграции применяются на пустой БД и откатываются (`downgrade -1` → `upgrade head`, W3);
- [ ] вход, оценки, синхронизация, уведомления, настройки, выход — проверены на 2+ реальных аккаунтах;
- [ ] уведомления не дублируются, ночные приходят утром;
- [x] `/metrics` отвечает, дашборд Celery не пустой (W2.1, локальная проверка);
- [ ] Sentry получает тестовую ошибку, в ней нет ПДн;
- [x] бэкап PostgreSQL восстанавливается на отдельной БД (W5.2);
- [ ] дефолтный пароль админки изменён, доступ по `superuser`;
- [x] лимиты: 30 апдейтов/мин на пользователя, 1 req/s к edu-tpi, backoff на 429/5xx;
- [x] README, ARCHITECTURE, ROADMAP, API, DEVELOPMENT соответствуют коду;
- [ ] логотип бота, описание, команды в `@BotFather` заданы.

---

## 13. Риски плана

| Риск | Вероятность | Влияние | Что делаем |
|---|---|---|---|
| Схема edu-tpi изменится во время MVP | Средняя | Высокое | Контрактные тесты на фикстурах, `ParseError` + алерт админу, изоляция парсера |
| Бан по лимитам edu-tpi | Низкая | Высокое | 1 req/s, групповой кеш, backoff, ручной запуск массовой синхронизации |
| Celery окажется избыточным для 100 пользователей | Средняя | Низкое | Очереди и задачи пишутся независимо от брокера — можно заменить исполнителя |
| Оценки «плывут» из-за нестабильного API (то есть, то нет) | Средняя | Среднее | Не удалять старые записи, хранить `updated_at`, показывать дату синхронизации |
| Нет времени на тесты в фазах 2–3 | Высокая | Среднее | Тесты входят в DoD; парсер и диф тестируются первыми |
| Один разработчик + Dependabot-шум | Средняя | Низкое | Авто-merge минорных обновлений, ревью раз в неделю |

---

## 14. После MVP (не входит в план)

- графики динамики успеваемости (изображения в сообщении);
- интеграция с расписанием занятий;
- напоминания о дедлайнах и экзаменах;
- поддержка других вузов (абстракция источника данных);
- PDF-экспорт;
- веб-кабинет (не Telegram).
