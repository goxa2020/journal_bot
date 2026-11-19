from __future__ import annotations
from typing import Any

import pytest

from bot.services.auth import DEFAULT_TOKEN_TTL_SECONDS, token_ttl_seconds


@pytest.mark.parametrize(
    ("expires_in", "expected"),
    [
        (10080, 604500),
        (10080.0, 604500),
        ("10080.0", 604500),
        (1, 60),
        (0, 60),
        (None, DEFAULT_TOKEN_TTL_SECONDS),
        ("", DEFAULT_TOKEN_TTL_SECONDS),
        ("not-a-number", DEFAULT_TOKEN_TTL_SECONDS),
    ],
)
def test_token_ttl_seconds(expires_in: Any, expected: int) -> None:
    """TTL = expiresIn(минуты) * 60 − 300, но не меньше 60 секунд."""
    assert token_ttl_seconds(expires_in) == expected
