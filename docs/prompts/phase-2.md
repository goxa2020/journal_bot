# Промпт для новой сессии: полностью выполнить Фазу 2 (синхронизация и оценки)

> Скопируй всё, что ниже разделителя, в новую сессию DSH.
> Промпт самодостаточен: он не требует прошлого диалога, но опирается на документы в репозитории.
> Фазы 0 и 1 закрыты и влиты в `main`; их результат считается данным, переделывать его не нужно.

---

Ты — единственный агент в сессии. Работаешь над проектом `C:\Users\User\Projects\journal_bot`:
Telegram-бот электронного журнала edu-tpi (Python 3.12–3.13, aiogram 3.32, SQLAlchemy 2.1 async,
PostgreSQL 14, Redis 7, Celery 5, Docker Compose). Архитектура и план написаны — твоя задача
не проектировать заново, а **полностью закрыть Фазу 2 (синхронизация и оценки)** из
`docs/ROADMAP.md` §4: задачи 2.1–2.11, чтобы пользователь видел оценки из журнала и мог
обновить их вручную.

## Перед началом (обязательно)

1. Прочитай:
   - `docs/ROADMAP.md` — §1 «Текущее состояние», §4 «Фаза 2 — синхронизация и оценки» (таблица
     задач и критерии приёмки), §12 «Порядок работы и Definition of Done», §13 «Риски»;
   - `docs/ARCHITECTURE.md` — §3 (слои и правила зависимостей), §4.1 (схема PostgreSQL),
     §4.2 (ключи Redis), §5.1–5.3 (клиент edu-tpi, подгруппы, лимиты и деградация),
     §6.3 (каталог задач), §7.1–7.2 (вход и ручная синхронизация), **§8 (ключ урока и диф
     оценок — главный алгоритм фазы)**, §9 (ошибки), §10 (безопасность);
   - `docs/API.md` — целиком: эндпоинты, поля, подвохи, коды ошибок;
   - `docs/DEVELOPMENT.md` — §2–4 (запуск, две конфигурации compose, команды), §5 (миграции),
     §6 (локализация), §7 (тесты), §9 (типовые проблемы), §10 (отладка задач), §13 (бэкапы);
   - `deploy/README.md` — прод на сервере, деплой, xray-прокси;
   - код: `bot/services/api_client.py`, `bot/services/journal_parser.py`, `bot/services/grades.py`,
     `bot/services/auth.py`, `bot/services/users.py`, `bot/tasks/base.py`, `bot/tasks/service.py`,
     `bot/database/models/*.py`, `migrations/versions/` (голова), `bot/handlers/`,
     `bot/keyboards/inline/`, `bot/utils/formatters.py`.
2. Проверь состояние: `git status` (чисто), `git log --oneline -5`, `git branch --show-current`.
   Ожидается `main` на `959ae4e` или новее, CI зелёный.
3. Заведи `todo_write` по задачам 2.1–2.11 и веди его по ходу работы.

## Что уже сделано (не переделывать)

- **Фаза 1 закрыта:** Celery-приложение (`bot/celery_app.py`, `bot/celery_config.py`), очереди
  `sync`/`notify`/`maintenance` и маршрутизация по именам задач уже настроены — `bot.tasks.sync.*`
  уедет в `sync` автоматически. Сервисы `worker` и `beat` есть в compose (сейчас в базовом
  `docker-compose.yml`, без отдельного профиля).
- **`bot/tasks/base.py`** — используй как есть: `run_async`, `task_session` (свой `AsyncEngine`
  с `NullPool`), `task_redis` (свой клиент в loop задачи), `task_lock(key, ttl)` на `SET NX EX`,
  `send_telegram_message`, `BaseTask` (`autoretry_for=(RetryableError,)`, `PermanentError` не
  ретраится, метрики `celery_tasks`/`celery_task_failures`/`celery_task_duration_seconds`).
  **Импортировать `bot.core.loader` из задач нельзя** — это главная ловушка Celery + asyncio.
- **Вход работает:** FSM логин→пароль в одном сообщении, кнопки «Ещё раз»/«Сменить данные»/
  «Отмена», пароль для повтора лежит в FSM только как Fernet-токен `password_enc`.
  `handle_auth_password` уже кладёт токен в Redis `auth:token:{user_id}` (TTL = `expiresIn`·60 − 300)
  и пишет `users` (Fernet-креды, `edu_user_id`, `group_id`, `group_name`, `full_name`,
  `is_authenticated`).
- **`bot/services/grades.py`** (`GradesService`) уже используется главным меню
  (`get_last_grade`) и админкой. Не ломай `get_last_grade`; расширяй сервис, а не дублируй.
- **`/healthz` и `/metrics`** работают в polling-режиме (`bot/core/health.py`).
- **Тесты:** 64 зелёных, `ruff` (ALL) чист. `pytest-asyncio` в режиме `auto`, `fakeredis`,
  для aiohttp свой стаб `ClientSession` (`respx` мокает **только** httpx).
- **Деплой:** `docker-compose.yml` — база без портов; `docker-compose.override.yml` — локальная
  разработка; `docker-compose.prod.yml` — сервер. `deploy/deploy.ps1` отправляет на сервер
  **явный список** путей — если добавишь новый каталог, нужный в рантайме, впиши его туда.

## Состояние окружения

- `main` на `959ae4e`; 64 теста; `ruff` зелёный. Локальный venv — Python 3.12, в контейнере
  3.13: не завязывайся на синтаксис, которого нет в 3.12.
- **Прод уже живёт на сервере** `192.168.1.7` (`/srv/journal_bot`, Debian 13, доступ по ключу
  `~/.ssh/journal_server`, `george` с sudo без пароля). Бот `@poly_journal_bot` работает
  в polling, стек healthy, БД содержит реальные данные (пользователи с зашифрованными
  кредами; оценки ещё не синхронизировались).
- **Один токен = один поллер.** Нельзя запускать второго бота одновременно с продовым —
  Telegram вернёт `409 Conflict`. Для ручной проверки в Telegram: либо выкати изменения на
  сервер (`pwsh deploy/deploy.ps1`), либо останови прод-бота
  (`docker compose -f docker-compose.yml -f docker-compose.prod.yml stop bot`), проверь локально
  и верни обратно. Второй экземпляр не поднимай.
- **Telegram с сервера идёт через xray** (`xray.service`, HTTP-прокси `172.17.0.1:10809`,
  `TELEGRAM_PROXY=http://host.docker.internal:10809` в серверном `.env`). Локально на Windows
  Telegram доступен только через VPN-прокси хоста `127.0.0.1:10809`:
  - для `uv add/lock/sync` нужен `$env:HTTPS_PROXY='http://127.0.0.1:10809'`, иначе PyPI
    не резолвится;
  - при сборке с новыми зависимостями — `--build-arg HTTP_PROXY=http://host.docker.internal:10809
    --build-arg HTTPS_PROXY=http://host.docker.internal:10809`;
  - edu-tpi с сервера доступен напрямую (проверено), прокси ему не нужен.
- **Серверный DNS — публичный** (`1.1.1.1`/`8.8.8.8` в `daemon.json` и `dhcpcd.conf`): роутер
  отдавал NXDOMAIN/NODATA, из-за этого контейнеры не резолвили edu-tpi. Не «возвращай как было».
- **БД и миграции.** Голова — `217e8389fd0e`. Миграция 2.1 меняет `grades`; на сервере лежат
  реальные данные, поэтому: сначала проверь `upgrade`/`downgrade`/`upgrade` на локальной БД,
  убедись, что свежий дамп есть (`pgbackup` пишет каждые 30 минут в том), и только потом
  выкатывай (`migrator` применяет миграции при `up -d`). `docker compose down -v` не запускать.
- Если работаешь в новом worktree: `.env` и `.env.local` не в git — скопируй их из
  `C:\Users\User\Projects\journal_bot` (не печатай и не коммить). Если pre-commit падает с
  `MSYS ... NtCreateDirectoryObject ... 0xC0000022`, скопируй `.pre-commit-cache` из main.
- Тесты на этой Windows-машине медленно импортируют aiogram (~15–20 с) — это окружение,
  а не тесты.
- Секреты: не печатать значения из `.env`/`.env.local`, не коммитить их; в логах задач —
  только id, без логинов и токенов.

## Задачи Фазы 2 (в этом порядке)

### 2.1. Миграция `grades`

- Новая ревизия Alembic поверх `217e8389fd0e` (`uv run alembic revision -m "..."` внутри
  контейнера миграций, чтобы совпадали зависимости — см. DEVELOPMENT §5).
- Привести таблицу к [ARCHITECTURE §8](docs/ARCHITECTURE.md): `id` → `BIGSERIAL`
  (суррогатный PK, `autoincrement=True`), добавить `edu_lesson_id BIGINT NULL` (это `dateID`,
  только для информации) и `hour_number SMALLINT NOT NULL`;
  `UNIQUE (user_id, journal_id, date, hour_number)`; индексы `(user_id, journal_id, date)` и
  `(journal_id)`; старые `uq_user_lesson_journal` и `idx_user_lesson` удалить.
- **Сначала посмотри, есть ли в таблице строки.** Если есть — нужен backfill `hour_number`
  (из парсера его можно вывести) или явное падение с понятным сообщением: молча ставить
  `DEFAULT 0` нельзя, иначе диф склеит разные пары.
- `downgrade` обязателен и рабочий.
- Обнови модель `bot/database/models/grade.py` и все места, где `GradesService.create`
  передаёт `grade_id` (PK больше не приходит из edu-tpi).

**Критерий:** на пустой БД `alembic upgrade head` → `downgrade -1` → `upgrade head` проходит;
`pytest` зелёный; `\d grades` в psql показывает новые constraint'ы и индексы.

### 2.2. Слить `api_client` и `journal_parser` в `bot/integrations/edu_tpi.py`

- Один модуль по [ARCHITECTURE §5.1](docs/ARCHITECTURE.md): `EduTpiClient` с типизированными
  ответами (`TokenInfo`, `EduUser`, `JournalBrief`, `JournalPayload` — dataclass'ы или pydantic
  внутри `bot/integrations/models.py`), методы `get_fingerprint`, `authorize`, `get_user_info`,
  `list_journals(token, year, sem)`, `get_journal(token, journal_id)`.
- Одна `aiohttp.ClientSession` на задачу, `timeout=60`, задержка ≥ 1 с между вызовами журнала
  в рамках токена, лимит 5 req/s суммарно (Redis-счётчик).
- Исключения — в `bot/core/errors.py` от `AppError`, по таблице [ARCHITECTURE §9](docs/ARCHITECTURE.md):
  `EduAuthError`, `EduTokenExpired`, `EduUnavailableError`, `EduRateLimitError`, `ParseError`
  (+ существующие `RetryableError`/`PermanentError` остаются для Celery). Сейчас edu-ошибки
  живут в `api_client.py` и продублированы в `journal_parser.py` — это и есть предмет слияния.
- `bot/services/auth.py` и тесты перевести на новый клиент; старые модули удалить (или оставить
  тонкие шимы на одну фазу, но без второй копии логики).

**Критерий:** unit-тесты на фикстурах проверяют маппинг кодов (400/401/403 → `EduAuthError`,
429 → `EduRateLimitError`, 5xx/таймаут → `EduUnavailableError`, битая схема → `ParseError`);
тестов на сеть нет; тесты входа по-прежнему зелёные.

### 2.3. Кеш журналов и подгруппы

- `bot/integrations/journal_cache.py` по [ARCHITECTURE §5.2](docs/ARCHITECTURE.md):
  ключ `journal:{group_id}:{journal_id}` и `...:sub:{md5(sorted(student_ids))[:8]}`,
  значение `{is_subgroup, synced_at, journal_name, student_ids, grades}`, TTL 15 мин;
  `journal_legend:global` и `grade_values:global` — 30 дней.
- Студента ищем по `edu_user_id` в `student_ids` кеша; промах — запрос журнала и запись в кеш.
- Кеш читается и пишется через Redis задачи (`task_redis`), а не через `bot.core.loader`.

**Критерий:** тесты: второй вызов по тому же журналу не делает HTTP-запрос; подгруппы дают
разные ключи; в кеше лежит `student_ids`; TTL выставлен.

### 2.4. Кеш токена, переавторизация и 401

- `get_token(user_id)`: сначала Redis `auth:token:{user_id}`; нет или истёк — расшифровать
  креды из `users`, авторизоваться, положить новый токен.
- 401 при вызове журнала — сбросить `auth:token:*`, один раз переавторизоваться по сохранённым
  данным; повторный 401 — `is_authenticated=False`, пользователю «Войдите заново: /start».
- 429 — `EduRateLimitError` с паузой; 5xx/таймаут — `EduUnavailableError` (ретраит `BaseTask`).

**Критерий:** тесты с `fakeredis` и стабом клиента: попадание в кеш; промах → переавторизация;
401 → одна переавторизация; 401 дважды → `EduAuthError` и `is_authenticated=False`.

### 2.5. `GradeSyncService.sync_user`

- `bot/services/grade_sync.py`: обойти журналы обоих семестров (`list_journals`), получить
  каждый журнал через кеш 2.3, вытащить занятия студента, сравнить с БД.
- Ключ урока — `(date, hour_number)`; `value` **обязательно `strip()`** (в `journalVal.value`
  приходят хвостовые пробелы, иначе диф всегда «новое»). Новые — вставка, изменённые — обновление
  с `updated_at`, пропавшие — не удалять (ARCHITECTURE §8).
- Писать `journals` (upsert имени/преподавателя/типа), `student_journal` (M2M), `sync_logs`
  (`sync_type`, `status`, `new_grades_count`, `updated_grades_count`, `message`).
- Возвращать сводку (dataclass: сколько новых/обновлённых, по каким журналам, ошибки по журналам),
  пригодную для текста пользователю и для лога.
- Ошибка одного журнала не должна валить всю синхронизацию: собрать и вернуть, а не падать
  (кроме `EduAuthError` — он прерывает всё).

**Критерий:** тесты на фикстурах: первая синхронизация вставляет N оценок и пишет `sync_logs`;
повторная — 0 новых, 0 обновлённых, дубликатов нет; изменённое значение → `updated_grades_count=1`
и `updated_at` обновился; значение с пробелами не считается изменением.

### 2.6. Задачи `sync_user_manual` и `sync_user_after_login`

- `bot/tasks/sync.py`: обе задачи — `BaseTask`, `task_lock(sync:lock:{user_id})`, `run_async` +
  `task_session`. Маршрут в очередь `sync` уже настроен по имени задачи — не дублируй `task_routes`.
- `sync_user_manual`: по завершении отправляет пользователю сводку через `send_telegram_message`;
  «уже идёт» (lock занят) — короткое сообщение, без ошибки.
- `sync_user_after_login`: без сообщения об успехе, ошибки — в лог и `sync_logs`.
- Маппинг ошибок: `EduUnavailableError`/`EduRateLimitError` → `RetryableError`;
  `ParseError`/`EduAuthError` → `PermanentError` + сообщение пользователю
  («не удалось разобрать журнал» / «войдите заново»).

**Критерий:** eager-тесты (`task_always_eager=True`): задача возвращает сводку; при занятом
lock завершается без исключения и пишет `skipped: locked`; сообщение отправляется (замокано);
`EduUnavailableError` превращается в ретрай, `ParseError` — нет.

### 2.7. `/sync` и кнопка «Обновить»

- `bot/handlers/message/sync.py` и обработчик callback'а: поставить задачу, ответить
  «⏳ Синхронизация запущена…»; если пользователь не авторизован — предложить войти.
- Обработать «уже идёт» (задача не поставлена повторно). Кнопка «Обновить» в меню, которая
  сейчас заглушка, должна вести сюда.

**Критерий:** тест: команда ставит ровно одну задачу (`.delay` замокан); неавторизованный
пользователь получает приглашение войти, а задача не ставится; повторное нажатие не плодит
задачи.

### 2.8. Экран `/grades`

- `bot/handlers/message/grades.py` + `bot/keyboards/inline/grades.py`: список журналов,
  выбор журнала, таблица оценок, средний балл по журналу, кнопки «Назад» и «Обновить».
- Только из БД, без сетевых запросов в хендлере. Пустое состояние — «оценок пока нет,
  нажмите Обновить».
- Диалог живёт в одном сообщении (как вход в 7.1): править `edit_message_text`, не спамить.

**Критерий:** тест рендера из подготовленных строк БД; пустое состояние; кнопка «Назад»
возвращает меню; на несуществующий журнал — понятная ошибка, не трейсбек.

### 2.9. Форматирование таблицы оценок

- `bot/utils/formatters.py`: таблица шириной 86 символов, обрезка длинных названий предметов,
  легенда обозначений (`Н`, `У`, `Б`, `О`), выравнивание дат; моноширинный `<pre>` в HTML.
- Учитывай, что Telegram считает ширину посимвольно, а кириллица и эмодзи в `<pre>` ведут себя
  по-разному — проверь на длинных реальных названиях.

**Критерий:** тесты: длинное название обрезается и не рвёт таблицу; пустые значения не ломают
колонки; легенда присутствует.

### 2.10. `/logout`

- Сброс `auth:token:{user_id}`, удаление шифрованных кредов (`edu_login_encrypted`,
  `edu_password_encrypted` = NULL), `is_authenticated=False`, сообщение и главное меню
  в том же сообщении.

**Критерий:** тест: после `/logout` токена в Redis нет, креды в БД NULL, `is_authenticated=False`.

### 2.11. `journals` upsert при синхронизации

- `bot/services/journals.py`: upsert по `id` журнала (имя, преподаватель, тип) + связь
  `student_journal`; не создавать дубликаты, не затирать чужие связи.

**Критерий:** тест: две синхронизации подряд не создают дублей; изменившееся название
обновляется; M2M не теряет другие журналы пользователя.

## Ограничения

- **Только Фаза 2.** Не писать уведомления (фаза 3), расписание beat (фаза 4), режим ожидания
  (фаза 5), статистику (фаза 6), экспорт (фаза 7), Flower/celery-exporter (фаза 8).
  `beat_schedule` оставь пустым.
- **Схему БД меняет только 2.1** и только в объёме из ARCHITECTURE §8. Других миграций в фазе
  быть не должно; если понадобилась — стоп и вопрос пользователю.
- Не менять `docs/ARCHITECTURE.md` без причины: решения зафиксированы. Если решение реально
  меняется — обоснуй и обнови документ в том же коммите.
- Не переиспользовать в задачах глобальные `engine`, `sessionmaker`, `redis_client`, `Bot`.
- `task_acks_late=True` означает возможные повторы: синхронизация обязана быть идемпотентной.
- i18n: все новые пользовательские строки — через `_()`/`n_()`, обе локали (`ru`, `en`),
  затем `pybabel compile` (`just babel-compile`); `.mo` в git не попадают.
- Секреты: не печатать значения из `.env`/`.env.local`, не коммитить их; в логах — только id.
- Коммиты — Conventional Commits, один коммит на задачу или логическую пару
  (`feat(sync): add grade sync service`, `feat(grades): add grades screen`).
  Хуки через `.githooks`; **не** использовать `--no-verify`; если хук упал — разобраться.
- **Прод не ломать.** Миграции и деплой на сервер — только после зелёных проверок локально;
  перед деплоем убедись, что свежий бэкап БД есть.

## Проверка перед отчётом (Definition of Done)

1. `just pre` (или `uv run ruff check` + `ruff format --check` + pre-commit) — зелёный.
2. `uv run mypy` — зелёный.
3. `uv run pytest -q` — зелёный; старые 64 теста не сломаны, новые покрывают 2.2–2.6, 2.9–2.11.
4. Миграция: на пустой БД `upgrade head` → `downgrade -1` → `upgrade head`; повторная
   синхронизация не создаёт дубликатов.
5. Ручная проверка в Telegram (через деплой на сервер или временно остановленного прод-бота):
   вход → оценки не пустые → «Обновить» → сводка → `/grades` показывает таблицу → `/logout`.
6. Логи: в `worker.log` и `docker compose logs worker` нет трейсбеков; видно `sync_logs`.
7. `docker compose up -d` (dev, база + override) поднимается; на сервере
   `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` — healthy.
8. Обновлены `docs/ROADMAP.md` (статусы 2.1–2.11, итог фазы, готовность MVP), `README.md`
   («что работает сейчас») и, при необходимости, `ARCHITECTURE.md`/`API.md`.
9. `git status` — чисто.

## Пуш в main

После того как **все** пункты Definition of Done выполнены, изменения нужно закоммитить и
**запушить в `main`**:

```bash
git push origin main
```

Это обязательный финальный шаг фазы, отдельного разрешения спрашивать не нужно. Перед пушем:
тесты и линтеры зелёные, миграция проверена в обе стороны, на сервере после деплоя стек
healthy. Если пуш не проходит по авторизации — сообщить пользователю и остановиться, не
переписывая историю и не используя `--force`.

## Отчёт в конце

1. Что сделано по каждой задаче 2.1–2.11 (файлы, коммиты).
2. Чем проверено: команды и результат, какие тесты добавлены и что они ловят; отдельно —
   результат `alembic upgrade/downgrade`, ручной синхронизации, `/grades`, `/logout`.
3. Что не удалось проверить и почему.
4. Замеченные проблемы вне фазы 2 (не исправлять, но записать в ROADMAP/отчёт): например,
   отсутствие экспортёра метрик Celery (фаза 8), ограничения `respx` с aiohttp, поведение
   `pgbackup`, `build_key` с хвостовым двоеточием.
5. Состояние прода: что задеплоено, какие миграции применены, когда снят последний бэкап.
6. Готовность к фазе 3: что уже можно использовать (клиент, кеш, токен, `GradeSyncService`,
   `sync_logs`), что нужно знать следующему агенту.
