"""Retenção de 14 dias (decisão do proprietário)."""

from datetime import timedelta

from app.domain.enums import ConversationState
from app.domain.operators import Session
from tests.conftest import OTHER_SENDER, SENDER, load_order


async def test_inactive_conversation_is_deleted_after_14_days(h, clock):
    await h.receive(load_order("delivery_pix_valido"))
    await h.c.handoff.close(SENDER, "joao")
    clock.advance(days=13)
    report = await h.c.retention.purge()
    assert report.conversations_deleted == 0

    clock.advance(days=1, seconds=1)
    report = await h.c.retention.purge()
    assert report.conversations_deleted == 1
    assert await h.q("get_conversation", SENDER) is None
    assert await h.q("list_inbound", SENDER) == []
    assert await h.q("list_drafts", SENDER) == []
    assert await h.q("list_outbound", SENDER) == []
    # Os números ficam (auditoria), sem o identificador do cliente.
    events = await h.q("list_audit")
    transitions = [e for e in events if e.kind == "transicao_estado"]
    assert [e.detail["motivo"] for e in transitions] == ["pedido_recebido", "encerrada"]
    assert all(e.conversation_id is None for e in events)
    assert SENDER not in str([e.model_dump() for e in events])


async def test_conversation_with_team_is_never_purged(h, clock):
    await h.receive(load_order("delivery_pix_valido"))  # HUMAN_PENDING
    clock.advance(days=60)
    report = await h.c.retention.purge()
    assert report.conversations_deleted == 0
    assert (await h.conversation()).state is ConversationState.HUMAN_PENDING
    assert (await h.q("list_inbound", SENDER))[0].text is not None


async def test_old_records_of_active_conversation_are_redacted(h, clock):
    await h.receive(load_order("delivery_pix_valido"))
    await h.c.handoff.resume(SENDER, "joao")
    clock.advance(days=15)
    await h.receive("Oi")  # conversa segue ativa

    report = await h.c.retention.purge()
    assert report.conversations_deleted == 0
    assert report.messages_redacted == 1
    assert report.replies_redacted == 1
    assert report.drafts_redacted == 1

    old, new = await h.q("list_inbound", SENDER)
    assert old.text is None and old.redacted_at is not None
    assert new.text == "Oi"
    draft = await h.only_draft()
    assert draft.name is None and draft.address is None and draft.phone_raw is None
    assert draft.items and draft.items[0].size == "Copo 500ml"  # estatística sem dado pessoal
    replies = await h.outbound()
    assert replies[0].text == "" and replies[1].text != ""


async def test_dry_run_counts_without_changing(h, clock):
    await h.receive("Oi")
    clock.advance(days=20)
    report = await h.c.retention.purge(dry_run=True)
    assert report.dry_run and report.conversations_deleted == 1
    assert await h.q("get_conversation", SENDER) is not None
    assert not any(e.kind == "retencao_executada" for e in await h.q("list_audit"))


async def test_audit_and_expired_sessions_are_purged(h, clock):
    await h.receive("Oi", sender=OTHER_SENDER)
    await h.c.handoff.take_over(OTHER_SENDER, "joao")
    operator = await h.c.auth.create_operator("joao", "senha-segura-123", "admin")
    await h.q(
        "add_session",
        Session(
            token_hash="a" * 64,
            operator_id=operator.id,
            csrf_token="x",
            created_at=clock.now(),
            expires_at=clock.now() + timedelta(hours=1),
        ),
    )
    clock.advance(days=366)
    report = await h.c.retention.purge()
    assert report.audit_deleted >= 1
    assert report.sessions_deleted == 1
    # Conversa com a equipe permanece, mesmo antiga.
    assert await h.q("get_conversation", OTHER_SENDER) is not None
    assert [e.kind for e in await h.q("list_audit")] == ["retencao_executada"]
