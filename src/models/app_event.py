from datetime import datetime, timezone
from typing import Literal
from beanie import Document, PydanticObjectId
from pydantic import Field


class AppEvent(Document):
    user_id: PydanticObjectId
    signal_id: PydanticObjectId
    signal_name: str
    value: float | None
    alert_triggered: bool
    status: Literal["ok", "error"]
    message: str = ""
    ran_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "app_events"
