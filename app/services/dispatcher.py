"""Envio das respostas da outbox, com revalidação imediatamente antes de cada tentativa.

- Falha transitória (ex.: limite de envio): nova tentativa com espera exponencial.
- Resultado incerto (timeout após enviar): UNKNOWN, nunca reenviado automaticamente.
- Envio interrompido (processo caiu durante SENDING): UNKNOWN após o prazo de lease.

Risco residual (documentado): uma resposta já em SENDING não pode ser cancelada. Se a equipe
assumir a conversa nesse intervalo, a mensagem em trânsito ainda chega ao cliente.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.clock import Clock
from app.core.logging import mask_id
from app.domain.enums import ConversationState, OutboundStatus
from app.domain.models import Conversation, OutboundIntent
from app.domain.store import StoreSettings
from app.integrations.whatsapp.gateway import GatewayError, MessagingGateway
from app.repositories.base import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_seconds: float = 5.0
    max_seconds: float = 300.0
    lease_seconds: int = 120

    def delay(self, attempts: int) -> timedelta:
        seconds = self.base_seconds * 2 ** max(attempts - 1, 0)
        return timedelta(seconds=min(seconds, self.max_seconds))


def _is_due(intent: OutboundIntent, now: datetime) -> bool:
    return intent.next_attempt_at is None or intent.next_attempt_at <= now


class Dispatcher:
    def __init__(
        self,
        db: Database,
        gateway: MessagingGateway,
        clock: Clock,
        policy: RetryPolicy | None = None,
    ) -> None:
        self._db = db
        self._gateway = gateway
        self._clock = clock
        self._policy = policy or RetryPolicy()

    async def dispatch_pending(self, conversation_id: str) -> list[OutboundIntent]:
        """Envia já as respostas vencidas de uma conversa (usado após processar uma mensagem)."""
        now = self._clock.now()
        async with self._db.transaction() as tx:
            pending = await tx.list_outbound(conversation_id, OutboundStatus.PENDING)
        due = [i for i in pending if _is_due(i, now)]
        return [await self.dispatch_intent(i.id) for i in due]

    async def dispatch_due(self, limit: int = 50) -> list[OutboundIntent]:
        async with self._db.transaction() as tx:
            due = await tx.list_due_outbound(self._clock.now(), limit)
        return [await self.dispatch_intent(i.id) for i in due]

    async def recover_stale_sending(self) -> int:
        now = self._clock.now()
        cutoff = now - timedelta(seconds=self._policy.lease_seconds)
        async with self._db.transaction() as tx:
            stale = await tx.list_stale_sending(cutoff)
            for intent in stale:
                intent.status = OutboundStatus.UNKNOWN
                intent.status_reason = "interrompido_durante_envio"
                intent.updated_at = now
                await tx.compare_and_set_outbound(intent, OutboundStatus.SENDING)
        for intent in stale:
            logger.warning("envio interrompido conversa=%s", mask_id(intent.conversation_id))
        return len(stale)

    async def dispatch_intent(self, intent_id: str) -> OutboundIntent:
        # 1) Reivindica a resposta numa transação curta, revalidando tudo.
        async with self._db.transaction() as tx:
            intent = await tx.get_outbound(intent_id)
            if intent is None:
                raise KeyError(intent_id)
            now = self._clock.now()
            if intent.status is not OutboundStatus.PENDING or not _is_due(intent, now):
                return intent
            conv = await tx.get_conversation(intent.conversation_id)
            store = await tx.get_store_settings()
            blocked = self._block_reason(intent, conv, store, now)
            if blocked:
                intent.status, intent.status_reason = blocked
                intent.updated_at = now
                await tx.compare_and_set_outbound(intent, OutboundStatus.PENDING)
                logger.info(
                    "resposta nao enviada conversa=%s motivo=%s",
                    mask_id(intent.conversation_id),
                    intent.status_reason,
                )
                return intent
            intent.status = OutboundStatus.SENDING
            intent.attempts += 1
            intent.sending_started_at = now
            intent.updated_at = now
            if not await tx.compare_and_set_outbound(intent, OutboundStatus.PENDING):
                # Outro processo reivindicou primeiro.
                current = await tx.get_outbound(intent_id)
                assert current is not None
                return current

        # 2) Envia fora da transação: a chamada de rede não segura o banco.
        try:
            result = await self._gateway.send_text(intent.conversation_id, intent.text)
        except GatewayError as exc:
            self._apply_failure(intent, exc)
        else:
            intent.status = OutboundStatus.SENT
            intent.status_reason = None
            intent.provider_message_id = result.provider_message_id
            intent.sent_at = self._clock.now()
        intent.updated_at = self._clock.now()

        # 3) Registra o resultado (só se ninguém marcou como interrompido nesse meio tempo).
        async with self._db.transaction() as tx:
            if not await tx.compare_and_set_outbound(intent, OutboundStatus.SENDING):
                logger.warning("resultado de envio descartado id=%s", intent.id)
                current = await tx.get_outbound(intent.id)
                assert current is not None
                return current
        return intent

    def _apply_failure(self, intent: OutboundIntent, exc: GatewayError) -> None:
        logger.warning(
            "falha no envio conversa=%s codigo=%s tentativa=%d",
            mask_id(intent.conversation_id),
            exc.code,
            intent.attempts,
        )
        if exc.outcome_unknown:
            intent.status = OutboundStatus.UNKNOWN
            intent.status_reason = exc.code
        elif exc.retryable and intent.attempts < self._policy.max_attempts:
            intent.status = OutboundStatus.PENDING
            intent.status_reason = exc.code
            intent.next_attempt_at = self._clock.now() + self._policy.delay(intent.attempts)
        else:
            intent.status = OutboundStatus.FAILED
            intent.status_reason = f"{exc.code}:tentativas_esgotadas" if exc.retryable else exc.code

    def _block_reason(
        self,
        intent: OutboundIntent,
        conv: Conversation | None,
        store: StoreSettings,
        now: datetime,
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
        if last is None or now - last > timedelta(hours=store.service_window_hours):
            # Fora da janela de atendimento: texto livre não pode ser enviado pela API.
            return OutboundStatus.BLOCKED, "fora_da_janela_de_atendimento"
        return None
