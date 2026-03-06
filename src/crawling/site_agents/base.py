from collections.abc import Awaitable, Callable
from pydantic import BaseModel

type ProgressCallback = Callable[[str], Awaitable[None]] | None


class AgentTool(BaseModel):
    name: str
    description: str
    parameters: dict          # JSON schema for args


class AgentResult(BaseModel):
    value: float | None = None
    digest_content: str | None = None
    persisted_memory: dict = {}
