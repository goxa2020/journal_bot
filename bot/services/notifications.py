"""Политика уведомлений о новых оценках (задачи 3.1–3.4).

Сервис отвечает на вопрос «что делать с новыми оценками» и ничего не отправляет:
у него нет `Bot` и он не импортирует `bot.core.loader` — отправкой занимаются задачи
(`bot/tasks/notify.py`). Так политику можно проверить тестом без Telegram, а из
групповой синхронизации фазы 4 вызвать ту же логику.

Правила (docs/ARCHITECTURE.md §7.4):

* `notification_enabled=False` — уведомлений нет;
* ночь 22:00–07:59 (Europe/Moscow) и включённое накопление — оценки уходят в Redis
  и отправляются утром одним списком;
* иначе — сразу, одним сообщением на всю пачку;
* ключ `notify:sent:{user_id}:{lesson_key}` (7 дней) не даёт уведомить об одной оценке
  дважды; маркер ставится до отправки и снимается, если отправка не удалась.

Время берётся из :func:`now`; тесты подменяют её, зависимость `freezegun` не нужна.
"""

from __future__ import annotations
import datetime as dt
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from loguru import logger

from bot.cache.redis import build_key
from bot.core.config import TIMEZONE
from bot.services.grade_sync import NewGradeNotice
from bot.services.users import (
    DEFAULT_MORNING_NOTIFICATION_TIME,
    NotificationSettings,
    load_notification_settings,
    set_notification_enabled,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

#: Ночь: с 22:00 до 07:59 включительно.
NIGHT_START_HOUR = 22
NIGHT_END_HOUR = 8

#: Сколько помнить, что об оценке уже уведомили.
SENT_TTL_SECONDS = 7 * 24 * 60 * 60

#: Ночной список живёт до утра плюс запас: если задача опоздала, данные не потеряны.
NIGHT_TTL_MARGIN = dt.timedelta(hours=2)

#: Минимальный TTL ключей Redis: нулевой TTL удалил бы ключ сразу.
MIN_TTL_SECONDS = 60

#: Пресеты времени утренней сводки (задача 3.3): по кругу, без FSM-ввода.
MORNING_TIME_PRESETS: tuple[dt.time, ...] = (dt.time(7, 0), dt.time(8, 0), dt.time(9, 0), dt.time(10, 0))


class NotificationKind(StrEnum):
    """Что решил сервис: ничего, отправить сразу или накопить до утра."""

    NONE = "none"
    IMMEDIATE = "immediate"
    NIGHT = "night"


@dataclass(slots=True)
class NotificationDecision:
    """Результат политики: что отправлять, когда и на каком языке."""

    kind: NotificationKind
    notices: list[NewGradeNotice] = field(default_factory=list)
    language_code: str | None = None
    morning_at: dt.datetime | None = None
    night_expires_at: dt.datetime | None = None


def now() -> dt.datetime:
    """Текущее время Europe/Moscow (тесты подменяют эту функцию)."""
    return dt.datetime.now(TIMEZONE)


def is_night(moment: dt.datetime) -> bool:
    """Ночь ли сейчас: 22:00–07:59 по Москве."""
    return moment.hour >= NIGHT_START_HOUR or moment.hour < NIGHT_END_HOUR


def next_morning(moment: dt.datetime, morning_time: dt.time) -> dt.datetime:
    """Ближайшее `morning_time` после `moment`; если сегодня уже прошло — завтра."""
    candidate = dt.datetime.combine(moment.date(), morning_time, tzinfo=TIMEZONE)
    if candidate <= moment:
        candidate += dt.timedelta(days=1)
    return candidate


def next_morning_preset(current: dt.time) -> dt.time:
    """Следующий пресет времени утра по кругу."""
    try:
        index = MORNING_TIME_PRESETS.index(current)
    except ValueError:
        return MORNING_TIME_PRESETS[0]
    return MORNING_TIME_PRESETS[(index + 1) % len(MORNING_TIME_PRESETS)]


def sent_key(user_id: int, lesson_key: str) -> str:
    """Ключ дедупликации уведомлений: `notify:sent:{user_id}:{lesson_key}`."""
    return build_key("notify:sent", user_id, lesson_key)


def night_key(user_id: int) -> str:
    """Ночная очередь пользователя: `notifications:night:{user_id}`."""
    return build_key("notifications:night", user_id)


def night_scheduled_key(user_id: int) -> str:
    """Один `send_night_batch` на пользователя: `notify:night:scheduled:{user_id}`."""
    return build_key("notify:night:scheduled", user_id)


def ttl_seconds_until(moment: dt.datetime) -> int:
    """Сколько секунд осталось до `moment` (не меньше `MIN_TTL_SECONDS`)."""
    return max(int((moment - now()).total_seconds()), MIN_TTL_SECONDS)


def _as_text(value: bytes | str) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


def unique_notices(notices: Iterable[NewGradeNotice]) -> list[NewGradeNotice]:
    """Убрать повторы по `lesson_key`, сохранив порядок."""
    seen: set[str] = set()
    result: list[NewGradeNotice] = []
    for notice in notices:
        if notice.lesson_key in seen:
            continue
        seen.add(notice.lesson_key)
        result.append(notice)
    return result


class NotificationService:
    """Политика и Redis-очередь уведомлений одного пользователя.

    Сервис не создаёт `Bot` и не отправляет сообщения: он только решает, что делать,
    и хранит маркеры/очередь. Отправка — в задачах `bot/tasks/notify.py`.
    """

    def __init__(self, *, redis: Redis, session: AsyncSession, user_id: int) -> None:
        self._redis = redis
        self._session = session
        self._user_id = user_id

    @property
    def user_id(self) -> int:
        return self._user_id

    async def load_settings(self) -> NotificationSettings | None:
        """Настройки уведомлений из БД (без кеша — сервис живёт и в воркере)."""
        return await load_notification_settings(self._session, self._user_id)

    async def decide(
        self,
        notices: Sequence[NewGradeNotice],
        *,
        force_immediate: bool = False,
    ) -> NotificationDecision:
        """Решить, что делать с пачкой новых оценок.

        `force_immediate=True` — ручная синхронизация: пользователь ждёт ответ, поэтому
        ночная политика не применяется, даже если сейчас ночь.
        """
        candidates = unique_notices(notices)
        if not candidates:
            return NotificationDecision(kind=NotificationKind.NONE)

        settings = await self.load_settings()
        if settings is None or not settings.enabled:
            logger.info("notification skipped user={} reason=disabled", self._user_id)
            return NotificationDecision(kind=NotificationKind.NONE)

        fresh = await self.unmarked(candidates)
        if not fresh:
            logger.info("notification skipped user={} reason=duplicate", self._user_id)
            return NotificationDecision(kind=NotificationKind.NONE)

        moment = now()
        if not force_immediate and settings.morning_enabled and is_night(moment):
            morning_at = next_morning(moment, settings.morning_time or DEFAULT_MORNING_NOTIFICATION_TIME)
            return NotificationDecision(
                kind=NotificationKind.NIGHT,
                notices=fresh,
                language_code=settings.language_code,
                morning_at=morning_at,
                night_expires_at=morning_at + NIGHT_TTL_MARGIN,
            )

        return NotificationDecision(
            kind=NotificationKind.IMMEDIATE,
            notices=fresh,
            language_code=settings.language_code,
        )

    async def unmarked(self, notices: Sequence[NewGradeNotice]) -> list[NewGradeNotice]:
        """Оставить только те оценки, о которых ещё не уведомляли."""
        if not notices:
            return []
        keys = [sent_key(self._user_id, notice.lesson_key) for notice in notices]
        values = await self._redis.mget(keys)
        return [notice for notice, value in zip(notices, values, strict=True) if value is None]

    async def mark(self, notices: Sequence[NewGradeNotice]) -> None:
        """Поставить маркеры «уже уведомили» до отправки (SET NX EX 7 дней)."""
        if not notices:
            return
        pipeline = self._redis.pipeline(transaction=False)
        for notice in notices:
            pipeline.set(sent_key(self._user_id, notice.lesson_key), "1", nx=True, ex=SENT_TTL_SECONDS)
        await pipeline.execute()

    async def unmark(self, notices: Sequence[NewGradeNotice]) -> None:
        """Снять маркеры: отправка не удалась, повтор должен снова увидеть оценки."""
        if not notices:
            return
        await self._redis.delete(*(sent_key(self._user_id, notice.lesson_key) for notice in notices))

    async def disable_notifications(self) -> None:
        """Выключить уведомления в БД (бот заблокирован пользователем)."""
        await set_notification_enabled(self._session, self._user_id, enabled=False)

    async def push_night(self, notices: Sequence[NewGradeNotice], *, expires_at: dt.datetime) -> int:
        """Положить оценки в ночную очередь; вернуть, сколько записей добавлено.

        Повторный вызов не дублирует уже лежащие в списке уроки: маркер дедупликации
        ставится до постановки, но при повторе задачи (acks_late) список мог сохраниться.
        """
        key = night_key(self._user_id)
        fresh = unique_notices(notices)
        if fresh:
            existing = await self._night_keys(key)
            fresh = [notice for notice in fresh if notice.lesson_key not in existing]
        if fresh:
            await self._redis.rpush(key, *(json.dumps(notice.to_dict(), ensure_ascii=False) for notice in fresh))
        await self._redis.expire(key, ttl_seconds_until(expires_at))
        return len(fresh)

    async def pop_night(self) -> list[NewGradeNotice]:
        """Забрать и очистить ночную очередь (атомарно, чтобы повтор не отправил дважды)."""
        key = night_key(self._user_id)
        pipeline = self._redis.pipeline(transaction=True)
        pipeline.lrange(key, 0, -1)
        pipeline.delete(key)
        results = await pipeline.execute()
        raw_items = results[0] if results else []

        notices: list[NewGradeNotice] = []
        for raw in raw_items or []:
            try:
                notices.append(NewGradeNotice.from_dict(json.loads(_as_text(raw))))
            except (KeyError, TypeError, ValueError):
                logger.warning("night queue record skipped user={}", self._user_id)
        return unique_notices(notices)

    async def claim_night_schedule(self, *, expires_at: dt.datetime) -> bool:
        """Занять право поставить один `send_night_batch` на пользователя.

        `False` — задача на это утро уже стоит; повторно её не создаём.
        """
        return bool(
            await self._redis.set(
                night_scheduled_key(self._user_id),
                "1",
                nx=True,
                ex=ttl_seconds_until(expires_at),
            ),
        )

    async def release_night_schedule(self) -> None:
        """Отпустить право постановки: задача не встала в очередь, нужно повторить."""
        await self._redis.delete(night_scheduled_key(self._user_id))

    async def clear_night_schedule(self) -> None:
        """Убрать маркер постановки после отправки утренней сводки."""
        await self._redis.delete(night_scheduled_key(self._user_id))

    async def _night_keys(self, key: str) -> set[str]:
        """Ключи уроков, уже лежащих в ночной очереди."""
        keys: set[str] = set()
        for raw in await self._redis.lrange(key, 0, -1):
            try:
                keys.add(NewGradeNotice.from_dict(json.loads(_as_text(raw))).lesson_key)
            except (KeyError, TypeError, ValueError):
                continue
        return keys
