import logging
import os
from logging.config import fileConfig

from alembic import context

from app import create_app
from app.extensions import db

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

os.environ.setdefault("ALEMBIC_RUNNING", "1")

_flask_app = create_app()

target_metadata = db.metadata


def _configure_url_from_app() -> str:
    database_uri = _flask_app.config["SQLALCHEMY_DATABASE_URI"]
    config.set_main_option("sqlalchemy.url", database_uri)
    return database_uri


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""

    url = _configure_url_from_app()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        compare_type=True,
        compare_server_default=True,
        version_table_schema="ops",
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    _configure_url_from_app()

    with _flask_app.app_context():
        connectable = db.engine

        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                include_schemas=True,
                compare_type=True,
                compare_server_default=True,
                version_table_schema="ops",
            )

            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
