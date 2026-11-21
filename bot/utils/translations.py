"""Переводы для процессов без aiogram (Celery-воркер).

В воркере нельзя импортировать `bot.core.loader` (он создаёт Bot и Redis-клиент в чужом
event loop), поэтому тексты берутся напрямую из gettext-каталога по языку пользователя.
В обработчиках бота остаётся обычный `_()`.
"""

from __future__ import annotations
from functools import lru_cache
from gettext import NullTranslations, translation

from bot.core.config import DEFAULT_LOCALE, I18N_DOMAIN, LOCALES_DIR


@lru_cache(maxsize=8)
def _catalog(locale: str) -> NullTranslations:
    return translation(I18N_DOMAIN, LOCALES_DIR, languages=[locale], fallback=True)


def translate(locale: str | None, message: str) -> str:
    """Перевести сообщение по ключу; неизвестная локаль — русская."""
    language = locale if locale in {"ru", "en"} else DEFAULT_LOCALE
    return _catalog(language).gettext(message)
