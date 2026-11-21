"""Типизированные ответы edu-tpi (docs/API.md, docs/ARCHITECTURE.md §5.1).

Клиент отдаёт не сырой JSON, а эти объекты: парсер и кеш работают с полями, а не с
ключами словаря, поэтому изменение схемы API ловится в одном месте.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bot.core.errors import ParseError

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Iterable


@dataclass(frozen=True, slots=True)
class TokenInfo:
    """Ответ `POST /api/tokenauth` (docs/API.md §3)."""

    access_token: str
    #: `expiresIn` в минутах; `None`, если API не прислал поле.
    expires_in_minutes: float | None = None
    edu_user_id: int | None = None


@dataclass(frozen=True, slots=True)
class EduUser:
    """Ответ `GET /api/tokenauth` (docs/API.md §4)."""

    user_id: int
    group_id: int | None = None
    group_name: str | None = None
    fio: str | None = None
    full_name: str | None = None


@dataclass(frozen=True, slots=True)
class JournalBrief:
    """Строка `returnList` из `GET /api/Journals/JournalList` (docs/API.md §5)."""

    id: int
    name: str
    teacher_name: str = ""
    type: str = ""
    group_name: str | None = None
    year: str | None = None


@dataclass(frozen=True, slots=True)
class Lesson:
    """Одно занятие студента: ключ `(date, hour_number)` и значение из `journalVal`."""

    date: dt.date
    hour_number: int
    edu_lesson_id: int
    value: str
    number_value: int | None = None
    is_mark: bool = False
    is_pass: bool = False
    is_valid_pass: bool = False

    @property
    def key(self) -> tuple[dt.date, int]:
        """Ключ урока для дифа оценок (docs/ARCHITECTURE.md §8)."""
        return self.date, self.hour_number

    @property
    def is_empty(self) -> bool:
        """Пустая ячейка журнала: занятия нет или его не отметили."""
        return not self.value and not self.is_mark and not self.is_pass


@dataclass(frozen=True, slots=True)
class StudentGrades:
    """Строка студента журнала со всеми его занятиями."""

    student_id: int
    lessons: tuple[Lesson, ...] = ()
    fio: str = ""
    full_name: str = ""


@dataclass(frozen=True, slots=True)
class JournalPayload:
    """Разобранный ответ `GET /api/Journals/Journal` (docs/API.md §6)."""

    journal_id: int
    name: str
    teacher_name: str = ""
    type: str = ""
    year: str = ""
    is_subgroup: bool = False
    students: tuple[StudentGrades, ...] = ()
    legend: dict[str, str] = field(default_factory=dict)

    @property
    def student_ids(self) -> tuple[int, ...]:
        """ID студентов, которые есть в ответе: ключ алгоритма подгрупп."""
        return tuple(student.student_id for student in self.students)

    def has_student(self, edu_user_id: int) -> bool:
        return any(student.student_id == edu_user_id for student in self.students)

    def find_student(
        self,
        edu_user_id: int,
        *,
        fio: str | None = None,
        full_name: str | None = None,
    ) -> StudentGrades:
        """Найти строку студента по `edu_user_id`, при промахе — по ФИО.

        Порядок важен: в `journalData` порядок студентов не гарантирован
        (docs/API.md §6.2), а `id` — единственный надёжный ключ.
        """
        for student in self.students:
            if student.student_id == edu_user_id:
                return student

        for student in self.students:
            if fio and student.fio == fio:
                return student
            if full_name and student.full_name == full_name:
                return student

        message = f"Студент {edu_user_id} не найден в журнале {self.journal_id}"
        raise ParseError(message)

    def lessons_for(
        self,
        edu_user_id: int,
        *,
        fio: str | None = None,
        full_name: str | None = None,
    ) -> tuple[Lesson, ...]:
        return self.find_student(edu_user_id, fio=fio, full_name=full_name).lessons

    def iter_values(self) -> Iterable[Lesson]:
        """Все занятия всех студентов: источник справочника `grade_values`."""
        for student in self.students:
            yield from student.lessons
