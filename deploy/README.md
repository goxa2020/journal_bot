# Деплой journal_bot

## Два окружения из одного набора файлов

| Файл | Кто использует | Что добавляет |
|---|---|---|
| `docker-compose.yml` | оба | сервисы, образы, healthcheck'и, сети, тома |
| `docker-compose.override.yml` | только локальная машина | порты на хост, `compose watch`, bind-mount `./admin` |
| `docker-compose.prod.yml` | только сервер | админка на `127.0.0.1`, лимиты памяти, мониторинг за профилем |

```bash
# Локально (override подхватывается сам):
docker compose up -d --build

# На сервере:
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Порты в базе не публикуются намеренно: в override списки только дополняются, «убрать» порт
наследованием нельзя.

## Что уезжает на сервер

[deploy.ps1](deploy.ps1) пакует не весь репозиторий, а явный список:

```
bot/  admin/  migrations/  configs/  alembic.ini  pyproject.toml  uv.lock
Dockerfile  .dockerignore  docker-compose.yml  docker-compose.prod.yml  deploy/xray-refresh.sh
```

Документация, тесты, `deploy/install/` (гайд установки Debian и `bootstrap.sh`) и инструменты
разработчика на сервере не нужны и туда не попадают. `docker-compose.override.yml` исключён
специально: иначе случайный `docker compose up` в `/srv/journal_bot` поднял бы dev-конфигурацию
с портами наружу. `.env` на сервере свой — он не перезаписывается никогда.

Появился каталог, нужный в рантайме, — добавьте его в `$paths` внутри `deploy.ps1`.

## Режимы доставки

| Режим | Команда | Когда |
|---|---|---|
| Сборка на сервере | `pwsh deploy/deploy.ps1` | обычный деплой, сервер резолвит `ghcr.io` |
| Код без сборки | `pwsh deploy/deploy.ps1 -NoBuild` | образ уже собран/загружен, менялись только код и конфиги |
| Готовый образ | `pwsh deploy/deploy.ps1 -ImageFile bot-image.tar.gz` | серверный BuildKit не резолвит `ghcr.io`; образ собран где угодно |
| Собрать и доставить | `pwsh deploy/deploy.ps1 -DeliverImage` | то же, но сборка и `docker save`/gzip — на машине разработчика |

`-ImageFile`/`-DeliverImage` передают архив образа (`docker save` → gzip) по scp, на сервере
выполняют `sudo docker load -i` и `docker compose … up -d --no-build`. Сеть BuildKit сервера
не участвует: базовый образ `ghcr.io/astral-sh/uv:...` уже внутри архива. `-NoBuild` не
взаимоисключается с обычным режимом по смыслу, но с `-ImageFile`/`-DeliverImage` его
указывать нельзя (скрипт завершится ошибкой).

Проверено 22.11.2026: локальная сборка → gzip 265 МБ → scp → `docker load` → `up -d
--no-build` → `bot`/`worker` healthy, второй поллер не поднимался.

## Сервер

| | |
|---|---|
| Адрес | `192.168.1.7`, Debian 13 trixie, Athlon II X4, 7.5 ГиБ, SSD 105 ГБ |
| Код | `/srv/journal_bot` |
| Пользователь | `george` (sudo без пароля), вход по ключу `~/.ssh/journal_server` |
| Админка | только localhost: `ssh -L 5000:127.0.0.1:5000 george@192.168.1.7` → <http://127.0.0.1:5000> |
| Логи | `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f bot` |
| Мониторинг | выключен; включить: `--profile monitoring` (Prometheus + Grafana) |
| Обновление | `pwsh deploy/deploy.ps1` (собирает и перезапускает) |

`.env` на сервере свой и в архив не попадает. От локального отличается тремя строками:
`USE_WEBHOOK=False`, `CELERY_WORKER_CONCURRENCY=2` (четыре prefork-процесса на четырёх старых
ядрах дерутся за CPU) и `TELEGRAM_PROXY`.

## Если сборка падает на `ghcr.io`

Демон тянет образы через `dns` из `/etc/docker/daemon.json` (1.1.1.1/8.8.8.8), а BuildKit
читает `/etc/resolv.conf`, куда dhcpcd пишет роутер `192.168.1.1`. Роутер иногда отвечает
`no such host` на `ghcr.io`, хотя `getent hosts ghcr.io` работает. Проверенный обход:

```bash
# на сервере: скачать базовый образ демоном (он резолвит через 1.1.1.1)
sudo docker pull ghcr.io/astral-sh/uv:0.5-python3.13-alpine
# затем с машины разработчика: сборка пойдёт из локального стора без сети
pwsh deploy/deploy.ps1
```

Альтернатива — везти готовый образ: `pwsh deploy/deploy.ps1 -DeliverImage` (локальная сборка →
`docker save` → gzip → `scp` → `docker load` → `up -d --no-build`). Это предпочтительный
режим, когда BuildKit сервера не резолвит `ghcr.io`: сеть сервера для сборки не нужна.
`-NoBuild` только распаковывает код и перезапускает стек без сборки.
Полный фикс — прописать в `/etc/resolv.conf` публичный DNS и не зависеть от роутера.

## Telegram: заблокирован провайдером

Проверено с сервера: TCP:443 до всех IP Telegram и `web.telegram.org` не проходят, при этом
Google, Docker Hub и GitHub открываются. Поэтому на сервере работает **xray** с VLESS+Reality,
а бот ходит в Bot API через него.

| | |
|---|---|
| Служба | `xray.service`, автозапуск, конфиг `/usr/local/etc/xray/config.json` (0600, там ключи) |
| Вход | HTTP-прокси `172.17.0.1:10809` — только docker-сети, из LAN закрыт ufw |
| В `.env` | `TELEGRAM_PROXY="http://host.docker.internal:10809"` |
| Проверка | `curl -x http://172.17.0.1:10809 -o /dev/null -w "%{http_code}\n" https://api.telegram.org/` → `302` |

Конфиг собран из подписки провайдера (формат sing-box, выдаётся по `User-Agent: Happ/2.0`).
Провайдер добавляет в него расширение `finalmask`, которого нет в обычном sing-box, поэтому
взят xray — он умеет Reality нативно, без фрагментации.

Обновить подписку (новые ноды, продление): `deploy/xray-refresh.sh` на сервере. Скрипт
проверяет конфиг через `xray -test` и перезапускает службу только если тот валиден.

## Особенности этой сети

**IPv6 отключён** на всех интерфейсах: провайдер выдаёт AAAA-записи, но маршрута нет, и Docker
падал на `network is unreachable`. Дополнительно dockerd переведён на системный резолвер
(`GODEBUG=netdns=cgo`) — Go-резолвер игнорирует `/etc/gai.conf`. Настройки персистентны и
повторяются в [install/bootstrap.sh](install/bootstrap.sh).

**ufw**: входящие запрещены, открыт только 22/tcp; из docker-подсетей разрешён 10809 (прокси).

## Проверено

- холодная перезагрузка: сервер вернулся за ~56 с, все контейнеры и xray поднялись сами;
- бот после перезагрузки стартовал без ретраев Telegram;
- дамп `pg_dump` 14 восстанавливаем (в дампе нет `transaction_timeout`, баг из ROADMAP закрыт);
- `deploy.ps1` прогнан целиком: упаковка → передача → сборка → перезапуск.

## Мониторинг

Профиль `monitoring` выключен по умолчанию. Конфиги готовы и проверены локально:

| Что | Где | Метрики |
|---|---|---|
| Prometheus | `configs/prometheus/prometheus.yml` | job `tgbot` (`bot:8080`), `worker` (`worker:9108`), `celery-exporter` (`celery-exporter:9808`) |
| Grafana | `configs/grafana/celery-sync.json` | дашборд «Celery / sync»: очередь, активные задачи, успех/ошибка/повтор, `sync_batch_*`, `sync_new_grades_total`, `notifications_total` |
| celery-exporter | compose-сервис `danihodovic/celery-exporter` | `celery_queue_length{queue_name}`, `celery_worker_tasks_active`, `celery_task_*_total` |

Включение на сервере: сначала скачать образы демоном (BuildKit их не тянет), затем поднять
профиль:

```bash
cd /srv/journal_bot
sudo docker pull prom/prometheus:v2.43.0
sudo docker pull grafana/grafana:8.5.22
sudo docker pull danihodovic/celery-exporter:latest
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile monitoring up -d
# targets: worker и celery-exporter должны быть UP
curl -s http://127.0.0.1:9090/api/v1/targets   # через SSH-туннель
```

Воркер уже в сети `monitoring`; `/metrics` воркера (`:9108`) наружу не публикуется, его
слушает только Prometheus. `celery-exporter` — в сетях `monitoring` (scrape) и `app` (Redis).
Память: ~1.1 ГиБ на Prometheus + Grafana + exporter (лимиты в `docker-compose.prod.yml`).
Мониторинг на проде **не включён** — это решение владельца, конфигурация к нему готова.

## Бэкапы вне машины

`pgbackup` пишет дампы в том на том же SSD (раз в 30 минут, глубина 7 дней / 4 недели /
6 месяцев). Имена — в UTC. Чтобы дамп существовал вне сервера, есть
[backup-pull.ps1](backup-pull.ps1):

```bash
pwsh deploy/backup-pull.ps1                  # последний дамп → ./backups, проверка gzip, UTC и МСК
pwsh deploy/backup-pull.ps1 -RestoreCheck    # + восстановление в отдельную БД bot_db_restorecheck
```

Скрипт берёт `latest`-дамп через `docker cp` во временный файл на сервере, копирует по scp,
распаковывает gzip средствами .NET (битый архив — ошибка), печатает дату в UTC и МСК и
возраст. С `-RestoreCheck` создаёт `bot_db_restorecheck` в локальном `tgbot-postgres`,
восстанавливает дамп и печатает число таблиц и пользователей — рабочая БД не трогается.
Проверено 22.11.2026: `bot_db-20261122-002956.sql.gz` (03:29 МСК), 9 таблиц, 1 пользователь.

Автоматического расписания pull и второго места хранения (S3/другой хост) нет: это решение
владельца. Пока достаточно запускать скрипт перед миграциями/деплоем и раз в месяц проверять
восстановление.

## Что осталось (внешние решения)

- [ ] сменить пароль `george` (для консоли) и `DEFAULT_ADMIN_PASSWORD` админки;
- [ ] включить `--profile monitoring` на сервере (образы скачать демоном, ~1.1 ГиБ памяти) —
      конфиги готовы, локально проверены;
- [ ] решить, нужно ли автоматическое расписание pull-бэкапа и/или S3/второй хост;
- [ ] прогнать `docker compose up -d --build` на чистой машине (в этой сессии не проверялось).
