---
description: "Task list for watch mode (фаза 5)"
---

# Tasks: Режим ожидания оценок

**Input**: Design documents from `/specs/001-watch-mode/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: включены — принцип II конституции и ROADMAP 5.4 требуют тест на новую логику.

**Organization**: задачи сгруппированы по историям из spec.md, чтобы каждую можно было
сделать, проверить и показать отдельно.

## Format: `[ID] [P?] [Story] Description`

- **[P]** — можно делать параллельно (другие файлы, нет зависимостей)
- **[Story]** — US1 / US2 / US3 из spec.md
- Пути — от корня репозитория

## Path Conventions

Одностраничный проект: `bot/`, `tests/` в корне (см. plan.md, «Source Code»).

---

## Phase 1: Setup

- [x] T001 Добавить `WatchModeSettings` (`WATCH_MODE_MINUTES=30`, `WATCH_MODE_TICK_MINUTES=5`, `WATCH_MODE_CLEANUP_MINUTE=10`) в `bot/core/config.py` и все три переменные с комментариями в `.env.example`
- [x] T002 [P] Добавить gauge `active_users` с меткой `watch_mode` в `bot/core/metrics.py` (`data-model.md`, «Redis: watch_mode:users» — счётчик ожидающих)
- [x] T003 [P] Добавить ключи `watch.*` из `contracts/ui-contract.md` в `bot/locales/ru/LC_MESSAGES/messages.po` и `bot/locales/en/LC_MESSAGES/messages.po`

---

## Phase 2: Foundational (блокирует все истории)

- [x] T004 Создать `bot/services/watch.py`: `WatchModeService` с `state()`, `enable()`, `extend()`, `disable()`, `expire_stale()`; поля `users.watch_mode_expires_at`, `users.watch_mode_last_sync_at` по `data-model.md`; локальная `now()` для тестов; `SADD`/`SREM` для `watch_mode:users`
- [x] T005 [P] Тесты `tests/unit/test_watch_mode_service.py`: включение/продление/выключение, остаток не отрицательный, отказ без `is_authenticated`, повторное включение = продление, идемпотентная уборка
- [x] T006 Добавить необязательный `sync_type` в `GradeSyncService.sync_user` (`bot/services/grade_sync.py`), чтобы записи режима попадали в `sync_logs` с `sync_type='watch_mode'` (`data-model.md`, «SyncLog.sync_type»); вызовы по умолчанию не меняются
- [x] T007 Зарегистрировать расписание и маршруты: `sync-watch-mode-users` и `cleanup-expired-watch-mode` в `bot/celery_app.py`, маршрут `sync_watch_mode_users` в очередь `sync` в `bot/celery_config.py` (`contracts/tasks-contract.md`)

**Checkpoint**: настройки, сервис и расписание есть — истории можно делать по одной.

---

## Phase 3: User Story 1 — оценка приходит через минуты (P1)

**Goal**: включённый режим проверяет журнал каждые 5 минут и присылает новые оценки обычным
уведомлением.

**Independent Test**: включить режим через сервис, добавить оценку в стаб журнала, выполнить
задачу в eager-режиме — уведомление поставлено, повторный прогон новых не даёт.

- [x] T008 [US1] Реализовать задачу `sync_watch_mode_users` в `bot/tasks/sync.py`: выборка пользователей с `watch_mode_expires_at > now()` (`data-model.md`, «Users.watch_mode_expires_at»), `sync_user(..., sync_type=WATCH_MODE)`, отправка через `send_grade_notification.delay`, обновление `watch_mode_last_sync_at`, метрики `sync_new_grades{type="watch"}` и лог цикла (`contracts/tasks-contract.md`)
- [x] T009 [US1] Тесты `tests/unit/test_watch_mode_tasks.py`: цикл ставит уведомление о новой оценке, повторный цикл дублей не даёт, пользователь без режима не попадает в выборку, ошибка журнала не выключает режим и не роняет цикл
- [x] T010 [P] [US1] Тест «один запрос на журнал за цикл для двух студентов одной группы» в `tests/unit/test_watch_mode_tasks.py` (SC-005; опирается на групповой кеш `journal:*`)

**Checkpoint**: US1 работает и проверяется без интерфейса — это MVP.

---

## Phase 4: User Story 2 — остаток, продление, выключение (P2)

**Goal**: пользователь видит остаток, продлевает и выключает режим из бота.

**Independent Test**: нажатия на экране режима меняют состояние и не плодят сообщений.

- [x] T011 [US2] Создать клавиатуру `bot/keyboards/inline/watch.py` по `contracts/ui-contract.md` (кнопки `watch:extend`, `watch:off`, `watch:refresh`, `common:menu`)
- [x] T012 [US2] Создать хендлер `bot/handlers/callback/watch.py`: экран выключенного и активного режима, включение, продление, выключение, обновление; `callback.answer()` в `finally`; отказ без авторизации с кнопкой входа; `edit_message_text` с `reply_markup`
- [x] T013 [US2] Убрать `"watch"` из `STUB_CALLBACKS` в `bot/handlers/callback/stubs.py` и подключить роутер там же, где остальные callback-роутеры
- [x] T014 [US2] Тесты `tests/unit/test_watch_mode_handler.py`: тексты экранов для активного и выключенного режима, продление, выключение, отказ без авторизации, отсутствие заглушки «в разработке» на `watch`

**Checkpoint**: US1 и US2 вместе дают полный пользовательский сценарий.

---

## Phase 5: User Story 3 — режим не залипает и не грузит журнал (P3)

**Goal**: истёкшие режимы снимаются сами, индекс не расходится с БД, нагрузка ограничена.

**Independent Test**: искусственно состарить режим — уборка снимает его и чистит множество;
повторный запуск уборки ничего не меняет.

- [x] T015 [US3] Реализовать `cleanup_expired_watch_mode` в `bot/tasks/service.py`: обнуление `watch_mode_expires_at`/`watch_mode_last_sync_at` у истёкших (`data-model.md`, «Users.watch_mode_last_sync_at»), `SREM` из `watch_mode:users`, сверка множества с БД и восстановление индекса
- [x] T016 [US3] Обновлять gauge `active_users{watch_mode}` после цикла и уборки в `bot/tasks/service.py` и `bot/tasks/sync.py`
- [x] T017 [US3] Тесты `tests/unit/test_watch_mode_tasks.py`: истечение снимает состояние, повторная уборка идемпотентна, индекс восстанавливается после потери, пользователь без режима не затрагивается (SC-006, SC-007)

**Checkpoint**: все три истории закрыты, режим безопасен по нагрузке.

---

## Phase 6: Polish & Cross-Cutting

- [x] T018 [P] Обновить `docs/ROADMAP.md` §7 (статусы 5.1–5.4) и, если правила продления изменились, `docs/ARCHITECTURE.md` §2/§7.5
- [x] T019 [P] Прогнать `just babel-compile` и проверить, что новые строки есть в обеих локалях (`msgfmt --check`)
- [x] T020 Прогнать `just pre` (ruff, format, mypy) и `just test`; добиться зелёного по всему набору, не только по новым тестам
- [ ] T021 Выполнить `specs/001-watch-mode/quickstart.md` (ручной сценарий в Telegram и проверки БД/Redis), зафиксировать результат в отчёте

---

## Dependencies

```text
T001 ─┬─▶ T004 ─┬─▶ T008 ─▶ T009 ─┐
T002 ─┤         ├─▶ T011 ─▶ T012 ─┤
T003 ─┘         └─▶ T015 ─▶ T017 ─┤
T006 ─────────────▶ T008          ├─▶ T020 ─▶ T021
T007 ─────────────▶ T008, T015    │
T012 ─▶ T013 ─▶ T014 ─────────────┘
T018, T019 — параллельно, до T020
```

Порядок историй: **US1 (MVP) → US2 → US3**. US2 не требует US1 для тестов (состояние меняет
сервис), но пользовательский сценарий имеет смысл только вместе.

## Parallel Execution Examples

- После T004: `T005` (тесты сервиса) и `T006` (параметр `sync_type`) — разные файлы.
- Внутри US1: `T009` и `T010` — один файл, поэтому последовательно; `T008` не параллелится ни с чем.
- Финал: `T018` и `T019` вместе, затем `T020`.

## Implementation Strategy

1. **MVP = US1** (T001–T010): режим проверяет и уведомляет, управление — пока через сервис.
   Это уже закрывает главную ценность («оценка через 5 минут»).
2. **US2** (T011–T014): интерфейс; после неё фаза 5 закрыта по ROADMAP.
3. **US3** (T015–T017): устойчивость и нагрузка; обязательна до прода, потому что адресует
   риск «вечного опроса журнала».
4. **Polish** (T018–T021): документация, локали, полный прогон, ручная проверка.

## Format Validation

Все задачи: `- [ ] TNNN [P?] [US?] описание с путём`. Setup и Polish — без метки истории,
Foundational — без метки истории, US-фазы — с `[US1]`/`[US2]`/`[US3]`.

## Открытое решение (влияет на T004/T005)

Продление: «новые 30 минут от момента продления» (выбрано в `research.md` п.3) или жёсткий
потолок «30 минут суммарно». При втором варианте меняются только `WatchModeService.extend`
и один тест в T005; остальные задачи не затрагиваются.
