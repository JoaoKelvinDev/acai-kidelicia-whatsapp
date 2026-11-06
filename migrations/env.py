"""Ambiente do Alembic (assíncrono). A URL vem da config do Alembic ou de DATABASE_URL."""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection

from app.core.config import Settings
from app.db.engine import create_engine
from app.db.schema import metadata

config = context.config
target_metadata = metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or Settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # necessário para ALTER TABLE no SQLite
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_engine(_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
            await connection.commit()
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(_run_async())
