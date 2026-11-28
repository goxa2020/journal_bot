# Implementation Plan: Режим ожидания оценок

**Branch**: `pilot/speckit-watch-mode` | **Date**: 2026-11-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-watch-mode/spec.md`

## Summary

Пользователь на 30 минут включает ускоренную проверку журнала: beat каждые 5 минут ставит
`sync_watch_mode_users`, задача берёт из `users` тех, у кого `watch_mode_expires_at > now()`,
синхронизирует их через существующий `GradeSyncService.sync_user` (групповой кеш журналов
обеспечивает один запрос на журнал за цикл) и отправляет новые оценки по уже существующему
пути `send_grade_notification` — с той же политикой день/ночь и той же дедупликацией.
Состояние живёт в БД (`users.watch_mode_expires_at`, `watch_mode_last_sync_at`) с индексом
в Redis (`watch_mode:users`); часовая задача `cleanup_expired_watch_mode` снимает истёкшие.
Схема БД не меняется: обе колонки и `sync_logs.sync_type='watch_mode'` уже существуют.

## Technical Context

**Language/Version**: Python 3.11–3.13 (`requires-python = ">=3.11,<4.0"`, CI гоняет 3.11/3.12/3.13)

**Primary Dependencies**: aiogram 3.32, SQLAlchemy 2.x (async, asyncpg), Celery 5.7 (broker Redis),
redis 8.x, pydantic-settings 2.x, prometheus-client

**Storage**: PostgreSQL 14 — `users.watch_mode_expires_at`, `users.watch_mode_last_sync_at`,
`sync_logs.sync_type = 'watch_mode'` (все есть с миграции `2025-12-14_update_models…`, новая
миграция не нужна); Redis — множество `watch_mode:users` **без TTL** (ARCHITECTURE §4.2: это
единственное исключение, его чистит задача, а не время жизни ключа)

**Testing**: pytest 9 + pytest-asyncio 1.5 (`asyncio_mode=auto`), `fakeredis`, HTTP-стаб
`tests/fakes.py`, Celery в eager-режиме; время подменяется monkeypatch'ем локального `now()`
в сервисе (как в `bot/services/notifications.py`), `freezegun` не добавляем

**Target Platform**: Linux-контейнеры (bot, worker, beat, admin), разработка на Windows

**Project Type**: web-service — Telegram-бот + Celery worker/beat + Flask-Admin в одном репозитории

**Performance Goals**: цикл проверки ≤5 мин; ≤1 HTTP-запрос на журнал за цикл независимо от
числа студентов группы в режиме; ответ на нажатие кнопки ≤2 с; лимиты edu-tpi 1 req/s на журнал
и 5 req/s суммарно не превышаются

**Constraints**: очередь `sync` (concurrency 2), приоритет 5 (ARCHITECTURE §6.4); задача
идемпотентна и защищена блокировкой; режим не блокирует ручную синхронизацию; при ошибке
журнала режим не выключается и пользователю не уходит поток ошибок

**Scale/Scope**: ~100–200 пользователей, до ~30 журналов на студента; в режиме одновременно
ожидаются единицы пользователей (продуктовое ограничение 30 минут)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Принцип | Как выполняется | Вердикт |
|---|---|---|
| I. Слои и единственный шлюз | хендлер → `WatchModeService` → `GradeSyncService`; HTTP к edu-tpi только через `bot/integrations/edu_tpi.py` (не трогаем) | PASS |
| II. Тест — условие закрытия | тесты на истечение, отсутствие дублей, лимит 30 минут, один запрос на журнал (ROADMAP 5.4) | PASS |
| III. Конфигурация, а не константы | `WatchModeSettings`: `WATCH_MODE_MINUTES=30`, `WATCH_MODE_TICK_MINUTES=5`, `WATCH_MODE_CLEANUP_MINUTE=10` в `Settings` и `.env.example` | PASS |
| IV. Долгая операция — Celery | проверка и уборка — только задачи; хендлер ставит/снимает состояние и отвечает сразу | PASS |
| V. Локализация | новые строки (`watch.*`) в `ru` и `en` в одном коммите | PASS |
| VI. Схема только миграцией | схема **не меняется**: колонки и значение `sync_type` уже есть; миграция не создаётся | PASS |
| VII. Наблюдаемость | `sync_total{type="watch"}`, `active_users{watch_mode}` (gauge), структурный лог с `user_id`, без ФИО и токенов | PASS |

Отклонений нет — `Complexity Tracking` не заполняется.

## Project Structure

### Documentation (this feature)

```text
specs/001-watch-mode/
├── plan.md              # этот файл
├── research.md          # Phase 0: решения и альтернативы
├── data-model.md        # Phase 1: сущности, состояния, переходы
├── quickstart.md        # Phase 1: как проверить руками и тестами
├── contracts/
│   ├── ui-contract.md   # callback_data, экраны, тексты
│   └── tasks-contract.md# имена задач, очереди, beat, ключи Redis
├── checklists/requirements.md
├── spec.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
bot/
├── handlers/callback/
│   ├── watch.py                     # НОВЫЙ: включение/продление/выключение + экран режима
│   ├── stubs.py                     # ИЗМЕНИТЬ: убрать "watch" из STUB_CALLBACKS
│   └── menu.py                      # точка входа в главное меню (не меняется)
├── keyboards/inline/
│   └── watch.py                     # НОВЫЙ: клавиатура экрана режима
├── services/
│   └── watch.py                     # НОВЫЙ: WatchModeService (состояние, сроки, индекс)
├── tasks/
│   ├── sync.py                      # ИЗМЕНИТЬ: sync_watch_mode_users
│   └── service.py                   # ИЗМЕНИТЬ: cleanup_expired_watch_mode
├── celery_app.py                    # ИЗМЕНИТЬ: две записи beat_schedule
├── celery_config.py                 # ИЗМЕНИТЬ: маршрут задачи в очередь sync
├── core/
│   ├── config.py                    # ИЗМЕНИТЬ: WatchModeSettings
│   └── metrics.py                   # ИЗМЕНИТЬ: gauge active_users{watch_mode}
└── locales/{ru,en}/LC_MESSAGES/messages.po  # ИЗМЕНИТЬ: строки экрана

tests/unit/
├── test_watch_mode_service.py       # НОВЫЙ: сроки, продление, истечение, идемпотентность
├── test_watch_mode_tasks.py         # НОВЫЙ: цикл, уборка, один запрос на журнал, ошибки
└── test_watch_mode_handler.py       # НОВЫЙ: сценарии нажатий, отказ без авторизации
```

**Structure Decision**: проект одностраничный (single project) с уже сложившимися слоями
`handlers`/`services`/`tasks`/`integrations`; новых пакетов не вводим, следуем ARCHITECTURE §3.

## Post-Design Constitution Re-check

После проектирования (research/data-model/contracts) гейты перепроверены:

- новых зависимостей нет (`freezegun` не добавляется) — принцип III и «минимальный дифф» целы;
- новых таблиц и миграций нет — принцип VI не нарушен, `data-model.md` это фиксирует;
- контракт задач не переименовывает существующие метрики и задачи — принцип VII цел;
- отказ без авторизации и «ошибка не выключает режим» закреплены в контрактах — FR-011/FR-013
  не потерялись при проектировании.

Вердикт: PASS без отклонений.

## Complexity Tracking

Не заполняется: нарушений конституции нет.
