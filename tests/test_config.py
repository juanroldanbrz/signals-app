# tests/test_config.py
from src.config import Settings

def test_settings_defaults():
    s = Settings(
        llm_api_key="test-key",
        jwt_secret="test-secret",
        mongo_uri="mongodb://localhost:27017",
    )
    assert s.default_interval_minutes == 60
    assert s.mongo_db == "signals"
    assert s.llm_model == "gemini/gemini-3.0-flash-preview"
    assert s.jwt_expire_minutes == 60 * 24 * 7
    assert s.email_verification is True
