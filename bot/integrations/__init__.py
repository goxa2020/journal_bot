"""Интеграции с внешним миром: edu-tpi и кеш его ответов.

`edu_tpi` — HTTP-клиент и разбор ответов, `journal_cache` — групповой кеш журналов и
алгоритм подгрупп. Слой не знает про БД и Telegram (docs/ARCHITECTURE.md §3).
"""

from bot.integrations.edu_tpi import EduTpiClient
from bot.integrations.journal_cache import JournalCache

__all__ = ["EduTpiClient", "JournalCache"]
