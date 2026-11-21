"""Клиент edu-tpi: маппинг кодов, таймаутов и разбор фикстур (задача 2.2).

Сети нет: `aiohttp.ClientSession` заменён `tests.fakes.FakeSession`.
"""

from __future__ import annotations

import aiohttp
import pytest

from tests.fakes import FakeResponse, install_session, load_fixture

from bot.core.errors import (
    EduAuthError,
    EduEmptyJournalError,
    EduRateLimitError,
    EduTokenExpired,
    EduUnavailableError,
    ParseError,
)
from bot.integrations.edu_tpi import (
    AUTH_URL,
    FP_URL,
    JOURNAL_URL,
    JOURNALS_URL,
    EduTpiClient,
    parse_journal,
)


def test_parse_journal_maps_students_lessons_and_flags() -> None:
    payload = parse_journal(load_fixture("journal_detail.json"), journal_id=27919)

    assert payload.journal_id == 27919
    assert payload.name == "Программирование"
    assert payload.teacher_name == "Преподавателев П.П."
    assert payload.type == "Лек"
    assert payload.is_subgroup is False
    assert payload.student_ids == (1001, 1002)

    first = payload.find_student(1001)
    # Значение "Н  " из journalVal обязано прийти без хвостовых пробелов.
    assert [lesson.value for lesson in first.lessons] == ["4", "Н"]
    assert [lesson.hour_number for lesson in first.lessons] == [1, 2]
    assert [lesson.edu_lesson_id for lesson in first.lessons] == [346734, 346950]
    assert first.lessons[0].is_mark is True
    assert first.lessons[0].number_value == 4
    assert first.lessons[1].is_pass is True
    assert first.lessons[1].number_value is None
    assert first.lessons[1].is_valid_pass is False

    second = payload.find_student(1002)
    assert second.lessons[0].is_empty is True
    assert second.lessons[1].value == "У"
    assert second.lessons[1].is_valid_pass is True

    # Легенда: ключи без пробелов, описания из ответа.
    assert payload.legend["Н"] == "Студент отсутствовал"
    assert payload.legend["У"] == "Уважительная причина"


def test_parse_journal_handles_subgroup_and_broken_date_format() -> None:
    payload = parse_journal(load_fixture("journal_detail_subgroup.json"), journal_id=27919)

    assert payload.is_subgroup is True
    assert payload.student_ids == (1001,)
    assert payload.find_student(1001).lessons[0].date.isoformat() == "2024-09-30"


def test_parse_journal_raises_parse_error_on_broken_schema() -> None:
    with pytest.raises(ParseError):
        parse_journal({"data": {"journalID": 1}}, journal_id=1)


async def test_authorize_returns_typed_token(monkeypatch: pytest.MonkeyPatch) -> None:
    install_session(
        monkeypatch,
        {
            ("GET", FP_URL): FakeResponse(payload=load_fixture("fingerprint.json")),
            ("POST", AUTH_URL): FakeResponse(payload=load_fixture("token.json")),
        },
    )

    async with EduTpiClient() as client:
        token = await client.authorize("student@donstu.ru", "secret")

    assert token.access_token == "token-123"
    assert token.expires_in_minutes == 10080.0
    assert token.edu_user_id == 1001


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_authorize_maps_auth_statuses_to_auth_error(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    install_session(
        monkeypatch,
        {
            ("GET", FP_URL): FakeResponse(payload=load_fixture("fingerprint.json")),
            ("POST", AUTH_URL): FakeResponse(status=status),
        },
    )

    async with EduTpiClient() as client:
        with pytest.raises(EduAuthError):
            await client.authorize("student@donstu.ru", "secret")


async def test_authorize_without_token_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    install_session(
        monkeypatch,
        {
            ("GET", FP_URL): FakeResponse(payload=load_fixture("fingerprint.json")),
            ("POST", AUTH_URL): FakeResponse(payload={"data": {"expiresIn": 100}}),
        },
    )

    async with EduTpiClient() as client:
        with pytest.raises(EduAuthError):
            await client.authorize("student@donstu.ru", "secret")


async def test_protected_401_raises_token_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    install_session(monkeypatch, {("GET", AUTH_URL): FakeResponse(status=401)})

    async with EduTpiClient() as client:
        with pytest.raises(EduTokenExpired):
            await client.get_user_info("token")


async def test_protected_403_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    install_session(monkeypatch, {("GET", AUTH_URL): FakeResponse(status=403)})

    async with EduTpiClient() as client:
        with pytest.raises(EduAuthError):
            await client.get_user_info("token")


async def test_rate_limit_carries_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    install_session(
        monkeypatch,
        {("GET", AUTH_URL): FakeResponse(status=429, headers={"Retry-After": "7"})},
    )

    async with EduTpiClient() as client:
        with pytest.raises(EduRateLimitError) as exc_info:
            await client.get_user_info("token")

    assert exc_info.value.retry_after == 7


async def test_server_error_maps_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    install_session(monkeypatch, {("GET", AUTH_URL): FakeResponse(status=503)})

    async with EduTpiClient() as client:
        with pytest.raises(EduUnavailableError):
            await client.get_user_info("token")


async def test_timeout_maps_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    install_session(monkeypatch, {("GET", AUTH_URL): TimeoutError()})

    async with EduTpiClient() as client:
        with pytest.raises(EduUnavailableError):
            await client.get_user_info("token")


async def test_network_error_maps_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    install_session(monkeypatch, {("GET", AUTH_URL): aiohttp.ClientConnectionError("refused")})

    async with EduTpiClient() as client:
        with pytest.raises(EduUnavailableError):
            await client.get_user_info("token")


async def test_broken_json_maps_to_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    install_session(monkeypatch, {("GET", AUTH_URL): FakeResponse(bad_json=True)})

    async with EduTpiClient() as client:
        with pytest.raises(ParseError):
            await client.get_user_info("token")


async def test_list_journals_returns_briefs(monkeypatch: pytest.MonkeyPatch) -> None:
    install_session(
        monkeypatch,
        {("GET", JOURNALS_URL): FakeResponse(payload=load_fixture("journal_list.json"))},
    )

    async with EduTpiClient() as client:
        journals = await client.list_journals("token", "2025-2026", 1)

    assert [journal.id for journal in journals] == [27919, 27920]
    assert journals[0].name == "Программирование"
    assert journals[0].teacher_name == "Преподавателев П.П."


async def test_list_journals_broken_schema_raises_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    install_session(monkeypatch, {("GET", JOURNALS_URL): FakeResponse(payload={"data": {"returnList": "no"}})})

    async with EduTpiClient() as client:
        with pytest.raises(ParseError):
            await client.list_journals("token", "2025-2026", 1)


async def test_get_journal_returns_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    install_session(
        monkeypatch,
        {("GET", JOURNAL_URL): FakeResponse(payload=load_fixture("journal_detail.json"))},
    )

    async with EduTpiClient(min_journal_interval=0) as client:
        payload = await client.get_journal("token", 27919)

    assert payload.name == "Программирование"
    assert payload.student_ids == (1001, 1002)


async def test_get_journal_without_data_raises_empty_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Архивный журнал: `state: -2, data: null` — пропуск, а не ParseError."""
    install_session(
        monkeypatch,
        {("GET", JOURNAL_URL): FakeResponse(payload={"state": -2, "data": None, "msg": "empty"})},
    )

    async with EduTpiClient(min_journal_interval=0) as client:
        with pytest.raises(EduEmptyJournalError):
            await client.get_journal("token", 32053)
