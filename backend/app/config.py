import os
from pathlib import Path

from dotenv import load_dotenv

# 必须在读取 os.environ 之前加载 .env，否则类属性会吃到空默认值。
_BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv()  # 也允许从 cwd 覆盖


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///./data/keep_password.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://127.0.0.1:5173").split(",") if o.strip()]
    VAULT_STORAGE_DIR = Path(os.environ.get("VAULT_STORAGE_DIR", "./data/vaults")).resolve()
    MAX_VAULT_BYTES = int(os.environ.get("MAX_VAULT_BYTES", str(16 * 1024 * 1024)))
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "noreply@example.com")
    SMTP_USE_TLS = _env_bool("SMTP_USE_TLS", True)
    MAIL_DEV_CONSOLE = _env_bool("MAIL_DEV_CONSOLE", True)
    # 仅在前面有可信反向代理（如 Caddy）时开启，才会读取 X-Forwarded-For
    TRUST_PROXY = _env_bool("TRUST_PROXY", False)
    JWT_WEB_HOURS = int(os.environ.get("JWT_WEB_HOURS", "168"))
    JWT_DEVICE_DAYS = int(os.environ.get("JWT_DEVICE_DAYS", "365"))
    PASSWORD_MIN_LENGTH = 12
    ARGON2_TIME_COST = 3
    ARGON2_MEMORY_COST = 65536
    ARGON2_PARALLELISM = 2
    LOGIN_FAIL_LIMIT = 8
    LOGIN_FAIL_WINDOW_SECONDS = 900
    CAPTCHA_AFTER_FAILURES = 3
    EMAIL_CODE_MAX_ATTEMPTS = int(os.environ.get("EMAIL_CODE_MAX_ATTEMPTS", "5"))
