"""Общая инфраструктура задач Celery (docs/ARCHITECTURE.md §6.5–6.6).

Правила, из-за которых этот модуль выглядит именно так:

* задача Celery синхронная, а приложение асинхронное → `run_async()` создаёт **свой**
  event loop на каждую задачу (`asyncio.run`);
* asyncpg-соединения привязаны к event loop → у задачи свой `AsyncEngine` с `NullPool`,
  который закрывается в `task_session()`;
* Redis-клиент и `Bot` тоже привязаны к loop → создаются внутри задачи
  (`task_redis()`, `send_telegram_message()`) и закрываются после неё;
* глобальные объекты бота (`bot.core.loader`) в задачах не используются: они живут
  в event loop процесса бота, а не воркера.

Импортировать `bot.core.loader` из `bot/tasks/*` нельзя — это главная ловушка
Celery + asyncio.
"""

from __future__ import annotations
import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import prometheus_client
from celery import Task
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from bot.core.config import settings
from bot.core.errors import PermanentError, RetryableError
from bot.database.database import CConnection, get_sessionmaker

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Coroutine

    from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

_T = TypeVar("_T")

# --- Метрики задач (ARCHITECTURE §11) ---------------------------------------------
# HTTP-эндпоинт для них появится вместе с celery-exporter в фазе 8; сейчас метрики
# живут в процессе воркера.
TASKS_TOTAL = prometheus_client.Counter(
    "celery_tasks",
    "Задачи Celery по результату выполнения.",
    ["task", "status"],
)
TASK_FAILURES = prometheus_client.Counter(
    "celery_task_failures",
    "Задачи Celery, завершившиеся ошибкой после всех повторов.",
    ["task"],
)
TASK_DURATION = prometheus_client.Histogram(
    "celery_task_duration_seconds",
    "Длительность выполнения задачи Celery, секунды.",
    ["task"],
)

LOCK_VALUE = "1"
WORKER_LOG_DIR = Path("logs")


def worker_log_path(pid: int) -> Path:
    """Файл лога процесса воркера: у каждого prefork-процесса свой писатель (W2.3).

    loguru не гарантирует корректную ротацию, когда в один файл пишут несколько
    процессов сразу, поэтому имя включает pid. Имена предсказуемы: `worker-<pid>.log`.
    """
    return WORKER_LOG_DIR / f"worker-{pid}.log"


def run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Выполнить корутину в отдельном event loop (один loop на задачу).

    Вызов изнутри уже работающего loop — ошибка: Celery-задача синхронная, а весь
    async-код должен быть собран в одну корутину, переданную сюда.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # Корутину никто не выполнит — закрываем, чтобы не было "never awaited".
    coro.close()
    message = (
        "run_async() вызван внутри работающего event loop. Задача Celery должна быть "
        "синхронной: соберите весь async-код в одну корутину и передайте её в run_async()."
    )
    raise RuntimeError(message)


def create_task_engine() -> AsyncEngine:
    """`AsyncEngine` задачи: `NullPool`, чтобы не переиспользовать соединения чужого loop."""
    return create_async_engine(
        url=settings.database_url,
        echo=settings.DEBUG,
        poolclass=NullPool,
        connect_args={"connection_class": CConnection},
    )


@asynccontextmanager
async def task_session() -> AsyncIterator[AsyncSession]:
    """Сессия БД на время задачи; движок создаётся и закрывается вместе с ней."""
    engine = create_task_engine()
    try:
        async with get_sessionmaker(engine)() as session:
            yield session
    finally:
        await engine.dispose()


def create_task_redis() -> Redis:
    """Redis-клиент задачи (база 0 — кеш и токены, не брокер)."""
    return Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASS or None,
        db=0,
        decode_responses=False,
    )


@asynccontextmanager
async def task_redis() -> AsyncIterator[Redis]:
    """Redis-клиент внутри loop задачи, закрывается после неё."""
    client = create_task_redis()
    try:
        yield client
    finally:
        await client.aclose()


@asynccontextmanager
async def task_lock(key: str, ttl: int = 300, *, release: bool = False) -> AsyncIterator[bool]:
    """Эксклюзивный lock задачи на `SET NX EX` (ARCHITECTURE §6.6).

    `key` — полный ключ Redis, например `sync:lock:{user_id}`. `yield False`, если ключ
    занят: задача выходит без ошибки (`task_acks_late` допускает повторы, второй запуск
    по тому же пользователю просто пропускается).

    `release=True` снимает lock после выхода из блока: так групповая синхронизация берёт
    `sync:lock:{user_id}` только на время дифа пользователя, иначе ручная синхронизация
    этого пользователя пропускалась бы до истечения `ttl`. По умолчанию lock не снимается
    вручную — его время жизни ограничено `ttl`, чтобы падение воркера не оставило вечный
    замок. Снятие тоже безопасно: `ttl` остаётся страховкой от падения процесса.
    """
    client = create_task_redis()
    try:
        acquired = bool(await client.set(key, LOCK_VALUE, nx=True, ex=ttl))
        if not acquired:
            logger.info("skipped: locked key={}", key)
        try:
            yield acquired
        finally:
            if acquired and release:
                try:
                    await client.delete(key)
                except Exception:  # noqa: BLE001 — освобождение лока не должно валить задачу
                    logger.exception("lock release failed key={}", key)
    finally:
        await client.aclose()


async def send_telegram_message(
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None,
) -> None:
    """Отправить сообщение из воркера: свой `Bot` на вызов, без polling-методов."""
    # aiogram тянет aiohttp и импортируется долго (на Windows/Docker — десятки секунд),
    # а воркеру он нужен только здесь: остальные задачи не должны платить за импорт.
    from aiogram import Bot  # noqa: PLC0415
    from aiogram.client.default import DefaultBotProperties  # noqa: PLC0415
    from aiogram.client.session.aiohttp import AiohttpSession  # noqa: PLC0415
    from aiogram.enums import ParseMode  # noqa: PLC0415

    session = AiohttpSession(proxy=settings.TELEGRAM_PROXY) if settings.TELEGRAM_PROXY else None
    async with Bot(
        token=settings.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    ) as bot:
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


#: Процессы, где файловый sink уже добавлен (после fork у каждого свой).
_LOGGING_READY: set[int] = set()


def configure_task_logging() -> None:
    """Логи задач: `logs/worker-<pid>.log` с ротацией (как у бота) и stdout воркера.

    Вызывается из сигнала `worker_process_init` — то есть в каждом процессе воркера,
    а не при импорте приложения: тесты и `celery inspect` не должны создавать файлы.
    """
    pid = os.getpid()
    if pid in _LOGGING_READY:
        return

    log_path = worker_log_path(pid)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_format = "{time} | {level} | {module}:{function}:{line} | {message}"
    level = "DEBUG" if settings.DEBUG else "INFO"

    # loguru по умолчанию пишет в stderr; в контейнере `docker compose logs` собирает оба
    # потока. Celery подменяет sys.stdout своим LoggingProxy — пишем в исходный поток,
    # иначе строки задач получают префикс `WARNING/ForkPoolWorker-1` от celery.
    logger.remove()
    logger.add(sys.__stdout__ or sys.stdout, level=level, format=log_format, colorize=False)
    logger.add(
        log_path,
        level="DEBUG",
        format=log_format,
        rotation="100 KB",
        compression="zip",
        enqueue=False,
    )
    _LOGGING_READY.add(pid)


# celery не поставляет типы (нет py.typed), поэтому для mypy Task — это Any.
class BaseTask(Task):  # type: ignore[misc]
    """База задач: повторы для временных ошибок, лог и метрики для всех.

    `RetryableError` ретраится автоматически (backoff 1→2→4… с потолком 240 с), а
    `PermanentError` — нет: он означает ошибку данных или схемы, повтор её не исправит.
    """

    autoretry_for = (RetryableError,)
    max_retries = 3
    retry_backoff = True
    retry_backoff_max = 240
    retry_jitter = True

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Обёртка вызова: время выполнения задачи в гистограмму.

        Celery выполняет задачу через `__call__`, если класс его переопределяет
        (`task_has_custom` в `celery.app.trace`), поэтому это работает и в воркере,
        и в eager-режиме.
        """
        started = time.perf_counter()
        try:
            return super().__call__(*args, **kwargs)
        finally:
            TASK_DURATION.labels(task=self.name).observe(time.perf_counter() - started)

    def on_success(self, retval: Any, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        TASKS_TOTAL.labels(task=self.name, status="success").inc()
        logger.info("task {}[{}] succeeded args={} kwargs={}", self.name, task_id, args, kwargs)

    def on_retry(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        TASKS_TOTAL.labels(task=self.name, status="retry").inc()
        logger.warning(
            "task {}[{}] retry #{} after {} args={}",
            self.name,
            task_id,
            self.request.retries,
            exc,
            args,
        )

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        TASKS_TOTAL.labels(task=self.name, status="failure").inc()
        TASK_FAILURES.labels(task=self.name).inc()
        # В аргументах задач только примитивы (id, строки) — ПДн в лог не попадают.
        kind = "permanent error" if isinstance(exc, PermanentError) else "failed"
        logger.error(
            "task {}[{}] {}: {} args={} kwargs={}",
            self.name,
            task_id,
            kind,
            exc,
            args,
            kwargs,
        )
