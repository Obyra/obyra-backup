from __future__ import annotations

import logging
import os
from logging.config import fileConfig

from alembic import context
from extensions import db

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger('alembic.env')

os.environ.setdefault("ALEMBIC_RUNNING", "1")

from app import app  # noqa: E402  pylint: disable=wrong-import-position

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
# target_metadata = None
target_metadata = db.metadata


def _configure_url_from_app() -> str:
    url = app.config["SQLALCHEMY_DATABASE_URI"]
    config.set_main_option("sqlalchemy.url", url)
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""

    url = _configure_url_from_app()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    _configure_url_from_app()

    with app.app_context():
        connectable = db.engine

        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
            )

            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
