from __future__ import annotations
import os
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from bot.core.encryption import validate_key
from bot.core.errors import ConfigError

if TYPE_CHECKING:
    from sqlalchemy.engine.url import URL

DIR = Path(__file__).absolute().parent.parent.parent
BOT_DIR = Path(__file__).absolute().parent.parent
LOCALES_DIR = f"{BOT_DIR}/locales"
I18N_DOMAIN = "messages"
DEFAULT_LOCALE = "ru"
TIMEZONE = ZoneInfo("Europe/Moscow")

# Какой env-файл читать. Для локального запуска: ENV_FILE=.env.local
ENV_FILE = os.getenv("ENV_FILE", ".env")


class EnvBaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")


class WebhookSettings(EnvBaseSettings):
    USE_WEBHOOK: bool = False
    WEBHOOK_BASE_URL: str = "https://xxx.ngrok-free.app"
    WEBHOOK_PATH: str = "/webhook"
    WEBHOOK_SECRET: str = ""
    WEBHOOK_HOST: str = "localhost"
    WEBHOOK_PORT: int = 8080

    @property
    def webhook_url(self) -> str:
        if settings.USE_WEBHOOK:
            return f"{self.WEBHOOK_BASE_URL}{self.WEBHOOK_PATH}"
        return f"http://localhost:{settings.WEBHOOK_PORT}{settings.WEBHOOK_PATH}"


class BotSettings(WebhookSettings):
    BOT_TOKEN: str
    SUPPORT_URL: str | None = None
    RATE_LIMIT: int | float = 0.5  # for throttling control
    # Прокси для Telegram Bot API. Нужен, когда VPN работает только на хосте
    # (Docker в него не ходит). В Docker Desktop: http://host.docker.internal:10809
    TELEGRAM_PROXY: str | None = None


class DBSettings(EnvBaseSettings):
    DB_HOST: str = "postgres"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASS: str | None = None
    DB_NAME: str = "postgres"

    @property
    def database_url(self) -> URL | str:
        if self.DB_PASS:
            return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        return f"postgresql+asyncpg://{self.DB_USER}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def database_url_psycopg2(self) -> str:
        if self.DB_PASS:
            return f"postgresql://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        return f"postgresql://{self.DB_USER}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


class CacheSettings(EnvBaseSettings):
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASS: str | None = None

    # REDIS_DATABASE: int = 1
    # REDIS_USERNAME: int | None = None
    # REDIS_TTL_STATE: int | None = None
    # REDIS_TTL_DATA: int | None = None

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASS:
            return f"redis://{self.REDIS_PASS}@{self.REDIS_HOST}:{self.REDIS_PORT}/0"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"


class CelerySettings(EnvBaseSettings):
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"
    CELERY_TIMEZONE: str = "Europe/Moscow"
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: list[str] = ["json"]
    CELERY_TASK_TIME_LIMIT: int = 300
    CELERY_TASK_SOFT_TIME_LIMIT: int = 250
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1
    CELERY_WORKER_MAX_TASKS_PER_CHILD: int = 1000
    CELERY_WORKER_CONCURRENCY: int = 4
    # Сколько секунд хранить результаты задач в backend (Redis, база 2).
    CELERY_RESULT_EXPIRES: int = 86400
    # True: задачи выполняются в вызывающем процессе без брокера. Для тестов и
    # ручной отладки (docs/DEVELOPMENT.md §10); в бою — False.
    CELERY_TASK_ALWAYS_EAGER: bool = False


class Settings(BotSettings, DBSettings, CacheSettings, CelerySettings):
    DEBUG: bool = False

    SENTRY_DSN: str | None = None

    AMPLITUDE_API_KEY: str | None = None
    POSTHOG_API_KEY: str | None = None

    # Оппортунистическая синхронизация (задача 4.2): ручное обновление одного
    # пользователя обновляет и других участников его группы из того же журнала.
    # По умолчанию выключено: повышает риск ложных «новых» оценок.
    SYNC_OPPORTUNISTIC: bool = False

    # Алерт админам о массовых сбоях (задача 4.4): минимальный размер прогона и доля
    # пользователей с ошибкой, при которой отправляется одно сообщение.
    SYNC_ALERT_FAILURE_RATIO: float = 0.2
    SYNC_ALERT_MIN_USERS: int = 5

    # Лимиты edu-tpi (W1.14): пауза между запросами деталей журнала в рамках клиента
    # и суммарный лимит запросов в секунду (Redis-счётчик). Раньше были константами
    # `EduTpiClient`; значения по умолчанию не меняем — снижение лимита риск бана,
    # повышение тоже. Менять только осознанно и в `.env`.
    EDU_MIN_JOURNAL_INTERVAL: float = 1.0
    EDU_MAX_RPS: int = 5

    # Порт HTTP-сервера метрик/healthz воркера (W2). Порт слушается только внутри
    # docker-сети `monitoring`, наружу не публикуется.
    WORKER_METRICS_PORT: int = 9108

    # Режим ожидания оценок (фаза 5, ARCHITECTURE §2/§6.6/§7.5): сколько действует один
    # период, с каким шагом beat проверяет ожидающих и в какую минуту часа снимаются
    # истёкшие. Значения по умолчанию — продуктовые: 30 минут, каждые 5 минут, :10.
    WATCH_MODE_MINUTES: int = 30
    WATCH_MODE_TICK_MINUTES: int = 5
    WATCH_MODE_CLEANUP_MINUTE: int = 10

    # Ключ шифрования учётных данных edu-tpi. Обязателен: случайный ключ ломает
    # расшифровку паролей после рестарта, поэтому дефолта у поля нет.
    ENCRYPTION_KEY: str

    @field_validator("ENCRYPTION_KEY")
    @classmethod
    def _validate_encryption_key(cls, value: str) -> str:
        key = value.strip()
        validate_key(key)
        return key


ENCRYPTION_KEY_MESSAGE = (
    "ENCRYPTION_KEY не задан или не является валидным ключом Fernet. Это ключ шифрования "
    "паролей edu-tpi: нужен 32-байтный url-safe base64 ключ, без него бот не запустится. "
    "Сгенерировать: "
    'uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)


def _config_error_text(exc: ValidationError) -> str:
    """Собрать понятное сообщение об ошибке конфигурации.

    Текст pydantic в лог не попадает: в нём может оказаться значение переменной
    (в том числе секрет), а нам нужна только подсказка, что делать.
    """
    errors = exc.errors()
    parts: list[str] = []

    if any(err.get("loc") == ("ENCRYPTION_KEY",) for err in errors):
        parts.append(ENCRYPTION_KEY_MESSAGE)

    missing = [
        str(err["loc"][0]) for err in errors if err.get("type") == "missing" and err.get("loc") != ("ENCRYPTION_KEY",)
    ]
    if missing:
        parts.append(f"Не заданы обязательные переменные окружения: {', '.join(missing)}.")

    if not parts:
        fields = ", ".join(str(err.get("loc", ("?",))[0]) for err in errors)
        parts.append(f"Некорректная конфигурация: проверьте {fields}.")

    parts.append("Заполните .env по образцу .env.example.")
    return " ".join(parts)


try:
    settings = Settings()
except ValidationError as exc:
    raise ConfigError(_config_error_text(exc)) from None
