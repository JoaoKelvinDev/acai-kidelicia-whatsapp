"""Estado durável: reinício, transação única e migrações."""

import asyncio

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from app.db.engine import (
    DatabaseNotMigratedError,
    alembic_config,
    create_engine,
    ensure_migrated,
)
from app.db.schema import metadata
from app.domain.enums import ConversationState, OutboundStatus, ReplyKind
from tests.conftest import SENDER, load_order, sqlite_url

# ── reinício ────────────────────────────────────────────────────────────────


async def test_restart_preserves_pending_data_state_and_processed_ids(harness_factory, tmp_path):
    db_path = tmp_path / "restart.sqlite"
    first = await harness_factory(db_path=db_path)
    await first.receive(load_order("delivery_dinheiro_sem_troco"), msg_id="wamid.A", dispatch=False)
    draft_id = (await first.only_draft()).id
    await first.c.engine.dispose()  # "desliga" o processo

    second = await harness_factory(db_path=db_path)
    conv = await second.conversation()
    assert conv.state is ConversationState.COLLECTING_DATA
    assert conv.active_draft_id == draft_id

    # Resposta pendente gravada antes do reinício é enviada pelo novo processo.
    [sent] = await second.c.dispatcher.dispatch_pending(SENDER)
    assert sent.kind is ReplyKind.ASK_DATA and sent.status is OutboundStatus.SENT

    # ID já processado continua deduplicado.
    again = await second.receive(load_order("delivery_dinheiro_sem_troco"), msg_id="wamid.A")
    assert again.duplicate

    # Pendência continua no mesmo rascunho.
    await second.receive("não preciso")
    assert (await second.kinds())[-1] is ReplyKind.CONFIRMATION
    assert (await second.only_draft()).id == draft_id


async def test_restart_preserves_global_pause_and_human_state(harness_factory, tmp_path):
    db_path = tmp_path / "pause.sqlite"
    first = await harness_factory(db_path=db_path)
    await first.receive("Oi")
    await first.c.handoff.take_over(SENDER, "joao")
    await first.c.handoff.set_global_pause(True, "joao")
    await first.c.engine.dispose()

    second = await harness_factory(db_path=db_path)
    assert (await second.q("get_store_settings")).automation_paused is True
    conv = await second.conversation()
    assert conv.state is ConversationState.HUMAN_ACTIVE
    assert conv.assignee == "joao"


# ── transação única ─────────────────────────────────────────────────────────


async def test_failure_mid_processing_rolls_back_everything(h, monkeypatch):
    async def explode(_ctx):
        raise RuntimeError("falha simulada")

    original = h.c.conversations._route
    monkeypatch.setattr(h.c.conversations, "_route", explode)
    with pytest.raises(RuntimeError):
        await h.receive(load_order("delivery_pix_valido"), msg_id="wamid.R")
    assert await h.q("list_inbound", SENDER) == []
    assert await h.q("get_conversation", SENDER) is None

    # O reenvio do mesmo evento (retry do provedor) é processado normalmente.
    monkeypatch.setattr(h.c.conversations, "_route", original)
    result = await h.receive(load_order("delivery_pix_valido"), msg_id="wamid.R")
    assert not result.duplicate
    assert await h.kinds() == [ReplyKind.CONFIRMATION]


async def test_concurrent_events_on_real_database(h):
    order = load_order("delivery_pix_valido")
    results = await asyncio.gather(*(h.receive(order, msg_id="wamid.C") for _ in range(5)))
    assert sum(not r.duplicate for r in results) == 1
    assert len(h.gateway.sent) == 1


# ── migrações ───────────────────────────────────────────────────────────────


def _diff(url: str) -> list:
    async def run() -> list:
        engine = create_engine(url)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(
                    lambda c: compare_metadata(MigrationContext.configure(c), metadata)
                )
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _tables(url: str) -> set[str]:
    async def run() -> set[str]:
        engine = create_engine(url)
        try:
            async with engine.connect() as conn:
                return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_migrations_match_schema_and_downgrade(tmp_path):
    url = sqlite_url(tmp_path / "migr.sqlite")
    config = alembic_config(url)
    command.upgrade(config, "head")
    assert _diff(url) == []
    assert {"conversations", "outbound_messages", "operators", "sessions"} <= _tables(url)
    command.downgrade(config, "base")
    assert _tables(url) <= {"alembic_version"}


async def test_unmigrated_database_is_refused(tmp_path):
    engine = create_engine(sqlite_url(tmp_path / "vazio.sqlite"))
    try:
        with pytest.raises(DatabaseNotMigratedError):
            await ensure_migrated(engine)
    finally:
        await engine.dispose()
