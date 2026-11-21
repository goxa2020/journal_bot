"""Запрос списка журналов: только с оценками и по дате последней оценки (2.8)."""

from __future__ import annotations
import datetime as dt
from types import SimpleNamespace

from bot.services.grades import GradesService


class _Result:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return self._rows


class _Session:
    def __init__(self, rows: list[SimpleNamespace] | None = None) -> None:
        self.statement = None
        self._rows = rows or []

    async def execute(self, statement):
        self.statement = statement
        return _Result(self._rows)


async def test_list_journals_filters_marks_and_sorts_by_last_date() -> None:
    session = _Session()

    await GradesService.list_journals(session, 1)  # type: ignore[arg-type]

    sql = str(session.statement)
    assert "HAVING count(grades.number_value) >" in sql
    assert "ORDER BY max(grades.date) DESC" in sql


async def test_list_journals_maps_last_grade_date() -> None:
    row = SimpleNamespace(
        id=1,
        name="Английский язык",
        teacher_name="Преподавателев П.П.",
        type="Пр",
        grades_count=2,
        average=4.5,
        last_grade_date=dt.date(2026, 11, 20),
    )
    session = _Session([row])

    journals = await GradesService.list_journals(session, 1)  # type: ignore[arg-type]

    assert len(journals) == 1
    assert journals[0].last_grade_date == dt.date(2026, 11, 20)
    assert journals[0].average == 4.5
