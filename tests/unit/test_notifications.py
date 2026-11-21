"""Политика уведомлений: день/ночь, настройки, дедупликация (задачи 3.1–3.4).

Сеть и Telegram здесь не участвуют: сервис только решает и хранит маркеры/очередь.
"""

from __future__ import annotations
import datetime as dt
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

from bot.core.config import TIMEZONE
from bot.services.grade_sync import NewGradeNotice
from bot.services.notifications import (
    MORNING_TIME_PRESETS,
    NotificationKind,
    NotificationService,
    is_night,
    next_morning,
    next_morning_preset,
    night_key,
    night_scheduled_key,
    sent_key,
    unique_notices,
)
from bot.services.users import NotificationSettings
from bot.utils.formatters import format_new_grades
from bot.utils.translations import translate

if TYPE_CHECKING:
    import pytest

DAY = dt.datetime(2026, 11, 22, 12, 0, tzinfo=TIMEZONE)
NIGHT = dt.datetime(2026, 11, 22, 23, 0, tzinfo=TIMEZONE)
LATE_NIGHT = dt.datetime(2026, 11, 23, 3, 0, tzinfo=TIMEZONE)
MORNING = dt.datetime(2026, 11, 23, 6, 0, tzinfo=TIMEZONE)


def _notice(
    *,
    journal_id: int = 10,
    hour: int = 1,
    value: str = "5",
    date: dt.date = dt.date(2026, 11, 20),
    name: str = "Программирование",
) -> NewGradeNotice:
    return NewGradeNotice(
        journal_id=journal_id,
        journal_name=name,
        journal_type="Лек",
        date=date,
        hour_number=hour,
        value=value,
        number_value=5 if value.isdigit() else None,
        is_mark=value.isdigit(),
        is_pass=not value.isdigit(),
    )


def _settings(
    *,
    enabled: bool = True,
    morning_enabled: bool = True,
    morning_time: dt.time = dt.time(8, 0),
    language: str | None = "ru",
) -> NotificationSettings:
    return NotificationSettings(
        enabled=enabled,
        morning_enabled=morning_enabled,
        morning_time=morning_time,
        language_code=language,
    )


def _patch_now(monkeypatch: pytest.MonkeyPatch, moment: dt.datetime) -> None:
    monkeypatch.setattr("bot.services.notifications.now", lambda: moment)


def _service(
    monkeypatch: pytest.MonkeyPatch,
    redis: Any,
    settings: NotificationSettings | None,
) -> tuple[NotificationService, AsyncMock]:
    loader = AsyncMock(return_value=settings)
    monkeypatch.setattr("bot.services.notifications.load_notification_settings", loader)
    service = NotificationService(redis=redis, session=AsyncMock(), user_id=1)
    return service, loader


async def test_day_sends_immediately(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    _patch_now(monkeypatch, DAY)
    service, _ = _service(monkeypatch, fake_redis, _settings())
    notice = _notice()

    decision = await service.decide([notice])

    assert decision.kind is NotificationKind.IMMEDIATE
    assert decision.notices == [notice]
    assert decision.language_code == "ru"
    assert decision.morning_at is None


async def test_night_collects_until_morning(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    _patch_now(monkeypatch, NIGHT)
    service, _ = _service(monkeypatch, fake_redis, _settings(morning_time=dt.time(8, 0)))

    decision = await service.decide([_notice()])

    assert decision.kind is NotificationKind.NIGHT
    assert decision.morning_at == dt.datetime(2026, 11, 23, 8, 0, tzinfo=TIMEZONE)
    assert decision.night_expires_at == dt.datetime(2026, 11, 23, 10, 0, tzinfo=TIMEZONE)


async def test_night_without_accumulation_sends_immediately(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    _patch_now(monkeypatch, NIGHT)
    service, _ = _service(monkeypatch, fake_redis, _settings(morning_enabled=False))

    decision = await service.decide([_notice()])

    assert decision.kind is NotificationKind.IMMEDIATE


async def test_disabled_notifications_send_nothing(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    _patch_now(monkeypatch, DAY)
    service, _ = _service(monkeypatch, fake_redis, _settings(enabled=False))

    decision = await service.decide([_notice()])

    assert decision.kind is NotificationKind.NONE
    assert decision.notices == []


async def test_empty_batch_does_not_touch_the_database(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    service, loader = _service(monkeypatch, fake_redis, _settings())

    decision = await service.decide([])

    assert decision.kind is NotificationKind.NONE
    loader.assert_not_awaited()


async def test_duplicate_lesson_is_not_notified_twice(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    _patch_now(monkeypatch, DAY)
    service, _ = _service(monkeypatch, fake_redis, _settings())
    notice = _notice()

    await service.mark([notice])
    decision = await service.decide([notice])

    assert decision.kind is NotificationKind.NONE
    ttl = await fake_redis.ttl(sent_key(1, notice.lesson_key))
    assert ttl > 6 * 24 * 60 * 60


async def test_only_unmarked_lessons_are_notified(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    _patch_now(monkeypatch, DAY)
    service, _ = _service(monkeypatch, fake_redis, _settings())
    sent, fresh = _notice(hour=1), _notice(hour=2)

    await service.mark([sent])
    decision = await service.decide([sent, fresh])

    assert decision.kind is NotificationKind.IMMEDIATE
    assert decision.notices == [fresh]


async def test_unmark_allows_the_retry_to_send_again(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    _patch_now(monkeypatch, DAY)
    service, _ = _service(monkeypatch, fake_redis, _settings())
    notice = _notice()

    await service.mark([notice])
    await service.unmark([notice])

    decision = await service.decide([notice])
    assert decision.kind is NotificationKind.IMMEDIATE


async def test_morning_already_passed_moves_to_tomorrow(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    # 07:30 — ещё ночь, но 07:00 уже прошло: ближайшее утро — завтра.
    _patch_now(monkeypatch, dt.datetime(2026, 11, 23, 7, 30, tzinfo=TIMEZONE))
    service, _ = _service(monkeypatch, fake_redis, _settings(morning_time=dt.time(7, 0)))

    decision = await service.decide([_notice()])

    assert decision.kind is NotificationKind.NIGHT
    assert decision.morning_at == dt.datetime(2026, 11, 24, 7, 0, tzinfo=TIMEZONE)


async def test_morning_ahead_is_today(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    _patch_now(monkeypatch, LATE_NIGHT)
    service, _ = _service(monkeypatch, fake_redis, _settings(morning_time=dt.time(8, 0)))

    decision = await service.decide([_notice()])

    assert decision.morning_at == dt.datetime(2026, 11, 23, 8, 0, tzinfo=TIMEZONE)


async def test_push_and_pop_night_roundtrip(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    _patch_now(monkeypatch, NIGHT)
    service, _ = _service(monkeypatch, fake_redis, _settings())
    notices = [_notice(hour=1), _notice(hour=2, value="4")]

    pushed = await service.push_night(notices, expires_at=NIGHT + dt.timedelta(hours=11))
    assert pushed == 2
    assert await fake_redis.ttl(night_key(1)) > 0

    assert await service.pop_night() == notices
    assert await service.pop_night() == []
    assert await fake_redis.lrange(night_key(1), 0, -1) == []


async def test_push_night_does_not_duplicate_existing_records(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis,
) -> None:
    _patch_now(monkeypatch, NIGHT)
    service, _ = _service(monkeypatch, fake_redis, _settings())
    notice = _notice()

    await service.push_night([notice], expires_at=NIGHT + dt.timedelta(hours=11))
    pushed = await service.push_night([notice], expires_at=NIGHT + dt.timedelta(hours=11))

    assert pushed == 0
    assert len(await fake_redis.lrange(night_key(1), 0, -1)) == 1


async def test_night_schedule_is_claimed_once(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    _patch_now(monkeypatch, NIGHT)
    service, _ = _service(monkeypatch, fake_redis, _settings())
    expires_at = NIGHT + dt.timedelta(hours=11)

    assert await service.claim_night_schedule(expires_at=expires_at) is True
    assert await service.claim_night_schedule(expires_at=expires_at) is False

    await service.release_night_schedule()
    assert await service.claim_night_schedule(expires_at=expires_at) is True
    assert await fake_redis.exists(night_scheduled_key(1)) == 1


async def test_blocked_user_gets_notifications_disabled(monkeypatch: pytest.MonkeyPatch, fake_redis) -> None:
    service, _ = _service(monkeypatch, fake_redis, _settings())
    setter = AsyncMock()
    monkeypatch.setattr("bot.services.notifications.set_notification_enabled", setter)

    await service.disable_notifications()

    setter.assert_awaited_once()
    assert setter.await_args.args[1] == 1
    assert setter.await_args.kwargs["enabled"] is False


def test_night_boundaries() -> None:
    def at(hour: int, minute: int = 0) -> dt.datetime:
        return dt.datetime(2026, 11, 22, hour, minute, tzinfo=TIMEZONE)

    assert is_night(at(21, 59)) is False
    assert is_night(at(22, 0)) is True
    assert is_night(at(23, 59)) is True
    assert is_night(at(0, 0)) is True
    assert is_night(at(7, 59)) is True
    assert is_night(at(8, 0)) is False


def test_morning_presets_cycle() -> None:
    assert (dt.time(7, 0), dt.time(8, 0), dt.time(9, 0), dt.time(10, 0)) == MORNING_TIME_PRESETS
    assert next_morning_preset(dt.time(7, 0)) == dt.time(8, 0)
    assert next_morning_preset(dt.time(10, 0)) == dt.time(7, 0)
    assert next_morning_preset(dt.time(6, 30)) == dt.time(7, 0)


def test_next_morning_keeps_timezone() -> None:
    moment = dt.datetime(2026, 11, 22, 23, 0, tzinfo=TIMEZONE)

    assert next_morning(moment, dt.time(8, 0)) == dt.datetime(2026, 11, 23, 8, 0, tzinfo=TIMEZONE)


def test_unique_notices_preserves_order() -> None:
    first, second = _notice(hour=1), _notice(hour=2)

    assert unique_notices([first, second, first]) == [first, second]


def test_notification_text_has_one_line_per_grade_and_escapes_html() -> None:
    notices = [
        _notice(hour=1, name="<b>Математика</b>"),
        _notice(hour=2, value="Н", name="Физика"),
    ]

    text = format_new_grades(notices, translate=lambda message: translate("ru", message))

    assert text.startswith("📊 Новые оценки")
    assert "20.11.2026" in text
    assert "&lt;b&gt;Математика&lt;/b&gt; Л" in text
    assert "— Н" in text
    assert "<b>Математика</b>" not in text
    assert len(text.splitlines()) == 3
