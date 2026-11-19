"""Шифрование чувствительных данных (см. docs/ARCHITECTURE.md §10).

Учётные данные edu-tpi хранятся в БД только в виде Fernet-токена. Ключ берётся из
`settings.ENCRYPTION_KEY` и валидируется при старте (см. `bot/core/config.py`).
"""

from __future__ import annotations
import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

INVALID_KEY_MESSAGE = (
    "ENCRYPTION_KEY не является валидным ключом Fernet. "
    "Нужен 32-байтный url-safe base64 ключ. Сгенерировать: "
    'uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)


def validate_key(key: str) -> None:
    """Проверить, что строка — валидный ключ Fernet.

    Raises:
        ValueError: ключ не является 32-байтной url-safe base64 строкой.

    """
    try:
        Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise ValueError(INVALID_KEY_MESSAGE) from exc


def _fernet() -> Fernet:
    # Импорт внутри функции: `bot.core.config` сам импортирует `validate_key`,
    # поэтому импорт настроек на уровне модуля дал бы циклическую зависимость.
    from bot.core.config import settings  # noqa: PLC0415

    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt(text: str) -> str:
    """Зашифровать строку и вернуть текстовый Fernet-токен."""
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str | None:
    """Расшифровать токен.

    Возвращает `None`, если токен повреждён или зашифрован другим ключом: это не
    ошибка сценария, а признак того, что учётные данные нужно запросить заново.
    """
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        logger.warning("Не удалось расшифровать сохранённые данные: ключ не совпадает или токен повреждён")
        return None
