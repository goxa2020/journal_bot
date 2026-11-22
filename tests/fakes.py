"""Тестовые двойники HTTP-слоя и клиентов (без сети)."""

from __future__ import annotations
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "edu_tpi"


def load_fixture(name: str) -> dict[str, Any]:
    """Обезличенный ответ API из `tests/fixtures/edu_tpi`."""
    with (FIXTURES / name).open(encoding="utf-8") as handle:
        return json.load(handle)


class FakeResponse:
    """Минимальный ответ aiohttp: статус, json, заголовки."""

    def __init__(
        self,
        status: int = 200,
        payload: Any = None,
        headers: dict[str, str] | None = None,
        *,
        bad_json: bool = False,
    ) -> None:
        self.status = status
        self._payload = payload
        self.headers = headers or {}
        self._bad_json = bad_json

    async def json(self, **_kwargs: Any) -> Any:
        if self._bad_json:
            msg = "not json"
            raise json.JSONDecodeError(msg, "", 0)
        return self._payload

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class FakeSession:
    """Подменяет `aiohttp.ClientSession`: маршруты по (метод, url)."""

    def __init__(self, routes: dict[tuple[str, str], FakeResponse | Exception]) -> None:
        self._routes = routes
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    async def close(self) -> None:
        return None

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append((method, str(url), kwargs))
        route = self._routes.get((method, str(url)))
        if route is None:
            msg = f"unexpected request: {method} {url}"
            raise AssertionError(msg)
        if isinstance(route, Exception):
            raise route
        return route


def install_session(
    monkeypatch: pytest.MonkeyPatch,
    routes: dict[tuple[str, str], FakeResponse | Exception],
) -> FakeSession:
    """Подменить HTTP-слой edu-tpi: свой стаб вместо сети и вместо respx (он не умеет aiohttp)."""
    session = FakeSession(routes)
    monkeypatch.setattr(
        "bot.integrations.edu_tpi.aiohttp.ClientSession",
        lambda **_kwargs: session,
    )
    return session
