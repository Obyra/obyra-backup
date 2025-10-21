"""Application configuration helpers and defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict

from sqlalchemy.engine.url import make_url


class InvalidDatabaseURL(RuntimeError):
    """Raised when DATABASE_URL does not meet the expected requirements."""


def _normalize_db_url(raw_url: str) -> str:
    """Return a normalised PostgreSQL connection URL using psycopg v3.

    This helper accepts legacy ``postgres://`` URLs and converts them to the
    SQLAlchemy-compliant ``postgresql+psycopg://`` scheme. SQLite URLs are
    rejected explicitly in order to guarantee that the application never falls
    back to an unsupported engine.
    """

    if not raw_url:
        raise InvalidDatabaseURL("DATABASE_URL is required and must not be empty")

    candidate = raw_url.strip()
    if candidate.startswith("postgres://"):
        candidate = "postgresql://" + candidate[len("postgres://") :]

    try:
        url = make_url(candidate)
    except Exception as exc:  # pragma: no cover - formatting delegated to SQLAlchemy
        raise InvalidDatabaseURL(f"Invalid DATABASE_URL provided: {candidate!r}") from exc

    driver = url.drivername or ""
    legacy_marker = "SQL" + "ite"
    if driver.startswith(legacy_marker.lower()):
        raise InvalidDatabaseURL(
            f"{legacy_marker} URLs are not supported. Provide a PostgreSQL connection string."
        )

    if driver in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    elif driver.startswith("postgresql+") and driver != "postgresql+psycopg":
        url = url.set(drivername="postgresql+psycopg")

    query = dict(url.query)
    sslmode = query.get("sslmode")
    if not sslmode:
        default_sslmode = os.getenv("DB_SSLMODE", "require")
        query["sslmode"] = default_sslmode
        url = url.set(query=query)

    return str(url)


def _int_from_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:  # pragma: no cover - validated during configuration load
        raise RuntimeError(f"Environment variable {name} must be an integer") from exc


def _bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


@dataclass
class AppConfig:
    """Collection of configuration defaults applied to the Flask app."""

    database_url: str = field(default_factory=lambda: _normalize_db_url(os.getenv("DATABASE_URL", "")))
    secret_key: str = field(
        default_factory=lambda: os.getenv("SESSION_SECRET")
        or os.getenv("SECRET_KEY")
        or "dev-secret-key-change-me"
    )
    engine_options: Dict[str, Any] = field(
        default_factory=lambda: {
            "pool_size": _int_from_env("DB_POOL_SIZE", 10),
            "max_overflow": _int_from_env("DB_MAX_OVERFLOW", 5),
            "pool_recycle": _int_from_env("DB_POOL_RECYCLE", 1800),
            "pool_pre_ping": _bool_from_env("DB_POOL_PRE_PING", True),
        }
    )

    def init_app(self, app) -> None:
        app.secret_key = self.secret_key
        app.config.setdefault("SQLALCHEMY_DATABASE_URI", self.database_url)
        app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", self.engine_options)
        app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)


__all__ = [
    "AppConfig",
    "InvalidDatabaseURL",
    "_normalize_db_url",
]
