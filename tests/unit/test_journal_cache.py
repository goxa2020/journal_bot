"""Кеш журналов и подгруппы (задача 2.3)."""

from __future__ import annotations
import datetime as dt
import hashlib

import pytest

from bot.core.errors import EduEmptyJournalError, ParseError
from bot.integrations.journal_cache import (
    GRADE_VALUES_KEY,
    LEGEND_KEY,
    JournalCache,
    journal_key,
    student_key,
    subgroup_key,
)
from bot.integrations.models import JournalPayload, Lesson, StudentGrades


class FakeClient:
    """Клиент, который отдаёт заранее заданные журналы и считает запросы."""

    def __init__(
        self,
        payloads: dict[str, JournalPayload],
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self._payloads = payloads
        self._errors = errors or {}
        self.calls: list[tuple[str, int]] = []

    async def get_journal(self, token: str, journal_id: int) -> JournalPayload:
        self.calls.append((token, journal_id))
        if token in self._errors:
            raise self._errors[token]
        return self._payloads[token]


def _payload(*, student_ids: tuple[int, ...], subgroup: bool, value: str = "4") -> JournalPayload:
    lessons = (
        Lesson(
            date=dt.date(2024, 9, 30),
            hour_number=1,
            edu_lesson_id=346734,
            value=value,
            number_value=4 if value.isdigit() else None,
            is_mark=value.isdigit(),
        ),
    )
    return JournalPayload(
        journal_id=27919,
        name="Программирование",
        teacher_name="Преподавателев П.П.",
        type="Лек",
        year="2024-2025",
        is_subgroup=subgroup,
        students=tuple(StudentGrades(student_id=student_id, lessons=lessons) for student_id in student_ids),
        legend={"Н": "Студент отсутствовал"},
    )


def _digest(student_ids: tuple[int, ...]) -> str:
    return hashlib.md5(
        ",".join(str(student_id) for student_id in sorted(student_ids)).encode(),
        usedforsecurity=False,
    ).hexdigest()[:8]


async def test_second_call_for_same_journal_does_not_hit_http(fake_redis) -> None:
    client = FakeClient({"token": _payload(student_ids=(1001,), subgroup=False)})
    cache = JournalCache(fake_redis, client)  # type: ignore[arg-type]

    first = await cache.get_journal(token="token", journal_id=27919, group_id=3273, edu_user_id=1001)
    second = await cache.get_journal(token="token", journal_id=27919, group_id=3273, edu_user_id=1001)

    assert len(client.calls) == 1
    assert first == second
    assert await fake_redis.ttl(journal_key(3273, 27919)) > 0


async def test_cache_value_contains_student_ids_and_ttl(fake_redis) -> None:
    client = FakeClient({"token": _payload(student_ids=(1001, 1002), subgroup=False)})
    cache = JournalCache(fake_redis, client)  # type: ignore[arg-type]

    await cache.get_journal(token="token", journal_id=27919, group_id=3273, edu_user_id=1001)

    key = journal_key(3273, 27919)
    ttl = await fake_redis.ttl(key)
    assert 0 < ttl <= 15 * 60
    raw = await fake_redis.get(key)
    assert raw is not None
    assert b"student_ids" in raw
    assert b"1001" in raw
    assert b"1002" in raw


async def test_subgroups_get_different_keys_and_are_reused(fake_redis) -> None:
    client = FakeClient(
        {
            "a": _payload(student_ids=(1001,), subgroup=True),
            "b": _payload(student_ids=(1002,), subgroup=True),
        },
    )
    cache = JournalCache(fake_redis, client)  # type: ignore[arg-type]

    await cache.get_journal(token="a", journal_id=27919, group_id=3273, edu_user_id=1001)
    await cache.get_journal(token="b", journal_id=27919, group_id=3273, edu_user_id=1002)

    base = journal_key(3273, 27919)
    assert len(client.calls) == 2
    assert await fake_redis.exists(f"{base}:sub:{_digest((1001,))}")
    assert await fake_redis.exists(f"{base}:sub:{_digest((1002,))}")
    assert _digest((1001,)) != _digest((1002,))

    # Третий вызов по первому студенту находит его подгруппу сканом, без HTTP.
    await cache.get_journal(token="a", journal_id=27919, group_id=3273, edu_user_id=1001)
    assert len(client.calls) == 2


async def test_legend_and_grade_values_are_global_with_long_ttl(fake_redis) -> None:
    client = FakeClient({"token": _payload(student_ids=(1001,), subgroup=False)})
    cache = JournalCache(fake_redis, client)  # type: ignore[arg-type]

    await cache.get_journal(token="token", journal_id=27919, group_id=3273, edu_user_id=1001)

    legend_ttl = await fake_redis.ttl(LEGEND_KEY)
    values_ttl = await fake_redis.ttl(GRADE_VALUES_KEY)
    assert legend_ttl > 29 * 24 * 60 * 60
    assert values_ttl > 29 * 24 * 60 * 60
    assert await cache.get_legend() == {"Н": "Студент отсутствовал"}
    assert (await cache.get_grade_values())["4"]["number_value"] == 4


async def test_subgroup_key_uses_hash_of_sorted_ids() -> None:
    base = journal_key(1, 2)
    assert subgroup_key(base, (1002, 1001)) == subgroup_key(base, (1001, 1002))
    assert subgroup_key(base, (1001,)) != subgroup_key(base, (1002,))


async def test_corrupt_cache_value_is_refetched(fake_redis) -> None:
    client = FakeClient({"token": _payload(student_ids=(1001,), subgroup=False)})
    cache = JournalCache(fake_redis, client)  # type: ignore[arg-type]
    await fake_redis.set(journal_key(3273, 27919), b"not-json")

    payload = await cache.get_journal(token="token", journal_id=27919, group_id=3273, edu_user_id=1001)

    assert payload.has_student(1001)
    assert len(client.calls) == 1


async def test_cached_journal_of_other_student_is_not_returned(fake_redis) -> None:
    client = FakeClient(
        {
            "a": _payload(student_ids=(1001,), subgroup=False),
            "b": _payload(student_ids=(1002,), subgroup=False),
        },
    )
    cache = JournalCache(fake_redis, client)  # type: ignore[arg-type]

    await cache.get_journal(token="a", journal_id=27919, group_id=3273, edu_user_id=1001)
    with pytest.raises(Exception, match="не найден"):
        # Кеш хранит только 1001; для 1002 клиент вернул журнал без него — ParseError.
        await cache.get_journal(token="a", journal_id=27919, group_id=3273, edu_user_id=1002)


async def test_empty_journal_is_negative_cached_for_that_student(fake_redis) -> None:
    client = FakeClient({}, errors={"token": EduEmptyJournalError("empty")})
    cache = JournalCache(fake_redis, client)  # type: ignore[arg-type]

    with pytest.raises(EduEmptyJournalError):
        await cache.get_journal(token="token", journal_id=27919, group_id=3273, edu_user_id=1001)
    with pytest.raises(EduEmptyJournalError):
        await cache.get_journal(token="token", journal_id=27919, group_id=3273, edu_user_id=1001)

    assert len(client.calls) == 1
    empty_key = f"{journal_key(3273, 27919)}:empty:1001"
    assert await fake_redis.exists(empty_key)
    assert await fake_redis.ttl(empty_key) > 0


NAME = "Студентов Степан Степанович"


def _named_payload(journal_id: int, students: tuple[StudentGrades, ...]) -> JournalPayload:
    return JournalPayload(
        journal_id=journal_id,
        name="Программирование",
        type="Лек",
        students=students,
        legend={"Н": "Студент отсутствовал"},
    )


def _student(student_id: int, *, full_name: str = NAME, fio: str = "Студентов С.С.") -> StudentGrades:
    return StudentGrades(
        student_id=student_id,
        lessons=(
            Lesson(
                date=dt.date(2024, 9, 30),
                hour_number=1,
                edu_lesson_id=346734,
                value="4",
                number_value=4,
                is_mark=True,
            ),
        ),
        fio=fio,
        full_name=full_name,
    )


async def test_redirected_student_id_is_mapped_and_gives_cache_hit(fake_redis) -> None:
    """W4: `tokenauth` id ≠ `journalData.id` — находим по ФИО и запоминаем id на 30 дней."""
    client = FakeClient({"token": _named_payload(27919, (_student(5001),))})
    cache = JournalCache(fake_redis, client)  # type: ignore[arg-type]

    await cache.get_journal(
        token="token",
        journal_id=27919,
        group_id=3273,
        edu_user_id=-22069,
        fio="Студентов С.С.",
        full_name=NAME,
    )

    assert await cache.get_student_id(-22069) == 5001
    ttl = await fake_redis.ttl(student_key(-22069))
    assert 29 * 24 * 60 * 60 < ttl <= 30 * 24 * 60 * 60

    # Повторный журнал того же студента берётся из кеша по маппингу, без HTTP.
    await cache.get_journal(
        token="token",
        journal_id=27919,
        group_id=3273,
        edu_user_id=-22069,
        fio="Студентов С.С.",
        full_name=NAME,
    )
    assert len(client.calls) == 1


async def test_ambiguous_full_name_does_not_create_mapping(fake_redis) -> None:
    """Однофамильцы: сопоставление неоднозначно — ошибка и никакого маппинга."""
    client = FakeClient({"token": _named_payload(27919, (_student(5001), _student(5002)))})
    cache = JournalCache(fake_redis, client)  # type: ignore[arg-type]

    with pytest.raises(ParseError):
        await cache.get_journal(
            token="token",
            journal_id=27919,
            group_id=3273,
            edu_user_id=-22069,
            fio="Студентов С.С.",
            full_name=NAME,
        )

    assert await fake_redis.exists(student_key(-22069)) == 0


async def test_known_mapping_is_used_before_full_name(fake_redis) -> None:
    """Сохранённый id строки журнала важнее ФИО: однофамилец не перехватит журнал."""
    await fake_redis.set(student_key(-22069), "5001")
    client = FakeClient({"token": _named_payload(27919, (_student(5001), _student(5002, full_name=NAME)))})
    cache = JournalCache(fake_redis, client)  # type: ignore[arg-type]

    student_id = await cache.resolve_student_id(
        _named_payload(27919, (_student(5001), _student(5002, full_name=NAME))),
        edu_user_id=-22069,
        full_name=NAME,
    )

    assert student_id == 5001
