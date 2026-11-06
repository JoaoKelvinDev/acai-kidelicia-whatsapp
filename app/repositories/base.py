"""Contrato de persistência. Etapa 1: memória. Etapa 2: SQLite/PostgreSQL com o mesmo contrato."""

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from app.domain.enums import OutboundStatus
from app.domain.models import (
    AuditEvent,
    Conversation,
    InboundMessage,
    OrderDraft,
    OutboundIntent,
)
from app.domain.store import StoreSettings


class ConcurrencyError(Exception):
    """Versão da conversa mudou entre leitura e gravação."""


class Repository(Protocol):
    def lock(self, conversation_id: str) -> AbstractAsyncContextManager[object]:
        """Serializa o processamento de uma conversa."""
        ...

    async def add_inbound(self, message: InboundMessage) -> bool:
        """Grava a mensagem; False se o ID do provedor já existia (deduplicação)."""
        ...

    async def list_inbound(self, conversation_id: str) -> list[InboundMessage]: ...

    async def get_conversation(self, conversation_id: str) -> Conversation | None: ...

    async def save_conversation(self, conversation: Conversation) -> Conversation:
        """Grava com controle otimista de versão; retorna a cópia com versão nova."""
        ...

    async def list_conversations(self) -> list[Conversation]: ...

    async def save_draft(self, draft: OrderDraft) -> None: ...

    async def get_draft(self, draft_id: str) -> OrderDraft | None: ...

    async def list_drafts(self, conversation_id: str) -> list[OrderDraft]: ...

    async def add_outbound(self, intent: OutboundIntent) -> bool:
        """False se a chave de idempotência já existia."""
        ...

    async def get_outbound(self, intent_id: str) -> OutboundIntent | None: ...

    async def save_outbound(self, intent: OutboundIntent) -> None: ...

    async def list_outbound(
        self, conversation_id: str, status: OutboundStatus | None = None
    ) -> list[OutboundIntent]: ...

    async def cancel_pending_outbound(
        self, conversation_id: str, *, reason: str, now: datetime
    ) -> int: ...

    async def add_audit(self, event: AuditEvent) -> None: ...

    async def list_audit(self, conversation_id: str | None = None) -> list[AuditEvent]: ...

    async def get_store_settings(self) -> StoreSettings: ...

    async def save_store_settings(self, settings: StoreSettings) -> None: ...
