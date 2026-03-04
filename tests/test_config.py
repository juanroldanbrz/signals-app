# tests/test_config.py
from src.config import Settings

def test_settings_defaults():
    s = Settings(
        _env_file=None,
        jwt_secret="test-secret",
        mongo_uri="mongodb://localhost:27017",
        mandatory_email_verification=False,
        resend_api_key="",
    )
    assert s.default_interval_minutes == 60
    assert s.mongo_db == "signals"
    assert s.llm_model == "gemini/gemini-2.0-flash"
    assert s.jwt_expire_minutes == 60 * 24 * 7
    assert s.mandatory_email_verification is False
    assert s.resend_api_key == ""
    assert s.vertexai_project == ""
    assert s.vertexai_location == "us-central1"
    assert s.vertexai_credentials == ""
