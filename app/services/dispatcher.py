"""Envio das intenções de resposta, com revalidação imediatamente antes do envio.

Risco residual (documentado): uma intenção já marcada como SENDING não pode ser cancelada.
Se a equipe assumir a conversa nesse intervalo, a mensagem em trânsito ainda chega ao cliente.
"""

import logging
from datetime import timedelta

from app.core.clock import Clock
from app.core.logging import mask_id
from app.domain.enums import ConversationState, OutboundStatus
from app.domain.models import Conversation, OutboundIntent
from app.domain.store import StoreSettings
from app.integrations.whatsapp.gateway import GatewayError, MessagingGateway
from app.repositories.base import Repository

logger = logging.getLogger(__name__)


class Dispatcher:
    def __init__(self, repo: Repository, gateway: MessagingGateway, clock: Clock) -> None:
        self._repo = repo
        self._gateway = gateway
        self._clock = clock

    async def dispatch_pending(self, conversation_id: str) -> list[OutboundIntent]:
        pending = await self._repo.list_outbound(conversation_id, OutboundStatus.PENDING)
        pending.sort(key=lambda i: i.created_at)
        return [await self._dispatch_one(conversation_id, i.id) for i in pending]

    async def _dispatch_one(self, conversation_id: str, intent_id: str) -> OutboundIntent:
        async with self._repo.lock(conversation_id):
            intent = await self._repo.get_outbound(intent_id)
            if intent is None:
                raise KeyError(intent_id)
            if intent.status is not OutboundStatus.PENDING:
                return intent
            conv = await self._repo.get_conversation(conversation_id)
            store = await self._repo.get_store_settings()
            now = self._clock.now()
            blocked = self._block_reason(intent, conv, store)
            if blocked:
                intent.status, intent.status_reason = blocked
                intent.updated_at = now
                await self._repo.save_outbound(intent)
                logger.info(
                    "resposta nao enviada conversa=%s motivo=%s",
                    mask_id(conversation_id),
                    intent.status_reason,
                )
                return intent
            intent.status = OutboundStatus.SENDING
            intent.updated_at = now
            await self._repo.save_outbound(intent)

        # Fora do lock: a chamada de rede não segura o processamento da conversa.
        try:
            result = await self._gateway.send_text(intent.conversation_id, intent.text)
        except GatewayError as exc:
            intent.status = OutboundStatus.UNKNOWN if exc.outcome_unknown else OutboundStatus.FAILED
            intent.status_reason = exc.code
            logger.warning(
                "falha no envio conversa=%s codigo=%s", mask_id(conversation_id), exc.code
            )
        else:
            intent.status = OutboundStatus.SENT
            intent.provider_message_id = result.provider_message_id
            intent.sent_at = self._clock.now()
        intent.updated_at = self._clock.now()
        await self._repo.save_outbound(intent)
        return intent

    def _block_reason(
        self, intent: OutboundIntent, conv: Conversation | None, store: StoreSettings
    ) -> tuple[OutboundStatus, str] | None:
        if store.automation_paused:
            return OutboundStatus.CANCELLED, "pausa_global"
        if conv is None:
            return OutboundStatus.CANCELLED, "conversa_inexistente"
        if intent.reply_epoch != conv.reply_epoch:
            return OutboundStatus.CANCELLED, "estado_alterado"
        if conv.state is ConversationState.CLOSED:
            return OutboundStatus.CANCELLED, "conversa_encerrada"
        last = conv.last_customer_message_at
        window = timedelta(hours=store.service_window_hours)
        if last is None or self._clock.now() - last > window:
            # Fora da janela de atendimento: texto livre não pode ser enviado pela API.
            return OutboundStatus.BLOCKED, "fora_da_janela_de_atendimento"
        return None
