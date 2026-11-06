from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.container import Container, build_container
from app.domain.enums import MessageType, OutboundStatus, ReplyKind, StoreStatus
from app.domain.models import Conversation, InboundMessage, OrderDraft, OutboundIntent, new_id
from app.domain.store import StoreSettings
from app.integrations.whatsapp.fake import FakeGateway
from app.services.conversation import HandleResult

FIXTURES = Path(__file__).parent / "fixtures" / "orders"
# Números sintéticos, sem relação com clientes reais.
SENDER = "5511974123058"
OTHER_SENDER = "5511963217045"
WEBSITE = "https://acaikideliciapl.com.br"
# Sexta-feira, 06/11/2026, 15:00 em São Paulo.
START = datetime(2026, 11, 6, 18, 0, tzinfo=UTC)


def load_order(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


def make_store(**overrides: Any) -> StoreSettings:
    base: dict[str, Any] = {
        "store_name": "Açaí Ki-Delícia PL",
        "website_url": WEBSITE,
        "status_override": StoreStatus.OPEN,
    }
    base.update(overrides)
    return StoreSettings(**base)


def make_settings() -> Settings:
    return Settings(_env_file=None, app_env="test")


class Harness:
    """Atalhos para simular mensagens e inspecionar o resultado."""

    def __init__(self, container: Container, clock: FixedClock) -> None:
        self.c = container
        self.clock = clock
        assert isinstance(container.gateway, FakeGateway)
        self.gateway: FakeGateway = container.gateway

    def inbound(
        self,
        text: str | None = None,
        *,
        sender: str = SENDER,
        msg_id: str | None = None,
        type: MessageType = MessageType.TEXT,
    ) -> InboundMessage:
        now = self.clock.now()
        return InboundMessage(
            provider_message_id=msg_id or f"wamid.{new_id()}",
            conversation_id=sender,
            type=type,
            text=text,
            timestamp=now,
            received_at=now,
        )

    async def receive(
        self,
        text: str | None = None,
        *,
        sender: str = SENDER,
        msg_id: str | None = None,
        type: MessageType = MessageType.TEXT,
        dispatch: bool = True,
    ) -> HandleResult:
        msg = self.inbound(text, sender=sender, msg_id=msg_id, type=type)
        result = await self.c.conversations.handle_inbound(msg)
        if dispatch:
            await self.c.dispatcher.dispatch_pending(sender)
        return result

    async def conversation(self, sender: str = SENDER) -> Conversation:
        conv = await self.c.repo.get_conversation(sender)
        assert conv is not None
        return conv

    async def outbound(self, sender: str = SENDER) -> list[OutboundIntent]:
        return await self.c.repo.list_outbound(sender)

    async def kinds(self, sender: str = SENDER) -> list[ReplyKind]:
        return [o.kind for o in await self.outbound(sender)]

    async def sent_kinds(self, sender: str = SENDER) -> list[ReplyKind]:
        return [o.kind for o in await self.outbound(sender) if o.status is OutboundStatus.SENT]

    async def drafts(self, sender: str = SENDER) -> list[OrderDraft]:
        return await self.c.repo.list_drafts(sender)

    async def only_draft(self, sender: str = SENDER) -> OrderDraft:
        drafts = await self.drafts(sender)
        assert len(drafts) == 1
        return drafts[0]

    def sent_texts(self) -> list[str]:
        return [s.text for s in self.gateway.sent]


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START)


@pytest.fixture
def harness_factory(clock: FixedClock):
    def factory(**store_overrides: Any) -> Harness:
        container = build_container(
            make_settings(), clock=clock, store=make_store(**store_overrides)
        )
        return Harness(container, clock)

    return factory


@pytest.fixture
def h(harness_factory) -> Harness:
    return harness_factory()
