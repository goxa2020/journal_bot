"""Кеш журналов и алгоритм подгрупп (docs/ARCHITECTURE.md §5.2).

Ключи:

* `journal:{group_id}:{journal_id}` — журнал группы;
* `journal:{group_id}:{journal_id}:sub:{md5(sorted(student_ids))[:8]}` — журнал подгруппы;
* `journal_legend:global` — легенда обозначений, 30 дней;
* `grade_values:global` — справочник значений `journalVal`, 30 дней.

Значение кеша содержит `student_ids`, поэтому чужой журнал не выдаётся за свой: студента
ищем по `edu_user_id`, а промах означает запрос к edu-tpi и запись нового кеша.
Redis передаётся снаружи (`task_redis` в задаче), глобальный клиент здесь не используется.
"""

from __future__ import annotations
import datetime as dt
import hashlib
from typing import TYPE_CHECKING, Any

from loguru import logger

from bot.cache.serialization import JSONSerializer
from bot.core.config import TIMEZONE
from bot.core.errors import EduEmptyJournalError, ParseError
from bot.integrations.models import JournalPayload, Lesson, StudentGrades

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from bot.integrations.edu_tpi import EduTpiClient

JOURNAL_TTL_SECONDS = 15 * 60
REFERENCE_TTL_SECONDS = 30 * 24 * 60 * 60
#: Маппинг `users.edu_user_id` → id строки `journalData` (W4). 30 дней: id студента
#: в журнале меняется ещё реже, чем TTL справочников.
STUDENT_ID_TTL_SECONDS = 30 * 24 * 60 * 60

LEGEND_KEY = "journal_legend:global"
GRADE_VALUES_KEY = "grade_values:global"


def student_key(edu_user_id: int) -> str:
    """Ключ маппинга id из `tokenauth` на id строки `journalData` (W4)."""
    return f"journal:student:{edu_user_id}"


def journal_key(group_id: int | None, journal_id: int) -> str:
    """Ключ журнала группы (без хвостового двоеточия — см. `build_key`)."""
    return f"journal:{group_id or 0}:{journal_id}"


def subgroup_key(base_key: str, student_ids: tuple[int, ...]) -> str:
    """Ключ журнала подгруппы: хеш списка студентов, а не случайный id."""
    digest = hashlib.md5(
        ",".join(str(student_id) for student_id in sorted(student_ids)).encode(),
        usedforsecurity=False,
    ).hexdigest()[:8]
    return f"{base_key}:sub:{digest}"


class JournalCache:
    """Читает журнал из Redis, а при промахе — из edu-tpi, и складывает обратно."""

    def __init__(
        self,
        redis: Redis,
        client: EduTpiClient,
        *,
        ttl: int = JOURNAL_TTL_SECONDS,
        reference_ttl: int = REFERENCE_TTL_SECONDS,
    ) -> None:
        self._redis = redis
        self._client = client
        self._ttl = ttl
        self._reference_ttl = reference_ttl

    async def get_journal(  # noqa: PLR0913
        self,
        *,
        token: str,
        journal_id: int,
        group_id: int | None,
        edu_user_id: int,
        fio: str | None = None,
        full_name: str | None = None,
    ) -> JournalPayload:
        """Журнал для студента: из кеша группы/подгруппы или запросом к edu-tpi."""
        base_key = journal_key(group_id, journal_id)
        empty_key = f"{base_key}:empty:{edu_user_id}"

        # Журнал чужой подгруппы (например, английский у второй подгруппы) API
        # отдаёт пустым. Запоминаем это на TTL, чтобы не ходить за ним каждый раз.
        if await self._redis.exists(empty_key):
            message = f"Журнал {journal_id} недоступен студенту {edu_user_id}"
            raise EduEmptyJournalError(message)

        cached = await self._find_in_cache(base_key, await self._candidate_ids(edu_user_id))
        if cached is not None:
            logger.debug("journal cache hit journal_id={} user_id={}", journal_id, edu_user_id)
            return cached

        try:
            payload = await self._client.get_journal(token, journal_id)
        except EduEmptyJournalError:
            await self._redis.set(empty_key, b"1", ex=self._ttl)
            raise
        # id из `tokenauth` может не совпадать с id строки `journalData`: ищем по
        # сохранённому маппингу и по ФИО, а найденный id запоминаем (W4).
        await self.resolve_student_id(payload, edu_user_id=edu_user_id, fio=fio, full_name=full_name)

        store_key = subgroup_key(base_key, payload.student_ids) if payload.is_subgroup else base_key
        await self._store(store_key, payload)
        if store_key != base_key:
            # Базовая запись — быстрый путь для повторного вызова того же студента;
            # подгруппы при этом остаются под своими ключами.
            await self._store(base_key, payload)
        await self.store_legend(payload.legend)
        await self.store_grade_values(payload)
        return payload

    async def resolve_student_id(
        self,
        payload: JournalPayload,
        *,
        edu_user_id: int,
        fio: str | None = None,
        full_name: str | None = None,
    ) -> int:
        """id строки журнала; заполняет маппинг, если студент найден по ФИО.

        Raises:
            ParseError: студента нет в журнале или ФИО совпало с несколькими строками.

        """
        student_id = await self.match_student(payload, edu_user_id=edu_user_id, fio=fio, full_name=full_name)
        if student_id is None:
            message = f"Студент {edu_user_id} не найден в журнале {payload.journal_id}"
            raise ParseError(message)
        return student_id

    async def match_student(
        self,
        payload: JournalPayload,
        *,
        edu_user_id: int,
        fio: str | None = None,
        full_name: str | None = None,
    ) -> int | None:
        """Найти студента, не падая на промахе; однозначное ФИО кешируется на 30 дней."""
        known_id = await self.get_student_id(edu_user_id)
        student_id = payload.resolve_student_id(edu_user_id, fio=fio, full_name=full_name, known_id=known_id)
        if student_id is None:
            if fio or full_name:
                # В лог — только id и журнал: ФИО и id строки журнала это ПДн.
                logger.warning(
                    "journal student ambiguous journal_id={} user_id={}",
                    payload.journal_id,
                    edu_user_id,
                )
            return None
        if student_id not in (edu_user_id, known_id):
            await self.store_student_id(edu_user_id, student_id)
        return student_id

    async def get_student_id(self, edu_user_id: int) -> int | None:
        """Сохранённый id строки `journalData`; `None`, если маппинга ещё нет."""
        raw = await self._redis.get(student_key(edu_user_id))
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            logger.warning("journal student map corrupt user_id={}", edu_user_id)
            return None

    async def store_student_id(self, edu_user_id: int, journal_user_id: int) -> None:
        """Запомнить id строки журнала; пишется только при однозначном совпадении."""
        await self._redis.set(student_key(edu_user_id), str(journal_user_id), ex=STUDENT_ID_TTL_SECONDS)

    async def _candidate_ids(self, edu_user_id: int) -> tuple[int, ...]:
        """Кого искать в кеше: сначала id из маппинга, затем id из `tokenauth`."""
        known_id = await self.get_student_id(edu_user_id)
        if known_id is None or known_id == edu_user_id:
            return (edu_user_id,)
        return (known_id, edu_user_id)

    async def _find_in_cache(self, base_key: str, candidate_ids: tuple[int, ...]) -> JournalPayload | None:
        payload = await self._load(base_key)
        if payload is not None and any(payload.has_student(student_id) for student_id in candidate_ids):
            return payload

        # Первый студент подгруппы пишет свой ключ; второй студент другой подгруппы
        # должен найти существующий кеш, а не идти в edu-tpi заново.
        prefix = f"{base_key}:sub:"
        async for raw_key in self._redis.scan_iter(match=f"{prefix}*"):
            key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
            payload = await self._load(key)
            if payload is not None and any(payload.has_student(student_id) for student_id in candidate_ids):
                return payload
        return None

    async def _load(self, key: str) -> JournalPayload | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        try:
            data = JSONSerializer.deserialize(raw)
            return _payload_from_dict(data)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            # Повреждённое значение не должно ломать синхронизацию: перезапишем его.
            logger.warning("journal cache corrupt key={} error={}", key, type(exc).__name__)
            return None

    async def _store(self, key: str, payload: JournalPayload) -> None:
        await self._redis.set(key, JSONSerializer.serialize(_payload_to_dict(payload)), ex=self._ttl)

    async def get_legend(self) -> dict[str, str]:
        raw = await self._redis.get(LEGEND_KEY)
        if raw is None:
            return {}
        try:
            data = JSONSerializer.deserialize(raw)
        except (TypeError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(key): str(value) for key, value in data.items()}

    async def store_legend(self, legend: dict[str, str]) -> None:
        if not legend:
            return
        existing = await self.get_legend()
        existing.update(legend)
        await self._redis.set(LEGEND_KEY, JSONSerializer.serialize(existing), ex=self._reference_ttl)

    async def get_grade_values(self) -> dict[str, dict[str, bool | int | None]]:
        raw = await self._redis.get(GRADE_VALUES_KEY)
        if raw is None:
            return {}
        try:
            data = JSONSerializer.deserialize(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    async def store_grade_values(self, payload: JournalPayload) -> None:
        """Пополнить глобальный справочник значений (30 дней, docs/ARCHITECTURE.md §4.2)."""
        known = await self.get_grade_values()
        changed = False
        for lesson in payload.iter_values():
            if not lesson.value:
                continue
            record = {
                "number_value": lesson.number_value,
                "is_mark": lesson.is_mark,
                "is_pass": lesson.is_pass,
                "is_valid_pass": lesson.is_valid_pass,
            }
            if known.get(lesson.value) != record:
                known[lesson.value] = record
                changed = True
        if changed:
            await self._redis.set(GRADE_VALUES_KEY, JSONSerializer.serialize(known), ex=self._reference_ttl)


def _payload_to_dict(payload: JournalPayload) -> dict[str, Any]:
    return {
        "journal_id": payload.journal_id,
        "is_subgroup": payload.is_subgroup,
        "synced_at": dt.datetime.now(TIMEZONE).isoformat(),
        "journal_name": payload.name,
        "teacher_name": payload.teacher_name,
        "type": payload.type,
        "year": payload.year,
        "student_ids": list(payload.student_ids),
        "legend": payload.legend,
        "grades": [
            {
                "student_id": student.student_id,
                "fio": student.fio,
                "full_name": student.full_name,
                "lessons": [
                    {
                        "date": lesson.date.isoformat(),
                        "hour_number": lesson.hour_number,
                        "edu_lesson_id": lesson.edu_lesson_id,
                        "value": lesson.value,
                        "number_value": lesson.number_value,
                        "is_mark": lesson.is_mark,
                        "is_pass": lesson.is_pass,
                        "is_valid_pass": lesson.is_valid_pass,
                    }
                    for lesson in student.lessons
                ],
            }
            for student in payload.students
        ],
    }


def _payload_from_dict(data: Any) -> JournalPayload:
    if not isinstance(data, dict):
        message = "journal cache value is not an object"
        raise TypeError(message)

    students: list[StudentGrades] = []
    for row in data["grades"]:
        lessons = tuple(
            Lesson(
                date=dt.date.fromisoformat(item["date"]),
                hour_number=int(item["hour_number"]),
                edu_lesson_id=int(item["edu_lesson_id"]),
                value=str(item["value"]),
                number_value=item.get("number_value"),
                is_mark=bool(item.get("is_mark")),
                is_pass=bool(item.get("is_pass")),
                is_valid_pass=bool(item.get("is_valid_pass")),
            )
            for item in row["lessons"]
        )
        students.append(
            StudentGrades(
                student_id=int(row["student_id"]),
                lessons=lessons,
                fio=str(row.get("fio", "")),
                full_name=str(row.get("full_name", "")),
            ),
        )

    return JournalPayload(
        journal_id=int(data["journal_id"]),
        name=str(data["journal_name"]),
        teacher_name=str(data.get("teacher_name", "")),
        type=str(data.get("type", "")),
        year=str(data.get("year", "")),
        is_subgroup=bool(data.get("is_subgroup")),
        students=tuple(students),
        legend={str(key): str(value) for key, value in (data.get("legend") or {}).items()},
    )
