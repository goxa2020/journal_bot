# Contract: задачи, расписание и ключи режима ожидания

## Задачи Celery

| Имя задачи | Очередь | Приоритет | Ожидаемый результат |
|---|---|---|---|
| `bot.tasks.sync.sync_watch_mode_users` | `sync` | 5 | `{"users": N, "new_grades": M, "errors": E, "duration_s": …}` |
| `bot.tasks.service.cleanup_expired_watch_mode` | `maintenance` | по умолчанию | `{"cleaned": N, "active": M}` |

Обе наследуют `BaseTask` (`bot/tasks/base.py`): ретраи, логи, метрики, `run_async` для
async-кода. `sync_watch_mode_users` — `expires=240`, `soft_time_limit`/`time_limit` в рамках
глобальных (300/250 с) не задаются.

## Расписание beat (`bot/celery_app.py`)

| Ключ | Задача | Расписание | `expires` |
|---|---|---|---|
| `sync-watch-mode-users` | `bot.tasks.sync.sync_watch_mode_users` | `crontab(minute="*/5")`, `priority=5` | 240 |
| `cleanup-expired-watch-mode` | `bot.tasks.service.cleanup_expired_watch_mode` | `crontab(minute=10)` | 3600 |

Шаг берётся из `Settings.watch_mode` (`WATCH_MODE_TICK_MINUTES`), но расписание собирается
при старте приложения: менять шаг = перезапуск beat. Существующая запись `sync-all-users`
остаётся без изменений.

## Redis

| Ключ | Тип | TTL | Операции |
|---|---|---|---|
| `watch_mode:users` | SET | нет | `SADD` при включении/продлении, `SREM` при выключении и уборке |

Ключ строится через `build_key("watch_mode:users")` (`bot/cache/redis.py`), чтобы не
дублировать формат. Другие ключи режима не вводятся.

## Контракт с `GradeSyncService`

- `sync_user(user_id, sync_type=SyncType.WATCH_MODE)` — новый необязательный параметр;
  поведение по умолчанию (`MANUAL`) сохраняется, существующие вызовы и тесты не меняются.
- Новые оценки → `send_grade_notification.delay(user_id, [notice.to_dict() …])` — тот же
  путь, что у ручной синхронизации.
- Ошибка пользователя (нет авторизации, журнал недоступен) — логируется, попадает в
  счётчик `errors`, цикл продолжается со следующим пользователем; режим **не** выключается.

## Метрики

| Метрика | Тип | Метки | Когда |
|---|---|---|---|
| `sync_new_grades` | Counter (существующая) | `type="watch"` | по числу новых оценок |
| `celery_tasks_total` | Counter (celery-exporter, фаза 8) | `task` | на каждую задачу |
| `active_users` | Gauge (существующая, если есть) | `watch_mode="true"` | после цикла и уборки |

Имена существующих метрик не переименовываются; новые метки добавляются только к
существующим счётчикам.

## Журналирование

- Один `INFO` на цикл: `watch cycle users={} new={} errors={} duration={:.2f}s`.
- Один `INFO` на включение/продление/выключение: `watch enabled user={} until={}`.
- Ошибки — `WARNING`/`ERROR` с `user_id` и типом ошибки; без ФИО, пароля, токена и тела
  ответа edu-tpi.

'## Маршрутизация

`bot.tasks.sync.sync_watch_mode_users` попадает в очередь `sync` существующим правилом
`bot.tasks.sync.*` — правка `TASK_ROUTES` не потребовалась. Уборка идёт в `maintenance`
через `*` (как и остальные служебные задачи).

## Совместимость'

- Ручная синхронизация (`sync_user_manual`) и плановая (`sync_all_users`) не меняют
  поведения; при одновременном запуске побеждает существующий member-lock, второй вызов
  возвращает «уже идёт», как сейчас.
- Пользователь без режима не получает ни новых задач, ни запросов к журналу (SC-007).
