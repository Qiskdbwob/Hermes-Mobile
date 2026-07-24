"""Cron job: Sync conversations to cloud"""

import asyncio

from hermes_mobile.config.settings import get_settings
from hermes_mobile.memory.provider import MobileMemoryProvider


async def main():
    settings = get_settings()
    provider = MobileMemoryProvider(
        db_path=settings.get_memory_db_path(),
        encrypt=settings.encrypt_memory,
    )

    # TODO: Implement cloud sync
    # For now, just list conversations
    conversations = await provider.list_conversations(limit=100)
    print(f"Found {len(conversations)} conversations to sync")

    provider.close()


if __name__ == "__main__":
    asyncio.run(main())
