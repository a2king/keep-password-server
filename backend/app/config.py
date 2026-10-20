import os
from pathlib import Path


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///./data/keep_password.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
    VAULT_STORAGE_DIR = Path(os.environ.get("VAULT_STORAGE_DIR", "./data/vaults")).resolve()
    MAX_VAULT_BYTES = int(os.environ.get("MAX_VAULT_BYTES", str(16 * 1024 * 1024)))
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "noreply@example.com")
    SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")
    MAIL_DEV_CONSOLE = os.environ.get("MAIL_DEV_CONSOLE", "true").lower() in ("1", "true", "yes")
    JWT_WEB_HOURS = int(os.environ.get("JWT_WEB_HOURS", "168"))
    JWT_DEVICE_DAYS = int(os.environ.get("JWT_DEVICE_DAYS", "365"))
    PASSWORD_MIN_LENGTH = 12
    ARGON2_TIME_COST = 3
    ARGON2_MEMORY_COST = 65536
    ARGON2_PARALLELISM = 2
    LOGIN_FAIL_LIMIT = 8
    LOGIN_FAIL_WINDOW_SECONDS = 900
    CAPTCHA_AFTER_FAILURES = 3
