"""
Idempotent migration: set signal_type="monitor" on all existing Signal documents
that were created before the signal_type field was added.

Run with: uv run python scripts/migrate_signal_type.py
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from src.config import settings


async def main() -> None:
    client = AsyncIOMotorClient(settings.mongo_uri)
    db = client[settings.mongo_db]
    result = await db["signals"].update_many(
        {"signal_type": {"$exists": False}},
        {"$set": {"signal_type": "monitor", "source_urls": [], "search_query": None}},
    )
    print(f"Updated {result.modified_count} signal(s) → signal_type='monitor'")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
