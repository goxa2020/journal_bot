import sys

sys.path.insert(0, ".")
import asyncio
from contextlib import suppress

from bot.services.journal_parser import InvalidCredsError, JournalParser, ParseError


async def main() -> None:
    parser = JournalParser()
    with suppress(InvalidCredsError, ParseError, Exception):
        await parser.parse_grades("dummy", "dummy")

if __name__ == "__main__":
    asyncio.run(main())
