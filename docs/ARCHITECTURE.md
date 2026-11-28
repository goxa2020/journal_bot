# Архитектура Journal Bot

**Версия:** 2.1 · **Дата:** 21.11.2026 · **Статус:** фазы 0–2 реализованы; целевая
архитектура для фаз 3–8
**Область:** Telegram-бот доступа к электронному журналу `edu-tpi.donstu.ru`

Документ описывает, как система должна быть устроена. Текущее состояние кода и порядок работ —
в [ROADMAP.md](ROADMAP.md). Спецификация внешнего API — в [API.md](API.md). Команды разработки —
в [DEVELOPMENT.md](DEVELOPMENT.md).

---

## 1. Контекст и цели

### Задача

Студент ДГТУ получает в Telegram то, ради чего иначе открывает веб-журнал: свои оценки,
посещаемость, средний балл и уведомления о новых оценках.

### Акторы

| Актор | Что делает | Ограничения |
|---|---|---|
| Студент | Авторизуется, смотрит оценки, включает уведомления | Одна учётная запись edu-tpi на Telegram-аккаунт |
| Администратор | Смотрит пользователей, логи синхронизаций, чинит залипших | Веб-панель, роль `superuser` |
| edu-tpi API | Источник данных | Неофициально используемый API, лимитов не публикует, схема может меняться |
| Telegram Bot API | Канал доставки | 30 сообщений/сек суммарно, 1 сообщение/сек в один чат |

### Целевые показатели

| Параметр | Значение |
|---|---|
| Пользователей | 100–300 (пик — начало сессии) |
| Ответ бота на команду | < 300 мс, независимо от синхронизации |
| Синхронизация одного пользователя | 3–10 с в фоне |
| Запросов к edu-tpi | ~1 на журнал на группу, а не на студента |
| Частота плановой синхронизации | каждые 6 часов |
| Частота режима ожидания | каждые 5 минут, не более 30 минут подряд |

### Не цели

- Замена веб-журнала: бот только читает.
- Хранение пароля в открытом виде, восстановление пароля, доступ к чужим оценкам.
- Мобильное/веб-приложение, API для третьих сторон.

---

## 2. Компоненты и топология

```
                    ┌──────────────────────────┐
   Telegram  ──────▶│  bot (aiogram 3)         │
                    │  handlers · FSM · i18n   │──┐
                    └──────────┬───────────────┘  │ enqueue
                               │ SQL              │
                    ┌──────────▼───────────────┐  │
                    │ pgbouncer ──▶ PostgreSQL │  │
                    └──────────▲───────────────┘  │
                               │ SQL              │
                    ┌──────────┴───────────────┐  │
                    │ worker (Celery)          │◀─┘
                    │ sync · notify · service  │
                    └──────────┬───────────────┘
                               │ HTTPS
                    ┌──────────▼───────────────┐
                    │ edu-tpi API              │
                    └──────────────────────────┘

  Redis: db0 — FSM + кеш + токены + лимиты
         db1 — брокер Celery
         db2 — результаты Celery
  beat (Celery beat) ──▶ расписание задач
  flower ──▶ UI мониторинга очередей
  admin (Flask-Admin) ──▶ PostgreSQL (свои таблицы admin/role)
  prometheus · grafana · node-exporter ──▶ метрики
```

| Компонент | Технология | Ответственность | Состояние |
|---|---|---|---|
| `bot` | aiogram 3.32, aiohttp | Приём апдейтов, FSM, клавиатуры, тексты, постановка задач | Работает |
| `worker` | Celery | Синхронизация, уведомления, обслуживание | Синхронизация работает; уведомления — фаза 3 |
| `beat` | Celery beat | Расписание периодических задач | Сервис работает, расписание пустое до фазы 4 |
| `flower` | Flower | UI очередей и задач | Не реализован |
| `admin` | Flask-Admin + Flask-Security | Просмотр и правка пользователей, журналов, логов | Работает, 1 экран |
| `postgres` | PostgreSQL 14 | Постоянные данные | Работает |
| `migrator` | Alembic | Применение миграций при старте compose | Работает (завершается) |
| `pgbouncer` | edoburu/pgbouncer | Пул соединений к PostgreSQL | Работает |
| `redis` | Redis 7 | FSM, кеш, токены, брокер и backend Celery | Работает (брокер ещё не используется) |
| `prometheus`/`grafana` | v2.43 / 8.5 | Метрики, дашборды | Prometheus есть, дашбордов бота нет |
| `pgbackup` | postgres-backup-local | Бэкапы раз в 30 минут | Работает |

### Правила взаимодействия компонентов

1. **`bot` не выполняет сетевые вызовы edu-tpi.** Любой вызов журнала — только из `worker`.
   Исключение на переходный период: вход (`tokenauth`), потому что пользователь ждёт ответ.
2. **`bot` не блокируется.** Всё, что дольше ~1 с, уходит в задачу.
3. **`worker` общается с Telegram сам** — отдельным экземпляром `Bot`, а не через процесс `bot`.
4. **Единственный источник истины — PostgreSQL.** Redis полностью восстановим.
5. **Обе стороны используют один `bot/core/config.py`** и один `.env`.

### Локальная сеть

Docker не наследует системный прокси хоста, поэтому Bot API может быть недоступен из
контейнера, даже если на хосте Telegram открывается. Решение — `TELEGRAM_PROXY`
(`http://host.docker.internal:10809`): бот создаёт `AiohttpSession(proxy=...)`, а воркер при
создании своего `Bot` (задача 1.6) обязан использовать ту же настройку. edu-tpi ходит напрямую —
это другой домен и обычно другой маршрут.

---

## 3. Слои кода и правила зависимостей

```
handlers/ keyboards/ filters/          интерфейс: разбор апдейта, тексты, кнопки
        │  (только вызов сервисов)
services/                              прикладные сценарии, транзакции, политика
        │
integrations/ (edu_tpi, journal_cache)   внешний мир
        │
database/ (models, repositories)       доступ к данным
        │
core/ (config, loader, cache)          инфраструктура
```

| Слой | Что можно | Что нельзя |
|---|---|---|
| `handlers/` | Вызывать сервисы, форматировать ответ, менять FSM | SQL-запросы, `aiohttp`, бизнес-правила |
| `services/` | Оркестрировать шаги, коммитить транзакции, решать «уведомлять или нет» | Знать про `Message`/`CallbackQuery`, строить клавиатуры |
| `integrations/` | HTTP, парсинг, кеш сырых ответов | Знать про БД и Telegram |
| `database/` | Запросы и модели | HTTP, Telegram, форматирование |
| `core/` | Настройки, подключения, обёртки | Прикладная логика |

Текущие отклонения, которые нужно устранить (см. ROADMAP, фаза 0–2):

- [bot/services/auth.py](../bot/services/auth.py) одновременно ходит в HTTP, шифрует пароль,
  пишет в Redis и в БД, и там же живёт правка сообщений Telegram (`edit_bot_message`).
  Целевое: `AuthService` (данные) + `handler` (сообщения).
- [bot/handlers/message/auth.py](../bot/handlers/message/auth.py) содержит правила валидации
  логина — это сервис.
- `bot/services/journals.py` и `bot/services/sync_logs.py` удалены в фазе 0: они были написаны
  под старую схему «предметов» и нигде не импортировались.

### Целевая структура каталогов

```
bot/
├── __main__.py            запуск бота (polling/webhook)
├── celery_app.py          приложение Celery + маршрутизация задач      [нет]
├── celery_config.py       параметры Celery                            [нет]
├── tasks/                 celery-задачи                                [нет]
│   ├── sync.py            sync_user_*, sync_all_users
│   ├── notify.py          send_*_notification
│   └── service.py         cleanup_*, collect_metrics
├── core/                  config, loader, cache, encryption
├── database/              engine, models, repositories
├── integrations/          edu-tpi клиент и парсер                      [частично: services/]
├── services/              auth, grade_sync, notification, statistics, export
├── handlers/              message/, callback/
├── keyboards/             inline/
├── middlewares/           auth, database, i18n, throttling, logging
├── locales/               ru/en
└── utils/                 форматирование, меню
```

---

## 4. Данные

### 4.1 PostgreSQL

Схема на текущий момент (голова — `2026_11_21_grades_v2`, 6 миграций).

**`users`** — один Telegram-пользователь.

| Поле | Тип | Назначение |
|---|---|---|
| `id` | BIGINT PK | Telegram user id |
| `language_code` | TEXT | ru/en для i18n |
| `edu_login_encrypted`, `edu_password_encrypted` | VARCHAR(255) | Fernet-шифр учётных данных |
| `edu_user_id` | BIGINT | ID студента в edu-tpi (`user.userID`) |
| `group_id`, `group_name` | BIGINT / TEXT | группа (`groupID`, `group`), ключ группового кеша |
| `full_name` | TEXT | `fio`, краткая форма |
| `is_authenticated` | BOOL | вход выполнен, данные можно синхронизировать |
| `notification_enabled` | BOOL | уведомления вообще |
| `morning_notification_enabled` | BOOL | копить ночные оценки до утра |
| `morning_notification_time` | TIME | по умолчанию 08:00 (Europe/Moscow) |
| `watch_mode_expires_at` | TIMESTAMP NULL | до какого времени «режим ожидания» |
| `watch_mode_last_sync_at` | TIMESTAMP NULL | время последней синхронизации в режиме ожидания |
| `is_admin` | BOOL | доступ к админ-командам бота |
| `created_at`, `updated_at` | TIMESTAMP | |

**`journals`** — дисциплина/журнал. PK — `id` журнала в edu-tpi.

| Поле | Назначение |
|---|---|
| `id` | `journalID` из edu-tpi |
| `name`, `teacher_name`, `type` | `dis`, `teacherName`, `type` (Лек/Пр/Лаб) |
| `created_at`, `updated_at` | |

**`grades`** — оценка/посещаемость одного студента на одном занятии.

| Поле | Назначение |
|---|---|
| `id` | `BIGSERIAL`, суррогатный PK (миграция `2026_11_21_grades_v2`) |
| `user_id` | FK → `users.id` |
| `journal_id` | FK → `journals.id` |
| `date` | дата занятия (DATE) |
| `hour_number` | номер пары в этот день, вторая часть ключа урока |
| `edu_lesson_id` | `dateID` из edu-tpi, информационное поле |
| `value` | отображаемое значение: `1`–`5`, `Н`, `У`, `Б`, `О`, пусто |
| `number_value` | 1–5 для оценок, NULL иначе |
| `is_mark`, `is_pass`, `is_valid_pass` | флаги из `journalVal` |
| `created_at`, `updated_at` | |

Уникальность: `UNIQUE (user_id, journal_id, date, hour_number)`; индексы
`(user_id, journal_id, date)` и `(journal_id)`.

**`sync_logs`** — журнал синхронизаций: `user_id`, `sync_type`
(`manual|auto|watch_mode`), `status` (`success|failed|in_progress|cancelled`),
`new_grades_count`, `updated_grades_count`, `message`, `created_at`.

**`student_journal`** — M2M `users ↔ journals` (какие журналы у пользователя есть).
Пока не заполняется; заполняется при синхронизации (фаза 2).

**Таблицы админки** `admin`, `role`, `roles_admins` создаются через `db.create_all()`
в [admin/app.py](../admin/app.py), а не миграциями. Это осознанный компромисс: админка живёт
отдельно от доменной схемы, но `alembic revision --autogenerate` про них не знает. Переносить
в миграции — задача фазы 8.

### 4.2 Redis

Всё в базе `db0`, кроме Celery.

| Ключ | Тип | TTL | Назначение |
|---|---|---|---|
| `fsm:*` | строки | сессия | состояние aiogram (`RedisStorage`); на шаге пароля содержит `password_enc` — Fernet-токен для кнопки «Ещё раз», открытого пароля нет |
| `main:<module>:<func>:<key>` | pickle/json | 10 с | `@cached` для `users` |
| `auth:token:{user_id}` | JSON | до `expiresIn` минус 5 мин | `accessToken` + `expires_at`, `edu_user_id`, `group_id` |
| `journal:{group_id}:{journal_id}` | JSON | 15 мин | разобранный журнал всей группы |
| `journal:{group_id}:{journal_id}:sub:{hash}` | JSON | 15 мин | журнал подгруппы (`isSubGroup=true`) |
| `journal:{group_id}:{journal_id}:empty:{user_id}` | строка | 15 мин | журнал недоступен студенту (чужая подгруппа): не запрашиваем повторно |
| `journal:student:{edu_user_id}` | строка | 30 дней | маппинг id из `tokenauth` на id строки `journalData` (W4); пишется только при однозначном совпадении по ФИО |
| `journal_legend:global` | JSON | 30 дней | `journalLegend` |
| `grade_values:global` | JSON | 30 дней | справочник `journalVal` |
| `sync:lock:{user_id}` | строка | 5 мин | защита от параллельной синхронизации одного пользователя; батч снимает его сразу после дифа (`release=True`) |
| `sync:all:lock` | строка | 1 ч | один прогон `sync_all_users` за раз; TTL — страховка от падения воркера |
| `sync:queued:{user_id}` | строка | 30 с | защита от повторной постановки задачи при двойном нажатии «Обновить» |
| `ratelimit:{user_id}` | счётчик | 60 с | лимит апдейтов от пользователя |
| `notifications:night:{user_id}` | list | до утра + 2 ч | накопленные ночные оценки (JSON-записи) |
| `notify:sent:{user_id}:{lesson_key}` | строка | 7 дней | защита от повторного уведомления |
| `notify:night:scheduled:{user_id}` | строка | до утра + 2 ч | один `send_night_batch` на пользователя |
| `watch_mode:users` | set | чистится задачей | пользователи в режиме ожидания |
| `api:ratelimit:edu` | счётчик | 1 с | глобальный лимит запросов к edu-tpi |

Правила: значения — только JSON (pickle оставить для внутреннего кеша функций); ключи всегда
строятся `build_key()`; TTL обязателен — единственное исключение `watch_mode:users`, которое
чистится задачей `cleanup_expired_watch_mode`, а не временем жизни ключа.

### 4.3 Что не хранится

- `accessToken` в PostgreSQL — только Redis, восстанавливается повторным входом.
- Сырые ответы API — только в кеше журналов, с TTL.
- Пароль в открытом виде — нигде, ни в логах, ни в Redis, ни в Sentry.

---

## 5. Интеграция edu-tpi

### 5.1 Клиент

Модуль `bot/integrations/edu_tpi.py` (в фазе 2 заменил `services/api_client.py` и
`services/journal_parser.py`; оба удалены):

```python
class EduTpiClient:
    async def get_fingerprint() -> str
    async def authorize(login, password) -> TokenInfo      # accessToken, expiresIn(мин), id
    async def get_user_info(token) -> EduUser              # userID, groupID, group, fio, fullName
    async def list_journals(token, year, sem) -> list[JournalBrief]
    async def get_journal(token, journal_id) -> JournalPayload
```

Правила:

- Один `aiohttp.ClientSession` на задачу, `timeout=60`, `raise_for_status` заменяется явной
  обработкой кодов (§10).
- Каждый вызов журнала — с задержкой ≥ `EDU_MIN_JOURNAL_INTERVAL` (по умолчанию 1 с) от
  предыдущего в рамках клиента; суммарный лимит — `EDU_MAX_RPS` (по умолчанию 5) через
  Redis-счётчик `api:ratelimit:edu`. Оба значения — в `Settings` (`.env`), по умолчанию
  совпадают с прежними константами клиента.
- 401 — токен недействителен: сбросить `auth:token:*`, один раз переавторизоваться по
  сохранённым шифрованным данным, при повторном 401 — попросить пользователя войти заново.
- `GET /api/tokenauth` проверяет `state`: успех — `state: 1`. `200` с другим `state`
  (например, `-1` при отозванном токене) — не битая схема, а отозванные данные входа,
  поэтому `EduAuthError`; `state: 1` без объекта `data` — `ParseError`.
- Учебный год: с сентября `YYYY-(YYYY+1)`, иначе `(YYYY-1)-YYYY`; запрашивается
  **текущий семестр** (сентябрь–январь — 1, февраль–август — 2). Следующий семестр не
  запрашивается: его журналы ещё пустые. Оценки прошлых семестров остаются в БД.
- Ответы кешируются: `journal_legend`, `grade_values`, `journal:*`.

### 5.2 Подгруппы

`journalData` содержит оценки не всей группы, а подгруппы студента, если `isSubGroup=true`.
Кеш журнала поэтому хранит список `student_ids`:

1. Ищем `journal:{group_id}:{journal_id}`; если студент есть в `student_ids` — берём оттуда.
   Студента ищем по id из маппинга `journal:student:{edu_user_id}` (W4), затем по
   `edu_user_id`, затем по однозначному ФИО; найденный id строки журнала запоминается на
   30 дней. Неоднозначное ФИО (однофамильцы) не записывается и даёт `ParseError`.
2. Иначе запрашиваем журнал токеном этого студента.
3. Если `isSubGroup=false` — ключ `...:{journal_id}`; если `true` —
   `...:{journal_id}:sub:{md5(sorted(student_ids))[:8]}`.
4. Сохраняем `{is_subgroup, synced_at, journal_name, student_ids, grades}`.

Эффект: 1 запрос на журнал без подгрупп и по 1 на подгруппу вместо запроса на каждого студента;
повторный прогон для аккаунта с расходящимися id (`edu_user_id = -22069`) попадает в кеш по
маппингу, а не ходит в edu-tpi заново.

### 5.3 Ограничения и деградация

- Лимит edu-tpi неизвестен → держим 1 req/s на токен и 5 req/s суммарно (Redis-счётчик).
- При 429/5xx — retry с backoff, задача не падает сразу.
- Схема ответа может измениться → жёсткая валидация структуры и `ParseError`, а не «тихий»
  пропуск: лучше алерт админу, чем пустые оценки у всех.

---

## 6. Celery

### 6.1 Приложение и брокер

| Параметр | Значение |
|---|---|
| Имя | `journal_bot` |
| Broker | `redis://redis:6379/1` |
| Result backend | `redis://redis:6379/2` |
| Сериализация | JSON, `accept_content=["json"]` |
| Часовой пояс | `Europe/Moscow`, `enable_utc=True` |
| `task_acks_late` | `True` — задача подтверждается после выполнения |
| `task_reject_on_worker_lost` | `True` |
| `worker_prefetch_multiplier` | `1` |
| `task_time_limit` / `soft` | 300 / 250 с |
| `worker_max_tasks_per_child` | 1000 |
| `broker_connection_retry_on_startup` | `True` |

Файлы: `bot/celery_app.py` (создание, `include`, `task_routes`, `beat_schedule`),
`bot/celery_config.py` (константы, читаются из `CelerySettings`).

### 6.2 Очереди и приоритеты

| Очередь | Задачи | Воркер | Смысл |
|---|---|---|---|
| `sync` | `sync_user_manual`, `sync_user_after_login`, `sync_watch_mode_users` | `worker-sync` (concurrency 2) | пользователь ждёт, важно быстро |
| `notify` | `send_grade_notification`, `send_night_batch` | `worker-notify` (concurrency 4) | лёгкие вызовы Bot API, `eta` |
| `maintenance` | `sync_all_users`, `cleanup_*`, `collect_metrics`, дайджест | `worker-maintenance` (concurrency 1) | фоновое, может ждать |

Приоритеты Celery в Redis (`priority`) включаются `task_queue_max_priority=10`;
для MVP достаточно разделения по очередям — приоритеты внутри очереди включаются, если
появится заметная очередь.

### 6.3 Каталог задач

| Задача | Аргументы | Что делает | Retry |
|---|---|---|---|
| `sync_user_manual` | `user_id` | Синхронизация по кнопке; по завершении — сообщение пользователю | 3, backoff 60→240 с |
| `sync_user_after_login` | `user_id` | Первая синхронизация после входа, без сообщения об успехе | 3 |
| `sync_watch_mode_users` | — | Все пользователи с `watch_mode_expires_at > now()` | — |
| `sync_all_users` | — | Групповая синхронизация по расписанию | — |
| `send_grade_notification` | `user_id`, `notices` (JSON-записи), `immediate` | Уведомление о новых оценках: днём сразу, ночью в очередь; `immediate=True` (режим ожидания) — сразу и ночью | 3 |
| `send_night_batch` | `user_id` | Отправка накопленного ночного списка (`eta` = утро) | 3 |
| `cleanup_expired_watch_mode` | — | Сброс истёкшего режима ожидания | — |
| `cleanup_old_logs` | `days=30` | Чистка `sync_logs` | — |
| `collect_metrics` | — | Обновление gauge-метрик | — |
| `send_monthly_digest` | `user_id` \| — | Дайджест (после MVP) | 1 |

Все задачи принимают только примитивы (id, строки) — никаких ORM-объектов в очереди.

### 6.4 Расписание beat

| Задача | Когда | Комментарий |
|---|---|---|
| `sync_all_users` | `crontab(minute=0, hour="*/6")` | 00, 06, 12, 18 МСК |
| `sync_watch_mode_users` | `crontab(minute="*/5")` | каждые 5 минут |
| `cleanup_expired_watch_mode` | `crontab(minute=10)` | каждый час |
| `cleanup_old_logs` | `crontab(minute=0, hour=3, day_of_month="*/2")` | раз в 2 дня |
| `collect_metrics` | `crontab(minute=5)` | каждый час |
| `send_monthly_digest` | `crontab(minute=0, hour=12, day_of_month=31)` | после MVP |

В коде сейчас включена только первая строка (`sync-all-users`): остальные появятся в фазах
5–7 и будут добавляться в тот же `beat_schedule`.

### 6.5 Мост sync/async

Celery-задачи синхронные, приложение — асинхронное. Правило:

```python
# bot/tasks/base.py
def run_async(coro):
    return asyncio.run(coro)          # один event loop на задачу
```

Внутри задачи:

```python
@celery_app.task(bind=True, ...)
def sync_user_manual(self, user_id: int) -> None:
    run_async(_sync_user_manual(user_id))
```

В `_sync_user_manual` создаётся **своя** сессия, а не глобальный `engine` из
[bot/database/database.py](../bot/database/database.py):

```python
@asynccontextmanager
async def task_session():
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with get_sessionmaker(engine)() as session:
            yield session
    finally:
        await engine.dispose()
```

Причины: asyncpg-соединения привязаны к event loop, а `asyncio.run` создаёт новый loop
на каждую задачу; `NullPool` + `dispose()` исключают переиспользование «чужого» соединения.
Существующий `get_engine()` с `pool_size=0` даёт **QueuePool без ограничения размера**
(проверено на SQLAlchemy 2.0), а не `NullPool`, поэтому для задач нужен явный `poolclass`.
Глобальный `engine` остаётся только для процесса бота.

Telegram из воркера:

```python
async with Bot(settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=HTML)) as bot:
    await bot.send_message(chat_id, text)
```

`Bot` создаётся и закрывается внутри задачи — держать глобальный инстанс нельзя
(соединения aiohttp снова привязаны к loop).

### 6.6 Идемпотентность и повторы

- `acks_late=True` означает возможный повторный запуск после падения воркера → все задачи
  обязаны быть идемпотентными.
- `sync_user_*` берут `sync:lock:{user_id}` (SET NX EX 300); не взяли — задача выходит без
  ошибки, в лог `sync skipped: locked`.
- `sync_all_users` берёт батч-лок `sync:all:lock` (TTL 3600, снимается по завершении): второй
  прогон выходит `{"status": "skipped", "reason": "locked"}`. Задача запускается с
  `expires=3600`, `soft_time_limit=1800`, `time_limit=1900` — глобальные 300/250 с рассчитаны
  на одного пользователя. Внутри батча per-user `sync:lock` берётся на время дифа участника и
  сразу снимается, поэтому ручная синхронизация этого пользователя не ждёт TTL.
- Вставка оценок — `INSERT ... ON CONFLICT (user_id, journal_id, date, hour_number) DO UPDATE`
  (после миграции §9).
- Уведомления дедуплицируются `notify:sent:{user_id}:{lesson_key}` (SET NX EX 7 дней);
  маркер ставится до отправки и удаляется, если отправка не удалась.
- Ночная очередь читается и очищается одной транзакцией: повторный запуск
  `send_night_batch` (acks_late) не отправляет тот же список дважды. Если отправка не
  удалась, список возвращается в Redis, а задача ретраится.
- `notify:night:scheduled:{user_id}` (SET NX) не даёт поставить вторую утреннюю задачу
  при повторной синхронизации; ключ снимается после успешной отправки.
- Ошибки делятся на `RetryableError` (сеть, 5xx, 429) и `PermanentError` (неверные данные,
  схема): первые — `self.retry`, вторые — лог, `sync_logs.status=failed`, уведомление админу.
  Блокировка бота (`TelegramForbiddenError`) — не ошибка: `notification_enabled=False`,
  маркеры снимаются, очередь и другие пользователи не страдают.

---

## 7. Потоки

### 7.1 Авторизация

```
/start → inline «Войти» → FSM: логин → пароль
   → AuthService.authorize(login, password)
        fingerprint → POST tokenauth → accessToken, expiresIn
        GET tokenauth(Bearer) → user{userID, groupID, group, fio}
        Fernet → users.edu_login_encrypted / edu_password_encrypted
        Redis auth:token:{user_id} (TTL = expiresIn*60 − 300)
   → сообщение «Авторизация успешна»
   → sync_user_after_login.delay(user_id)
   → главное меню с реальной последней оценкой
```

Сообщения бота редактируются на месте (`edit_bot_message`), сообщения пользователя удаляются —
секретный ввод не остаётся в чате. Отмена — inline-кнопкой: reply-клавиатуру нельзя прикрепить
к `edit_message_text`, поэтому в шагах авторизации используется `get_cancel_inline_keyboard()`.
Неверные учётные данные, недоступность edu-tpi и истечение токена различаются в ответах
пользователю (см. §9).

Весь диалог входа живёт в **одном сообщении**: «Войти» правит меню на месте, «Отмена»
возвращает меню в то же сообщение, успешный вход заменяет его на «Авторизация успешна» +
главное меню. Новые сообщения на каждом шаге не создаются — иначе в чате копились копии меню.

При сбое edu-tpi показывается `get_auth_error_keyboard()` из трёх кнопок: «Ещё раз» (повтор
того же запроса с теми же данными), «Сменить данные» (тот же коллбек `auth_start`, что у
«Войти») и «Отмена». Чтобы повтор не требовал вводить пароль заново, после ввода он кладётся
в FSM-состояние как `password_enc` — Fernet-токен, как и в БД; открытый пароль в Redis не
попадает. Токен удаляется после неверного пароля, отмены и успешного входа.

### 7.2 Ручная синхронизация

```
кнопка «Обновить»/ /sync
   → sync_user_manual.delay(user_id)          (400 мс)
   → «⏳ Синхронизация запущена…»
worker:
   lock → AuthService.get_token(user_id)      (Redis или переавторизация)
   → list_journals(оба семестра)
   → для каждого журнала: get_journal через кеш группы/подгруппы
   → diff с БД → upsert grades → sync_logs
   → новые оценки? → NotificationService
   → сообщение «📊 Синхронизировано: N новых оценок» / «Изменений нет»
```

### 7.3 Плановая синхронизация групп

```
beat 6ч → sync_all_users (очередь maintenance, батч-лок sync:all:lock)
   load_sync_candidates: is_authenticated, group_id и edu_user_id not null
   group_by(group_id)
   для группы:
       unprocessed = {edu_user_id участников}
       журналы = list_journals(токен первого участника; при 401 — следующего)  # один раз
       while unprocessed:
           лидер = минимальный edu_user_id из unprocessed
           для каждого журнала:
               payload = JournalCache.get_journal(токен лидера)   # 1 запрос на группу/подгруппу
               для каждого участника группы из payload (кроме уже обработанных в этой паре):
                   sync:lock(user) → apply_payload (диф + upsert + student_journal)
                   → sync_logs(sync_type=auto) → send_grade_notification.delay(новые оценки)
               unprocessed -= {студенты из payload}
           unprocessed не уменьшился → warning, оставшиеся failed, выход из группы
```

`apply_payload` — тот же диф, что у ручной синхронизации (`GradeSyncService`): он ищет
студента в `payload` по `edu_user_id`, а при расхождении id — по ФИО (на проде `userID`
из `tokenauth` бывает отрицательным и не совпадает с `journalData.id`). `unprocessed`
отвечает только за то, нужен ли ещё один проход с токеном другой подгруппы; сам диф идёт
по **всем** журналам группы, а набор `applied` не даёт обработать пару «участник + журнал»
дважды.

Ошибки: `EduEmptyJournalError` — пропуск (чужая подгруппа, архивный журнал),
`EduAuthError` одного участника — он `failed`, остальные продолжают, `ParseError` журнала —
ошибка журнала, `EduUnavailableError`/`EduRateLimitError` — ошибка группы/прогона. Если
список журналов не получен ни для одной группы, задача бросает `RetryableError` и Celery
повторяет батч (он идемпотентен). Один `EduTpiClient`, `JournalCache`, сессия и Redis на
весь прогон, `TokenService` — на участника. Уведомления из батча — только
`send_grade_notification.delay` (сводок и счётчиков нет), после коммита журнала.

Оппортунистическая часть (задача 4.2, `SYNC_OPPORTUNISTIC=false` по умолчанию): после дифа
текущего пользователя ручная синхронизация применяет тот же `payload` к другим участникам
группы, которые в нём есть, под их `sync:lock` (занят — пропуск). Уведомление уходит только
если по этому журналу у участника уже были оценки: первичный импорт молчит. В
`sync_user_after_login` оппортунистическая часть не включается никогда.

### 7.4 Уведомления

```
sync_user_manual: новые уроки (NewGradeNotice) → notify_new_grades(user_id, notices, manual=True)
sync_user_after_login: уведомлений нет (первичный импорт)

notify_new_grades → NotificationService.decide(notices, force_immediate=manual)
   notification_enabled? нет → метрика skipped, выходим
   маркеры notify:sent:* уже стоят? → метрика skipped, выходим
   ночь 22:00–07:59 МСК и morning_notification_enabled (и это не ручная синхронизация)?
       да  → mark → RPUSH notifications:night:{user_id}, EXPIRE до утра + 2 ч
              notify:night:scheduled:{user_id} NX → send_night_batch.apply_async(eta=утро)
       нет → mark → send_telegram_message (одно сообщение на всю пачку)
   TelegramForbidden → notification_enabled=False, маркеры снять, метрика blocked
   TelegramRetryAfter → sleep(retry_after ≤ 60 с), один повтор; снова 429 → RetryableError
   прочее → маркеры снять, метрика failed, RetryableError (задача повторится)

send_night_batch: pop_night() (LRANGE+DEL) → одно сообщение списком → clear schedule key
   ошибка отправки → список вернуть в Redis и RetryableError (повтор не потеряет данные)
```

Ручная синхронизация ночью отвечает сразу: пользователь ждёт ответ на своё действие, и
ночная политика к ней не применяется. Одна оценка — одно сообщение, много — список
(дата, предмет с пометкой «Л»/«П», значение); «пинг-понгов» по одной оценке нет.
Фоновая (групповая) синхронизация молчит, кроме новых оценок: после коммита журнала она
ставит `send_grade_notification.delay(user_id, notices)` (то есть `manual=False`, ночью —
в ночную очередь) и не шлёт ни сводок, ни счётчиков.
Метрики: `notifications_total{kind,status}` и `sync_new_grades{type}` в
[bot/core/metrics.py](../bot/core/metrics.py) (процесс воркера, HTTP-экспорт — фаза 8).

### 7.5 Режим ожидания (фаза 5, реализовано 27.11.2026)

```
кнопка «Режим ожидания» → watch_mode_expires_at = now()+30 мин, SADD watch_mode:users
beat 5 мин → sync_watch_mode_users → только эти пользователи, priority 5
beat час (:10) → cleanup_expired_watch_mode → сброс истёкших, SREM, сверка индекса с БД
интерфейс показывает остаток времени, продление даёт новые 30 минут от текущего момента
```

Решения, принятые при реализации:

* источник истины — `users.watch_mode_expires_at`; множество `watch_mode:users` — индекс
  без TTL, который чистит задача (единственное исключение из правила TTL, §4.2);
* продление — новый период 30 минут от момента продления («не более 30 минут подряд»
  читается как «без продления — не дольше 30 минут»);
* цикл читает БД, а не множество, поэтому истёкший режим не проверяется даже при
  пропущенной уборке;
* синхронизация идёт тем же `GradeSyncService.sync_user` с `sync_type=watch_mode`:
  групповой кеш журналов даёт один HTTP-запрос на журнал за цикл независимо от числа
  студентов группы в режиме;
* уведомления — существующий путь `send_grade_notification` с `immediate=True`: в режиме
  ожидания сообщение уходит сразу и ночью, потому что ускоренную проверку включил сам
  пользователь; дедупликация `notify:sent:*` не меняется (решение 27.11.2026);
* настройки: `WATCH_MODE_MINUTES`, `WATCH_MODE_TICK_MINUTES`, `WATCH_MODE_CLEANUP_MINUTE`;
* метрики: `sync_new_grades{type="watch"}`, `active_users{watch_mode="true"}`.

---

## 8. Ключ урока и диф оценок

Проблема текущей схемы: `grades.id` объявлен первичным ключом и по исходному проекту равен
`dateID` занятия из edu-tpi. `dateID` один и тот же для всех студентов группы, поэтому
вторая запись по тому же занятию другого пользователя нарушит PK. Синхронизация на этой схеме
работать не может.

Целевая схема реализована миграцией `2026_11_21_grades_v2` (задача 2.1):

| Изменение | Детали |
|---|---|
| `grades.id` | `BIGSERIAL` — суррогатный PK |
| `edu_lesson_id` | BIGINT — `dateID`, информационное поле |
| `hour_number` | SMALLINT — номер пары, часть ключа |
| Уникальность | `UNIQUE (user_id, journal_id, date, hour_number)` |
| Индексы | `(user_id, journal_id, date)` для экранов, `(journal_id)` для массовой синхронизации |

Диф: загружаем существующие `(date, hour_number) → value` по журналу, сравниваем с пришедшими;
новые — вставка, изменённые (преподаватель исправил оценку) — обновление с `updated_at`,
удалённые — не удаляем, а помечаем `is_deleted` только если появится требование.

Значение из `journalVal.value` приходит с хвостовыми пробелами (`"Н  "`) — **`strip()` перед
сохранением обязателен**, иначе сравнение «новое/старое» всегда истинно и уведомления
превращаются в спам.

---

## 9. Ошибки и реакция

| Ситуация | Исключение | Реакция | Пользователю |
|---|---|---|---|
| Неверный логин/пароль | `EduAuthError` | Без retry, `is_authenticated=False` | «❌ Логин или пароль неверны» |
| Токен истёк | `EduTokenExpired` | Переавторизация по сохранённым данным | — |
| 401 после переавторизации | `EduAuthError` | Сброс токена | «Войдите заново: /start» |
| `GET /api/tokenauth`: `200`, `state != 1` | `EduAuthError` | Сброс токена — данные входа отозваны | «Войдите заново: /start» |
| 5xx, таймаут | `EduUnavailableError` | Retry 3× (60/120/240 с) | «⚠️ Журнал недоступен, попробуйте позже» |
| 429 | `EduRateLimitError` | Retry с большей паузой | — |
| Изменилась схема ответа | `ParseError` | Без retry, лог + алерт админу | «⚠️ Не удалось разобрать журнал» |
| Архивный журнал: `state: -2`, `data: null` | `EduEmptyJournalError` | Пропуск журнала, без retry | — |
| Telegram: бот заблокирован | `TelegramForbidden` | `notification_enabled=False` | — |
| Telegram: 429 | `TelegramRetryAfter` | `sleep(retry_after)`, повтор | — |
| Нет `ENCRYPTION_KEY` | `ConfigError` | Падение на старте | — |

Все исключения — в `bot/core/errors.py`, иерархия от `AppError`. В логах и Sentry — без
логина, пароля и токена.

---

## 10. Безопасность

| Аспект | Решение |
|---|---|
| Учётные данные edu-tpi | Fernet (AES-128-CBC + HMAC), ключ в `ENCRYPTION_KEY`, только в `.env` |
| Ключ шифрования | Обязателен, валидируется на старте (`Fernet`); без валидного ключа бот не запускается. Случайный ключ по умолчанию убран в фазе 0 — он ломал расшифровку после рестарта |
| Пароль в чате | Сообщение пользователя удаляется сразу после чтения, пароль не логируется |
| Токен | Redis с TTL, не попадает в БД и логи |
| Rate limit бота | Redis-счётчик на пользователя, 30 апдейтов/мин (+ текущий TTLCache как быстрый слой) |
| Админка | Flask-Security, пароль хэшируется, доступ по роли `superuser`, дефолтный пароль менять при первом запуске |
| Секреты в репозитории | `.env` в `.gitignore`; в `.env.example` только плейсхолдеры |
| Логи | `sync_logs.message` не содержит ПДн; Sentry `send_default_pii=False` |
| Ротация ключа | Не в MVP: смена `ENCRYPTION_KEY` потребует повторного входа всех пользователей |

---

## 11. Наблюдаемость

**Метрики.** HTTP-метрики aiohttp-сервера webhook (`tgbot_requests`, `tgbot_responses`,
`tgbot_request_duration`, `tgbot_requests_in_progress`, `tgbot_exceptions`) и эндпоинт
`/metrics` живут в [bot/middlewares/prometheus.py](../bot/middlewares/prometheus.py).
Метрики задач — в [bot/tasks/base.py](../bot/tasks/base.py), бизнес-метрики — в
[bot/core/metrics.py](../bot/core/metrics.py):

| Метрика | Тип | Метки | Где считается |
|---|---|---|---|
| `notifications_total` | Counter | `kind` (immediate/night), `status` (sent/skipped/failed/blocked) | `bot/tasks/notify.py` |
| `sync_new_grades` | Counter | `type` (manual/auto) | `bot/tasks/sync.py` |
| `sync_batch_users` | Counter | `status` (success/failed/skipped) | `bot/tasks/sync.py` |
| `sync_batch_duration_seconds` | Histogram | — | `bot/tasks/sync.py` |
| `celery_tasks`, `celery_task_failures`, `celery_task_duration_seconds` | Counter/Histogram | `task`, `status` | `bot/tasks/base.py` |

Метрики задач и бизнес-метрики считаются в процессе воркера. С W2 они экспортируются по
HTTP: сервис `worker` работает в multiprocess-режиме `prometheus_client`
(`PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus-multiproc`, tmpfs), а главный процесс воркера
поднимает HTTP-сервер на `WORKER_METRICS_PORT` (по умолчанию `9108`, только сеть
`monitoring`, наружу не публикуется) с `/metrics` и `/healthz`
([bot/core/worker_metrics.py](../bot/core/worker_metrics.py)). Каталог mmap-файлов чистится
до старта Celery, `mark_process_dead` вызывается на завершении дочернего процесса.
Без `PROMETHEUS_MULTIPROC_DIR` (бот, тесты, локальный запуск) сервер не поднимается, и
метрики читаются из обычного `REGISTRY`.

`Counter` с именем `sync_new_grades` экспонируется как `sync_new_grades_total`,
`sync_batch_users` — как `sync_batch_users_total` (поведение prometheus-client).

Алерт админам (задача 4.4) — не метрика, а следствие метрик прогона: если пользователей в
батче не меньше `SYNC_ALERT_MIN_USERS` и доля `failed` не меньше
`SYNC_ALERT_FAILURE_RATIO`, `sync_all_users` отправляет **одно** сообщение каждому админу
(`load_admin_ids` без кеша, `send_telegram_message` из воркера). Текст — gettext-ключ
`sync.batch_alert` с числами `{users}`, `{failed}`, `{groups}`; имён и названий журналов в
нём нет. Ошибка Telegram при алерте батч не роняет.

Целевой набор:

| Метрика | Тип | Метки |
|---|---|---|
| `bot_updates_total` | Counter | `type` (message/callback) |
| `bot_commands_total` | Counter | `command` |
| `bot_handler_duration_seconds` | Histogram | `handler` |
| `sync_total` | Counter | `type` (manual/auto/watch), `status` |
| `sync_duration_seconds` | Histogram | `type` |
| `sync_new_grades` | Counter | `type` |
| `notifications_total` | Counter | `kind` (immediate/night/digest), `status` |
| `active_users` | Gauge | `is_authenticated`, `watch_mode` |
| `edu_requests_total` | Counter | `endpoint`, `status` |

Ограничение: у бота `/metrics` поднимается в обоих режимах — в webhook его обслуживает
aiohttp-приложение webhook, в polling — отдельный сервер из [bot/core/health.py](../bot/core/health.py).

**Celery**: контейнер `celery-exporter` (`danihodovic/celery-exporter`) читает брокер и
отдаёт `celery_queue_length{queue_name}`, `celery_active_consumer_count`,
`celery_worker_tasks_active`, `celery_task_sent_total`, `celery_task_received_total`,
`celery_task_started_total`, `celery_task_succeeded_total`, `celery_task_failed_total`,
`celery_task_retried_total`, `celery_task_runtime`. Prometheus job'ы `worker` (`worker:9108`)
и `celery-exporter` (`celery-exporter:9808`) описаны в
[configs/prometheus/prometheus.yml](../configs/prometheus/prometheus.yml); дашборд
`Celery / sync` (`uid: celery-sync`) — в
[configs/grafana/celery-sync.json](../configs/grafana/celery-sync.json): очередь, активные
задачи, успех/ошибка/повтор задач, `sync_batch_users_total` по статусу,
`sync_batch_duration_seconds` (p95/avg), `sync_new_grades_total`, `notifications_total`.
Flower не добавляется: для ручного разбора достаточно `celery inspect`.

**Логи**: loguru, `logs/telegram_bot.log` с ротацией; в воркере — файл на процесс
`logs/worker-<pid>.log` (W2.3): у prefork-пула каждый процесс пишет свой файл, поэтому
ротация не конфликтует. Уровни: `INFO` для бизнес-событий (`sync finished user=… new=…`),
`WARNING` для деградации, `ERROR` для постоянных ошибок, `DEBUG` — тела ответов API только
при `DEBUG=true`.

**Sentry**: в боте через loguru-интеграцию, в воркере — `CeleryIntegration`;
`environment` из env, `release` из git sha.

**Healthchecks**: `pgbouncer` и `redis` — есть; `worker` — HTTP `/healthz` на `:9108`
(`timeout: 5s`, `interval: 30s`, `start_period: 60s`), Celery CLI не запускается;
`bot` — HTTP `/healthz` на `WEBHOOK_PORT`.

---

## 12. Принятые решения

| № | Решение | Альтернативы | Почему так |
|---|---|---|---|
| A1 | Celery + Redis worker, а не asyncio-планировщик в боте | APScheduler в процессе | Выбран владельцем проекта: ретраи, отдельные очереди, изоляция тяжёлых задач; при 300 пользователях запас по масштабированию |
| A2 | Групповой кеш журналов + алгоритм подгрупп | Запрос на каждого студента | 1 запрос вместо 25; иначе бан по лимитам edu-tpi |
| A3 | `asyncio.run` внутри задачи + своя сессия и `Bot` на задачу | Синхронный SQLAlchemy в воркере | Один драйвер (asyncpg) и одна модель на бота и воркер, без дублирования |
| A4 | Суррогатный PK `grades` + `UNIQUE(user_id, journal_id, date, hour_number)` | PK = `dateID` | `dateID` общий для всех студентов и не может быть PK |
| A5 | Разделение Redis по базам: 0 — данные, 1 — брокер, 2 — результаты | Одна база | Брокер не вытесняет кеш, `FLUSHDB` для кеша безопасен |
| A6 | Fernet для учётных данных, ключ только в env | Хэш пароля | Пароль нужен в открытом виде для повторной авторизации в edu-tpi |
| A7 | gettext + `.po`/`.mo`, ru по умолчанию | JSON-словари | Уже работает, стандартный инструментарий, `n_` для отложенных строк |
| A8 | Fail-fast конфигурация | Дефолты на всё | Случайный `ENCRYPTION_KEY` и пустой `BOT_TOKEN` должны падать на старте, а не через неделю |
| A9 | `acks_late` + идемпотентность задач | `acks_early` | Не терять задачи при падении воркера; цена — возможно повторное выполнение |
| A10 | Ночные уведомления копятся в Redis до утра | Задача с `eta` на каждую оценку | Один пользователь — одно сообщение утром, меньше шума и вызовов API |
| A11 | Админка отдельными таблицами (`admin`, `role`) вне миграций | Единая схема | Меньше связности; `autogenerate` их не видит, поэтому в `migrations/env.py` они исключены через `include_object` — `alembic check` остаётся чистым |
| A12 | Метрики воркера — `prometheus_client` multiprocess + `celery-exporter`, без Flower | Flower, отдельный экспортёр, только celery-exporter | Бизнес-метрики (`sync_*`, `notifications_total`) живут в процессах воркера, celery-exporter их не видит; multiprocess отдаёт их по HTTP без нового сервиса, celery-exporter добавляет состояние Celery |
| A13 | Маппинг `edu_user_id` → id строки журнала в Redis (`journal:student:*`, 30 дней) | Колонка `users.journal_user_id` + миграция; сопоставление только по ФИО | Не меняет схему БД и работает при расхождении id; пишется только при однозначном ФИО, однофамильцы не угадываются |
| A14 | Лимиты edu-tpi — в `Settings` (`EDU_MIN_JOURNAL_INTERVAL`, `EDU_MAX_RPS`) | Константы в клиенте | Значения по умолчанию не меняются, но подбираются под нагрузку без правки кода (фаза 8) |

---

## 13. Ограничения и риски

| Риск | Влияние | Смягчение |
|---|---|---|
| edu-tpi меняет схему ответа | Оценки перестают обновляться | Валидация + `ParseError` + алерт; контрактные тесты на фикстурах |
| Бан по IP/аккаунту за частые запросы | Полная остановка синхронизации | Глобальный лимит, групповой кеш, backoff, ручное включение массовой синхронизации |
| Неофициальный API | Возможны блокировки без предупреждения | Не хранить ничего лишнего, честный disclaimer, быстрый откат |
| Один `worker` на всё | Долгая очередь в пик | Очереди по типам, увеличение concurrency, вынос `maintenance` на ночь |
| `acks_late` + дубликаты задач | Двойные уведомления | Дедуп `notify:sent:*`, upsert оценок, lock на пользователя |
| Пароли в БД | Утечка БД = утечка паролей | Fernet; ключ хранится отдельно от бэкапа БД, оба — вне git |
| Админка с дефолтным паролем | Захват панели | Принудительная смена при первом входе (задача фазы 8) |
| `ENCRYPTION_KEY` потерян | Все пароли нерасшифровываемы | Ключ в бэкапе, документированная процедура восстановления (повторный вход) |

---

## 14. Что нужно изменить в коде

Полный список — [ROADMAP.md](ROADMAP.md). Архитектурно значимое:

1. **Фаза 0 — сделано.** Ключ `accessToken` и перевод `expiresIn` из минут в секунды;
   обязательный `ENCRYPTION_KEY` и `encryption.py`; кеш `is_authorized`; удаление
   `journals.py`/`sync_logs.py` и reply-клавиатуры; `uvloop` только на Linux; каркас тестов
   и 40 unit-тестов.
2. **Фаза 1 — сделано.** `celery_app.py`, `tasks/`, сервисы в compose, мост sync/async,
   `/healthz`.
3. **Фаза 2 — сделано.** Слияние `api_client` и `journal_parser` в `integrations/edu_tpi.py`;
   кеш журналов и подгруппы; `TokenService`; `GradeSyncService`; миграция `grades`;
   `/sync`, `/grades`, `/logout`.
4. **Фаза 3 — сделано.** `NotificationService` (политика «день/ночь», дедупликация),
   задачи `send_grade_notification`/`send_night_batch`, ночная очередь в Redis, экран
   `/settings`, метрики `notifications_total`/`sync_new_grades` и worker-safe аналитика.
5. **Фаза 4 — сделано.** `GroupSyncService` и `sync_all_users` в очереди `maintenance` по
   расписанию beat (каждые 6 часов), батч-лок `sync:all:lock` и per-user lock со снятием
   после дифа, вынесенный `GradeSyncService.apply_payload`, оппортунистическая синхронизация
   за флагом `SYNC_OPPORTUNISTIC`, метрики `sync_batch_users`/`sync_batch_duration_seconds`
   и алерт админам при массовых сбоях.
6. **Технический долг W1–W5 — сделано (22.11.2026).** `/metrics` и `/healthz` воркера
   (multiprocess), celery-exporter и дашборд, дешёвый healthcheck, файл лога на pid,
   `alembic check` без дрейфа, маппинг `journal:student:*`, лимиты edu-tpi в настройках,
   `wcwidth` для таблиц, доставка образа и pull-бэкапы. Открытые внешние ограничения —
   ROADMAP, «Замечено вне фазы 5».

После этого код соответствует этой схеме, и документ можно перевести в статус «реализовано».
