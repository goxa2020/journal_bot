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

## Что осталось

- [ ] вынести бэкапы PostgreSQL за пределы машины (сейчас `pgbackup` пишет в том на том же SSD,
      ротация 7 дней / 4 недели / 6 месяцев уже настроена);
- [ ] сменить пароль `george` (для консоли) и `DEFAULT_ADMIN_PASSWORD` админки;
- [ ] при желании включить мониторинг: `--profile monitoring` (образы Prometheus и Grafana
      на сервер ещё не скачаны).
