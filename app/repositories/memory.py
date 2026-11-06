"""Repositório em memória — apenas desenvolvimento local e testes.

Não sobrevive a reinício; não serve para operação real (ver Etapa 2). Devolve cópias para
imitar a semântica de um banco e evitar mutações acidentais compartilhadas.
"""

import asyncio
from datetime import datetime

from app.domain.enums import OutboundStatus
from app.domain.models import (
    AuditEvent,
    Conversation,
    InboundMessage,
    OrderDraft,
    OutboundIntent,
)
from app.domain.store import StoreSettings
from app.repositories.base import ConcurrencyError


class MemoryRepository:
    def __init__(self, store: StoreSettings) -> None:
        self._store = store.model_copy(deep=True)
        self._conversations: dict[str, Conversation] = {}
        self._messages: dict[str, InboundMessage] = {}
        self._drafts: dict[str, OrderDraft] = {}
        self._outbound: dict[str, OutboundIntent] = {}
        self._outbound_keys: set[str] = set()
        self._audit: list[AuditEvent] = []
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, conversation_id: str) -> asyncio.Lock:
        return self._locks.setdefault(conversation_id, asyncio.Lock())

    async def add_inbound(self, message: InboundMessage) -> bool:
        if message.provider_message_id in self._messages:
            return False
        self._messages[message.provider_message_id] = message.model_copy(deep=True)
        return True

    async def list_inbound(self, conversation_id: str) -> list[InboundMessage]:
        return [
            m.model_copy(deep=True)
            for m in self._messages.values()
            if m.conversation_id == conversation_id
        ]

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        conv = self._conversations.get(conversation_id)
        return conv.model_copy(deep=True) if conv else None

    async def save_conversation(self, conversation: Conversation) -> Conversation:
        stored = self._conversations.get(conversation.id)
        current_version = stored.version if stored else 0
        if conversation.version != current_version:
            raise ConcurrencyError(conversation.id)
        saved = conversation.model_copy(deep=True, update={"version": current_version + 1})
        self._conversations[conversation.id] = saved
        return saved.model_copy(deep=True)

    async def list_conversations(self) -> list[Conversation]:
        return [c.model_copy(deep=True) for c in self._conversations.values()]

    async def save_draft(self, draft: OrderDraft) -> None:
        self._drafts[draft.id] = draft.model_copy(deep=True)

    async def get_draft(self, draft_id: str) -> OrderDraft | None:
        draft = self._drafts.get(draft_id)
        return draft.model_copy(deep=True) if draft else None

    async def list_drafts(self, conversation_id: str) -> list[OrderDraft]:
        return [
            d.model_copy(deep=True)
            for d in self._drafts.values()
            if d.conversation_id == conversation_id
        ]

    async def add_outbound(self, intent: OutboundIntent) -> bool:
        if intent.idempotency_key in self._outbound_keys:
            return False
        self._outbound_keys.add(intent.idempotency_key)
        self._outbound[intent.id] = intent.model_copy(deep=True)
        return True

    async def get_outbound(self, intent_id: str) -> OutboundIntent | None:
        intent = self._outbound.get(intent_id)
        return intent.model_copy(deep=True) if intent else None

    async def save_outbound(self, intent: OutboundIntent) -> None:
        if intent.id not in self._outbound:
            raise KeyError(intent.id)
        self._outbound[intent.id] = intent.model_copy(deep=True)

    async def list_outbound(
        self, conversation_id: str, status: OutboundStatus | None = None
    ) -> list[OutboundIntent]:
        return [
            i.model_copy(deep=True)
            for i in self._outbound.values()
            if i.conversation_id == conversation_id and (status is None or i.status == status)
        ]

    async def cancel_pending_outbound(
        self, conversation_id: str, *, reason: str, now: datetime
    ) -> int:
        count = 0
        for intent in self._outbound.values():
            if intent.conversation_id == conversation_id and (
                intent.status == OutboundStatus.PENDING
            ):
                intent.status = OutboundStatus.CANCELLED
                intent.status_reason = reason
                intent.updated_at = now
                count += 1
        return count

    async def add_audit(self, event: AuditEvent) -> None:
        self._audit.append(event.model_copy(deep=True))

    async def list_audit(self, conversation_id: str | None = None) -> list[AuditEvent]:
        return [
            e.model_copy(deep=True)
            for e in self._audit
            if conversation_id is None or e.conversation_id == conversation_id
        ]

    async def get_store_settings(self) -> StoreSettings:
        return self._store.model_copy(deep=True)

    async def save_store_settings(self, settings: StoreSettings) -> None:
        self._store = settings.model_copy(deep=True)
