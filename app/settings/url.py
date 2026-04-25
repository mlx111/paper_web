"""Connection settings loaded from environment variables."""

from pathlib import Path
import os

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(dotenv_path=None, override=False):  # type: ignore[override]
        if dotenv_path is None:
            return False

        path = Path(dotenv_path)
        if not path.exists():
            return False

        loaded = False
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and (override or key not in os.environ):
                os.environ[key] = value
                loaded = True
        return loaded


load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=False)


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _get_str(name: str, default: str) -> str:
    return os.getenv(name, default)


DB_URL = _get_str("DB_URL", "mysql+aiomysql://root:password@localhost:3306/paper?charset=utf8")
REDIS_URL = _get_str("REDIS_URL", "redis://localhost:6379/0")

MAIL_SERVER = _get_str("MAIL_SERVER", "smtp.example.com")
MAIL_PORT = _get_int("MAIL_PORT", 465)
MAIL_USERNAME = _get_str("MAIL_USERNAME", "")
MAIL_PASSWORD = _get_str("MAIL_PASSWORD", "")
MAIL_FROM = _get_str("MAIL_FROM", MAIL_USERNAME)
MAIL_FROM_NAME = _get_str("MAIL_FROM_NAME", "MyPaperWeb")
MAIL_SSL_TLS = _get_bool("MAIL_SSL_TLS", True)
MAIL_STARTTLS = _get_bool("MAIL_STARTTLS", False)
