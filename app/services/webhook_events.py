"""Aplicação dos eventos do webhook que não são mensagens de cliente.

- Status de entrega: deduplicados por (id, status, horário) e aplicados à resposta enviada,
  sem regredir (lida não volta para entregue). Falha de entrega fica registrada; não há reenvio
  automático. Status nunca vira mensagem nem gera resposta (sem loop).
- Eco do app do celular (coexistência): a equipe respondeu pelo aplicativo, então a automação
  daquela conversa é pausada (HUMAN_ACTIVE). Comportamento a validar com evento real.
"""

import logging

from app.core.clock import Clock
from app.core.logging import mask_id
from app.domain.enums import AUTOMATED_STATES, ConversationState, DeliveryStatus
from app.domain.models import Conversation, DeliveryStatusEvent
from app.integrations.whatsapp.webhook import OwnerEcho, StatusUpdate
from app.repositories.base import Database
from app.services.transitions import transition

logger = logging.getLogger(__name__)

APP_ECHO_ACTOR = "app_whatsapp"
_RANK = {
    DeliveryStatus.SENT: 1,
    DeliveryStatus.DELIVERED: 2,
    DeliveryStatus.READ: 3,
    DeliveryStatus.FAILED: 4,
}


class WebhookEventService:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def apply_status(self, update: StatusUpdate) -> bool:
        """True se o status foi aplicado a uma resposta nossa."""
        now = self._clock.now()
        event = DeliveryStatusEvent(
            idempotency_key=(
                f"{update.provider_message_id}:{update.status.value}:"
                f"{int(update.timestamp.timestamp())}"
            ),
            provider_message_id=update.provider_message_id,
            status=update.status,
            occurred_at=update.timestamp,
            error_code=update.error_code,
            error_title=update.error_title,
            received_at=now,
        )
        async with self._db.transaction() as tx:
            if not await tx.add_status_event(event):
                return False
            intent = await tx.get_outbound_by_provider_id(update.provider_message_id)
            if intent is None:
                return False  # ex.: mensagem enviada pelo painel da Meta
            current = _RANK.get(intent.delivery_status, 0) if intent.delivery_status else 0
            if update.status is DeliveryStatus.DELIVERED:
                intent.delivered_at = intent.delivered_at or update.timestamp
            if update.status is DeliveryStatus.READ:
                intent.read_at = intent.read_at or update.timestamp
            if _RANK[update.status] > current:
                intent.delivery_status = update.status
                if update.status is DeliveryStatus.FAILED:
                    intent.delivery_error_code = update.error_code
                    logger.warning(
                        "entrega falhou conversa=%s codigo=%s",
                        mask_id(intent.conversation_id),
                        update.error_code,
                    )
            intent.updated_at = now
            await tx.save_outbound(intent)
        return True

    async def apply_owner_echo(self, echo: OwnerEcho) -> bool:
        """True se a automação da conversa foi pausada por causa do eco."""
        now = self._clock.now()
        async with self._db.transaction() as tx:
            conv = await tx.get_conversation(echo.to_wa_id)
            if conv is None:
                # A loja iniciou a conversa pelo app: o bot não deve assumir depois.
                conv = Conversation(id=echo.to_wa_id, created_at=now, updated_at=now)
            elif conv.state not in AUTOMATED_STATES:
                return False
            await transition(
                tx,
                conv,
                ConversationState.HUMAN_ACTIVE,
                reason="resposta_pelo_aplicativo",
                actor=APP_ECHO_ACTOR,
                now=now,
            )
            conv.assignee = APP_ECHO_ACTOR
            await tx.save_conversation(conv)
        return True
