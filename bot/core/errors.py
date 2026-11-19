"""Иерархия ошибок приложения (см. docs/ARCHITECTURE.md §9).

Пока в фазе 0 здесь только ошибки конфигурации. Ошибки edu-tpi (`EduAuthError`,
`EduUnavailableError`, `ParseError`) переедут сюда в фазе 2 вместе с `integrations/`.
"""

from __future__ import annotations


class AppError(Exception):
    """Базовая ошибка приложения."""


class ConfigError(AppError):
    """Некорректная или неполная конфигурация: с ней бот не должен запускаться."""
