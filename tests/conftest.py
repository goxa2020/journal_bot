"""Общие фикстуры тестов.

Переменные окружения выставляются до первого импорта `bot.*`: `bot.core.config`
создаёт `Settings` при импорте и без BOT_TOKEN/ENCRYPTION_KEY упадёт. Значения
ниже — тестовые заглушки, а не настоящие секреты.
"""

from __future__ import annotations
import os
from typing import TYPE_CHECKING

import fakeredis.aioredis
import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from aiogram.utils.i18n import I18n

os.environ.setdefault("BOT_TOKEN", "123456789:AAFakeTokenForTestsOnly_1234567890X")
os.environ.setdefault("ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("REDIS_HOST", "127.0.0.1")
os.environ.setdefault("TELEGRAM_PROXY", "")

TEST_ENCRYPTION_KEY = os.environ["ENCRYPTION_KEY"]


@pytest.fixture
async def fake_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """Подменяет redis-клиент модуля кеша; ключи живут только внутри теста."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    monkeypatch.setattr("bot.cache.redis.redis_client", client)
    yield client
    await client.aclose()


@pytest.fixture
def ru_locale() -> Iterator[I18n]:
    """Активирует русскую локаль aiogram для проверки готовых текстов.

    `I18n.context()` не принимает локаль: она берётся из `ctx_locale`, который
    по умолчанию равен `default_locale` (ru).
    """
    from bot.core.loader import i18n  # noqa: PLC0415 — импорт после выставления env

    with i18n.context():
        yield i18n
