"""HTTP-эндпоинты бота вне webhook-режима: `/healthz` и `/metrics` (задача 1.6).

В webhook-режиме их обслуживает aiohttp-приложение webhook'а (`bot/__main__.py`).
В polling-режиме своего HTTP-сервера нет, поэтому поднимаем отдельный: `docker compose`
публикует `WEBHOOK_PORT`, а healthcheck контейнера бота ходит в `/healthz`.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from aiohttp import web
from aiohttp.web_runner import AppRunner, TCPSite
from loguru import logger

from bot.core.config import settings
from bot.handlers.message.metrics import MetricsView

if TYPE_CHECKING:
    from aiohttp.web_request import Request

HEALTH_PATH = "/healthz"
METRICS_PATH = "/metrics"

_runner: AppRunner | None = None


async def healthz(_request: Request) -> web.Response:
    """Liveness-проба: процесс бота жив и обслуживает HTTP."""
    return web.json_response({"status": "ok", "service": "bot"})


def create_health_app() -> web.Application:
    application = web.Application()
    application.router.add_get(HEALTH_PATH, healthz)
    application.router.add_view(METRICS_PATH, MetricsView)
    return application


async def start_health_server() -> None:
    """Поднять HTTP-сервер на `WEBHOOK_HOST:WEBHOOK_PORT`; повторный вызов — no-op."""
    global _runner  # noqa: PLW0603
    if _runner is not None:
        return

    runner = AppRunner(create_health_app())
    await runner.setup()
    site = TCPSite(runner, host=settings.WEBHOOK_HOST, port=settings.WEBHOOK_PORT)
    await site.start()
    _runner = runner
    logger.info(
        "health server on {}:{} — {} и {}",
        settings.WEBHOOK_HOST,
        settings.WEBHOOK_PORT,
        HEALTH_PATH,
        METRICS_PATH,
    )


async def stop_health_server() -> None:
    """Остановить HTTP-сервер, если он поднят (вызывается из `on_shutdown`)."""
    global _runner
    runner, _runner = _runner, None
    if runner is None:
        return
    await runner.cleanup()
    logger.info("health server stopped")
