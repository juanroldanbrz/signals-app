from datetime import datetime, timezone
from enum import Enum
from beanie import Document, PydanticObjectId
from pydantic import Field


class RunStatus(str, Enum):
    OK = "ok"
    ERROR = "error"


class SignalRun(Document):
    user_id: PydanticObjectId
    signal_id: PydanticObjectId
    ran_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    value: float | None = None
    alert_triggered: bool = False
    status: RunStatus = RunStatus.OK
    raw_result: str | None = None

    class Settings:
        name = "signal_runs"
