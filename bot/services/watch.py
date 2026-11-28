"""Режим ожидания оценок (фаза 5, docs/ARCHITECTURE.md §7.5).

Пользователь на 30 минут включает ускоренную проверку журнала. Состояние — поле
`users.watch_mode_expires_at` (истина) плюс множество `watch_mode:users` в Redis (индекс
для планировщика, без TTL: его чистит задача, а не время жизни ключа).

Сервис не ходит в сеть и не отправляет сообщений: включение/продление/выключение — это
изменение состояния, а проверку делает задача `bot.tasks.sync.sync_watch_mode_users`.

Время берётся из :func:`now` — тесты подменяют её, `freezegun` не нужен. Значение
хранится без `tzinfo`, как и остальные `TIMESTAMP` в этой БД (`TIMEZONE('utc+3', now())`).
"""

from __future__ import annotations
import datetime as dt
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import func, select, update

from bot.cache.redis import build_key
from bot.core.config import TIMEZONE
from bot.database.models import User

if TYPE_CHECKING:
    from collections.abc import Sequence

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

#: Множество ожидающих: единственный ключ без TTL (ARCHITECTURE §4.2).
WATCH_USERS_KEY = build_key("watch_mode:users")

#: Причины отказа во включении — их различает хендлер, чтобы дать понятный ответ.
REASON_NOT_FOUND = "not_found"
REASON_NOT_AUTHENTICATED = "not_authenticated"


def now() -> dt.datetime:
    """Текущее время Europe/Moscow без `tzinfo` (тесты подменяют эту функцию)."""
    return dt.datetime.now(TIMEZONE).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class WatchState:
    """Состояние режима у одного пользователя."""

    active: bool
    expires_at: dt.datetime | None = None
    #: Остаток в минутах, округлённый вверх: 29:30 → 30. Никогда не отрицательный.
    minutes_left: int = 0


@dataclass(frozen=True, slots=True)
class WatchOutcome:
    """Результат действия: изменилось ли состояние и почему нет."""

    state: WatchState
    changed: bool
    reason: str | None = None


class WatchModeService:
    """Включение, продление и снятие режима ожидания.

    Один экземпляр на задачу или на запрос: сервис держит сессию и Redis, но не
    кеширует состояние между вызовами.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        redis: Redis,
        minutes: int,
    ) -> None:
        self._session = session
        self._redis = redis
        self._minutes = minutes

    # ── Чтение ──────────────────────────────────────────────────────────────

    async def get_state(self, user_id: int) -> WatchState:
        """Текущее состояние режима (активен ли, до какого момента, сколько осталось)."""
        result = await self._session.execute(select(User.watch_mode_expires_at).where(User.id == user_id))
        expires_at = result.scalar_one_or_none()
        return self._state(expires_at)

    async def active_user_ids(self) -> list[int]:
        """Пользователи с неистёкшим режимом — то, что проверяет цикл синхронизации."""
        moment = now()
        query = (
            select(User.id)
            .where(
                User.watch_mode_expires_at.is_not(None),
                User.watch_mode_expires_at > moment,
            )
            .order_by(User.id)
        )
        result = await self._session.execute(query)
        return [row[0] if not isinstance(row, int) else row for row in result.all()]

    async def count_active(self) -> int:
        """Сколько пользователей сейчас в режиме (для метрики `active_users`)."""
        query = (
            select(func.count())
            .select_from(User)
            .where(
                User.watch_mode_expires_at.is_not(None),
                User.watch_mode_expires_at > now(),
            )
        )
        result = await self._session.execute(query)
        return int(result.scalar_one() or 0)

    # ── Изменение состояния ─────────────────────────────────────────────────

    async def enable(self, user_id: int) -> WatchOutcome:
        """Включить режим или продлить активный — одно действие.

        Требует авторизации: без неё проверять нечего, а история синхронизаций
        заполнялась бы ошибками.
        """
        result = await self._session.execute(select(User.is_authenticated).where(User.id == user_id))
        authenticated = result.scalar_one_or_none()
        if authenticated is None:
            return WatchOutcome(state=WatchState(active=False), changed=False, reason=REASON_NOT_FOUND)
        if not authenticated:
            return WatchOutcome(state=WatchState(active=False), changed=False, reason=REASON_NOT_AUTHENTICATED)

        expires_at = self._new_expiry()
        await self._session.execute(
            update(User).where(User.id == user_id).values(watch_mode_expires_at=expires_at),
        )
        await self._session.commit()
        await self._redis.sadd(WATCH_USERS_KEY, user_id)
        state = self._state(expires_at)
        logger.info("watch enabled user={} until={} minutes={}", user_id, expires_at, state.minutes_left)
        return WatchOutcome(state=state, changed=True)

    async def disable(self, user_id: int) -> WatchOutcome:
        """Выключить режим досрочно: снять срок и убрать из индекса."""
        await self._session.execute(
            update(User).where(User.id == user_id).values(watch_mode_expires_at=None, watch_mode_last_sync_at=None),
        )
        await self._session.commit()
        await self._redis.srem(WATCH_USERS_KEY, user_id)
        logger.info("watch disabled user={}", user_id)
        return WatchOutcome(state=WatchState(active=False), changed=True)

    async def mark_synced(self, user_ids: Sequence[int]) -> None:
        """Записать время последней проверки в режиме (для диагностики и админки)."""
        if not user_ids:
            return
        await self._session.execute(
            update(User).where(User.id.in_(user_ids)).values(watch_mode_last_sync_at=now()),
        )
        await self._session.commit()

    async def expire_stale(self) -> int:
        """Снять истёкшие режимы и выровнять индекс по БД. Идемпотентно.

        Возвращает число снятых режимов. Вызывается часовой задачей; цикл
        синхронизации и без неё не берёт истёкших (условие `> now`), поэтому
        «залипнуть» режим не может даже при пропущенной уборке.
        """
        moment = now()
        stale_result = await self._session.execute(
            select(User.id).where(
                User.watch_mode_expires_at.is_not(None),
                User.watch_mode_expires_at <= moment,
            ),
        )
        stale = [row[0] if not isinstance(row, int) else row for row in stale_result.all()]

        if stale:
            await self._session.execute(
                update(User).where(User.id.in_(stale)).values(watch_mode_expires_at=None, watch_mode_last_sync_at=None),
            )
            await self._session.commit()
            for user_id in stale:
                await self._redis.srem(WATCH_USERS_KEY, user_id)
            logger.info("watch expired users={}", len(stale))

        await self._reconcile_index()
        return len(stale)

    async def _reconcile_index(self) -> None:
        """Сверить множество Redis с БД: добавить активных, убрать лишних.

        Нужна, если Redis очистили или, наоборот, удаление ключа не доехало.
        """
        active = await self.active_user_ids()
        active_set = set(active)
        stored = await self._redis.smembers(WATCH_USERS_KEY)
        stored_ids = {_as_int(member) for member in stored}

        missing = active_set - stored_ids
        extra = stored_ids - active_set
        if missing:
            await self._redis.sadd(WATCH_USERS_KEY, *missing)
        for user_id in extra:
            await self._redis.srem(WATCH_USERS_KEY, user_id)
        if missing or extra:
            logger.warning("watch index reconciled added={} removed={}", len(missing), len(extra))

    # ── Вспомогательное ─────────────────────────────────────────────────────

    def _new_expiry(self) -> dt.datetime:
        return now() + dt.timedelta(minutes=self._minutes)

    def _state(self, expires_at: dt.datetime | None) -> WatchState:
        """Собрать состояние из срока: остаток считается вверх и не бывает нулевым у активного."""
        if expires_at is None:
            return WatchState(active=False)
        seconds_left = (expires_at - now()).total_seconds()
        if seconds_left <= 0:
            return WatchState(active=False, expires_at=expires_at)
        return WatchState(
            active=True,
            expires_at=expires_at,
            minutes_left=max(1, math.ceil(seconds_left / 60)),
        )


def _as_int(member: bytes | str | int) -> int:
    """Привести член Redis-множества к `int` (клиент может отдавать байты)."""
    if isinstance(member, bytes):
        return int(member.decode())
    return int(member)
