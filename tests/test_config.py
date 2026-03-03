# tests/test_config.py
from src.config import Settings

def test_settings_defaults():
    s = Settings(
        gemini_api_key="test-key",
        mongo_uri="mongodb://localhost:27017",
    )
    assert s.default_interval_minutes == 60
    assert s.mongo_db == "signals"
