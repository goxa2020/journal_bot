"""Общие фикстуры тестов.

Переменные окружения выставляются до первого импорта `bot.*`: `bot.core.config`
создаёт `Settings` при импорте и без BOT_TOKEN/ENCRYPTION_KEY упадёт. Значения
ниже — тестовые заглушки, а не настоящие секреты.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import TYPE_CHECKING

import fakeredis.aioredis
import pytest
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from loguru import logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

    from aiogram.utils.i18n import I18n

os.environ.setdefault("BOT_TOKEN", "123456789:AAFakeTokenForTestsOnly_1234567890X")
os.environ.setdefault("ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("REDIS_HOST", "127.0.0.1")
os.environ.setdefault("TELEGRAM_PROXY", "")
# Аналитика из воркера: пустой ключ = тихий no-op, тесты не ходят в сеть даже если
# в локальном `.env` ключ заполнен.
os.environ.setdefault("AMPLITUDE_API_KEY", "")
os.environ.setdefault("POSTHOG_API_KEY", "")

TEST_ENCRYPTION_KEY = os.environ["ENCRYPTION_KEY"]

LOCALES_DIR = Path(__file__).resolve().parent.parent / "bot" / "locales"


def _compile_stale_locales() -> None:
    """Скомпилировать `.po` → `.mo`, если `.mo` нет или он старше перевода.

    `.mo` не в git, а тесты проверяют готовые русские тексты. Без этого шага на
    чистом клоне приходилось вручную звать `just babel-compile`. Компиляция идёт
    на импорте `conftest.py`: он загружается раньше тестовых модулей, а значит
    раньше первого импорта `bot.*` и первого чтения каталога gettext. Фикстура
    (даже session-scoped) к этому моменту уже опоздала бы: тестовые модули
    импортируются на этапе collection.
    """
    for po_path in sorted(LOCALES_DIR.glob("*/LC_MESSAGES/messages.po")):
        mo_path = po_path.with_suffix(".mo")
        if mo_path.exists() and mo_path.stat().st_mtime >= po_path.stat().st_mtime:
            continue
        with po_path.open("rb") as po_file:
            catalog = read_po(po_file)
        with mo_path.open("wb") as mo_file:
            write_mo(mo_file, catalog)


_compile_stale_locales()


@pytest.fixture
async def fake_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    """Подменяет redis-клиенты модулей; ключи живут только внутри теста."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    monkeypatch.setattr("bot.cache.redis.redis_client", client)
    # Тот же клиент под именем loader: им пользуются обработчики входа и /logout.
    monkeypatch.setattr("bot.core.loader.redis_client", client)
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


@pytest.fixture
def celery_eager() -> Iterator[None]:
    """Выполняет задачи Celery в текущем процессе: без брокера и без сети.

    `task_eager_propagates=True` — исключение задачи видно в тесте, а не только
    в результате (`result.state`). Значения возвращаются после теста.
    """
    from bot.celery_app import celery_app  # noqa: PLC0415 — импорт после выставления env

    conf = celery_app.conf
    previous = (conf.task_always_eager, conf.task_eager_propagates)
    conf.update(task_always_eager=True, task_eager_propagates=True)
    yield
    conf.update(task_always_eager=previous[0], task_eager_propagates=previous[1])


@pytest.fixture
def log_messages() -> Iterator[list[str]]:
    """Собирает текст сообщений loguru (INFO и выше) внутри теста."""
    messages: list[str] = []
    handler_id = logger.add(
        lambda message: messages.append(message.record["message"]),
        level="INFO",
    )
    yield messages
    logger.remove(handler_id)
