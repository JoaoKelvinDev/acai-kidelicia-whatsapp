"""Transição de estado da conversa, compartilhada pelo bot e pelo controle humano."""

from datetime import datetime

from app.domain.enums import HUMAN_STATES, ConversationState
from app.domain.models import AuditEvent, Conversation
from app.repositories.base import Repository

_EPOCH_STATES = HUMAN_STATES | {ConversationState.CLOSED}


async def transition(
    repo: Repository,
    conv: Conversation,
    new_state: ConversationState,
    *,
    reason: str,
    actor: str,
    now: datetime,
) -> None:
    """Muda o estado (o chamador grava a conversa).

    Ao entrar ou sair de estado humano/encerrado, a época de respostas avança e toda resposta
    automática ainda não enviada é cancelada. Respostas criadas depois desta chamada (ex.: a
    própria confirmação que acompanha o handoff) recebem a época nova e seguem válidas.
    """
    old_state = conv.state
    cancelled = 0
    if new_state in _EPOCH_STATES or old_state in _EPOCH_STATES:
        conv.reply_epoch += 1
        cancelled = await repo.cancel_pending_outbound(
            conv.id, reason=f"transicao_{new_state.value.lower()}", now=now
        )
    conv.state = new_state
    conv.updated_at = now
    conv.handoff_reason = reason if new_state in HUMAN_STATES else None
    await repo.add_audit(
        AuditEvent(
            conversation_id=conv.id,
            kind="transicao_estado",
            actor=actor,
            detail={
                "de": old_state.value,
                "para": new_state.value,
                "motivo": reason,
                "respostas_canceladas": cancelled,
            },
            created_at=now,
        )
    )
