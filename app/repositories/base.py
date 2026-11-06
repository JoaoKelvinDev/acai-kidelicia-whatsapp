"""Contrato de persistência.

Toda leitura e escrita acontece dentro de `Database.transaction()`: ou tudo é gravado, ou
nada é. Implementação atual: SQL (SQLite local; PostgreSQL proposto para produção).
"""

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from app.domain.enums import ConversationState, OutboundStatus
from app.domain.models import (
    AuditEvent,
    Conversation,
    DeliveryStatusEvent,
    InboundMessage,
    OrderDraft,
    OutboundIntent,
)
from app.domain.operators import Operator, Session
from app.domain.store import StoreSettings


class ConcurrencyError(Exception):
    """Versão da conversa mudou entre leitura e gravação."""


class DuplicateError(Exception):
    """Registro com chave única já existente."""


class Tx(Protocol):
    # Mensagens recebidas
    async def add_inbound(self, message: InboundMessage) -> bool:
        """Grava a mensagem; False se o ID do provedor já existia (deduplicação)."""
        ...

    async def list_inbound(self, conversation_id: str) -> list[InboundMessage]: ...

    # Conversas
    async def get_conversation(self, conversation_id: str) -> Conversation | None: ...

    async def save_conversation(self, conversation: Conversation) -> Conversation:
        """Controle otimista de versão; devolve a cópia com versão nova."""
        ...

    async def list_conversations(
        self, states: set[ConversationState] | None = None, limit: int | None = None
    ) -> list[Conversation]: ...

    async def delete_conversation(self, conversation_id: str) -> None:
        """Remove conversa, mensagens, rascunhos e respostas; anonimiza a auditoria."""
        ...

    # Rascunhos
    async def save_draft(self, draft: OrderDraft) -> None: ...

    async def get_draft(self, draft_id: str) -> OrderDraft | None: ...

    async def list_drafts(self, conversation_id: str) -> list[OrderDraft]: ...

    # Respostas (outbox)
    async def add_outbound(self, intent: OutboundIntent) -> bool:
        """False se a chave de idempotência já existia."""
        ...

    async def get_outbound(self, intent_id: str) -> OutboundIntent | None: ...

    async def save_outbound(self, intent: OutboundIntent) -> None: ...

    async def compare_and_set_outbound(
        self, intent: OutboundIntent, expected: OutboundStatus
    ) -> bool:
        """Grava só se o status atual no banco for `expected` (reivindicação atômica)."""
        ...

    async def list_outbound(
        self, conversation_id: str, status: OutboundStatus | None = None
    ) -> list[OutboundIntent]: ...

    async def get_outbound_by_provider_id(
        self, provider_message_id: str
    ) -> OutboundIntent | None: ...

    async def add_status_event(self, event: DeliveryStatusEvent) -> bool:
        """False se o mesmo status já foi recebido (webhook repetido)."""
        ...

    async def list_status_events(self, provider_message_id: str) -> list[DeliveryStatusEvent]: ...

    async def purge_status_events_before(self, cutoff: datetime) -> int: ...

    async def list_due_outbound(self, now: datetime, limit: int) -> list[OutboundIntent]: ...

    async def list_stale_sending(self, started_before: datetime) -> list[OutboundIntent]: ...

    async def cancel_pending_outbound(
        self, conversation_id: str, *, reason: str, now: datetime
    ) -> int: ...

    # Retenção
    async def redact_inbound_before(
        self, conversation_id: str, cutoff: datetime, now: datetime
    ) -> int: ...

    async def redact_outbound_before(
        self, conversation_id: str, cutoff: datetime, now: datetime
    ) -> int: ...

    async def purge_audit_before(self, cutoff: datetime) -> int: ...

    # Auditoria
    async def add_audit(self, event: AuditEvent) -> None: ...

    async def list_audit(self, conversation_id: str | None = None) -> list[AuditEvent]: ...

    # Configuração da loja
    async def get_store_settings(self) -> StoreSettings: ...

    async def save_store_settings(self, settings: StoreSettings, now: datetime) -> None: ...

    # Operadores e sessões
    async def add_operator(self, operator: Operator) -> None: ...

    async def get_operator(self, operator_id: str) -> Operator | None: ...

    async def get_operator_by_username(self, username: str) -> Operator | None: ...

    async def save_operator(self, operator: Operator) -> None: ...

    async def add_session(self, session: Session) -> None: ...

    async def get_session(self, token_hash: str) -> Session | None: ...

    async def delete_session(self, token_hash: str) -> None: ...

    async def delete_operator_sessions(self, operator_id: str) -> int: ...

    async def purge_expired_sessions(self, now: datetime) -> int: ...


class Database(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[Tx]: ...
