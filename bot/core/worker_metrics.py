"""HTTP-экспорт метрик воркера: `/metrics` и `/healthz` (W2.1, W2.2).

Бизнес-метрики (`sync_batch_users`, `sync_new_grades`, `notifications_total`) и метрики
задач (`celery_task_*`) считаются в процессах Celery, а не в процессе бота. Чтобы
Prometheus их видел, воркер работает в multiprocess-режиме `prometheus_client`:

* каталог `PROMETHEUS_MULTIPROC_DIR` задан только у сервиса `worker` в compose, до
  старта Celery он очищается, чтобы старые mmap-файлы не смешивались с новыми;
* каждый процесс пишет значения в mmap-файлы этого каталога;
* главный процесс воркера отдаёт их по HTTP через `MultiProcessCollector` (порт
  `WORKER_METRICS_PORT`, по умолчанию 9108), наружу порт не публикуется;
* `/healthz` на том же сервере — дешёвая liveness-проба для healthcheck'а вместо
  `celery inspect ping` (тот поднимает Celery CLI на ~8 с).

Без `PROMETHEUS_MULTIPROC_DIR` (тесты, локальный запуск, процесс бота) модуль ничего не
запускает: метрики читаются из обычного `REGISTRY`, как раньше.
"""

from __future__ import annotations
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from loguru import logger
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from prometheus_client.multiprocess import MultiProcessCollector, mark_process_dead

from bot.core.config import settings

METRICS_PATH = "/metrics"
HEALTH_PATH = "/healthz"

#: Переменная, включающая multiprocess-режим prometheus_client (задаётся в compose).
MULTIPROC_ENV = "PROMETHEUS_MULTIPROC_DIR"


def multiproc_dir() -> str | None:
    """Каталог multiprocess-режима; `None`, если режим выключен."""
    value = os.environ.get(MULTIPROC_ENV, "").strip()
    return value or None


def render_metrics(registry: CollectorRegistry | None = None) -> bytes:
    """Тело ответа `/metrics` в текстовом формате Prometheus."""
    if registry is None:
        return generate_latest()
    return generate_latest(registry)


def _send(handler: BaseHTTPRequestHandler, status: HTTPStatus, body: bytes, content_type: str) -> None:
    handler.send_response(status.value)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(registry: CollectorRegistry) -> type[BaseHTTPRequestHandler]:
    """Обработчик HTTP: только `/metrics` и `/healthz`, без лишних заголовков и логов."""

    class WorkerMetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == HEALTH_PATH:
                _send(self, HTTPStatus.OK, b'{"status": "ok", "service": "worker"}', "application/json")
            elif self.path == METRICS_PATH:
                _send(self, HTTPStatus.OK, render_metrics(registry), CONTENT_TYPE_LATEST)
            else:
                _send(self, HTTPStatus.NOT_FOUND, b'{"status": "not found"}', "application/json")

        def log_message(self, _format: str, *_args: object) -> None:
            """Не засорять логи воркера строкой доступа на каждый scrape."""

    return WorkerMetricsHandler


def start_worker_metrics_server(port: int | None = None) -> ThreadingHTTPServer | None:
    """Поднять HTTP-сервер метрик воркера; `None`, если multiprocess-режим выключен."""
    directory = multiproc_dir()
    if directory is None:
        logger.debug("worker metrics: {} не задан — HTTP-сервер не поднимается", MULTIPROC_ENV)
        return None
    if not Path(directory).is_dir():
        logger.warning("worker metrics: каталог {} не существует — HTTP-сервер не поднимается", directory)
        return None

    registry = CollectorRegistry()
    # prometheus_client не поставляет типы для multiprocess-API (как Celery для Task).
    MultiProcessCollector(registry, path=directory)  # type: ignore[no-untyped-call]
    listen_port = settings.WORKER_METRICS_PORT if port is None else port
    # 0.0.0.0 — намеренно: порт слушается только внутри docker-сети monitoring,
    # наружу не публикуется (в compose у сервиса нет ports).
    server = ThreadingHTTPServer(("0.0.0.0", listen_port), make_handler(registry))  # noqa: S104
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, name="worker-metrics", daemon=True)
    thread.start()
    logger.info(
        "worker metrics on 0.0.0.0:{} — {} и {}",
        server.server_address[1],
        METRICS_PATH,
        HEALTH_PATH,
    )
    return server


def stop_worker_metrics_server(server: ThreadingHTTPServer | None) -> None:
    """Остановить HTTP-сервер метрик (идемпотентно)."""
    if server is None:
        return
    server.shutdown()
    server.server_close()
    logger.info("worker metrics server stopped")


def mark_worker_process_dead(pid: int | None = None) -> None:
    """Удалить mmap-файлы завершившегося процесса воркера (multiprocess-режим)."""
    directory = multiproc_dir()
    if directory is None:
        return
    mark_process_dead(os.getpid() if pid is None else pid, path=directory)  # type: ignore[no-untyped-call]
