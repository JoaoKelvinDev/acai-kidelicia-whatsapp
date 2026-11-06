"""Engine assíncrona e verificação de migrações."""

from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import event
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.db.schema import metadata

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_engine(url: str) -> AsyncEngine:
    parsed = make_url(url)
    is_sqlite = parsed.get_backend_name() == "sqlite"
    if is_sqlite and parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(url)
    if is_sqlite:
        _configure_sqlite(engine)
    return engine


def _configure_sqlite(engine: AsyncEngine) -> None:
    """Transações de escrita serializadas (BEGIN IMMEDIATE) e espera em vez de erro de lock.

    Receita da documentação do SQLAlchemy para aiosqlite: desliga o BEGIN automático do
    driver e emite o BEGIN explicitamente, o que também corrige SAVEPOINTs.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(engine.sync_engine, "begin")
    def _on_begin(conn: Connection) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE")


async def create_schema(engine: AsyncEngine) -> None:
    """Somente para testes. Produção e desenvolvimento usam `python -m app.cli migrate`."""
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


class DatabaseNotMigratedError(RuntimeError):
    pass


async def ensure_migrated(engine: AsyncEngine) -> None:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    async with engine.connect() as conn:
        current = await conn.run_sync(
            lambda sync_conn: MigrationContext.configure(sync_conn).get_current_revision()
        )
    if current != head:
        raise DatabaseNotMigratedError(
            f"Banco na revisão {current!r}, esperado {head!r}. "
            "Rode: uv run python -m app.cli migrate"
        )
