from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from bot.core.encryption import decrypt, encrypt, validate_key


def test_encrypt_decrypt_roundtrip() -> None:
    token = encrypt("student@donstu.ru")

    assert token != "student@donstu.ru"
    assert decrypt(token) == "student@donstu.ru"


def test_invalid_key_fails_validation() -> None:
    with pytest.raises(ValueError, match="Fernet"):
        validate_key("too-short-to-be-a-key")


def test_generated_key_is_valid() -> None:
    validate_key(Fernet.generate_key().decode())


def test_corrupted_token_returns_none() -> None:
    token = encrypt("secret")

    assert decrypt(token[:-2] + "AA") is None


def test_token_encrypted_with_another_key_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    token = encrypt("secret")
    monkeypatch.setattr("bot.core.config.settings.ENCRYPTION_KEY", Fernet.generate_key().decode())

    assert decrypt(token) is None
