"""Приложение Celery (docs/ARCHITECTURE.md §6.1).

Точка входа для воркера и beat:

    celery -A bot.celery_app worker -l INFO -Q sync,notify,maintenance
    celery -A bot.celery_app beat -l INFO

Импорт этого модуля не подключается к брокеру: соединение открывается только при
запуске воркера/beat или при постановке задачи (`.delay()`), поэтому приложение можно
импортировать в тестах и в скриптах.
"""

from __future__ import annotations
from typing import Any

from celery import Celery
from celery.signals import worker_process_init

from bot.celery_config import APP_NAME, CELERY_CONFIG, TASK_ROUTES

celery_app = Celery(APP_NAME, include=["bot.tasks.service"])
celery_app.config_from_object(CELERY_CONFIG, namespace=None)

# Маршрутизация: см. bot/celery_config.py (по именам задач, а не по объектам).
celery_app.conf.task_routes = TASK_ROUTES

# Расписание пустое осознанно: задачи синхронизации/уведомлений появятся в фазах 2–3,
# cleanup и сбор метрик — в фазе 8 (ARCHITECTURE §6.4). Beat в этой фазе только
# проверяется как сервис.
celery_app.conf.beat_schedule = {}


# celery не поставляет типы, поэтому декоратор сигнала для mypy нетипизированный.
@worker_process_init.connect  # type: ignore[untyped-decorator]
def _configure_task_logging(**_: Any) -> None:
    """Настроить логи задач в каждом процессе воркера (файл + stdout)."""
    from bot.tasks.base import configure_task_logging  # noqa: PLC0415 — воркер уже стартовал

    configure_task_logging()
