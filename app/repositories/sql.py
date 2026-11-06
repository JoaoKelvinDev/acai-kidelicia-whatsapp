"""Implementação SQL do contrato de persistência (SQLAlchemy Core assíncrono).

Concorrência: no SQLite cada transação começa com BEGIN IMMEDIATE (escritas serializadas).
A versão da conversa e o status da resposta são conferidos no próprio UPDATE, o que mantém
a proteção também em PostgreSQL ou com mais de um processo.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import Row, and_, delete, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.db import schema as t
from app.domain.enums import ConversationState, OutboundStatus
from app.domain.models import (
    AuditEvent,
    Conversation,
    InboundMessage,
    OrderDraft,
    OutboundIntent,
)
from app.domain.operators import Operator, Session
from app.domain.store import StoreSettings
from app.repositories.base import ConcurrencyError, DuplicateError

_TERMINAL_OUTBOUND = (
    OutboundStatus.SENT,
    OutboundStatus.FAILED,
    OutboundStatus.UNKNOWN,
    OutboundStatus.CANCELLED,
    OutboundStatus.BLOCKED,
)


def _mapping(row: Row[Any]) -> dict[str, Any]:
    return dict(row._mapping)


class SqlDatabase:
    def __init__(self, engine: AsyncEngine, default_store: StoreSettings) -> None:
        self._engine = engine
        self._default_store = default_store

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["SqlTx"]:
        async with self._engine.begin() as conn:
            yield SqlTx(conn, self._default_store)


class SqlTx:
    def __init__(self, conn: AsyncConnection, default_store: StoreSettings) -> None:
        self._conn = conn
        self._default_store = default_store

    async def _insert_unique(self, statement: Any) -> bool:
        try:
            async with self._conn.begin_nested():
                await self._conn.execute(statement)
        except IntegrityError:
            return False
        return True

    # ── mensagens recebidas ─────────────────────────────────────────────────

    async def add_inbound(self, message: InboundMessage) -> bool:
        existing = await self._conn.scalar(
            select(t.inbound_messages.c.provider_message_id).where(
                t.inbound_messages.c.provider_message_id == message.provider_message_id
            )
        )
        if existing is not None:
            return False
        return await self._insert_unique(insert(t.inbound_messages).values(**message.model_dump()))

    async def list_inbound(self, conversation_id: str) -> list[InboundMessage]:
        c = t.inbound_messages.c
        rows = await self._conn.execute(
            select(t.inbound_messages)
            .where(c.conversation_id == conversation_id)
            .order_by(c.timestamp, c.received_at)
        )
        return [InboundMessage.model_validate(_mapping(r)) for r in rows]

    async def redact_inbound_before(
        self, conversation_id: str, cutoff: datetime, now: datetime
    ) -> int:
        c = t.inbound_messages.c
        result = await self._conn.execute(
            update(t.inbound_messages)
            .where(c.conversation_id == conversation_id, c.timestamp < cutoff)
            .where(c.redacted_at.is_(None))
            .values(text=None, redacted_at=now)
        )
        return result.rowcount

    # ── conversas ───────────────────────────────────────────────────────────

    async def get_conversation(self, conversation_id: str) -> Conversation | None:
        row = (
            await self._conn.execute(
                select(t.conversations).where(t.conversations.c.id == conversation_id)
            )
        ).first()
        return Conversation.model_validate(_mapping(row)) if row else None

    async def save_conversation(self, conversation: Conversation) -> Conversation:
        new_version = conversation.version + 1
        values = conversation.model_dump(exclude={"version"})
        if conversation.version == 0:
            inserted = await self._insert_unique(
                insert(t.conversations).values(**values, version=new_version)
            )
            if not inserted:
                raise ConcurrencyError(conversation.id)
        else:
            c = t.conversations.c
            result = await self._conn.execute(
                update(t.conversations)
                .where(c.id == conversation.id, c.version == conversation.version)
                .values(**values, version=new_version)
            )
            if result.rowcount != 1:
                raise ConcurrencyError(conversation.id)
        return conversation.model_copy(update={"version": new_version})

    async def list_conversations(
        self, states: set[ConversationState] | None = None, limit: int | None = None
    ) -> list[Conversation]:
        c = t.conversations.c
        query = select(t.conversations).order_by(c.updated_at.desc())
        if states is not None:
            query = query.where(c.state.in_([s.value for s in states]))
        if limit is not None:
            query = query.limit(limit)
        rows = await self._conn.execute(query)
        return [Conversation.model_validate(_mapping(r)) for r in rows]

    async def delete_conversation(self, conversation_id: str) -> None:
        for table in (t.inbound_messages, t.order_drafts, t.outbound_messages):
            await self._conn.execute(
                delete(table).where(table.c.conversation_id == conversation_id)
            )
        await self._conn.execute(
            update(t.audit_events)
            .where(t.audit_events.c.conversation_id == conversation_id)
            .values(conversation_id=None)
        )
        await self._conn.execute(
            delete(t.conversations).where(t.conversations.c.id == conversation_id)
        )

    # ── rascunhos ───────────────────────────────────────────────────────────

    async def save_draft(self, draft: OrderDraft) -> None:
        values = {
            "conversation_id": draft.conversation_id,
            "source_message_id": draft.source_message_id,
            "state": draft.state.value,
            "fingerprint": draft.fingerprint,
            "created_at": draft.created_at,
            "updated_at": draft.updated_at,
            "redacted_at": draft.redacted_at,
            "data": draft.model_dump(mode="json"),
        }
        result = await self._conn.execute(
            update(t.order_drafts).where(t.order_drafts.c.id == draft.id).values(**values)
        )
        if result.rowcount == 0:
            await self._conn.execute(insert(t.order_drafts).values(id=draft.id, **values))

    async def get_draft(self, draft_id: str) -> OrderDraft | None:
        data = await self._conn.scalar(
            select(t.order_drafts.c.data).where(t.order_drafts.c.id == draft_id)
        )
        return OrderDraft.model_validate(data) if data is not None else None

    async def list_drafts(self, conversation_id: str) -> list[OrderDraft]:
        c = t.order_drafts.c
        rows = await self._conn.scalars(
            select(c.data).where(c.conversation_id == conversation_id).order_by(c.created_at, c.id)
        )
        return [OrderDraft.model_validate(data) for data in rows]

    # ── respostas (outbox) ──────────────────────────────────────────────────

    async def add_outbound(self, intent: OutboundIntent) -> bool:
        c = t.outbound_messages.c
        existing = await self._conn.scalar(
            select(c.id).where(c.idempotency_key == intent.idempotency_key)
        )
        if existing is not None:
            return False
        return await self._insert_unique(insert(t.outbound_messages).values(**intent.model_dump()))

    async def get_outbound(self, intent_id: str) -> OutboundIntent | None:
        row = (
            await self._conn.execute(
                select(t.outbound_messages).where(t.outbound_messages.c.id == intent_id)
            )
        ).first()
        return OutboundIntent.model_validate(_mapping(row)) if row else None

    async def save_outbound(self, intent: OutboundIntent) -> None:
        result = await self._conn.execute(
            update(t.outbound_messages)
            .where(t.outbound_messages.c.id == intent.id)
            .values(**intent.model_dump(exclude={"id"}))
        )
        if result.rowcount != 1:
            raise KeyError(intent.id)

    async def compare_and_set_outbound(
        self, intent: OutboundIntent, expected: OutboundStatus
    ) -> bool:
        c = t.outbound_messages.c
        result = await self._conn.execute(
            update(t.outbound_messages)
            .where(c.id == intent.id, c.status == expected.value)
            .values(**intent.model_dump(exclude={"id"}))
        )
        return result.rowcount == 1

    async def list_outbound(
        self, conversation_id: str, status: OutboundStatus | None = None
    ) -> list[OutboundIntent]:
        c = t.outbound_messages.c
        query = select(t.outbound_messages).where(c.conversation_id == conversation_id)
        if status is not None:
            query = query.where(c.status == status.value)
        rows = await self._conn.execute(query.order_by(c.created_at, c.id))
        return [OutboundIntent.model_validate(_mapping(r)) for r in rows]

    async def list_due_outbound(self, now: datetime, limit: int) -> list[OutboundIntent]:
        c = t.outbound_messages.c
        rows = await self._conn.execute(
            select(t.outbound_messages)
            .where(
                c.status == OutboundStatus.PENDING.value,
                or_(c.next_attempt_at.is_(None), c.next_attempt_at <= now),
            )
            .order_by(c.created_at, c.id)
            .limit(limit)
        )
        return [OutboundIntent.model_validate(_mapping(r)) for r in rows]

    async def list_stale_sending(self, started_before: datetime) -> list[OutboundIntent]:
        c = t.outbound_messages.c
        rows = await self._conn.execute(
            select(t.outbound_messages).where(
                c.status == OutboundStatus.SENDING.value, c.sending_started_at < started_before
            )
        )
        return [OutboundIntent.model_validate(_mapping(r)) for r in rows]

    async def cancel_pending_outbound(
        self, conversation_id: str, *, reason: str, now: datetime
    ) -> int:
        c = t.outbound_messages.c
        result = await self._conn.execute(
            update(t.outbound_messages)
            .where(c.conversation_id == conversation_id, c.status == OutboundStatus.PENDING.value)
            .values(status=OutboundStatus.CANCELLED.value, status_reason=reason, updated_at=now)
        )
        return result.rowcount

    async def redact_outbound_before(
        self, conversation_id: str, cutoff: datetime, now: datetime
    ) -> int:
        c = t.outbound_messages.c
        result = await self._conn.execute(
            update(t.outbound_messages)
            .where(
                and_(
                    c.conversation_id == conversation_id,
                    c.created_at < cutoff,
                    c.redacted_at.is_(None),
                    c.status.in_([s.value for s in _TERMINAL_OUTBOUND]),
                )
            )
            .values(text="", redacted_at=now)
        )
        return result.rowcount

    # ── auditoria ───────────────────────────────────────────────────────────

    async def add_audit(self, event: AuditEvent) -> None:
        await self._conn.execute(insert(t.audit_events).values(**event.model_dump()))

    async def list_audit(self, conversation_id: str | None = None) -> list[AuditEvent]:
        c = t.audit_events.c
        query = select(t.audit_events).order_by(c.created_at, c.id)
        if conversation_id is not None:
            query = query.where(c.conversation_id == conversation_id)
        rows = await self._conn.execute(query)
        return [AuditEvent.model_validate(_mapping(r)) for r in rows]

    async def purge_audit_before(self, cutoff: datetime) -> int:
        result = await self._conn.execute(
            delete(t.audit_events).where(t.audit_events.c.created_at < cutoff)
        )
        return result.rowcount

    # ── configuração da loja ────────────────────────────────────────────────

    async def get_store_settings(self) -> StoreSettings:
        data = await self._conn.scalar(
            select(t.store_settings.c.data).where(t.store_settings.c.id == 1)
        )
        if data is None:
            return self._default_store.model_copy(deep=True)
        return StoreSettings.model_validate(data)

    async def save_store_settings(self, settings: StoreSettings, now: datetime) -> None:
        values = {"data": settings.model_dump(mode="json"), "updated_at": now}
        result = await self._conn.execute(
            update(t.store_settings).where(t.store_settings.c.id == 1).values(**values)
        )
        if result.rowcount == 0:
            await self._conn.execute(insert(t.store_settings).values(id=1, **values))

    # ── operadores e sessões ────────────────────────────────────────────────

    async def add_operator(self, operator: Operator) -> None:
        if not await self._insert_unique(insert(t.operators).values(**operator.model_dump())):
            raise DuplicateError(operator.username)

    async def get_operator(self, operator_id: str) -> Operator | None:
        row = (
            await self._conn.execute(select(t.operators).where(t.operators.c.id == operator_id))
        ).first()
        return Operator.model_validate(_mapping(row)) if row else None

    async def get_operator_by_username(self, username: str) -> Operator | None:
        row = (
            await self._conn.execute(select(t.operators).where(t.operators.c.username == username))
        ).first()
        return Operator.model_validate(_mapping(row)) if row else None

    async def save_operator(self, operator: Operator) -> None:
        await self._conn.execute(
            update(t.operators)
            .where(t.operators.c.id == operator.id)
            .values(**operator.model_dump(exclude={"id"}))
        )

    async def add_session(self, session: Session) -> None:
        await self._conn.execute(insert(t.sessions).values(**session.model_dump()))

    async def get_session(self, token_hash: str) -> Session | None:
        row = (
            await self._conn.execute(
                select(t.sessions).where(t.sessions.c.token_hash == token_hash)
            )
        ).first()
        return Session.model_validate(_mapping(row)) if row else None

    async def delete_session(self, token_hash: str) -> None:
        await self._conn.execute(delete(t.sessions).where(t.sessions.c.token_hash == token_hash))

    async def delete_operator_sessions(self, operator_id: str) -> int:
        result = await self._conn.execute(
            delete(t.sessions).where(t.sessions.c.operator_id == operator_id)
        )
        return result.rowcount

    async def purge_expired_sessions(self, now: datetime) -> int:
        result = await self._conn.execute(delete(t.sessions).where(t.sessions.c.expires_at <= now))
        return result.rowcount
