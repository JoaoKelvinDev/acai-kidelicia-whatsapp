"""Modelos de domínio. Persistência real (SQL) entra na Etapa 2."""

import secrets
import threading
import time
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.enums import (
    ConversationState,
    DraftState,
    IssueKind,
    MessageType,
    Modality,
    OutboundStatus,
    PaymentMethod,
    ReplyKind,
)

_id_lock = threading.Lock()
_last_id_micros = 0


def new_id() -> str:
    """ID de 32 hex ordenável pelo momento de criação (desempate estável em listagens)."""
    global _last_id_micros
    with _id_lock:
        _last_id_micros = max(time.time_ns() // 1000, _last_id_micros + 1)
        prefix = _last_id_micros
    return f"{prefix:014x}{secrets.token_hex(9)}"


class InboundMessage(BaseModel):
    provider_message_id: str
    conversation_id: str  # identificador do remetente fornecido pelo WhatsApp
    type: MessageType = MessageType.TEXT
    text: str | None = None
    timestamp: datetime
    received_at: datetime
    redacted_at: datetime | None = None  # texto removido pela política de retenção


class Conversation(BaseModel):
    id: str
    state: ConversationState = ConversationState.AUTO_ACTIVE
    last_customer_message_at: datetime | None = None
    last_inbound_message_id: str | None = None
    assignee: str | None = None
    active_draft_id: str | None = None
    handoff_reason: str | None = None
    # Incrementa a cada handoff/retomada/encerramento; respostas de época anterior são canceladas.
    reply_epoch: int = 0
    version: int = 0
    created_at: datetime
    updated_at: datetime


class RawField(BaseModel):
    label: str
    value: str


class OrderItem(BaseModel):
    position: int
    quantity_raw: str | None = None
    quantity: int | None = None
    size: str | None = None
    base: str | None = None
    creams: list[str] = Field(default_factory=list)
    ice_creams: list[str] = Field(default_factory=list)
    extras: list[str] = Field(default_factory=list)
    unknown_fields: list[RawField] = Field(default_factory=list)


class Issue(BaseModel):
    kind: IssueKind
    field: str
    code: str
    # True: o cliente não deve ser solicitado a corrigir; a equipe precisa conferir.
    requires_human: bool = False


class OrderDraft(BaseModel):
    id: str = Field(default_factory=new_id)
    conversation_id: str
    source_message_id: str
    origin: Literal["site"] = "site"
    state: DraftState = DraftState.INCOMPLETE
    fingerprint: str = ""

    name: str | None = None
    phone_raw: str | None = None
    modality_raw: str | None = None
    modality: Modality | None = None
    address: str | None = None
    reference: str | None = None
    delivery_fee_raw: str | None = None
    delivery_fee: Decimal | None = None
    # Texto do site é editável pelo cliente: a taxa nunca é verificada nesta etapa.
    delivery_fee_verified: bool = False
    payment_raw: str | None = None
    payment: PaymentMethod | None = None
    change_raw: str | None = None
    change_needed: bool | None = None
    change_for: Decimal | None = None

    items: list[OrderItem] = Field(default_factory=list)
    raw_fields: dict[str, str] = Field(default_factory=dict)
    unknown_fields: list[RawField] = Field(default_factory=list)
    unparsed_lines: list[str] = Field(default_factory=list)
    repeated_fields: list[str] = Field(default_factory=list)
    possible_duplicate_of: str | None = None

    issues: list[Issue] = Field(default_factory=list)
    correction_attempts: int = 0
    created_at: datetime
    updated_at: datetime
    redacted_at: datetime | None = None


class OutboundIntent(BaseModel):
    id: str = Field(default_factory=new_id)
    conversation_id: str
    idempotency_key: str
    kind: ReplyKind
    text: str
    status: OutboundStatus = OutboundStatus.PENDING
    status_reason: str | None = None
    reply_epoch: int
    source_message_id: str | None = None
    provider_message_id: str | None = None
    attempts: int = 0
    next_attempt_at: datetime | None = None  # None = imediato
    sending_started_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None = None
    redacted_at: datetime | None = None


AuditValue = str | int | bool | None | list[str]


class AuditEvent(BaseModel):
    id: str = Field(default_factory=new_id)
    conversation_id: str | None
    kind: str
    actor: str
    # Somente metadados (estados, motivos, nomes de campos). Nunca nome, telefone ou endereço.
    detail: dict[str, AuditValue] = Field(default_factory=dict)
    created_at: datetime
