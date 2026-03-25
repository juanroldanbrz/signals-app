from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class User(Document):
    email: str
    hashed_password: str
    is_verified: bool = False
    verify_token: str | None = None
    reset_token: str | None = None
    subscription_type: Literal["FREE", "UNLIMITED"] = "FREE"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "users"
        indexes = [IndexModel([("email", 1)], unique=True)]
