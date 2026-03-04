from datetime import datetime, timezone

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class User(Document):
    email: str
    hashed_password: str
    is_verified: bool = False
    verify_token: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "users"
        indexes = [IndexModel([("email", 1)], unique=True)]
