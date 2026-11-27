"""Задачи уведомлений о новых оценках (задачи 3.2 и 3.4).

Очередь задач — `notify` (маршрут `bot.tasks.notify.*` уже настроен в
`bot/celery_config.py`). Задачи только доставляют: политику «день/ночь/ничего» решает
`NotificationService`, маркеры дедупликации и ночную очередь тоже он.

Правила (docs/ARCHITECTURE.md §6.6, §7.4, §9):

* `task_acks_late=True` → повторный запуск не должен слать то же сообщение дважды:
  днём это маркеры `notify:sent:*`, ночью — атомарное чтение и очистка списка;
* бот заблокирован (`TelegramForbiddenError`) → `notification_enabled=False`, лог, без
  бесконечных повторов; остальные пользователи и очередь не страдают;
* `TelegramRetryAfter` → ждём `retry_after` (не больше минуты) и повторяем один раз;
* прочие сетевые ошибки → `RetryableError`, маркеры снимаются, задача повторится.
"""

from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

from loguru import logger

from bot.celery_app import celery_app
from bot.core.errors import PermanentError, RetryableError
from bot.core.metrics import observe_notification
from bot.services.analytics import EventProperties, track_worker_event
from bot.services.grade_sync import NewGradeNotice
from bot.services.notifications import (
    NIGHT_TTL_MARGIN,
    NotificationDecision,
    NotificationKind,
    NotificationService,
    now,
)
from bot.tasks.base import BaseTask, run_async, send_telegram_message, task_redis, task_session
from bot.utils.formatters import format_new_grades
from bot.utils.translations import translate

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Потолок ожидания перед повтором после 429 от Telegram.
RETRY_AFTER_LIMIT_SECONDS = 60


@dataclass(slots=True)
class NotificationOutcome:
    """Что сделала задача: канал, результат и сколько оценок в сообщении."""

    kind: str
    status: str
    count: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Результат задачи Celery: только строки и числа."""
        return {"kind": self.kind, "status": self.status, "count": self.count}


def _render(notices: Sequence[NewGradeNotice], language: str | None) -> str:
    return format_new_grades(notices, translate=lambda message: translate(language, message))


async def _handle_blocked(
    service: NotificationService,
    user_id: int,
    notices: Sequence[NewGradeNotice],
    *,
    kind: str,
) -> NotificationOutcome:
    """Пользователь заблокировал бота: выключить уведомления, маркеры снять."""
    await service.unmark(notices)
    try:
        await service.disable_notifications()
    except Exception:  # noqa: BLE001 — блокировка важнее записи в БД, но очередь не валим
        logger.exception("notification disable failed user={}", user_id)
    observe_notification(kind, "blocked")
    logger.warning("notification blocked user={} kind={}", user_id, kind)
    return NotificationOutcome(kind=kind, status="blocked")


async def _handle_failed(
    service: NotificationService,
    user_id: int,
    notices: Sequence[NewGradeNotice],
    *,
    kind: str,
    error: BaseException,
) -> NoReturn:
    """Отправка не удалась: снять маркеры, чтобы повтор снова увидел оценки."""
    await service.unmark(notices)
    observe_notification(kind, "failed")
    # В лог — только тип ошибки: текст оценки и название журнала там не нужны.
    logger.warning("notification failed user={} kind={} error={}", user_id, kind, type(error).__name__)
    message = "Не удалось отправить уведомление о новых оценках"
    raise RetryableError(message) from error


async def _deliver(
    service: NotificationService,
    user_id: int,
    notices: Sequence[NewGradeNotice],
    *,
    kind: str,
    language: str | None,
) -> NotificationOutcome:
    """Отправить пачку одним сообщением, классифицируя ошибки Telegram."""
    # aiogram импортируется лениво (как в `send_telegram_message`): воркер не платит
    # за него на старте, а исключения нужны только в момент отправки.
    from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter  # noqa: PLC0415

    text = _render(notices, language)
    await service.mark(notices)

    try:
        try:
            await send_telegram_message(user_id, text)
        except TelegramRetryAfter as exc:
            wait = min(max(int(exc.retry_after), 0), RETRY_AFTER_LIMIT_SECONDS)
            logger.warning("telegram retry_after user={} kind={} wait={}", user_id, kind, wait)
            await asyncio.sleep(max(wait, 1))
            await send_telegram_message(user_id, text)
    except TelegramForbiddenError:
        return await _handle_blocked(service, user_id, notices, kind=kind)
    except Exception as exc:  # noqa: BLE001 — сеть, 5xx и второй 429 одинаково временные
        await _handle_failed(service, user_id, notices, kind=kind, error=exc)

    observe_notification(kind, "sent")
    logger.info("notification sent user={} kind={} count={}", user_id, kind, len(notices))
    return NotificationOutcome(kind=kind, status="sent", count=len(notices))


async def _queue_night(
    service: NotificationService,
    user_id: int,
    decision: NotificationDecision,
) -> NotificationOutcome:
    """Положить оценки в ночную очередь и поставить одну задачу на утро."""
    expires_at = decision.night_expires_at or now() + NIGHT_TTL_MARGIN
    eta = decision.morning_at or now()

    await service.mark(decision.notices)
    pushed = await service.push_night(decision.notices, expires_at=expires_at)

    if await service.claim_night_schedule(expires_at=expires_at):
        try:
            send_night_batch.apply_async(args=[user_id], eta=eta)
        except Exception as exc:
            await service.release_night_schedule()
            await service.unmark(decision.notices)
            logger.warning("night batch schedule failed user={}", user_id)
            message = "Не удалось поставить ночную сводку в очередь"
            raise RetryableError(message) from exc

    logger.info("notification queued user={} kind=night count={}", user_id, pushed)
    return NotificationOutcome(kind="night", status="queued", count=pushed)


async def notify_new_grades(
    user_id: int,
    notices: Sequence[NewGradeNotice],
    *,
    manual: bool = False,
) -> dict[str, Any]:
    """Политика + доставка: сразу, в ночную очередь или ничего.

    `manual=True` — ручная синхронизация: пользователь ждёт ответ, поэтому даже ночью
    сообщение уходит сразу. Эту же функцию вызывает `send_grade_notification`, когда
    уведомления появятся у фоновой синхронизации (фаза 4).
    """
    if not notices:
        return NotificationOutcome(kind="none", status="skipped").as_dict()

    async with task_redis() as redis, task_session() as session:
        service = NotificationService(redis=redis, session=session, user_id=user_id)
        decision = await service.decide(notices, force_immediate=manual)

        if decision.kind is NotificationKind.NONE:
            observe_notification("immediate", "skipped")
            return NotificationOutcome(kind="none", status="skipped").as_dict()

        if decision.kind is NotificationKind.NIGHT:
            return (await _queue_night(service, user_id, decision)).as_dict()

        outcome = await _deliver(
            service,
            user_id,
            decision.notices,
            kind="immediate",
            language=decision.language_code,
        )
        if outcome.status == "sent":
            await track_worker_event(
                user_id,
                "New Grade",
                language=decision.language_code,
                properties=EventProperties(count=len(decision.notices), kind="immediate"),
            )
        return outcome.as_dict()


async def _send_night_batch(user_id: int) -> dict[str, Any]:
    """Отправить накопленный ночной список одним сообщением."""
    async with task_redis() as redis, task_session() as session:
        service = NotificationService(redis=redis, session=session, user_id=user_id)
        settings = await service.load_settings()
        notices = await service.pop_night()

        if not notices:
            await service.clear_night_schedule()
            observe_notification("night", "skipped")
            logger.info("night batch skipped user={} reason=empty", user_id)
            return NotificationOutcome(kind="night", status="skipped").as_dict()

        if settings is None or not settings.enabled:
            await service.clear_night_schedule()
            observe_notification("night", "skipped")
            logger.info("night batch skipped user={} reason=disabled", user_id)
            return NotificationOutcome(kind="night", status="skipped").as_dict()

        try:
            outcome = await _deliver(
                service,
                user_id,
                notices,
                kind="night",
                language=settings.language_code,
            )
        except RetryableError:
            # Список уже очищен: вернуть его, иначе повтор задачи нечего отправлять.
            await service.push_night(notices, expires_at=now() + NIGHT_TTL_MARGIN)
            raise

        await service.clear_night_schedule()
        if outcome.status == "sent":
            await track_worker_event(
                user_id,
                "New Grade",
                language=settings.language_code,
                properties=EventProperties(count=len(notices), kind="night"),
            )
        return outcome.as_dict()


def _parse_notices(payload: Sequence[dict[str, Any]]) -> list[NewGradeNotice]:
    """Разобрать JSON-записи из аргументов задачи; битые — постоянная ошибка."""
    try:
        return [NewGradeNotice.from_dict(item) for item in payload]
    except (KeyError, TypeError, ValueError) as exc:
        message = "Некорректные данные уведомления в аргументах задачи"
        raise PermanentError(message) from exc


# celery не поставляет типы, поэтому декоратор задачи для mypy нетипизированный.
@celery_app.task(base=BaseTask, bind=True, name="bot.tasks.notify.send_grade_notification")  # type: ignore[untyped-decorator]
def send_grade_notification(
    self: BaseTask,
    user_id: int,
    notices: list[dict[str, Any]],
    immediate: bool = False,
) -> dict[str, Any]:
    """Немедленное уведомление о новых оценках (вход для фоновой синхронизации).

    `immediate=True` — режим ожидания (фаза 5): пользователь включил проверку сам и
    ждёт оценку сейчас, поэтому политика «ночь/утро» не применяется и сообщение уходит
    сразу, как у ручной синхронизации. Дедупликация `notify:sent:*` действует всегда.
    """
    return run_async(notify_new_grades(user_id, _parse_notices(notices), manual=immediate))


@celery_app.task(base=BaseTask, bind=True, name="bot.tasks.notify.send_night_batch")  # type: ignore[untyped-decorator]
def send_night_batch(self: BaseTask, user_id: int) -> dict[str, Any]:
    """Утренняя сводка: один список, поставленный на `eta` ночной задачей."""
    return run_async(_send_night_batch(user_id))
