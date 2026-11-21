"""Бизнес-метрики, которые считает воркер (задача 3.5, docs/ARCHITECTURE.md §11).

Метрики живут в процессе воркера: HTTP-эндпоинт и celery-exporter появятся в фазе 8,
поэтому здесь только объявления счётчиков, без сервера и без зависимости от aiogram.
"""

from __future__ import annotations

import prometheus_client

#: Уведомления о новых оценках: канал (`immediate`/`night`) и результат
#: (`sent`/`skipped`/`failed`/`blocked`).
NOTIFICATIONS_TOTAL = prometheus_client.Counter(
    "notifications_total",
    "Уведомления о новых оценках по каналу доставки и результату.",
    ["kind", "status"],
)

#: Новые оценки, найденные синхронизацией: `type` — `manual` или `auto`.
SYNC_NEW_GRADES = prometheus_client.Counter(
    "sync_new_grades",
    "Новые оценки, найденные синхронизацией.",
    ["type"],
)


def observe_notification(kind: str, status: str) -> None:
    """Увеличить `notifications_total{kind,status}` на единицу."""
    NOTIFICATIONS_TOTAL.labels(kind=kind, status=status).inc()


def observe_new_grades(sync_type: str, count: int) -> None:
    """Учесть `count` новых оценок; метка `type` — `manual` или `auto`."""
    if count > 0:
        SYNC_NEW_GRADES.labels(type=sync_type).inc(count)
