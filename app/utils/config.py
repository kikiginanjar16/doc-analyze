import os
from pathlib import Path


def load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        os.environ.setdefault(key, value)


load_dotenv()

def env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def env_str(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or default).strip()

OPENAI_API_KEY = env_str("OPENAI_API_KEY")
OPENAI_MODEL_TEXT = env_str("OPENAI_MODEL_TEXT", "gpt-4.1-mini")
OPENAI_MODEL_VISION = env_str("OPENAI_MODEL_VISION", OPENAI_MODEL_TEXT)

DATABASE_URL = env_str("DATABASE_URL")

MAX_PAGES_DEFAULT = env_int("MAX_PAGES_DEFAULT", 10)
MAX_SLIDES_DEFAULT = env_int("MAX_SLIDES_DEFAULT", 20)
SCAN_TEXT_THRESHOLD = env_int("SCAN_TEXT_THRESHOLD", 200)
REQUEST_TIMEOUT_SECONDS = env_int("REQUEST_TIMEOUT_SECONDS", 120)
WEBHOOK_TIMEOUT_SECONDS = env_int("WEBHOOK_TIMEOUT_SECONDS", 15)
WEBHOOK_MAX_RETRIES = env_int("WEBHOOK_MAX_RETRIES", 3)
WEBHOOK_RETRY_BACKOFF_SECONDS = env_int("WEBHOOK_RETRY_BACKOFF_SECONDS", 2)
