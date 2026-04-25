"""Alembic migration environment.

`.env` is the single source of truth for ``DATABASE_URL``, matching how
the FastAPI app loads config via pydantic-settings. This ensures
migrations and the running app always target the same DB. Models are
imported so ``target_metadata = Base.metadata`` sees every table.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from alembic import context
from app.db.models import Base

load_dotenv(override=False)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_db_url = os.environ.get("DATABASE_URL")
if not _db_url:
    msg = (
        "DATABASE_URL is not set. Configure it in backend/.env or export "
        "it inline before running alembic (e.g. "
        "`DATABASE_URL=sqlite:///./data/ci.db alembic upgrade head`)."
    )
    raise RuntimeError(msg)
config.set_main_option("sqlalchemy.url", _db_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
