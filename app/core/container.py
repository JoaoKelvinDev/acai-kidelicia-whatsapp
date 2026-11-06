"""Montagem das dependências. Um único ponto para trocar memória/fake por SQL/Cloud API."""

from dataclasses import dataclass

from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.domain.store import StoreSettings
from app.integrations.whatsapp.fake import FakeGateway
from app.integrations.whatsapp.gateway import MessagingGateway
from app.repositories.base import Repository
from app.repositories.memory import MemoryRepository
from app.services.conversation import ConversationService
from app.services.dispatcher import Dispatcher
from app.services.handoff import HandoffService


@dataclass
class Container:
    settings: Settings
    clock: Clock
    repo: Repository
    gateway: MessagingGateway
    conversations: ConversationService
    dispatcher: Dispatcher
    handoff: HandoffService


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
) -> Container:
    clock = clock or SystemClock()
    gateway = gateway or FakeGateway()
    repo = MemoryRepository(store or default_store_settings(settings))
    return Container(
        settings=settings,
        clock=clock,
        repo=repo,
        gateway=gateway,
        conversations=ConversationService(repo, clock),
        dispatcher=Dispatcher(repo, gateway, clock),
        handoff=HandoffService(repo, clock),
    )
