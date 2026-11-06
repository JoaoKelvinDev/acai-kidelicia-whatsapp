"""Montagem das dependências. Um único ponto para trocar fake por Cloud API (Etapa 3)."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.db.engine import create_engine
from app.domain.store import StoreSettings
from app.integrations.whatsapp.fake import FakeGateway
from app.integrations.whatsapp.gateway import MessagingGateway
from app.repositories.base import Database
from app.repositories.sql import SqlDatabase
from app.services.auth import AuthService
from app.services.conversation import ConversationService
from app.services.dispatcher import Dispatcher, RetryPolicy
from app.services.handoff import HandoffService
from app.services.retention import RetentionService
from app.workers.outbox import OutboxWorker


@dataclass
class Container:
    settings: Settings
    clock: Clock
    engine: AsyncEngine
    db: Database
    gateway: MessagingGateway
    conversations: ConversationService
    dispatcher: Dispatcher
    handoff: HandoffService
    auth: AuthService
    retention: RetentionService
    worker: OutboxWorker


def default_store_settings(settings: Settings) -> StoreSettings:
    return StoreSettings(
        store_name=settings.store_name,
        website_url=settings.store_website_url,
        timezone=settings.store_timezone,
    )


def build_container(
    settings: Settings,
    *,
    clock: Clock | None = None,
    gateway: MessagingGateway | None = None,
    store: StoreSettings | None = None,
    engine: AsyncEngine | None = None,
) -> Container:
    """`store` é a configuração usada enquanto nada foi salvo no banco."""
    clock = clock or SystemClock()
    gateway = gateway or FakeGateway()
    engine = engine or create_engine(settings.database_url)
    db = SqlDatabase(engine, store or default_store_settings(settings))
    dispatcher = Dispatcher(
        db,
        gateway,
        clock,
        RetryPolicy(
            max_attempts=settings.outbox_max_attempts,
            base_seconds=settings.outbox_backoff_base_seconds,
            max_seconds=settings.outbox_backoff_max_seconds,
            lease_seconds=settings.outbox_sending_lease_seconds,
        ),
    )
    return Container(
        settings=settings,
        clock=clock,
        engine=engine,
        db=db,
        gateway=gateway,
        conversations=ConversationService(db, clock),
        dispatcher=dispatcher,
        handoff=HandoffService(db, clock),
        auth=AuthService(
            db,
            clock,
            session_ttl=timedelta(hours=settings.session_ttl_hours),
            max_failures=settings.login_max_failures,
            lockout=timedelta(minutes=settings.login_lockout_minutes),
        ),
        retention=RetentionService(
            db,
            clock,
            retention_days=settings.retention_days,
            audit_retention_days=settings.audit_retention_days,
        ),
        worker=OutboxWorker(dispatcher, settings.outbox_poll_seconds),
    )
