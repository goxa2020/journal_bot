"""HTTP-метрики и healthz воркера (W2), имя файла лога на pid (W2.3)."""

from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

import prometheus_client
import pytest

from bot.core.config import Settings
from bot.core.worker_metrics import (
    HEALTH_PATH,
    METRICS_PATH,
    MULTIPROC_ENV,
    make_handler,
    multiproc_dir,
    render_metrics,
    start_worker_metrics_server,
    stop_worker_metrics_server,
)
from bot.tasks.base import worker_log_path

if TYPE_CHECKING:
    from pathlib import Path


def test_worker_metrics_port_default_is_9108() -> None:
    assert Settings.model_fields["WORKER_METRICS_PORT"].default == 9108


def test_worker_log_path_is_per_pid() -> None:
    first = worker_log_path(123)
    second = worker_log_path(456)

    assert first.name == "worker-123.log"
    assert second.name == "worker-456.log"
    assert first.parent == second.parent


def test_multiproc_dir_reads_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(MULTIPROC_ENV, f" {tmp_path} ")
    assert multiproc_dir() == str(tmp_path)
    monkeypatch.setenv(MULTIPROC_ENV, "   ")
    assert multiproc_dir() is None


def test_server_is_not_started_without_multiproc_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MULTIPROC_ENV, raising=False)
    assert start_worker_metrics_server(port=0) is None


def test_server_is_not_started_when_dir_is_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(MULTIPROC_ENV, str(tmp_path / "missing"))
    assert start_worker_metrics_server(port=0) is None


def test_render_metrics_returns_plain_text_exposition() -> None:
    registry = prometheus_client.CollectorRegistry()
    gauge = prometheus_client.Gauge("w2_test_metric", "Проверка экспорта", registry=registry)
    gauge.set(3)

    body = render_metrics(registry)

    assert b"w2_test_metric 3.0" in body


def test_healthz_and_metrics_are_served_by_handler(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(MULTIPROC_ENV, str(tmp_path))
    server = start_worker_metrics_server(port=0)
    assert server is not None
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    # Без прокси из окружения: локальный HTTP-сервер не должен идти через VPN.
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(f"{base}{HEALTH_PATH}", timeout=5) as response:
            assert response.status == 200
            assert json.loads(response.read()) == {"status": "ok", "service": "worker"}

        with opener.open(f"{base}{METRICS_PATH}", timeout=5) as response:
            assert response.status == 200
            # В multiprocess-каталоге пока нет файлов — тело пустое, но формат верный.
            assert response.headers["Content-Type"].startswith("text/plain")

        with pytest.raises(HTTPError) as exc_info:
            opener.open(f"{base}/nope", timeout=5)
        assert exc_info.value.code == 404
    finally:
        stop_worker_metrics_server(server)


def test_make_handler_is_a_stdlib_handler() -> None:
    handler = make_handler(prometheus_client.CollectorRegistry())

    assert issubclass(handler, BaseHTTPRequestHandler)
