"""Бизнес-метрики, которые считает воркер (задачи 3.5 и 4.4, docs/ARCHITECTURE.md §11).

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

#: Пользователи в прогоне `sync_all_users`: `status` — success/failed/skipped.
SYNC_BATCH_USERS = prometheus_client.Counter(
    "sync_batch_users",
    "Пользователи в прогоне массовой синхронизации по результату.",
    ["status"],
)

#: Длительность прогона `sync_all_users` в секундах.
SYNC_BATCH_DURATION = prometheus_client.Histogram(
    "sync_batch_duration_seconds",
    "Длительность прогона массовой синхронизации, секунды.",
)


def observe_notification(kind: str, status: str) -> None:
    """Увеличить `notifications_total{kind,status}` на единицу."""
    NOTIFICATIONS_TOTAL.labels(kind=kind, status=status).inc()


def observe_new_grades(sync_type: str, count: int) -> None:
    """Учесть `count` новых оценок; метка `type` — `manual` или `auto`."""
    if count > 0:
        SYNC_NEW_GRADES.labels(type=sync_type).inc(count)


def observe_batch_users(status: str, count: int) -> None:
    """Учесть `count` пользователей прогона с результатом `status`."""
    if count > 0:
        SYNC_BATCH_USERS.labels(status=status).inc(count)


def observe_batch_duration(seconds: float) -> None:
    """Записать длительность прогона в гистограмму (даже для пустого батча)."""
    SYNC_BATCH_DURATION.observe(max(seconds, 0.0))
