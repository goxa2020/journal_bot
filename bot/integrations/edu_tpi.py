"""Клиент edu-tpi: HTTP и разбор ответов в одном месте (docs/ARCHITECTURE.md §5.1).

Раньше это были два модуля с двойниками ошибок и собственными сессиями на каждый запрос
(`services/api_client.py` и `services/journal_parser.py`). Теперь:

* один `aiohttp.ClientSession` на задачу (создаётся в `async with EduTpiClient()`);
* типизированные ответы (`bot/integrations/models.py`), а не словари;
* ошибки — из `bot/core/errors.py`, по таблице docs/ARCHITECTURE.md §9;
* лимиты: не больше 5 запросов в секунду суммарно (Redis-счётчик `api:ratelimit:edu`)
  и пауза `min_journal_interval` между запросами деталей журнала в рамках клиента.
"""

from __future__ import annotations
import asyncio
import datetime as dt
import time
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Self

import aiohttp

from bot.core.errors import (
    EduAuthError,
    EduEmptyJournalError,
    EduRateLimitError,
    EduTokenExpired,
    EduUnavailableError,
    ParseError,
)
from bot.integrations.models import EduUser, JournalBrief, JournalPayload, Lesson, StudentGrades, TokenInfo

if TYPE_CHECKING:
    from redis.asyncio import Redis

BASE_URL = "https://edu-tpi.donstu.ru"
FP_URL = f"{BASE_URL}/api/UserInfo/Devices/RandomIdentity"
AUTH_URL = f"{BASE_URL}/api/tokenauth"
JOURNALS_URL = f"{BASE_URL}/api/Journals/JournalList"
JOURNAL_URL = f"{BASE_URL}/api/Journals/Journal"

TIMEOUT = aiohttp.ClientTimeout(total=60)
RATE_LIMIT_KEY = "api:ratelimit:edu"
#: Сколько запросов в секунду разрешено суммарно по всем задачам.
MAX_REQUESTS_PER_SECOND = 5
#: Пауза между запросами деталей журнала в рамках одного токена (docs/ARCHITECTURE.md §5.1).
MIN_JOURNAL_INTERVAL = 1.0


def parse_iso_date(value: str) -> dt.date:
    """Дата из `journalDates`; API иногда присылает `2024-09-30T000000`."""
    return dt.datetime.fromisoformat(value.replace("T000000", "T00:00:00")).date()


def _as_int(value: object) -> int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, str, float)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, str, float)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        message = "В ответе edu-tpi нет объекта data"
        raise ParseError(message)
    return data


def parse_journal(payload: dict[str, Any], *, journal_id: int) -> JournalPayload:  # noqa: C901, PLR0912, PLR0915
    """Разобрать `GET /api/Journals/Journal` (docs/API.md §6).

    Значение ячейки обязательно `strip()`: в `journalVal.value` приходят хвостовые
    пробелы, из-за которых диф всегда видел бы «новую» оценку (docs/ARCHITECTURE.md §8).
    """
    data = _data(payload)

    raw_values = data.get("journalVal")
    raw_students = data.get("journalData")
    raw_dates = data.get("journalDates")
    if not isinstance(raw_values, list) or not isinstance(raw_students, list) or not isinstance(raw_dates, list):
        message = "Неожиданная структура журнала: нет journalVal/journalData/journalDates"
        raise ParseError(message)

    values: dict[int, dict[str, Any]] = {}
    for item in raw_values:
        if not isinstance(item, dict):
            message = "Неожиданная структура journalVal"
            raise ParseError(message)
        value_id = _as_int(item.get("id"))
        if value_id is not None:
            values[value_id] = item

    dates: list[tuple[int, dt.date, int]] = []
    for item in raw_dates:
        if not isinstance(item, dict):
            message = "Неожиданная структура journalDates"
            raise ParseError(message)
        date_id = _as_int(item.get("dateID"))
        raw_date = item.get("date")
        hour_number = _as_int(item.get("hourNumber"))
        if date_id is None or not isinstance(raw_date, str) or hour_number is None:
            message = "В journalDates не хватает dateID/date/hourNumber"
            raise ParseError(message)
        try:
            lesson_date = parse_iso_date(raw_date)
        except ValueError as exc:
            message = f"Не удалось разобрать дату занятия: {raw_date!r}"
            raise ParseError(message) from exc
        dates.append((date_id, lesson_date, hour_number))

    students: list[StudentGrades] = []
    for row in raw_students:
        if not isinstance(row, dict):
            message = "Неожиданная структура journalData"
            raise ParseError(message)
        student_id = _as_int(row.get("id"))
        if student_id is None:
            # Служебная строка без id бесполезна, но и падать из-за неё нельзя.
            continue

        lessons: list[Lesson] = []
        for date_id, lesson_date, hour_number in dates:
            raw_cell = row.get(str(date_id))
            if raw_cell is None:
                continue
            value_id = _as_int(raw_cell)
            if value_id is None:
                continue
            value_obj = values.get(value_id)
            if value_obj is None:
                continue

            display_value = _as_str(value_obj.get("value"))
            is_mark = bool(value_obj.get("isMark"))
            is_pass = bool(value_obj.get("isPass"))
            number_value = _as_int(value_obj.get("numberValue")) if is_mark else None
            lessons.append(
                Lesson(
                    date=lesson_date,
                    hour_number=hour_number,
                    edu_lesson_id=date_id,
                    value=display_value,
                    number_value=number_value,
                    is_mark=is_mark,
                    is_pass=is_pass,
                    is_valid_pass=display_value in {"У", "Б"},
                ),
            )

        lessons.sort(key=lambda lesson: (lesson.date, lesson.hour_number))
        students.append(
            StudentGrades(
                student_id=student_id,
                lessons=tuple(lessons),
                fio=_as_str(row.get("fio")),
                full_name=_as_str(row.get("fullName")),
            ),
        )

    info = data.get("journalInfo")
    info = info if isinstance(info, dict) else {}
    name = _as_str(info.get("dis"))
    if not name:
        message = "В ответе журнала нет названия дисциплины"
        raise ParseError(message)

    legend_raw = data.get("journalLegend")
    legend: dict[str, str] = {}
    if isinstance(legend_raw, dict):
        legend = {_as_str(key): _as_str(value) for key, value in legend_raw.items() if _as_str(key)}

    return JournalPayload(
        journal_id=journal_id,
        name=name,
        teacher_name=_as_str(info.get("teacherName")),
        type=_as_str(info.get("type")),
        year=_as_str(info.get("year")),
        is_subgroup=bool(data.get("isSubGroup")),
        students=tuple(students),
        legend=legend,
    )


class EduTpiClient:
    """HTTP-клиент edu-tpi с типизированными ответами и лимитами.

    Клиент можно использовать как контекстный менеджер: `async with EduTpiClient() as client`.
    Сессия создаётся на время задачи и закрывается вместе с клиентом; переданная снаружи
    сессия не закрывается.
    """

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession | None = None,
        redis: Redis | None = None,
        min_journal_interval: float = MIN_JOURNAL_INTERVAL,
        max_requests_per_second: int = MAX_REQUESTS_PER_SECOND,
    ) -> None:
        self._session = session
        self._owns_session = session is None
        self._redis = redis
        self._min_journal_interval = min_journal_interval
        self._max_rps = max_requests_per_second
        self._last_journal_at = 0.0

    async def __aenter__(self) -> Self:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=TIMEOUT)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
        self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            message = "EduTpiClient используется вне async with"
            raise RuntimeError(message)
        return self._session

    async def _acquire_global_slot(self) -> None:
        """Глобальный лимит 5 запросов/с через Redis-счётчик (docs/ARCHITECTURE.md §5.3)."""
        if self._redis is None:
            return

        for _ in range(50):
            count = int(await self._redis.incr(RATE_LIMIT_KEY))
            if count == 1:
                await self._redis.expire(RATE_LIMIT_KEY, 1)
            if count <= self._max_rps:
                return
            await asyncio.sleep(0.05)

        message = "Превышен глобальный лимит запросов к edu-tpi"
        raise EduRateLimitError(message, retry_after=1)

    async def _wait_journal_interval(self) -> None:
        """Пауза между запросами деталей журнала в рамках одного токена."""
        if self._min_journal_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_journal_at
        remaining = self._min_journal_interval - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)
        self._last_journal_at = time.monotonic()

    async def _request(  # noqa: C901, PLR0913
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        params: dict[str, str] | None = None,
        json_body: dict[str, str] | None = None,
        auth_request: bool = False,
    ) -> dict[str, Any]:
        await self._acquire_global_slot()
        headers = {"Authorization": f"Bearer {token}"} if token else None

        try:
            async with self.session.request(method, url, params=params, json=json_body, headers=headers) as response:
                status = int(response.status)
                if status == HTTPStatus.TOO_MANY_REQUESTS:
                    retry_after = self._retry_after(response)
                    message = f"edu-tpi ограничил запросы: {status}"
                    raise EduRateLimitError(message, retry_after=retry_after)
                if status in {HTTPStatus.BAD_REQUEST, HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
                    if auth_request:
                        message = f"Неверные учётные данные edu-tpi: {status}"
                        raise EduAuthError(message)
                    if status == HTTPStatus.UNAUTHORIZED:
                        message = "Токен edu-tpi истёк или отозван"
                        raise EduTokenExpired(message)
                    if status == HTTPStatus.FORBIDDEN:
                        message = f"Доступ к edu-tpi запрещён: {status}"
                        raise EduAuthError(message)
                    message = f"Неожиданный ответ edu-tpi: {status}"
                    raise ParseError(message)
                if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
                    message = f"edu-tpi недоступен: {status}"
                    raise EduUnavailableError(message)
                if status >= HTTPStatus.BAD_REQUEST:
                    message = f"Неожиданный ответ edu-tpi: {status}"
                    raise ParseError(message)
                try:
                    payload = await response.json(content_type=None)
                except ValueError as exc:
                    message = "edu-tpi вернул не JSON"
                    raise ParseError(message) from exc
        except (aiohttp.ClientError, TimeoutError) as exc:
            message = f"Сеть или таймаут edu-tpi: {type(exc).__name__}"
            raise EduUnavailableError(message) from exc

        if not isinstance(payload, dict):
            message = "edu-tpi вернул JSON не того типа"
            raise ParseError(message)
        return payload

    @staticmethod
    def _retry_after(response: aiohttp.ClientResponse) -> int | None:
        raw = response.headers.get("Retry-After") if response.headers else None
        return _as_int(raw)

    async def get_fingerprint(self) -> str:
        """`GET /api/UserInfo/Devices/RandomIdentity` (docs/API.md §2)."""
        payload = await self._request("GET", FP_URL)
        fingerprint = _data(payload).get("randomIdentity")
        if not isinstance(fingerprint, str) or not fingerprint:
            message = "В ответе нет randomIdentity"
            raise ParseError(message)
        return fingerprint

    async def authorize(self, login: str, password: str) -> TokenInfo:
        """`POST /api/tokenauth`: войти и получить `accessToken` (docs/API.md §3)."""
        fingerprint = await self.get_fingerprint()
        payload = await self._request(
            "POST",
            AUTH_URL,
            json_body={"userName": login, "password": password, "fingerprint": fingerprint},
            auth_request=True,
        )
        data = _data(payload)
        access_token = data.get("accessToken")
        if not isinstance(access_token, str) or not access_token:
            message = "В ответе входа нет accessToken"
            raise EduAuthError(message)
        return TokenInfo(
            access_token=access_token,
            expires_in_minutes=_as_float(data.get("expiresIn")),
            edu_user_id=_as_int(data.get("id")),
        )

    async def get_user_info(self, token: str) -> EduUser:
        """`GET /api/tokenauth`: кто я и в какой группе (docs/API.md §4).

        Успех — `state: 1`. Если `state` другой (например, `-1` — токен отозван),
        API отвечает `200` с `data: null`: это не «битая схема», а недействительные
        данные входа, поэтому `EduAuthError` (как 401/403), а не `ParseError`.
        """
        payload = await self._request("GET", AUTH_URL, token=token)
        state = payload.get("state")
        if state != 1:
            message = f"edu-tpi отклонил токен: state={state!r}"
            raise EduAuthError(message)
        data = _data(payload)
        raw_user = data.get("user")
        if not isinstance(raw_user, dict):
            message = "В ответе нет объекта user"
            raise ParseError(message)
        user_id = _as_int(raw_user.get("userID"))
        if user_id is None:
            message = "В ответе нет user.userID"
            raise ParseError(message)
        return EduUser(
            user_id=user_id,
            group_id=_as_int(raw_user.get("groupID")),
            group_name=_as_str(raw_user.get("group")) or None,
            fio=_as_str(raw_user.get("fio")) or None,
            full_name=_as_str(raw_user.get("fullName")) or None,
        )

    async def list_journals(self, token: str, year: str, sem: int) -> list[JournalBrief]:
        """`GET /api/Journals/JournalList` (docs/API.md §5)."""
        payload = await self._request(
            "GET",
            JOURNALS_URL,
            token=token,
            params={
                "prepID": "undefined",
                "groupID": "undefined",
                "typeJournal": "1",
                "year": year,
                "sem": str(sem),
            },
        )
        data = _data(payload)
        rows = data.get("returnList")
        if not isinstance(rows, list):
            message = "В ответе нет списка журналов returnList"
            raise ParseError(message)

        journals: list[JournalBrief] = []
        for row in rows:
            if not isinstance(row, dict):
                message = "Неожиданная структура списка журналов"
                raise ParseError(message)
            journal_id = _as_int(row.get("id"))
            name = _as_str(row.get("dis"))
            if journal_id is None or not name:
                continue
            journals.append(
                JournalBrief(
                    id=journal_id,
                    name=name,
                    teacher_name=_as_str(row.get("prepodName")) or _as_str(row.get("prepName")),
                    type=_as_str(row.get("type")),
                    group_name=_as_str(row.get("groupName")) or None,
                    year=_as_str(row.get("year")) or year,
                ),
            )

        if rows and not journals:
            message = "Ни одна строка списка журналов не содержит id и названия"
            raise ParseError(message)
        return journals

    async def get_journal(self, token: str, journal_id: int) -> JournalPayload:
        """`GET /api/Journals/Journal`: весь журнал группы/подгруппы (docs/API.md §6)."""
        await self._wait_journal_interval()
        payload = await self._request("GET", JOURNAL_URL, token=token, params={"journalID": str(journal_id)})
        # Некоторые архивные журналы есть в списке, но API отдаёт `state: -2, data: null`.
        # Это не ошибка схемы: пропускаем журнал, а не валим всю синхронизацию.
        state = payload.get("state")
        if payload.get("data") is None and isinstance(state, int) and state != 1:
            message = f"Журнал {journal_id} пуст (state={state})"
            raise EduEmptyJournalError(message)
        parsed = parse_journal(payload, journal_id=journal_id)
        if not parsed.students:
            message = f"В журнале {journal_id} нет студентов"
            raise EduEmptyJournalError(message)
        return parsed
