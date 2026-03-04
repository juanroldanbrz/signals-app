"""
Set subscription type for a user.

Usage:
    uv run python scripts/set_subscription.py <email> <FREE|UNLIMITED>

Examples:
    uv run python scripts/set_subscription.py juan@example.com UNLIMITED
    uv run python scripts/set_subscription.py someone@example.com FREE
"""
import asyncio
import sys

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from src.config import settings
from src.models.user import User


async def main(email: str, subscription: str) -> None:
    client = AsyncIOMotorClient(settings.mongo_uri)
    await init_beanie(database=client[settings.mongo_db], document_models=[User])

    user = await User.find_one(User.email == email)
    if not user:
        print(f"User not found: {email}")
        sys.exit(1)

    user.subscription_type = subscription
    await user.save()
    print(f"Updated {email} → {subscription}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] not in ("FREE", "UNLIMITED"):
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
