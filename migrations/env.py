"""Alembic environment configuration for the OBYRA project."""

from __future__ import annotations

from dotenv import load_dotenv
load_dotenv()

import os
from contextlib import nullcontext
from logging.config import fileConfig
from pathlib import Path
from typing import Optional

from alembic import context
from sqlalchemy import engine_from_config, pool, text
from extensions import db

config = context.config
target_metadata = db.metadata


def _configure_logging() -> None:
    candidates = []
    if config.config_file_name:
        candidates.append(Path(config.config_file_name))
    candidates.append(Path(__file__).resolve().parent.parent / "alembic.ini")
    for candidate in candidates:
        if candidate and candidate.exists():
            fileConfig(str(candidate))
            break


def _escape_percent(url: str) -> str:
    if "%" not in url:
        return url
    return url.replace("%", "%%").replace("%%%%", "%%")


def _set_sqlalchemy_url(url: str) -> str:
    if not url:
        raise RuntimeError(
            "ALEMBIC_DATABASE_URL no está definido y alembic.ini no provee sqlalchemy.url"
        )
    config.set_main_option("sqlalchemy.url", _escape_percent(url))
    return url


def _convert_railway_url(url: str) -> str:
    """Convertir URL de Railway al formato SQLAlchemy con psycopg."""
    if url and url.startswith("postgresql://") and "+psycopg" not in url:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _get_url() -> str:
    env_url = os.getenv("ALEMBIC_DATABASE_URL")
    if env_url:
        return _set_sqlalchemy_url(_convert_railway_url(env_url))

    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return _set_sqlalchemy_url(ini_url)

    raise RuntimeError("No database URL available for Alembic")


def _load_flask_app() -> Optional["Flask"]:
    try:
        from app import app as flask_app
        return flask_app
    except Exception:
        try:
            from app import create_app
        except Exception:
            return None
        return create_app()


_flask_app = _load_flask_app()


def _app_context_scope():
    if _flask_app is None:
        return nullcontext()
    try:
        from flask import has_app_context
        if has_app_context():
            return nullcontext()
    except Exception:
        return nullcontext()
    return _flask_app.app_context()


def _ensure_models_loaded() -> None:
    try:
        import models  # noqa: F401
    except Exception as exc:
        logger = None
        if _flask_app is not None:
            logger = getattr(_flask_app, "logger", None)
        if logger is not None:
            logger.warning("No se pudieron cargar los modelos para Alembic: %s", exc)


def run_migrations_offline() -> None:
    url = _get_url()
    configure_args = dict(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table="alembic_version",
        version_table_schema="app",
        compare_type=True,
        compare_server_default=True,
    )
    with _app_context_scope():
        _ensure_models_loaded()
        context.configure(**configure_args)
        with context.begin_transaction():
            context.run_migrations()


def run_migrations_online() -> None:
    url = _get_url()
    section = dict(config.get_section(config.config_ini_section) or {})
    section["sqlalchemy.url"] = url

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        try:
            # Asegura que todo caiga en schema app por defecto
            connection.exec_driver_sql("SET search_path TO app, public")
        except Exception:
            pass

        configure_args = dict(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table="alembic_version",
            version_table_schema="app",
            compare_type=True,
            compare_server_default=True,
        )
        with _app_context_scope():
            _ensure_models_loaded()
            context.configure(**configure_args)
            with context.begin_transaction():
                context.run_migrations()


def main() -> None:
    _configure_logging()
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()


main()
