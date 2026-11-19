"""Иерархия ошибок приложения (см. docs/ARCHITECTURE.md §9).

В фазе 1 добавлено разделение на временные и постоянные ошибки задачи: от него зависит,
ретраится задача или сразу считается упавшей. Ошибки edu-tpi (`EduAuthError`,
`EduUnavailableError`, `ParseError`) переедут сюда в фазе 2 вместе с `integrations/`.
"""

from __future__ import annotations


class AppError(Exception):
    """Базовая ошибка приложения."""


class ConfigError(AppError):
    """Некорректная или неполная конфигурация: с ней бот не должен запускаться."""


class RetryableError(AppError):
    """Временная ошибка задачи: имеет смысл повторить.

    Сеть, таймаут, 5xx, 429 — задача ретраится автоматически (`BaseTask.autoretry_for`)
    с backoff до `max_retries` раз (docs/ARCHITECTURE.md §9).
    """


class PermanentError(AppError):
    """Постоянная ошибка задачи: повтор не поможет.

    Неверные данные, изменившаяся схема ответа, отсутствующий пользователь — задачу
    нужно залогировать как `ERROR` и не ретраить (иначе повторы только забьют очередь).
    """
