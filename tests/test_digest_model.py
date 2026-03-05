import pytest
from src.models.digest import DigestContent, SourceRef


def test_source_ref_date_optional():
    ref = SourceRef(title="Article", url="https://example.com")
    assert ref.date is None


def test_digest_content_serializes():
    content = DigestContent(
        summary="AI is evolving fast.",
        key_points=["Point A", "Point B"],
        sources=[SourceRef(title="TechCrunch", url="https://techcrunch.com", date="2026-03-05")],
    )
    data = content.model_dump()
    assert data["summary"] == "AI is evolving fast."
    assert len(data["key_points"]) == 2
    assert data["sources"][0]["date"] == "2026-03-05"


def test_digest_content_roundtrips_json():
    content = DigestContent(
        summary="Summary text",
        key_points=["k1"],
        sources=[SourceRef(title="S", url="https://s.com", date="2026-01-01")],
    )
    json_str = content.model_dump_json()
    restored = DigestContent.model_validate_json(json_str)
    assert restored.summary == "Summary text"
    assert restored.sources[0].url == "https://s.com"
