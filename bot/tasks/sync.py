"""Задачи синхронизации оценок (задачи 2.6, 4.1–4.4; docs/ARCHITECTURE.md §6.3).

Поодиночке (`sync_user_manual`, `sync_user_after_login`) задачи идут в очередь `sync` по
имени (`bot.tasks.sync.*`), берут `sync:lock:{user_id}` и работают со своими Redis/сессией/
клиентом внутри `run_async`. Глобальные объекты бота не используются.

Плановая групповая синхронизация `sync_all_users` смонтирована в очередь `maintenance`
(точный маршрут в `bot/celery_config.py`) и держит батч-лок `sync:all:lock`: пересекающиеся
прогоны не идут параллельно. Синхронизация идемпотентна: повторный запуск после
`acks_late` не создаёт дубликатов (`ON CONFLICT` по ключу урока и по id журнала), а
уведомления дедуплицируются маркерами `notify:sent:*`.
"""

from __future__ import annotations
import time
from typing import TYPE_CHECKING, Any

from loguru import logger

from bot.cache.redis import build_key
from bot.celery_app import celery_app
from bot.core.config import DEFAULT_LOCALE, settings
from bot.core.errors import (
    EduAuthError,
    EduRateLimitError,
    EduUnavailableError,
    ParseError,
    PermanentError,
    RetryableError,
)
from bot.core.metrics import (
    observe_batch_duration,
    observe_batch_users,
    observe_new_grades,
    set_active_watch_users,
)
from bot.database.models.sync_log import SyncType
from bot.integrations.edu_tpi import EduTpiClient
from bot.integrations.journal_cache import JournalCache
from bot.services.analytics import EventProperties, track_worker_event
from bot.services.auth import TokenService
from bot.services.grade_sync import GradeSyncService, NewGradeNotice, SyncSummary
from bot.services.group_sync import BatchSummary, GroupSyncService
from bot.services.users import load_admin_ids, load_user_sync_info
from bot.services.watch import WatchModeService
from bot.tasks.base import BaseTask, run_async, send_telegram_message, task_lock, task_redis, task_session
from bot.tasks.notify import notify_new_grades, send_grade_notification
from bot.utils.formatters import format_sync_summary
from bot.utils.misc import n_
from bot.utils.translations import translate

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

USER_MESSAGES = {
    "locked": n_("sync.already_running"),
    "auth": n_("sync.auth_required"),
    "parse": n_("sync.parse_failed"),
    "unavailable": n_("sync.unavailable"),
}

#: Текст алерта админам (задача 4.4): только числа, без имён и названий журналов.
BATCH_ALERT_MESSAGE = n_("sync.batch_alert")

#: Батч-лок: один прогон `sync_all_users` за раз (TTL — страховка от падения воркера).
SYNC_ALL_LOCK_KEY = "sync:all:lock"
BATCH_LOCK_TTL = 3600

#: `sync:lock:{user_id}` на время дифа одного пользователя в батче (задача 4.3).
USER_SYNC_LOCK_TTL = 300


def _user_lock(user_id: int) -> AbstractAsyncContextManager[bool]:
    """Per-user lock для батча и оппортунистической части; снимается после дифа."""
    return task_lock(build_key("sync:lock", user_id), ttl=USER_SYNC_LOCK_TTL, release=True)


def _edu_client(redis: Redis | None) -> EduTpiClient:
    """Клиент edu-tpi с лимитами из настроек (W1.14).

    Значения по умолчанию совпадают с константами клиента (1 req/s на журнал,
    5 req/s суммарно), поэтому поведение не меняется, но лимиты можно настроить
    через `.env` без правки кода.
    """
    return EduTpiClient(
        redis=redis,
        min_journal_interval=settings.EDU_MIN_JOURNAL_INTERVAL,
        max_requests_per_second=settings.EDU_MAX_RPS,
    )


def _schedule_notification(user_id: int, notices: Sequence[NewGradeNotice]) -> None:
    """Поставить фоновое уведомление (`manual=False`-семантика) после коммита журнала.

    Ошибка брокера логируется и не отменяет уже сохранённые оценки: при повторном
    прогоне дедупликация `notify:sent:*` не даст дублей.
    """
    try:
        send_grade_notification.delay(user_id, [notice.to_dict() for notice in notices])
    except Exception:  # noqa: BLE001 — оценки уже в БД, уведомление вторично
        logger.exception("notification scheduling failed user={}", user_id)


async def _user_language(session: AsyncSession, user_id: int) -> str | None:
    user = await load_user_sync_info(session, user_id)
    return user.language_code if user else None


async def _run_sync(
    user_id: int,
    *,
    sync_type: SyncType,
) -> tuple[SyncSummary | None, str | None, str | None]:
    """Выполнить синхронизацию; вернуть (сводка, код ошибки, язык пользователя).

    `None` вместо сводки означает, что синхронизация не состоялась: занятый lock,
    ошибка авторизации, разбора или недоступность edu-tpi.
    """
    async with task_lock(build_key("sync:lock", user_id)) as acquired:
        if not acquired:
            return None, "locked", None

        async with task_redis() as redis, task_session() as session:
            language = await _user_language(session, user_id)
            async with _edu_client(redis) as client:
                tokens = TokenService(redis=redis, session=session, user_id=user_id, client=client)
                cache = JournalCache(redis, client)
                service = GradeSyncService(
                    session=session,
                    client=client,
                    cache=cache,
                    tokens=tokens,
                    sync_type=sync_type,
                    # Оппортунистическая часть — только для ручной синхронизации: при
                    # первом входе она уведомила бы о всём импорте (задача 4.2).
                    opportunistic=settings.SYNC_OPPORTUNISTIC and sync_type is SyncType.MANUAL,
                    user_lock=_user_lock,
                    notifier=_schedule_notification,
                )
                try:
                    summary = await service.sync_user(user_id)
                except EduAuthError:
                    return None, "auth", language
                except ParseError:
                    return None, "parse", language
                except (EduUnavailableError, EduRateLimitError):
                    return None, "unavailable", language
                await _track_sync(summary, sync_type)
                return summary, None, language


def _metrics_type(sync_type: SyncType) -> str:
    """Метка `type` для `sync_new_grades`: manual, auto или watch (режим ожидания)."""
    if sync_type is SyncType.MANUAL:
        return "manual"
    if sync_type is SyncType.WATCH_MODE:
        return "watch"
    return "auto"


async def _track_sync(summary: SyncSummary, sync_type: SyncType) -> None:
    """Метрика и событие аналитики: сколько новых оценок нашла синхронизация."""
    observe_new_grades(_metrics_type(sync_type), summary.new_grades)
    await track_worker_event(
        summary.user_id,
        "Sync New Grades",
        language=summary.language_code,
        properties=EventProperties(count=summary.new_grades, kind=_metrics_type(sync_type)),
    )


def _notify(user_id: int, notices: list[NewGradeNotice]) -> dict[str, Any]:
    """Уведомить о новых оценках, не ломая уже состоявшуюся синхронизацию.

    Если Telegram недоступен, пользователь всё равно получит сводку синхронизации:
    уведомление — приятный бонус, а результат его действия — обязательство.
    """
    try:
        return run_async(notify_new_grades(user_id, notices, manual=True))
    except RetryableError:
        logger.warning("notification failed user={} — summary fallback", user_id)
        return {"status": "failed"}


def _summary_message(summary: SyncSummary, language: str | None) -> str:
    return format_sync_summary(summary, translate=lambda text: translate(language, text))


def _is_out_of_retries(task: BaseTask) -> bool:
    return int(task.request.retries) >= int(task.max_retries)


@celery_app.task(base=BaseTask, bind=True, name="bot.tasks.sync.sync_user_manual")  # type: ignore[untyped-decorator]
def sync_user_manual(self: BaseTask, user_id: int) -> dict[str, Any]:
    """Синхронизация по кнопке «Обновить»: по завершении — сводка пользователю."""
    summary, error, language = run_async(_run_sync(user_id, sync_type=SyncType.MANUAL))

    if error == "locked":
        run_async(send_telegram_message(user_id, translate(language, USER_MESSAGES["locked"])))
        return {"status": "skipped", "reason": "locked"}

    if error is not None:
        text = translate(language, USER_MESSAGES[error])
        if error == "unavailable":
            if not _is_out_of_retries(self):
                # Пока есть повторы, не шлём «недоступен»: следующая попытка может успеть.
                logger.warning("sync unavailable user={} retry={}", user_id, self.request.retries)
                raise RetryableError(text)
            run_async(send_telegram_message(user_id, text))
            return {"status": "failed", "reason": "unavailable"}

        run_async(send_telegram_message(user_id, text))
        raise PermanentError(text)

    if summary is None:  # pragma: no cover — защита от рассинхронизации веток
        message = "Синхронизация завершилась без результата"
        raise PermanentError(message)

    # Одно сообщение вместо сводки и уведомления: новые оценки уходят списком,
    # счётчик «новых N» пользователь видит только если уведомления выключены.
    outcome: dict[str, Any] = {"status": "skipped"}
    if summary.new_notices:
        outcome = _notify(user_id, summary.new_notices)

    if outcome.get("status") == "sent":
        return summary.as_dict()
    if outcome.get("status") == "blocked":
        # Бот заблокирован — сводка тоже не дойдёт, второй ошибки не создаём.
        return summary.as_dict()

    run_async(send_telegram_message(user_id, _summary_message(summary, language)))
    return summary.as_dict()


@celery_app.task(base=BaseTask, bind=True, name="bot.tasks.sync.sync_user_after_login")  # type: ignore[untyped-decorator]
def sync_user_after_login(self: BaseTask, user_id: int) -> dict[str, Any]:
    """Первая синхронизация после входа: без сообщения об успехе."""
    summary, error, language = run_async(_run_sync(user_id, sync_type=SyncType.AUTO))

    if error == "locked":
        return {"status": "skipped", "reason": "locked"}

    if error is not None:
        text = translate(language, USER_MESSAGES[error])
        logger.warning("sync after login failed user={} error={}", user_id, error)
        if error == "unavailable" and not _is_out_of_retries(self):
            raise RetryableError(text)
        if error == "unavailable":
            return {"status": "failed", "reason": "unavailable"}
        raise PermanentError(text)

    if summary is None:  # pragma: no cover
        message = "Синхронизация завершилась без результата"
        raise PermanentError(message)

    return summary.as_dict()


#: Лок цикла режима ожидания: пересекающиеся циклы не должны проверять одних и тех же
#: дважды. TTL — страховка от падения воркера, а не основной механизм.
WATCH_CYCLE_LOCK_KEY = "watch:cycle:lock"
WATCH_CYCLE_LOCK_TTL = 240


async def _sync_watch_user(user_id: int) -> tuple[int, int]:
    """Синхронизировать одного ожидающего; вернуть (новые оценки, ошибка 0/1).

    Ошибка одного пользователя не должна ронять цикл: остальные ждут своей проверки.
    """
    try:
        summary, error, _language = await _run_sync(user_id, sync_type=SyncType.WATCH_MODE)
    except Exception:  # noqa: BLE001 — цикл обязан дойти до остальных ожидающих
        logger.exception("watch sync failed user={}", user_id)
        return 0, 1

    if error is not None:
        # «locked» — ручная синхронизация уже идёт, это не ошибка режима.
        logger.warning("watch sync skipped user={} reason={}", user_id, error)
        return 0, 0 if error == "locked" else 1
    if summary is None:  # pragma: no cover — защита от рассинхронизации веток
        return 0, 1

    if summary.new_notices:
        _schedule_notification(user_id, summary.new_notices)
    return summary.new_grades, 0


async def _run_watch_cycle() -> dict[str, Any]:
    """Один цикл режима ожидания: только ожидающие, один запрос на журнал.

    Список берётся из БД (условие `watch_mode_expires_at > now()`), поэтому цикл
    корректен даже без часовой уборки: истёкших он просто не видит.
    """
    started = time.perf_counter()
    async with task_lock(WATCH_CYCLE_LOCK_KEY, ttl=WATCH_CYCLE_LOCK_TTL, release=True) as acquired:
        if not acquired:
            return {"status": "skipped", "reason": "locked", "users": 0, "new_grades": 0, "errors": 0}

        users = new_grades = errors = 0
        processed: list[int] = []
        async with task_redis() as redis, task_session() as session:
            watch = WatchModeService(session=session, redis=redis, minutes=settings.WATCH_MODE_MINUTES)
            user_ids = await watch.active_user_ids()
            for user_id in user_ids:
                users += 1
                found, failed = await _sync_watch_user(user_id)
                new_grades += found
                errors += failed
                processed.append(user_id)
            await watch.mark_synced(processed)
            set_active_watch_users(await watch.count_active())

    duration = time.perf_counter() - started
    logger.info("watch cycle users={} new={} errors={} duration={:.2f}s", users, new_grades, errors, duration)
    return {
        "status": "ok",
        "users": users,
        "new_grades": new_grades,
        "errors": errors,
        "duration_s": round(duration, 3),
    }


def _observe_batch(summary: BatchSummary) -> None:
    """Метрики прогона (задача 4.4): пользователи по статусу, длительность, оценки."""
    observe_batch_users("success", summary.success)
    observe_batch_users("failed", summary.failed)
    observe_batch_users("skipped", summary.skipped)
    observe_batch_duration(summary.duration_s)
    observe_new_grades("auto", summary.new_grades)


async def _send_batch_alert(session: AsyncSession, summary: BatchSummary) -> None:
    """Один алерт всем админам, если сбоев в прогоне слишком много (задача 4.4).

    Порог — из настроек (`SYNC_ALERT_MIN_USERS`, `SYNC_ALERT_FAILURE_RATIO`). Ошибка
    отправки логируется и не роняет батч: оценки уже сохранены, а алерт вторичен.
    """
    if summary.users < settings.SYNC_ALERT_MIN_USERS or summary.users == 0:
        return
    failure_ratio = summary.failed / summary.users
    if failure_ratio < settings.SYNC_ALERT_FAILURE_RATIO:
        return

    admin_ids = await load_admin_ids(session)
    if not admin_ids:
        logger.warning("sync batch alert: no admins failed={} users={}", summary.failed, summary.users)
        return

    text = translate(DEFAULT_LOCALE, BATCH_ALERT_MESSAGE).format(
        users=summary.users,
        failed=summary.failed,
        groups=summary.groups,
    )
    sent = 0
    for admin_id in admin_ids:
        try:
            await send_telegram_message(admin_id, text)
            sent += 1
        except Exception:  # noqa: BLE001 — алерт не должен ронять батч
            logger.exception("sync batch alert failed admin={}", admin_id)
    logger.warning(
        "sync batch alert users={} failed={} ratio={:.2f} admins={}/{}",
        summary.users,
        summary.failed,
        failure_ratio,
        sent,
        len(admin_ids),
    )


async def _run_batch() -> dict[str, Any]:
    """Один прогон групповой синхронизации: батч-лок, группы, метрики, алерт."""
    started = time.perf_counter()
    async with task_lock(SYNC_ALL_LOCK_KEY, ttl=BATCH_LOCK_TTL, release=True) as acquired:
        if not acquired:
            # Пересекающийся прогон: не ошибка, следующий по расписанию подхватит.
            return {
                "status": "skipped",
                "reason": "locked",
                "groups": 0,
                "users": 0,
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "new_grades": 0,
                "updated_grades": 0,
                "errors": [],
                "duration_s": 0.0,
            }

        async with task_redis() as redis, task_session() as session:
            async with _edu_client(redis) as client:
                service = GroupSyncService(
                    session=session,
                    client=client,
                    cache=JournalCache(redis, client),
                    redis=redis,
                    user_lock=_user_lock,
                    notifier=_schedule_notification,
                )
                summary = await service.sync_all()
            await _send_batch_alert(session, summary)

    summary.duration_s = time.perf_counter() - started
    _observe_batch(summary)
    return summary.as_dict()


# Celery 5.7.0 не поставляет типы, поэтому декоратор задачи для mypy нетипизированный.
@celery_app.task(  # type: ignore[untyped-decorator]
    base=BaseTask,
    bind=True,
    name="bot.tasks.sync.sync_all_users",
    expires=3600,
    soft_time_limit=1800,
    time_limit=1900,
)
def sync_all_users(self: BaseTask) -> dict[str, Any]:
    """Плановая синхронизация всех пользователей (очередь `maintenance`, задача 4.1).

    Лимиты больше глобальных 300/250 с: прогон на сотню пользователей не укладывается в
    бюджет одной задачи. `expires=3600` не даёт выполнить устаревший дубль из очереди.
    """
    return run_async(_run_batch())


# Celery 5.7.0 не поставляет типы, поэтому декоратор задачи для mypy нетипизированный.
@celery_app.task(  # type: ignore[untyped-decorator]
    base=BaseTask,
    bind=True,
    name="bot.tasks.sync.sync_watch_mode_users",
    expires=240,
    priority=5,
)
def sync_watch_mode_users(self: BaseTask) -> dict[str, Any]:
    """Проверка пользователей в режиме ожидания (фаза 5, задача 5.2).

    `expires` меньше шага beat (5 минут): устаревший цикл из очереди не выполняется —
    следующий всё равно придёт вовремя. Очередь `sync`: пользователь ждёт результата.
    """
    return run_async(_run_watch_cycle())
