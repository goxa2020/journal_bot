"""Синхронизация оценок: диф по ключу урока, upsert и `sync_logs` (задача 2.5).

Алгоритм (docs/ARCHITECTURE.md §8):

1. журналы текущего семестра через `EduTpiClient.list_journals` (кеш в `JournalCache`);
2. занятия студента из журнала, ключ — `(date, hour_number)`;
3. новые — вставка, изменённые — обновление с `updated_at`, пропавшие — **не удаляем**;
4. ошибка одного журнала не валит всю синхронизацию, кроме `EduAuthError`.

`value` из `journalVal` приходит с хвостовыми пробелами, поэтому значение
нормализуется `strip()` и при сравнении, и при сохранении.
"""

from __future__ import annotations
import dataclasses
import datetime as dt
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
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
from bot.services.users import load_group_members, load_user_sync_info

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession

    from bot.database.models import Grade
    from bot.integrations.edu_tpi import EduTpiClient
    from bot.integrations.journal_cache import JournalCache
    from bot.integrations.models import JournalBrief, JournalPayload, Lesson
    from bot.services.auth import TokenService
    from bot.services.users import UserSyncInfo

#: Как взять `sync:lock:{user_id}` воркера (задачи передают `task_lock`).
UserLockFactory = Callable[[int], "AbstractAsyncContextManager[bool]"]
#: Постановка фонового уведомления о новых оценках (`send_grade_notification.delay`).
GradeNotifier = Callable[[int, "Sequence[NewGradeNotice]"], None]


SEPTEMBER = 9
JANUARY = 1


def academic_year(today: dt.date | None = None) -> str:
    """Учебный год: с сентября `YYYY-(YYYY+1)`, иначе `(YYYY-1)-YYYY` (docs/API.md §1)."""
    current = today or dt.datetime.now(TIMEZONE).date()
    if current.month >= SEPTEMBER:
        return f"{current.year}-{current.year + 1}"
    return f"{current.year - 1}-{current.year}"


def current_semester(today: dt.date | None = None) -> int:
    """Текущий семестр: 1 — сентябрь–январь, 2 — февраль–август.

    Следующий семестр не запрашиваем: его журналы ещё пустые, а лишние запросы
    к edu-tpi тратят лимит. Оценки прошлых семестров остаются в БД.
    """
    current = today or dt.datetime.now(TIMEZONE).date()
    if current.month >= SEPTEMBER or current.month == JANUARY:
        return 1
    return 2


@dataclass(frozen=True, slots=True)
class NewGradeNotice:
    """Новая оценка, о которой нужно уведомить пользователя (задача 3.1).

    Ключ урока (`lesson_key`) — то же самое, что ключ дедупликации уведомлений:
    `journal_id:date:hour_number`. Он не хранится полем, а вычисляется, чтобы не
    разойтись с данными: ключ должен совпадать у постановки маркера и у проверки.
    """

    journal_id: int
    journal_name: str
    journal_type: str
    date: dt.date
    hour_number: int
    value: str
    number_value: int | None = None
    is_mark: bool = False
    is_pass: bool = False

    @property
    def lesson_key(self) -> str:
        """Ключ урока для `notify:sent:{user_id}:{lesson_key}`."""
        return f"{self.journal_id}:{self.date.isoformat()}:{self.hour_number}"

    def to_dict(self) -> dict[str, Any]:
        """JSON-безопасная запись для Redis и аргументов задачи Celery."""
        return {
            "journal_id": self.journal_id,
            "journal_name": self.journal_name,
            "journal_type": self.journal_type,
            "date": self.date.isoformat(),
            "hour_number": self.hour_number,
            "value": self.value,
            "number_value": self.number_value,
            "is_mark": self.is_mark,
            "is_pass": self.is_pass,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NewGradeNotice:
        """Восстановить уведомление из JSON-записи (`to_dict`)."""
        return cls(
            journal_id=int(data["journal_id"]),
            journal_name=str(data["journal_name"]),
            journal_type=str(data.get("journal_type") or ""),
            date=dt.date.fromisoformat(str(data["date"])),
            hour_number=int(data["hour_number"]),
            value=str(data.get("value") or ""),
            number_value=int(data["number_value"]) if data.get("number_value") is not None else None,
            is_mark=bool(data.get("is_mark")),
            is_pass=bool(data.get("is_pass")),
        )


@dataclass(slots=True)
class JournalSyncResult:
    """Итог по одному журналу: сколько нового/обновлённого и была ли ошибка."""

    journal_id: int
    name: str
    new_grades: int = 0
    updated_grades: int = 0
    error: str | None = None
    skipped: bool = False
    notices: list[NewGradeNotice] = field(default_factory=list)
    #: Были ли у пользователя оценки этого журнала до дифа (задача 4.2): первичный
    #: импорт не должен выглядеть как «новые оценки» в оппортунистической синхронизации.
    had_existing: bool = False


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
    #: Новые уроки с данными для сообщения (задача 3.1); в результат задачи не уходят.
    new_notices: list[NewGradeNotice] = field(default_factory=list)

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
            "new_notices": len(self.new_notices),
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
    """Синхронизация оценок одного пользователя.

    Диф одного журнала вынесен в :meth:`apply_payload`: его же использует групповая
    синхронизация (`bot/services/group_sync.py`) и оппортунистическая часть (задача 4.2),
    поэтому логика «новые/изменённые/upsert» существует в одном месте.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        session: AsyncSession,
        client: EduTpiClient,
        cache: JournalCache,
        tokens: TokenService,
        sync_type: SyncType = SyncType.MANUAL,
        opportunistic: bool = False,
        user_lock: UserLockFactory | None = None,
        notifier: GradeNotifier | None = None,
    ) -> None:
        self._session = session
        self._client = client
        self._cache = cache
        self._tokens = tokens
        self._sync_type = sync_type
        #: Обновлять других участников группы тем же журналом (задача 4.2).
        self._opportunistic = opportunistic
        #: Чужой `sync:lock` не трогаем: идёт ручная синхронизация этого пользователя.
        self._user_lock = user_lock
        self._notifier = notifier

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
            summary.new_notices.extend(result.notices)
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
        semester = current_semester()
        journals = await self._tokens.call(
            lambda token: self._client.list_journals(token, year=year, sem=semester),
        )
        # Список уже одного семестра; дубликаты на всякий случай убираем по id.
        return list({brief.id: brief for brief in journals}.values())

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
        result = await self.apply_payload(user, brief, payload)
        if self._opportunistic:
            await self._sync_group_peers(user, brief, payload)
        return result

    async def apply_payload(
        self,
        user: UserSyncInfo,
        brief: JournalBrief,
        payload: JournalPayload,
    ) -> JournalSyncResult:
        """Применить уже полученный журнал к одному пользователю и закоммитить.

        Используется и ручной синхронизацией (`sync_user`), и групповой (фаза 4):
        один запрос к edu-tpi обслуживает всю группу, а диф остаётся в одном месте.
        """
        edu_user_id = user.edu_user_id
        if edu_user_id is None or user.group_id is None:
            message = f"У пользователя {user.id} нет edu_user_id или group_id"
            raise PermanentError(message)

        lessons = payload.lessons_for(
            edu_user_id,
            fio=user.full_name,
            full_name=user.full_name,
        )
        incoming = [_normalized(lesson) for lesson in lessons]
        incoming = [lesson for lesson in incoming if not lesson.is_empty]

        existing = await GradesService.load_lesson_map(self._session, user.id, brief.id)
        had_existing = bool(existing)
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
            had_existing=had_existing,
            notices=[
                NewGradeNotice(
                    journal_id=brief.id,
                    journal_name=payload.name or brief.name,
                    journal_type=brief.type or payload.type,
                    date=lesson.date,
                    hour_number=lesson.hour_number,
                    value=lesson.value,
                    number_value=lesson.number_value,
                    is_mark=lesson.is_mark,
                    is_pass=lesson.is_pass,
                )
                for lesson in new_lessons
            ],
        )

    async def _sync_group_peers(
        self,
        user: UserSyncInfo,
        brief: JournalBrief,
        payload: JournalPayload,
    ) -> None:
        """Оппортунистическая синхронизация участников группы (задача 4.2).

        Журнал уже получен для текущего пользователя, поэтому остальным участникам
        группы в том же `payload` он достаётся без запроса к edu-tpi. Уведомляем только
        тех, у кого по этому журналу уже были оценки: первичный импорт молчит.
        """
        group_id = user.group_id
        if group_id is None:
            return

        student_ids = set(payload.student_ids)
        members = await load_group_members(self._session, group_id)

        for member in members:
            if member.id == user.id or member.edu_user_id is None or member.edu_user_id not in student_ids:
                continue
            try:
                async with self._member_lock(member.id) as acquired:
                    if not acquired:
                        logger.info("opportunistic skipped: locked user={}", member.id)
                        continue
                    peer_result = await self.apply_payload(member, brief, payload)
            except Exception:  # noqa: BLE001 — чужой журнал не должен валить синхронизацию
                await self._rollback()
                logger.exception("opportunistic sync failed user={} journal={}", member.id, brief.id)
                continue

            if peer_result.notices and peer_result.had_existing:
                self._notify(member.id, peer_result.notices)
            logger.info(
                "opportunistic sync user={} journal={} new={} updated={}",
                member.id,
                brief.id,
                peer_result.new_grades,
                peer_result.updated_grades,
            )

    @asynccontextmanager
    async def _member_lock(self, user_id: int) -> AsyncIterator[bool]:
        """`sync:lock` участника группы; без фабрики блокировок — «всегда свободен»."""
        if self._user_lock is None:
            yield True
            return
        async with self._user_lock(user_id) as acquired:
            yield acquired

    def _notify(self, user_id: int, notices: Sequence[NewGradeNotice]) -> None:
        """Поставить фоновое уведомление; ошибка брокера не отменяет сохранённые оценки."""
        if self._notifier is None:
            return
        try:
            self._notifier(user_id, notices)
        except Exception:  # noqa: BLE001 — данные уже в БД, уведомление вторично
            logger.exception("notification scheduling failed user={}", user_id)

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
