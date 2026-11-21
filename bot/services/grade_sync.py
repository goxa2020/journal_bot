"""Синхронизация оценок: диф по ключу урока, upsert и `sync_logs` (задача 2.5).

Алгоритм (docs/ARCHITECTURE.md §8):

1. журналы обоих семестров через `EduTpiClient.collect_journals` (кеш в `JournalCache`);
2. занятия студента из журнала, ключ — `(date, hour_number)`;
3. новые — вставка, изменённые — обновление с `updated_at`, пропавшие — **не удаляем**;
4. ошибка одного журнала не валит всю синхронизацию, кроме `EduAuthError`.

`value` из `journalVal` приходит с хвостовыми пробелами, поэтому значение
нормализуется `strip()` и при сравнении, и при сохранении.
"""

from __future__ import annotations
import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING, Any

from loguru import logger

from bot.core.config import TIMEZONE
from bot.core.errors import (
    EduAuthError,
    EduEmptyJournalError,
    EduRateLimitError,
    EduUnavailableError,
    ParseError,
    PermanentError,
)
from bot.database.models.sync_log import SyncStatus, SyncType
from bot.services.grades import GradesService
from bot.services.journals import upsert_and_link
from bot.services.sync_logs import write_sync_log
from bot.services.users import load_user_sync_info

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.database.models import Grade
    from bot.integrations.edu_tpi import EduTpiClient
    from bot.integrations.journal_cache import JournalCache
    from bot.integrations.models import JournalBrief, Lesson
    from bot.services.auth import TokenService
    from bot.services.users import UserSyncInfo


SEPTEMBER = 9


def academic_year(today: dt.date | None = None) -> str:
    """Учебный год: с сентября `YYYY-(YYYY+1)`, иначе `(YYYY-1)-YYYY` (docs/API.md §1)."""
    current = today or dt.datetime.now(TIMEZONE).date()
    if current.month >= SEPTEMBER:
        return f"{current.year}-{current.year + 1}"
    return f"{current.year - 1}-{current.year}"


@dataclass(slots=True)
class JournalSyncResult:
    """Итог по одному журналу: сколько нового/обновлённого и была ли ошибка."""

    journal_id: int
    name: str
    new_grades: int = 0
    updated_grades: int = 0
    error: str | None = None
    skipped: bool = False


@dataclass(slots=True)
class SyncSummary:
    """Сводка синхронизации — для текста пользователю, лога и `sync_logs`."""

    user_id: int
    sync_type: SyncType
    status: SyncStatus
    new_grades: int = 0
    updated_grades: int = 0
    journals: list[JournalSyncResult] = field(default_factory=list)
    error_codes: list[str] = field(default_factory=list)
    language_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Сериализуемый результат задачи Celery (в backend уходит JSON)."""
        return {
            "user_id": self.user_id,
            "sync_type": str(self.sync_type),
            "status": str(self.status),
            "new_grades": self.new_grades,
            "updated_grades": self.updated_grades,
            "journals": len(self.journals),
            "error_codes": list(self.error_codes),
        }


def _normalized(lesson: Lesson) -> Lesson:
    """Значение без хвостовых пробелов (docs/ARCHITECTURE.md §8)."""
    if lesson.value == lesson.value.strip():
        return lesson
    return dataclasses.replace(lesson, value=lesson.value.strip())


def _grade_changed(grade: Grade, lesson: Lesson) -> bool:
    return (
        grade.value != lesson.value
        or grade.number_value != lesson.number_value
        or grade.is_mark != lesson.is_mark
        or grade.is_pass != lesson.is_pass
        or grade.is_valid_pass != lesson.is_valid_pass
    )


class GradeSyncService:
    """Синхронизация оценок одного пользователя."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        client: EduTpiClient,
        cache: JournalCache,
        tokens: TokenService,
        sync_type: SyncType = SyncType.MANUAL,
    ) -> None:
        self._session = session
        self._client = client
        self._cache = cache
        self._tokens = tokens
        self._sync_type = sync_type

    async def sync_user(self, user_id: int) -> SyncSummary:  # noqa: C901, PLR0912, PLR0915
        """Синхронизировать все журналы пользователя и вернуть сводку."""
        user = await load_user_sync_info(self._session, user_id)
        if user is None:
            message = f"Пользователь {user_id} не найден"
            raise PermanentError(message)
        if not user.is_authenticated:
            await self._log_failure(user_id, SyncStatus.FAILED, "not_authenticated")
            message = "Пользователь не авторизован в edu-tpi"
            raise EduAuthError(message)

        summary = SyncSummary(user_id=user_id, sync_type=self._sync_type, status=SyncStatus.SUCCESS)
        summary.language_code = user.language_code

        if user.edu_user_id is None or user.group_id is None:
            await self._log_failure(user_id, SyncStatus.FAILED, "no_group")
            message = "У пользователя нет edu_user_id или group_id"
            raise PermanentError(message)

        try:
            journals = await self._list_journals()
        except EduAuthError:
            await self._log_failure(user_id, SyncStatus.FAILED, "auth")
            raise
        except ParseError:
            await self._log_failure(user_id, SyncStatus.FAILED, "parse")
            raise
        except (EduUnavailableError, EduRateLimitError):
            await self._log_failure(user_id, SyncStatus.FAILED, "unavailable")
            raise

        logger.info("sync started user={} journals={}", user_id, len(journals))

        retryable_error: Exception | None = None
        successful_journals = 0
        for brief in journals:
            try:
                result = await self._sync_journal(user, brief)
            except EduAuthError:
                await self._rollback()
                await self._log_failure(user_id, SyncStatus.FAILED, "auth", summary)
                raise
            except (EduUnavailableError, EduRateLimitError) as exc:
                await self._rollback()
                result = JournalSyncResult(journal_id=brief.id, name=brief.name, error="unavailable")
                retryable_error = exc
            except EduEmptyJournalError:
                # Журнал есть в списке, но данных по нему нет — не ошибка.
                await self._rollback()
                logger.info("sync journal empty journal_id={} user={}", brief.id, user_id)
                result = JournalSyncResult(journal_id=brief.id, name=brief.name, skipped=True)
            except ParseError as exc:
                await self._rollback()
                logger.warning(
                    "sync journal parse failed journal_id={} user={} error={}",
                    brief.id,
                    user_id,
                    exc,
                )
                result = JournalSyncResult(journal_id=brief.id, name=brief.name, error="parse")
            except Exception:  # noqa: BLE001 — один журнал не должен валить остальные
                await self._rollback()
                logger.exception("sync journal failed journal_id={} user={}", brief.id, user_id)
                result = JournalSyncResult(journal_id=brief.id, name=brief.name, error="internal")

            summary.journals.append(result)
            summary.new_grades += result.new_grades
            summary.updated_grades += result.updated_grades
            if result.error is None:
                successful_journals += 1
            else:
                summary.error_codes.append(result.error)

        if not successful_journals and retryable_error is not None:
            # Ничего не обновили из-за сети/5xx — пусть BaseTask повторит задачу.
            summary.status = SyncStatus.FAILED
            await self._write_summary_log(summary)
            raise retryable_error

        summary.status = SyncStatus.FAILED if summary.error_codes else SyncStatus.SUCCESS
        await self._write_summary_log(summary)
        logger.info(
            "sync finished user={} status={} new={} updated={} journals={} errors={}",
            user_id,
            summary.status,
            summary.new_grades,
            summary.updated_grades,
            len(summary.journals),
            len(summary.error_codes),
        )
        return summary

    async def _list_journals(self) -> list[JournalBrief]:
        year = academic_year()
        by_id: dict[int, JournalBrief] = {}
        for sem in (1, 2):
            operation = partial(self._client.list_journals, year=year, sem=sem)
            journals = await self._tokens.call(operation)
            for brief in journals:
                by_id.setdefault(brief.id, brief)
        return list(by_id.values())

    async def _sync_journal(self, user: UserSyncInfo, brief: JournalBrief) -> JournalSyncResult:
        edu_user_id = user.edu_user_id
        group_id = user.group_id
        if edu_user_id is None or group_id is None:
            message = f"У пользователя {user.id} нет edu_user_id или group_id"
            raise PermanentError(message)

        payload = await self._tokens.call(
            lambda token: self._cache.get_journal(
                token=token,
                journal_id=brief.id,
                group_id=group_id,
                edu_user_id=edu_user_id,
                fio=user.full_name,
            ),
        )
        lessons = payload.lessons_for(
            edu_user_id,
            fio=user.full_name,
            full_name=user.full_name,
        )
        incoming = [_normalized(lesson) for lesson in lessons]
        incoming = [lesson for lesson in incoming if not lesson.is_empty]

        existing = await GradesService.load_lesson_map(self._session, user.id, brief.id)
        new_lessons = [lesson for lesson in incoming if lesson.key not in existing]
        changed = [
            (existing[lesson.key], lesson)
            for lesson in incoming
            if lesson.key in existing and _grade_changed(existing[lesson.key], lesson)
        ]

        await upsert_and_link(self._session, user.id, brief)
        if new_lessons:
            await GradesService.insert_lessons(self._session, user.id, brief.id, new_lessons)
        for grade, lesson in changed:
            await GradesService.update_lesson(grade, lesson)
        await self._session.commit()

        return JournalSyncResult(
            journal_id=brief.id,
            name=brief.name,
            new_grades=len(new_lessons),
            updated_grades=len(changed),
        )

    async def _rollback(self) -> None:
        """Откатить незавершённую транзакцию журнала, чтобы следующий журнал записался."""
        try:
            await self._session.rollback()
        except Exception:  # noqa: BLE001 — откат не должен скрывать исходную ошибку
            logger.exception("sync rollback failed")

    async def _write_summary_log(self, summary: SyncSummary) -> None:
        message = f"journals={len(summary.journals)} errors={len(summary.error_codes)}"
        await write_sync_log(
            self._session,
            user_id=summary.user_id,
            sync_type=summary.sync_type,
            status=summary.status,
            new_grades_count=summary.new_grades,
            updated_grades_count=summary.updated_grades,
            message=message,
        )

    async def _log_failure(
        self,
        user_id: int,
        status: SyncStatus,
        code: str,
        summary: SyncSummary | None = None,
    ) -> None:
        await write_sync_log(
            self._session,
            user_id=user_id,
            sync_type=self._sync_type,
            status=status,
            new_grades_count=summary.new_grades if summary else 0,
            updated_grades_count=summary.updated_grades if summary else 0,
            message=f"failed: {code}",
        )
