"""Cron job: Cleanup expired memory entries"""

import asyncio

from hermes_mobile.config.settings import get_settings
from hermes_mobile.memory.provider import MobileMemoryProvider


async def main():
    settings = get_settings()
    provider = MobileMemoryProvider(
        db_path=settings.get_memory_db_path(),
        encrypt=settings.encrypt_memory,
    )

    await provider.cleanup_expired()
    print("Memory cleanup completed")

    provider.close()


if __name__ == "__main__":
    asyncio.run(main())
