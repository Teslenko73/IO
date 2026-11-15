"""Konfiguracja aplikacji ze zmiennych środowiskowych."""
import logging
import os
from dataclasses import dataclass
from datetime import timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)


def _to_bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _async_url(url: str) -> str:
    """Akceptuje też zwykłe postgresql://, bo SQLAlchemy async potrzebuje asyncpg."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    return url


def database_url_from_env() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Brak zmiennej środowiskowej DATABASE_URL, "
            "np. postgresql+asyncpg://user:haslo@localhost:5432/baza"
        )
    return _async_url(url)


@dataclass(frozen=True)
class Settings:
    database_url: str
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "no-reply@localhost"
    smtp_tls: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            database_url=database_url_from_env(),
            smtp_host=env.get("SMTP_HOST") or None,
            smtp_port=int(env.get("SMTP_PORT") or 587),
            smtp_user=env.get("SMTP_USER") or None,
            smtp_password=env.get("SMTP_PASSWORD") or None,
            smtp_from=env.get("SMTP_FROM") or "no-reply@localhost",
            smtp_tls=_to_bool(env.get("SMTP_TLS"), True),
        )


def mail_timezone_from_env() -> tzinfo:
    """Strefa, w której daty są pokazywane w mailach (domyślnie Europe/Warsaw)."""
    name = os.environ.get("MAIL_TIMEZONE") or "Europe/Warsaw"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning("Nieznana strefa MAIL_TIMEZONE=%r, używam UTC", name)
        return timezone.utc


def cors_origins_from_env() -> list[str]:
    """CORS_ORIGINS=https://formularz.example.com,http://localhost:3000 (puste = bez CORS)."""
    raw = os.environ.get("CORS_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip()]
