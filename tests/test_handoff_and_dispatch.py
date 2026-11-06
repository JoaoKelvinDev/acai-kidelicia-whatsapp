import pytest

from app.domain.enums import ConversationState, OutboundStatus, ReplyKind
from app.integrations.whatsapp.gateway import GatewayError
from app.repositories.base import ConcurrencyError
from app.services.handoff import ConversationNotFoundError
from tests.conftest import SENDER, load_order


async def test_take_over_cancels_reply_not_yet_sent(h):
    await h.receive("Oi", dispatch=False)
    conv = await h.c.handoff.take_over(SENDER, "joao")
    assert conv.state is ConversationState.HUMAN_ACTIVE
    assert conv.assignee == "joao"
    await h.c.dispatcher.dispatch_pending(SENDER)
    assert h.gateway.sent == []
    [intent] = await h.outbound()
    assert intent.status is OutboundStatus.CANCELLED


async def test_stale_epoch_is_rechecked_at_send_time(h):
    """Mesmo que a intenção escape do cancelamento em lote, a época impede o envio."""
    await h.receive("Oi", dispatch=False)
    [intent] = await h.outbound()
    conv = await h.conversation()
    conv.reply_epoch += 1
    await h.c.repo.save_conversation(conv)
    [result] = await h.c.dispatcher.dispatch_pending(SENDER)
    assert result.status is OutboundStatus.CANCELLED
    assert result.status_reason == "estado_alterado"
    assert intent.id == result.id
    assert h.gateway.sent == []


async def test_confirmation_created_with_handoff_is_still_sent(h):
    await h.receive(load_order("delivery_pix_valido"))
    assert (await h.conversation()).state is ConversationState.HUMAN_PENDING
    assert await h.sent_kinds() == [ReplyKind.CONFIRMATION]


async def test_global_pause_cancels_pending_reply(h):
    await h.receive("Oi", dispatch=False)
    await h.c.handoff.set_global_pause(True, "joao")
    [result] = await h.c.dispatcher.dispatch_pending(SENDER)
    assert result.status is OutboundStatus.CANCELLED
    assert result.status_reason == "pausa_global"
    assert h.gateway.sent == []


async def test_outside_24h_window_free_text_is_blocked_not_faked(h, clock):
    await h.receive("Oi", dispatch=False)
    clock.advance(hours=24, seconds=1)
    [result] = await h.c.dispatcher.dispatch_pending(SENDER)
    assert result.status is OutboundStatus.BLOCKED
    assert result.status_reason == "fora_da_janela_de_atendimento"
    assert result.sent_at is None
    assert h.gateway.sent == []


async def test_inside_24h_window_is_sent(h, clock):
    await h.receive("Oi", dispatch=False)
    clock.advance(hours=23, minutes=59)
    [result] = await h.c.dispatcher.dispatch_pending(SENDER)
    assert result.status is OutboundStatus.SENT


async def test_gateway_failure_is_recorded(h):
    h.gateway.fail_next(GatewayError("rate_limit", retryable=True))
    await h.receive("Oi")
    [intent] = await h.outbound()
    assert intent.status is OutboundStatus.FAILED
    assert intent.status_reason == "rate_limit"


async def test_unknown_outcome_is_not_resent_blindly(h):
    h.gateway.fail_next(GatewayError("timeout", outcome_unknown=True))
    await h.receive("Oi")
    await h.c.dispatcher.dispatch_pending(SENDER)
    [intent] = await h.outbound()
    assert intent.status is OutboundStatus.UNKNOWN
    assert h.gateway.sent == []


async def test_resume_returns_to_automation(h):
    await h.receive(load_order("delivery_pix_valido"))
    conv = await h.c.handoff.resume(SENDER, "joao")
    assert conv.state is ConversationState.AUTO_ACTIVE
    assert conv.active_draft_id is None
    await h.receive("Oi")
    assert (await h.kinds())[-1] is ReplyKind.GREETING


async def test_pause_then_messages_are_only_recorded(h):
    await h.receive("Oi")
    await h.c.handoff.pause(SENDER, "joao")
    result = await h.receive("quero um açaí")
    assert result.outbound_ids == []
    assert (await h.conversation()).state is ConversationState.HUMAN_PENDING


async def test_close_keeps_history(h):
    await h.receive("Oi")
    await h.c.handoff.close(SENDER, "joao")
    assert (await h.conversation()).state is ConversationState.CLOSED
    assert len(await h.c.repo.list_inbound(SENDER)) == 1
    assert len(await h.outbound()) == 1


async def test_actions_require_actor_and_existing_conversation(h):
    with pytest.raises(ValueError):
        await h.c.handoff.pause(SENDER, "  ")
    with pytest.raises(ConversationNotFoundError):
        await h.c.handoff.pause("5511000000001", "joao")


async def test_audit_records_transitions_without_personal_data(h):
    await h.receive(load_order("delivery_pix_valido"))
    await h.c.handoff.take_over(SENDER, "joao")
    events = await h.c.repo.list_audit(SENDER)
    transitions = [e for e in events if e.kind == "transicao_estado"]
    assert [(e.detail["para"], e.actor) for e in transitions] == [
        ("HUMAN_PENDING", "bot"),
        ("HUMAN_ACTIVE", "joao"),
    ]
    # conversation_id é o wa_id (identidade da conversa); detalhes não repetem dados pessoais.
    dumped = str([(e.kind, e.actor, e.detail) for e in events])
    for personal in ("Mariana", "97412", "Acácias", "padaria"):
        assert personal not in dumped


async def test_optimistic_version_check(h):
    await h.receive("Oi")
    stale = await h.conversation()
    fresh = await h.conversation()
    await h.c.repo.save_conversation(fresh)
    with pytest.raises(ConcurrencyError):
        await h.c.repo.save_conversation(stale)
