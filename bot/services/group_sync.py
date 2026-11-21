"""Плановая синхронизация всех пользователей по группам (задача 4.1).

Алгоритм (docs/ARCHITECTURE.md §7.3):

1. кандидаты — авторизованные пользователи с `group_id` и `edu_user_id`;
2. группа обрабатывается целиком: `unprocessed` — её студенты по `edu_user_id`;
3. список журналов берётся **один раз на группу** токеном любого участника (если у
   первого токена ошибка авторизации — пробуем следующего);
4. для каждого журнала `JournalCache.get_journal` отдаёт группу/подгруппу из кеша или
   одним запросом к edu-tpi; этот же `payload` применяется ко всем участникам группы,
   которые в нём есть (диф — `GradeSyncService.apply_payload`, без копирования);
5. студенты, пришедшие в `payload`, убираются из `unprocessed` — подгруппа обработана,
   даже если этих людей нет среди пользователей бота;
6. если за проход `unprocessed` не уменьшился — предупреждение, оставшиеся помечаются
   `failed`, группа закрывается (защита от бесконечного цикла).

Ошибки: `EduEmptyJournalError` — пропуск (чужая подгруппа), `EduAuthError` одного
участника — он `failed`, остальные продолжают, `ParseError` журнала — ошибка журнала,
`EduUnavailableError`/`EduRateLimitError` — ошибка прогона (задача повторится целиком).
"""

from __future__ import annotations
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from bot.core.errors import (
    EduAuthError,
    EduEmptyJournalError,
    EduRateLimitError,
    EduUnavailableError,
    ParseError,
    RetryableError,
)
from bot.database.models.sync_log import SyncStatus, SyncType
from bot.services.auth import TokenService
from bot.services.grade_sync import (
    GradeSyncService,
    NewGradeNotice,
    academic_year,
    current_semester,
)
from bot.services.sync_logs import write_sync_log
from bot.services.users import load_sync_candidates

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.integrations.edu_tpi import EduTpiClient
    from bot.integrations.journal_cache import JournalCache
    from bot.integrations.models import JournalBrief, JournalPayload
    from bot.services.grade_sync import GradeNotifier, UserLockFactory
    from bot.services.users import UserSyncInfo

#: Больше проходов по одной группе не бывает: каждый проход добавляет новую подгруппу.
MAX_PASSES = 10

#: Сколько кодов ошибок оставлять в результате задачи (JSON уходит в backend).
MAX_ERROR_CODES = 10


@dataclass(slots=True)
class BatchSummary:
    """Итог прогона `sync_all_users`: только числа и коды ошибок."""

    status: str = "success"
    groups: int = 0
    users: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    new_grades: int = 0
    updated_grades: int = 0
    errors: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        """JSON-безопасный результат задачи Celery."""
        return {
            "status": self.status,
            "groups": self.groups,
            "users": self.users,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "new_grades": self.new_grades,
            "updated_grades": self.updated_grades,
            "errors": list(self.errors[:MAX_ERROR_CODES]),
            "duration_s": round(self.duration_s, 3),
        }


@dataclass(slots=True)
class MemberResult:
    """Итог по одному участнику группы: статус, числа и коды ошибок."""

    user_id: int
    status: str = "success"
    new_grades: int = 0
    updated_grades: int = 0
    journals: int = 0
    error_codes: list[str] = field(default_factory=list)


def _add_error(summary: BatchSummary, code: str) -> None:
    """Добавить код ошибки один раз: в результате нужны причины, а не счётчик."""
    if code not in summary.errors:
        summary.errors.append(code)


class GroupSyncService:
    """Синхронизация всех пользователей: один запрос на группу/подгруппу."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        session: AsyncSession,
        client: EduTpiClient,
        cache: JournalCache,
        redis: Redis,
        user_lock: UserLockFactory | None = None,
        notifier: GradeNotifier | None = None,
    ) -> None:
        self._session = session
        self._client = client
        self._cache = cache
        self._redis = redis
        self._user_lock = user_lock
        self._notifier = notifier
        self._token_services: dict[int, TokenService] = {}

    async def sync_all(self) -> BatchSummary:
        """Синхронизировать всех кандидатов; пустая БД — успех с нулями."""
        started = time.perf_counter()
        summary = BatchSummary()

        candidates = await load_sync_candidates(self._session)
        summary.users = len(candidates)

        by_group: dict[int, list[UserSyncInfo]] = defaultdict(list)
        for user in candidates:
            if user.group_id is None:  # pragma: no cover — отфильтровано в запросе
                continue
            by_group[user.group_id].append(user)
        summary.groups = len(by_group)

        logger.info("sync batch started groups={} users={}", summary.groups, summary.users)

        listed_groups = 0
        for group_id in sorted(by_group):
            members = by_group[group_id]
            try:
                listed = await self._sync_group(group_id, members, summary)
            except (EduUnavailableError, EduRateLimitError, ParseError) as exc:
                logger.warning("sync batch: group failed group={} error={}", group_id, type(exc).__name__)
                _add_error(summary, "unavailable" if not isinstance(exc, ParseError) else "parse")
                # Эти пользователи не синхронизированы, но прогон продолжается.
                summary.failed += len(members)
                continue
            if listed:
                listed_groups += 1

        if by_group and listed_groups == 0:
            # Список журналов не получен ни для одной группы: edu-tpi лежит целиком.
            # Батч идемпотентен, поэтому Celery может безопасно повторить его.
            message = "Список журналов не получен ни для одной группы"
            raise RetryableError(message)

        if summary.failed == 0:
            summary.status = "success"
        elif summary.success or summary.skipped:
            summary.status = "partial"
        else:
            summary.status = "failed"

        summary.duration_s = time.perf_counter() - started
        logger.info(
            "sync batch finished status={} groups={} users={} success={} failed={} skipped={} "
            "new={} updated={} duration={:.1f}s",
            summary.status,
            summary.groups,
            summary.users,
            summary.success,
            summary.failed,
            summary.skipped,
            summary.new_grades,
            summary.updated_grades,
            summary.duration_s,
        )
        return summary

    async def _sync_group(  # noqa: C901 — один проход по группе читается сверху вниз
        self,
        group_id: int,
        members: list[UserSyncInfo],
        summary: BatchSummary,
    ) -> bool:
        """Обработать одну группу; `False` — список журналов получить не удалось."""
        unprocessed: dict[int, UserSyncInfo] = {
            member.edu_user_id: member
            for member in sorted(members, key=lambda item: (item.edu_user_id or 0, item.id))
            if member.edu_user_id is not None
        }
        results: dict[int, MemberResult] = {}

        journals = await self._list_group_journals(group_id, members)
        if journals is None:
            return False

        passes = 0
        while unprocessed and passes < MAX_PASSES:
            passes += 1
            before = len(unprocessed)
            leader = unprocessed[min(unprocessed)]
            leader_id = int(leader.edu_user_id or 0)
            tokens = self._tokens_for(leader)
            leader_failed = False
            group_unavailable = False

            for brief in journals:
                try:
                    payload = await self._get_payload(
                        tokens,
                        brief=brief,
                        group_id=group_id,
                        edu_user_id=leader_id,
                        fio=leader.full_name,
                    )
                except EduEmptyJournalError:
                    # Журнал есть в списке, но данных для этого студента нет: чужая
                    # подгруппа (или архивный журнал). Не ошибка.
                    logger.debug("sync batch: journal empty journal_id={} group={}", brief.id, group_id)
                    continue
                except EduAuthError:
                    # Токен лидера не годится: он failed, дальше идёт следующий проход
                    # с другим лидером и его токеном.
                    logger.warning("sync batch: leader auth failed group={} user={}", group_id, leader.id)
                    self._mark_failed(results, leader, "auth")
                    _add_error(summary, "auth")
                    unprocessed.pop(leader_id, None)
                    leader_failed = True
                    break
                except ParseError:
                    logger.warning("sync batch: journal parse failed journal_id={} group={}", brief.id, group_id)
                    _add_error(summary, "parse")
                    continue
                except (EduUnavailableError, EduRateLimitError):
                    # edu-tpi недоступен: группа не доработана, но прогон продолжается.
                    logger.warning(
                        "sync batch: journal unavailable journal_id={} group={}",
                        brief.id,
                        group_id,
                    )
                    _add_error(summary, "unavailable")
                    for member in list(unprocessed.values()):
                        self._mark_failed(results, member, "unavailable")
                    unprocessed.clear()
                    group_unavailable = True
                    break

                await self._apply_to_members(brief, payload, unprocessed, results)

            if leader_failed:
                continue
            if group_unavailable:
                break
            if len(unprocessed) >= before:
                logger.warning(
                    "sync batch: no progress group={} unprocessed={} — marking failed",
                    group_id,
                    len(unprocessed),
                )
                _add_error(summary, "unprocessed")
                for member in list(unprocessed.values()):
                    self._mark_failed(results, member, "unprocessed")
                unprocessed.clear()

        await self._write_member_logs(members, results, summary)
        return True

    async def _list_group_journals(
        self,
        group_id: int,
        members: list[UserSyncInfo],
    ) -> list[JournalBrief] | None:
        """Список журналов один раз на группу; при 401 — токен следующего участника."""
        year = academic_year()
        semester = current_semester()

        for member in sorted(members, key=lambda item: (item.edu_user_id or 0, item.id)):
            tokens = self._tokens_for(member)
            try:
                journals = await tokens.call(
                    lambda token: self._client.list_journals(token, year=year, sem=semester),
                )
            except EduAuthError:
                logger.warning(
                    "sync batch: list journals auth failed group={} user={}",
                    group_id,
                    member.id,
                )
                continue
            # Список уже одного семестра; дубликаты на всякий случай убираем по id.
            unique = list({brief.id: brief for brief in journals}.values())
            logger.info(
                "sync batch: journals received group={} user={} count={}",
                group_id,
                member.id,
                len(unique),
            )
            return unique
        return None

    async def _get_payload(
        self,
        tokens: TokenService,
        *,
        brief: JournalBrief,
        group_id: int,
        edu_user_id: int,
        fio: str | None,
    ) -> JournalPayload:
        """Журнал для лидера: из кеша группы/подгруппы или одним запросом."""
        return await tokens.call(
            lambda token: self._cache.get_journal(
                token=token,
                journal_id=brief.id,
                group_id=group_id,
                edu_user_id=edu_user_id,
                fio=fio,
            ),
        )

    async def _apply_to_members(
        self,
        brief: JournalBrief,
        payload: JournalPayload,
        unprocessed: dict[int, UserSyncInfo],
        results: dict[int, MemberResult],
    ) -> None:
        """Применить журнал ко всем участникам группы, которые в нём есть."""
        student_ids = set(payload.student_ids)

        for member in sorted(unprocessed.values(), key=lambda item: (item.edu_user_id or 0, item.id)):
            if member.edu_user_id not in student_ids:
                continue
            await self._apply_member(brief, payload, member, results)

        # Подгруппа обработана целиком, даже если часть студентов — не пользователи бота.
        for student_id in student_ids:
            unprocessed.pop(student_id, None)

    async def _apply_member(
        self,
        brief: JournalBrief,
        payload: JournalPayload,
        member: UserSyncInfo,
        results: dict[int, MemberResult],
    ) -> None:
        """Диф и коммит для одного участника под `sync:lock:{user_id}`."""
        result = self._result_for(results, member)

        async with self._member_lock(member.id) as acquired:
            if not acquired:
                # Идёт ручная синхронизация этого пользователя: повторный прогон подхватит.
                logger.info("sync batch skipped: locked user={}", member.id)
                result.status = "skipped"
                return
            try:
                journal_result = await self._service_for(member).apply_payload(member, brief, payload)
            except Exception:  # noqa: BLE001 — один пользователь не валит группу
                await self._rollback()
                logger.exception("sync batch: user failed user={} journal={}", member.id, brief.id)
                self._mark_failed(results, member, "internal")
                return

        result.journals += 1
        result.new_grades += journal_result.new_grades
        result.updated_grades += journal_result.updated_grades
        if journal_result.notices:
            self._notify(member.id, journal_result.notices)

    async def _write_member_logs(
        self,
        members: list[UserSyncInfo],
        results: dict[int, MemberResult],
        summary: BatchSummary,
    ) -> None:
        """`sync_logs` с `sync_type=auto` и счётчики прогона по каждому участнику."""
        for member in sorted(members, key=lambda item: item.id):
            result = results.get(member.id)
            if result is None:
                # В журналах не нашёлся никто: пользователь остался без данных.
                result = MemberResult(user_id=member.id, status="failed", error_codes=["unprocessed"])
            if result.status == "skipped":
                summary.skipped += 1
                continue

            failed = result.status == "failed"
            summary.failed += int(failed)
            summary.success += int(not failed)
            summary.new_grades += result.new_grades
            summary.updated_grades += result.updated_grades
            for code in result.error_codes:
                _add_error(summary, code)

            await write_sync_log(
                self._session,
                user_id=member.id,
                sync_type=SyncType.AUTO,
                status=SyncStatus.FAILED if failed else SyncStatus.SUCCESS,
                new_grades_count=result.new_grades,
                updated_grades_count=result.updated_grades,
                message=f"journals={result.journals} errors={len(result.error_codes)}",
            )

    def _tokens_for(self, member: UserSyncInfo) -> TokenService:
        """`TokenService` на участника: один экземпляр на прогон группы."""
        service = self._token_services.get(member.id)
        if service is None:
            service = TokenService(
                redis=self._redis,
                session=self._session,
                user_id=member.id,
                client=self._client,
            )
            self._token_services[member.id] = service
        return service

    def _service_for(self, member: UserSyncInfo) -> GradeSyncService:
        """Сервис дифа для участника: тот же кеш, клиент и сессия прогона."""
        return GradeSyncService(
            session=self._session,
            client=self._client,
            cache=self._cache,
            tokens=self._tokens_for(member),
            sync_type=SyncType.AUTO,
        )

    def _result_for(self, results: dict[int, MemberResult], member: UserSyncInfo) -> MemberResult:
        result = results.get(member.id)
        if result is None:
            result = MemberResult(user_id=member.id)
            results[member.id] = result
        return result

    def _mark_failed(
        self,
        results: dict[int, MemberResult],
        member: UserSyncInfo,
        code: str,
    ) -> None:
        result = self._result_for(results, member)
        result.status = "failed"
        if code not in result.error_codes:
            result.error_codes.append(code)

    async def _rollback(self) -> None:
        """Откатить незавершённую транзакцию пользователя, чтобы группа продолжилась."""
        try:
            await self._session.rollback()
        except Exception:  # noqa: BLE001 — откат не должен скрывать исходную ошибку
            logger.exception("sync batch rollback failed")

    @asynccontextmanager
    async def _member_lock(self, user_id: int) -> AsyncIterator[bool]:
        """`sync:lock` участника; без фабрики блокировок — «всегда свободен»."""
        if self._user_lock is None:
            yield True
            return
        async with self._user_lock(user_id) as acquired:
            yield acquired

    def _notify(self, user_id: int, notices: Sequence[NewGradeNotice]) -> None:
        """Поставить уведомление о новых оценках; ошибка брокера не валит батч."""
        if self._notifier is None:
            return
        try:
            self._notifier(user_id, notices)
        except Exception:  # noqa: BLE001 — оценки уже сохранены, уведомление вторично
            logger.exception("sync batch: notification scheduling failed user={}", user_id)
