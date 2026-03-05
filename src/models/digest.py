from pydantic import BaseModel


class SourceRef(BaseModel):
    title: str
    url: str
    date: str | None = None


class DigestContent(BaseModel):
    summary: str
    key_points: list[str]
    sources: list[SourceRef]
