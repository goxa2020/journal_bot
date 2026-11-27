# Quickstart: проверка режима ожидания

Пошаговая проверка того, что фича работает end-to-end. Не заменяет `tasks.md` и не
содержит кода реализации.

## Предпосылки

- Ветка `pilot/speckit-watch-mode`, `uv sync` выполнен, `.env` есть (`ENCRYPTION_KEY`,
  `TELEGRAM_BOT_TOKEN`, БД и Redis доступны).
- Пользователь в Telegram авторизован в edu-tpi (иначе проверять включение бессмысленно).
- Docker-стек поднят: `docker compose ps` — `postgres`, `redis`, `worker`, `beat` в `running`.

## Автоматические проверки

```powershell
just test                      # весь pytest, включая новые тесты режима
uv run pytest tests/unit/test_watch_mode_service.py tests/unit/test_watch_mode_tasks.py -q
just pre                       # ruff check + format --check + mypy bot/
```

Ожидаемо: зелёные, число тестов выросло относительно текущих 282.

## Сценарий руками (Telegram)

1. Открыть главное меню → «👁 Режим ожидания» (в заглушке «в разработке» его быть не должно).
2. Нажать «Включить». Ожидаемо: экран «Режим ожидания включён», остаток 30 мин, кнопки
   «Продлить»/«Выключить»/«Обновить».
3. Нажать «Обновить» через минуту: остаток должен уменьшиться, сообщения в чате не плодятся
   (экран редактируется на месте).
4. Нажать «Продлить»: остаток снова 30 мин, второго экрана в чате нет.
5. Нажать «Выключить»: экран «выключен», дальнейших проверок нет.

## Проверка состояния

```powershell
# БД: кто в режиме и до какого времени
docker compose exec -T postgres psql -U "$env:POSTGRES_USER" -d "$env:POSTGRES_DB" `
  -c "SELECT id, watch_mode_expires_at, watch_mode_last_sync_at FROM users WHERE watch_mode_expires_at IS NOT NULL;"

# Redis: индекс ожидающих
docker compose exec -T redis redis-cli SMEMBERS watch_mode:users

# История синхронизаций по режиму
docker compose exec -T postgres psql -U "$env:POSTGRES_USER" -d "$env:POSTGRES_DB" `
  -c "SELECT sync_type, status, count(*) FROM sync_logs WHERE sync_type = 'watch_mode' GROUP BY 1,2;"

# Задачи и расписание
docker compose exec -T worker celery -A bot.celery_app inspect scheduled | Select-String watch
```

Ожидаемо: строка в `users` появляется сразу после включения, `SMEMBERS` содержит этого
пользователя, `watch_mode_last_sync_at` обновляется раз в 5 минут, `sync_logs` получает
записи с `sync_type='watch_mode'`, в `beat` видны обе задачи.

## Проверка истечения (без ожидания 30 минут)

1. Временно выставить `WATCH_MODE_MINUTES=1` в `.env`, перезапустить `bot`, `worker`, `beat`.
2. Включить режим, подождать ~6 минут.
3. Ожидаемо: проверки прекратились, `watch_mode_expires_at` стал `NULL`, пользователь
   исчез из `watch_mode:users`; уведомлений о «истёкшем» режиме нет.
4. Вернуть `WATCH_MODE_MINUTES=30` и перезапустить сервисы.

## Наблюдаемость

- `/metrics` воркера (`:9108`): `sync_new_grades{type="watch"}` растёт при новых оценках,
  `active_users{watch_mode="true"}` отражает число ожидающих.
- В логе воркера одна строка на цикл: `watch cycle users=… new=… errors=…`.

## Критерии приёмки фичи

Сверять со `spec.md`: SC-001 (≤5 минут), SC-002 (не дольше 35 минут), SC-003 (нет дублей),
SC-004 (ответ ≤2 с), SC-005 (один запрос на журнал за цикл), SC-006 (нет истёкших после
уборки), SC-007 (посторонние не затронуты).
