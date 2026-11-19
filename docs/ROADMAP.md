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

Кратко: инфраструктура, схема данных, каркас бота, вход в edu-tpi и парсер журнала — есть.
Продуктовая часть (оценки, синхронизация, уведомления) — не начата.

| Блок | Статус | Что есть | Чего нет |
|---|---|---|---|
| Инфраструктура | ✅ | compose (бот, воркер, beat, админка, postgres, pgbouncer, redis, миграции, бэкапы, prometheus, grafana, node-exporter), Dockerfile ×2, CI, pre-commit, `just`/`make` | Flower и celery-exporter (фаза 8) |
| Схема БД | 🟡 | `users`, `journals`, `grades`, `sync_logs`, `student_journal`, 5 миграций | корректного PK `grades` (см. 2.1) |
| Каркас бота | ✅ | polling/webhook, FSM в Redis, middlewares, i18n ru/en, меню, аналитика, Sentry, логи, `/healthz` и `/metrics` в обоих режимах | обработчиков оценок/статистики/настроек |
| Вход в edu-tpi | ✅ | FSM логин→пароль с inline-отменой, `api_client`, обязательный `ENCRYPTION_KEY`, токен в Redis, `users` обновляется, «сервис недоступен» отличается от неверных данных | кеша токена и повторной авторизации по сохранённым данным (2.4) |
| Парсер журнала | 🟡 | `JournalParser`: список журналов, детали, выборка строки студента, уроки | группового кеша, подгрупп, сохранения в БД |
| Синхронизация | ⬜ | — | `GradeSyncService`, диф, `sync_logs` |
| Уведомления | ⬜ | — | `NotificationService`, ночная политика |
| Экраны оценок/статистики | ⬜ | — | `/grades`, `/stats`, `/settings`, `/logout`, callback-обработчики |
| Celery | ✅ | приложение `journal_bot`, очереди `sync`/`notify`/`maintenance`, `BaseTask` (ретраи, lock, логи, метрики), мост sync/async, smoke-задача `ping`, сервисы `worker`/`beat` в compose | задач синхронизации и уведомлений (фазы 2–3), расписания beat (фаза 4) |
| Админка | 🟡 | вход, роли, пользователи, дашборд | журналы, оценки, логи синхронизаций |
| Тесты | ✅ | pytest + pytest-asyncio, `fakeredis`, HTTP-стаб edu-tpi, 63 теста (включая Celery в eager-режиме), job «Run tests» в CI | тестов парсера, дифа и интеграционных сценариев (фазы 2–3) |

**Готовность MVP: ~60%** (инфраструктура, вход, фундамент и каркас фоновой обработки готовы,
тесты закрывают то, что уже написано; синхронизация, оценки и уведомления — нет).

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
Отправка из воркера в Telegram проверена вызовом `send_telegram_message` из контейнера
`worker` (сообщение пришло в admin-чат из БД). Задач синхронизации и уведомлений нет —
это фазы 2–3; расписание beat пустое до фазы 4.

---

## 4. Фаза 2 — синхронизация и оценки (ядро MVP)

Цель: пользователь видит свои оценки, полученные из журнала, и может обновить их вручную.

| № | Задача | Статус | Ч | Файлы |
|---|---|---|---|---|
| 2.1 | Миграция `grades`: суррогатный PK, `edu_lesson_id`, `hour_number`, `UNIQUE(user_id, journal_id, date, hour_number)` | ⬜ | 2 | `migrations/versions/`, [bot/database/models/grade.py](../bot/database/models/grade.py) |
| 2.2 | Слить `api_client` и `journal_parser` в `integrations/edu_tpi.py`: типизированные ответы, ошибки, таймауты | ⬜ | 4 | `bot/integrations/edu_tpi.py` |
| 2.3 | Кеш журналов и алгоритм подгрупп (`student_ids`, `isSubGroup`, ключи `journal:*`) | ⬜ | 5 | `bot/integrations/journal_cache.py` |
| 2.4 | Кеш токена в Redis, повторная авторизация по сохранённым данным, обработка 401 | ⬜ | 3 | `bot/services/auth.py` |
| 2.5 | `GradeSyncService.sync_user`: диф, upsert, `sync_logs`, возврат сводки | ⬜ | 6 | `bot/services/grade_sync.py` |
| 2.6 | Задачи `sync_user_manual`, `sync_user_after_login` + сообщение пользователю | ⬜ | 3 | `bot/tasks/sync.py` |
| 2.7 | `/sync` и кнопка «Обновить»: постановка задачи, «⏳ запущено», результат, обработка «уже идёт» | ⬜ | 3 | `bot/handlers/message/sync.py`, `bot/handlers/callback/` |
| 2.8 | Экран `/grades`: таблица по журналам, выбор журнала, кнопки «Назад/Обновить» | ⬜ | 5 | `bot/handlers/message/grades.py`, `bot/keyboards/inline/grades.py` |
| 2.9 | Форматирование таблицы оценок (ширина 86, обрезка названий, легенда) + тесты | ⬜ | 3 | `bot/utils/formatters.py` |
| 2.10 | `/logout`: сброс токена, удаление шифрованных данных, `is_authenticated=False` | ⬜ | 2 | `bot/handlers/message/auth.py` |
| 2.11 | `journals` upsert при синхронизации (имя, преподаватель, тип) | ⬜ | 2 | `bot/services/journals.py` |

**Итог фазы: ~38 ч.** Критерий приёмки:
- после входа в БД появляются журналы и оценки, совпадающие с веб-журналом;
- повторная синхронизация не создаёт дубликатов и пишет `sync_logs`;
- `/grades` показывает таблицу, средний балл по журналу;
- синхронизация двух пользователей одной группы делает один запрос на журнал (видно по логам);
- тесты: диф оценок, подгруппы, парсер на фикстурах.

---

## 5. Фаза 3 — уведомления (финиш MVP)

| № | Задача | Статус | Ч | Файлы |
|---|---|---|---|---|
| 3.1 | `NotificationService`: немедленное уведомление, форматирование, проверка настроек | ⬜ | 3 | `bot/services/notifications.py` |
| 3.2 | Ночное накопление в Redis + `send_night_batch` с `eta` на утро пользователя | ⬜ | 4 | `bot/tasks/notify.py` |
| 3.3 | Экран `/settings`: уведомления вкл/выкл, «копить ночью», время утра | ⬜ | 4 | `bot/handlers/message/settings.py`, `bot/keyboards/inline/settings.py` |
| 3.4 | Дедупликация (`notify:sent:*`), обработка `TelegramForbidden`/`RetryAfter` | ⬜ | 2 | `bot/tasks/notify.py` |
| 3.5 | Метрики и события аналитики: `notifications_total`, `sync_new_grades` | ⬜ | 2 | [bot/middlewares/prometheus.py](../bot/middlewares/prometheus.py) |
| 3.6 | Тесты политики: день/ночь, дубликаты, выключенные уведомления | ⬜ | 3 | `tests/unit/` |

**Итог фазы: ~18 ч.** Критерий приёмки:
- новая оценка днём приходит одним сообщением в течение минуты после синхронизации;
- оценка в 23:00 не будит, а приходит утром одним списком в указанное время;
- повторный запуск задачи не отправляет то же уведомление дважды;
- пользователь, заблокировавший бота, не ломает очередь.

### 🎯 MVP готов, когда

- [ ] вход, оценки, ручная синхронизация и уведомления работают на реальных данных;
- [ ] `docker compose up -d` на чистой машине поднимает всё, включая воркер и beat;
- [ ] `pytest` и `mypy` зелёные в CI;
- [ ] в логах нет паролей и токенов;
- [ ] README и ROADMAP отражают фактическое состояние.

**Оценка MVP: ~93 ч** (фазы 0–3). При 8–10 ч/неделю — около 2,5 месяцев.

---

## 6. Фаза 4 — автоматическая синхронизация

| № | Задача | Статус | Ч | Файлы |
|---|---|---|---|---|
| 4.1 | `sync_all_users`: группировка по `group_id`, обход подгрупп через `unprocessed_students` | ⬜ | 4 | `bot/tasks/sync.py` |
| 4.2 | Оппортунистическая синхронизация участников группы (флаг `SYNC_OPPORTUNISTIC`) | ⬜ | 3 | `bot/services/grade_sync.py` |
| 4.3 | Расписание beat: 6 часов, ночное окно, блокировка пересекающихся запусков | ⬜ | 2 | `bot/celery_app.py` |
| 4.4 | Метрики массовой синхронизации, алерт при массовых ошибках | ⬜ | 2 | `bot/tasks/sync.py` |
| 4.5 | Тест: два пользователя одной группы — один запрос на журнал | ⬜ | 2 | `tests/integration/` |

**Итог: ~13 ч.** Критерий: за прогон 100 пользователей ≤ ~120 запросов к edu-tpi,
ошибки не роняют весь прогон.

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
| 8.3 | `celery-exporter` + дашборд Grafana «Celery», панель синхронизаций | ⬜ | 4 | [docker-compose.yml](../docker-compose.yml), `configs/grafana/` |
| 8.4 | Нагрузочный прогон (200 пользователей), настройка concurrency и лимитов | ⬜ | 3 | — |
| 8.5 | Runbook: что делать при 401 у всех, бане API, переполнении очереди | ⬜ | 2 | `docs/RUNBOOK.md` |
| 8.6 | `docs/UI.md`: экраны и тексты (перенос из архива), сверка README с кодом | ⬜ | 3 | `docs/` |
| 8.7 | Починить или удалить `scripts/postgres/*` (ссылаются на несуществующую БД `app`, нет `pg_dump` в образе) | ⬜ | 1 | [scripts/postgres/](../scripts/postgres/) |

**Итог: ~20 ч.**

---

## 11. Сводка

| Фаза | Содержание | Часы | Статус |
|---|---|---|---|
| 0 | Фундамент и исправления | 18 | ✅ |
| 1 | Celery | 19 | ✅ |
| 2 | Синхронизация и оценки | 38 | ⬜ |
| 3 | Уведомления | 18 | ⬜ |
| **MVP** | **0–3** | **~93** | **🟡 60% готовности** |
| 4 | Автосинхронизация | 13 | ⬜ |
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

### Замечено вне фазы 0 (не исправлялось)

- `build_key("auth:token", user_id)` даёт ключ с хвостовым двоеточием (`auth:token:1:`), а
  [ARCHITECTURE.md](ARCHITECTURE.md) §4.2 обещает `auth:token:{user_id}`. Работает, но формат
  стоит выровнять в фазе 2 вместе с кешем токена.
- `respx` (0.23) не умеет мокать `aiohttp` — он работает только с `httpx`. HTTP-тесты входа
  используют локальный стаб `aiohttp.ClientSession`; `respx` оставлен в dev-зависимостях на
  случай перехода интеграций на httpx в фазе 2. Решение о клиенте — задача 2.2.
- `api_client` и `journal_parser` дублируют URL и создают сессию на каждый запрос; слияние —
  задача 2.2.
- `bot/services/journal_parser.py` нигде не импортируется, но нужен фазе 2 — оставлен осознанно.
- `grades.id` остаётся PK от `dateID` — синхронизация на такой схеме невозможна, миграция 2.1.
- `bot/services/auth.py` по-прежнему смешивает HTTP, шифрование, Redis, БД и правку сообщений
  Telegram — рефакторинг в 2.2/2.4.
- `pgbackup` снимает дампы клиентом `pg_dump` 17 с сервера PostgreSQL 14: в дампе есть
  `SET transaction_timeout`, которого нет в 14, поэтому восстановление «как есть» падает.
  Варианты — обновить сервер до 17 или закрепить клиент 14; в этой сессии дамп восстановлен
  с удалением этой строки.
- `get_edu_credentials` возвращает `(None, None)`, если повреждена любая из двух частей; после
  смены `ENCRYPTION_KEY` пользователь просто входит заново, отдельного уведомления нет.
- Комментарии `#:` в `.po` ссылаются на удалённые файлы; `just babel` их перегенерирует.
- `.mo` не в git: перед `pytest` (тесты проверяют русские тексты) и ручным запуском нужен
  `just babel-compile`; CI компилирует локали отдельным шагом.
- `uv add` / `uv lock` на машине разработчика ходят в PyPI только через прокси хоста
  (`HTTPS_PROXY=http://127.0.0.1:10809`) — это окружение, а не проблема проекта.

### Замечено вне фазы 1 (не исправлялось)

- **`just dev` (локальный бот) не читает `.env.local`.** В justfile включены `set dotenv-load`
  и `set export`, поэтому переменные `.env` попадают в окружение процесса и в
  pydantic-settings перекрывают значения из `.env.local` (`ENV_FILE` задаёт только файл, а не
  приоритет): локальный бот пойдёт на `pgbouncer`/`redis` вместо `127.0.0.1:6432`/`6380`.
  `just dev-worker` обходит это, убирая экспортированные переменные перед запуском; общий фикс
  (решение за владельцем) — `set dotenv-load := false` или явный список переменных в рецепте.
- **Метрики задач Celery не экспортируются по HTTP.** `celery_tasks_total`,
  `celery_task_failures_total`, `celery_task_duration_seconds` живут в процессе воркера;
  `/metrics` бота их не видит. Нужен celery-exporter/Flower — фаза 8.
- **`.env` не содержал `CELERY_*`** (были только дефолты `CelerySettings`): в Docker это работало
  на значениях по умолчанию, локально — нет. Добавлены `CELERY_BROKER_URL`,
  `CELERY_RESULT_BACKEND`, `CELERY_RESULT_EXPIRES`, `CELERY_TASK_ALWAYS_EAGER` в `.env` и
  `.env.local` (файлы не в git).
- **Celery не поставляет типы (`py.typed`)** — в трёх местах стоят `# type: ignore`
  (`BaseTask(Task)`, декоратор задачи, декоратор сигнала). Если выйдет типизированный релиз,
  игноры нужно снять.
- **`worker` healthcheck зависит от `celery inspect ping`**: проверка запускает полноценный
  `celery` CLI (~8 с на этой машине), поэтому `timeout: 30s`, `start_period: 120s`; при
  перегрузке брокера контейнер может формально «unhealthy», хотя задачи идут. Для MVP приемлемо,
  при проблемах — увеличить `timeout`/`retries`.
- **Медленный импорт на Windows + Docker Desktop.** В контейнере `import aiogram` занимает ~60 с,
  `celery -A ...` (healthcheck) — ~8 с, поэтому: aiogram импортируется локально внутри
  `send_telegram_message` (остальные задачи за него не платят), а у healthcheck воркера
  `timeout: 30s`, `start_period: 120s`. На Linux-хосте в разы быстрее; при переносе на VPS таймауты
  можно уменьшить.
- **Ротация `logs/worker.log` не мультипроцессная**: loguru не гарантирует корректную ротацию,
  когда в файл пишут несколько процессов-детей prefork-пула (2 по умолчанию). При нескольких
  воркерах — отдельный файл на pid или `enqueue=True` с одним писателем (фаза 8).

### Исправлено по ходу вне фазы 0

- **[docker-compose.yml](../docker-compose.yml): `PGDATA` был в кавычках.** Compose передаёт
  значение вместе с ними, поэтому кластер создавался в слое контейнера, а не в томе
  `tgbot_postgres-data`; любое пересоздание `postgres` теряло БД. Кавычки убраны, том теперь
  используется по назначению. Данные после пересоздания восстановлены из `pgbackup`
  (последний дамп — 19.11.2026 02:13); изменения за 02:13–05:14, если они были, потеряны —
  проверить при следующем входе.

### Чек-лист перед production (после MVP)

- [ ] `docker compose up -d --build` на чистой машине поднимает бота, воркер, beat, админку;
- [ ] миграции применяются на пустой БД и откатываются;
- [ ] вход, оценки, синхронизация, уведомления, настройки, выход — проверены на 2+ реальных аккаунтах;
- [ ] уведомления не дублируются, ночные приходят утром;
- [ ] `/metrics` отвечает, дашборд Celery не пустой;
- [ ] Sentry получает тестовую ошибку, в ней нет ПДн;
- [ ] бэкап PostgreSQL восстанавливается на отдельной БД;
- [ ] дефолтный пароль админки изменён, доступ по `superuser`;
- [ ] лимиты: 30 апдейтов/мин на пользователя, 1 req/s к edu-tpi, backoff на 429/5xx;
- [ ] README, ARCHITECTURE, ROADMAP, API, DEVELOPMENT соответствуют коду;
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
