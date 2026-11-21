<h1 align="center">📔 Journal Bot</h1>

<h3 align="center">
Telegram-бот с доступом к электронному журналу успеваемости edu-tpi ДГТУ
</h3>

<p align="center">
<a href="https://www.python.org/downloads"><img alt="Python" src="https://img.shields.io/github/languages/top/goxa2020/journal_bot?logo=python&logoColor=white"></a>
<a href="https://github.com/goxa2020/journal_bot/commits/main/"><img alt="Commits" src="https://img.shields.io/github/commit-activity/w/goxa2020/journal_bot?logo=conventionalcommits&logoColor=white&label=commits"></a>
<a href="https://github.com/goxa2020/journal_bot/actions/workflows/linters.yml"><img src="https://img.shields.io/github/actions/workflow/status/goxa2020/journal_bot/linters.yml?label=linters&logo=precommit&logoColor=white" alt="Linters Status"/></a>
</p>

> [!WARNING]
> **🚧 Проект в активной разработке**
>
> Готовы вход в edu-tpi, синхронизация оценок, экран `/grades`, ручное обновление и выход.
> Уведомления и экраны настроек/статистики — в работе. Бот не предназначен для публичного
> использования до готовности MVP. Актуальное состояние — [docs/ROADMAP.md](docs/ROADMAP.md).

## О проекте

Journal Bot даёт студенту в Telegram то, ради чего иначе открывают веб-журнал `edu-tpi.donstu.ru`:
оценки, посещаемость, средний балл и уведомления о новых оценках. Каждый пользователь входит
своим edu-логином; данные из журнала забираются в фоне и складываются в PostgreSQL.

### Что работает сейчас

- ✅ вход в edu-tpi внутри бота: логин → пароль → данные пользователя (`/start`);
- ✅ хранение учётных данных в зашифрованном виде (Fernet), токен в Redis с переавторизацией
  по сохранённым данным;
- ✅ синхронизация оценок из журнала: журналы обоих семестров, групповой кеш и подгруппы,
  диф по `(дата, пара)`, журналы и оценки в PostgreSQL, история в `sync_logs`;
- ✅ экран `/grades`: все журналы с непустыми записями (оценки и `Н/У/Б/О`), сортировка
  по последней записи, пометки «Л»/«П», таблица до 50 символов, средний балл, пустые состояния;
- ✅ ручное обновление: `/sync` и кнопка «Обновить» ставят задачу Celery, по завершении
  приходит сводка, повторное нажатие не плодит задачи;
- ✅ `/logout`: удаление токена и шифрованных учётных данных;
- ✅ каркас: локализация ru/en, меню, регистрация пользователей, аналитика, Sentry,
  HTTP-метрики;
- ✅ фоновая обработка: Celery 5 + Redis, очереди `sync`/`notify`/`maintenance`, сервисы
  `worker` и `beat` в compose, базовый класс задачи (повторы, lock на пользователя, логи,
  метрики), задачи `sync_user_manual` и `sync_user_after_login`;
- ✅ `/healthz` и `/metrics` у бота в обоих режимах (polling и webhook), healthcheck контейнера;
- ✅ админ-панель Flask-Admin: вход по ролям, список пользователей;
- ✅ тесты: pytest + pytest-asyncio, `fakeredis`, HTTP-стаб и фикстуры edu-tpi, 151 тест,
  job «Run tests» в CI;
- ✅ Docker Compose: бот, воркер, beat, админка, PostgreSQL, PgBouncer, Redis, миграции, бэкапы,
  Prometheus, Grafana.

### Что в плане

- ⬜ уведомления о новых оценках, в том числе ночных — с доставкой утром;
- ⬜ экран `/settings` (уведомления вкл/выкл, время утра) и `/stats`;
- ⬜ автоматическая синхронизация по расписанию, режим ожидания оценок;
- ⬜ статистика: средний балл, посещаемость, динамика;
- ⬜ экспорт в Excel, месячный дайджест, расширенная админка, Flower и метрики Celery.

Полный план с оценками и критериями приёмки — [docs/ROADMAP.md](docs/ROADMAP.md).

## Документация

| Документ | О чём |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | целевая архитектура: компоненты, данные, Celery, потоки, безопасность, принятые решения |
| [docs/ROADMAP.md](docs/ROADMAP.md) | план разработки: текущее состояние, фазы, задачи, Definition of Done |
| [docs/API.md](docs/API.md) | спецификация edu-tpi API: эндпоинты, поля, подвохи, ошибки |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | запуск, команды, миграции, локализация, тесты, отладка |
| [docs/archive/](docs/archive/README.md) | документы первой итерации (не актуальны, оставлены как история) |

## Технологии

**Бот:** Python 3.13, aiogram 3.32, SQLAlchemy 2.0 (asyncpg), Alembic, Pydantic v2, Redis (FSM, кеш),
Celery 5 + Redis (фоновые задачи), gettext для локализации, loguru, Sentry, prometheus-client.

**Данные:** PostgreSQL 14 через PgBouncer, Redis 7.

**Админка:** Flask-Admin, Flask-Security, Flask-SQLAlchemy, gunicorn.

**Инфраструктура:** Docker Compose (конфигурации dev и prod), uv, just/make, pre-commit, GitHub Actions (ruff, mypy, CodeQL,
Hadolint, Dependabot), Prometheus + Grafana, бэкапы PostgreSQL.

## Быстрый старт

1. Склонировать и создать окружение:

```bash
git clone https://github.com/goxa2020/journal_bot.git
cd journal_bot
cp .env.example .env
```

2. Заполнить в `.env` минимум `BOT_TOKEN` и `ENCRYPTION_KEY`
   (ключ: `uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
   Если VPN работает только на хосте, добавьте `TELEGRAM_PROXY=http://host.docker.internal:10809`
   (порт локального прокси VPN-клиента) — иначе контейнер не достучится до Telegram.

3. Запустить:

```bash
docker compose up -d --build
docker compose logs -f bot
```

Это конфигурация разработчика: порты, `compose watch` и живая админка. Прод-запуск на сервере —
явная пара файлов, `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
(админка только на `127.0.0.1`, лимиты памяти, мониторинг за профилем). Отличия, деплой и
обход блокировки Telegram — [deploy/README.md](deploy/README.md).

Миграции применяются автоматически сервисом `migrator`. Воркер и beat поднимаются вместе со
стеком. Админка — `http://localhost:${ADMIN_PORT}`, Prometheus — `:9090`, Grafana — `:3000`,
`/healthz` бота — `http://localhost:${WEBHOOK_PORT}/healthz`.

Локальный запуск без Docker, быстрый цикл (`just dev`, `just dev-worker`, `just watch`), миграции,
тесты и отладка фоновых задач — [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Структура репозитория

```
journal_bot/
├── bot/                # бот: handlers, services, database, locales, middlewares
├── admin/              # админ-панель Flask-Admin
├── docs/               # документация (актуальная и архив)
├── migrations/         # миграции Alembic
├── configs/            # Prometheus, Grafana
├── scripts/            # бэкапы и вспомогательные скрипты
├── docker-compose.yml  # окружение разработки и деплоя
├── justfile / Makefile # команды
└── pyproject.toml      # зависимости, настройки ruff/mypy
```

Каталог `dev/` — остаток первой итерации, содержимое переехало в `docs/`.

## Безопасность

- учётные данные edu-tpi шифруются Fernet, ключ — только в переменных окружения;
- пароль никогда не пишется в логи, Sentry и Redis;
- токен живёт только в Redis с TTL и восстанавливается повторным входом;
- ограничение частоты апдейтов на пользователя, защита от параллельных синхронизаций;
- секреты не попадают в репозиторий: `.env` в `.gitignore`, в примере — только плейсхолдеры.

## Дисклеймер

Бот неофициальный и не связан с `edu-tpi.donstu.ru` или администрацией ДГТУ. API используется
на свой риск: он не документирован и может измениться. Разработчики не гарантируют точность
отображаемых данных и сохранность учётных записей.

## Лицензия

MIT — см. [LICENSE](LICENSE).

---

<p align="center">Сделано с ❤️ для студентов ПИ ДГТУ</p>
