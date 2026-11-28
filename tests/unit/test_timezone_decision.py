"""Единый часовой пояс бота — решение, зафиксированное тестом (ARCHITECTURE §4.4).

Тест намеренно «жёсткий»: если кто-то поменяет `TIMEZONE` или границы ночи, тест упадёт
и заставит прочитать §4.4 и ROADMAP §13 (риск «пользователь в другом поясе»).
"""

from __future__ import annotations
import datetime as dt
from zoneinfo import ZoneInfo

from bot.core.config import TIMEZONE
from bot.services.notifications import is_night, next_morning

MSK = ZoneInfo("Europe/Moscow")


def test_bot_works_in_moscow_time_by_design() -> None:
    assert TIMEZONE == MSK


def test_night_window_is_moscow_wall_time() -> None:
    """Ночь 22:00–08:00 считается по московскому времени, а не по локальному."""
    assert is_night(dt.datetime(2026, 11, 27, 22, 0, tzinfo=MSK))
    assert is_night(dt.datetime(2026, 11, 28, 7, 59, tzinfo=MSK))
    assert not is_night(dt.datetime(2026, 11, 27, 21, 59, tzinfo=MSK))
    assert not is_night(dt.datetime(2026, 11, 28, 8, 0, tzinfo=MSK))


def test_morning_batch_is_scheduled_at_moscow_morning() -> None:
    night = dt.datetime(2026, 11, 27, 23, 30, tzinfo=MSK)

    morning = next_morning(night, dt.time(8, 0))

    assert morning == dt.datetime(2026, 11, 28, 8, 0, tzinfo=MSK)
    assert morning.utcoffset() == dt.timedelta(hours=3)
