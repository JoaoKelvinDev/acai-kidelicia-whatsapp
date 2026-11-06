"""Esquema do banco (SQLAlchemy Core). Alterações sempre via migração Alembic.

Colunas consultáveis ficam explícitas; o rascunho de pedido e a configuração da loja são
gravados também como JSON completo do modelo, para evoluir sem migração a cada campo.
Mensagens e rascunhos não têm chave estrangeira para a conversa porque são gravados antes
dela na mesma transação.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

from app.db.types import UTCDateTime

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

conversations = Table(
    "conversations",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("state", String(20), nullable=False, index=True),
    Column("last_customer_message_at", UTCDateTime(), nullable=True),
    Column("last_inbound_message_id", String(255), nullable=True),
    Column("assignee", String(80), nullable=True),
    Column("active_draft_id", String(32), nullable=True),
    Column("handoff_reason", String(80), nullable=True),
    Column("provider_user_id", String(128), nullable=True),
    Column("reply_epoch", Integer, nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
)

inbound_messages = Table(
    "inbound_messages",
    metadata,
    Column("provider_message_id", String(255), primary_key=True),
    Column("conversation_id", String(32), nullable=False, index=True),
    Column("type", String(20), nullable=False),
    Column("text", Text, nullable=True),
    Column("timestamp", UTCDateTime(), nullable=False),
    Column("received_at", UTCDateTime(), nullable=False),
    Column("redacted_at", UTCDateTime(), nullable=True),
    Column("provider_user_id", String(128), nullable=True),
)

order_drafts = Table(
    "order_drafts",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("conversation_id", String(32), nullable=False, index=True),
    Column("source_message_id", String(255), nullable=False),
    Column("state", String(20), nullable=False),
    Column("fingerprint", String(64), nullable=False, index=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    Column("redacted_at", UTCDateTime(), nullable=True),
    Column("data", JSON, nullable=False),
)

outbound_messages = Table(
    "outbound_messages",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("conversation_id", String(32), nullable=False, index=True),
    Column("idempotency_key", String(320), nullable=False, unique=True),
    Column("kind", String(30), nullable=False),
    Column("text", Text, nullable=False),
    Column("status", String(20), nullable=False),
    Column("status_reason", String(120), nullable=True),
    Column("reply_epoch", Integer, nullable=False),
    Column("source_message_id", String(255), nullable=True),
    Column("provider_message_id", String(255), nullable=True),
    Column("attempts", Integer, nullable=False),
    Column("next_attempt_at", UTCDateTime(), nullable=True),
    Column("sending_started_at", UTCDateTime(), nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    Column("sent_at", UTCDateTime(), nullable=True),
    Column("redacted_at", UTCDateTime(), nullable=True),
    Column("delivery_status", String(20), nullable=True),
    Column("delivered_at", UTCDateTime(), nullable=True),
    Column("read_at", UTCDateTime(), nullable=True),
    Column("delivery_error_code", Integer, nullable=True),
)
Index("ix_outbound_messages_provider_message_id", outbound_messages.c.provider_message_id)
Index(
    "ix_outbound_messages_status_next",
    outbound_messages.c.status,
    outbound_messages.c.next_attempt_at,
)

delivery_status_events = Table(
    "delivery_status_events",
    metadata,
    Column("idempotency_key", String(400), primary_key=True),
    Column("provider_message_id", String(255), nullable=False, index=True),
    Column("status", String(20), nullable=False),
    Column("occurred_at", UTCDateTime(), nullable=False),
    Column("error_code", Integer, nullable=True),
    Column("error_title", String(200), nullable=True),
    Column("received_at", UTCDateTime(), nullable=False, index=True),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("conversation_id", String(32), nullable=True, index=True),
    Column("kind", String(60), nullable=False),
    Column("actor", String(80), nullable=False),
    Column("detail", JSON, nullable=False),
    Column("created_at", UTCDateTime(), nullable=False, index=True),
)

store_settings = Table(
    "store_settings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("data", JSON, nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
)

operators = Table(
    "operators",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("username", String(40), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("role", String(20), nullable=False),
    Column("active", Boolean, nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("last_login_at", UTCDateTime(), nullable=True),
)

sessions = Table(
    "sessions",
    metadata,
    Column("token_hash", String(64), primary_key=True),
    Column(
        "operator_id",
        String(32),
        ForeignKey("operators.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("csrf_token", String(64), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("expires_at", UTCDateTime(), nullable=False, index=True),
)
