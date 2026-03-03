from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from beanie import Document
from pydantic import Field


class SignalStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class Signal(Document):
    name: str
    source_url: str
    source_extraction_query: str
    chart_type: Literal["line", "bar", "flag"] = "line"
    interval_minutes: int = 60
    alert_enabled: bool = True
    status: SignalStatus = SignalStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_run_at: datetime | None = None
    last_value: float | None = None
    alert_triggered: bool = False
    consecutive_errors: int = 0
    next_run_at: datetime | None = None
    condition_type: Literal["above", "below", "equals", "change"] | None = None
    condition_threshold: float | None = None

    class Settings:
        name = "signals"
