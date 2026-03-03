# tests/conftest.py
import os
from pathlib import Path


def _load_dotenv() -> None:
    """Parse .env from project root and populate os.environ (setdefault — never overwrite)."""
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_dotenv()
# Unit tests that mock the LLM still need a non-empty key to pass pydantic validation
os.environ.setdefault("LLM_API_KEY", "test-key-for-testing")
