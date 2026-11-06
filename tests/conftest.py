from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient

from app.core.clock import FixedClock
from app.core.config import Settings
from app.core.container import Container, build_container
from app.db.engine import alembic_config, create_engine, create_schema
from app.domain.enums import MessageType, OutboundStatus, ReplyKind, StoreStatus
from app.domain.models import Conversation, InboundMessage, OrderDraft, OutboundIntent, new_id
from app.domain.store import StoreSettings
from app.integrations.whatsapp.fake import FakeGateway
from app.main import create_app
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


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "app_env": "test",
        "require_migrated_db": False,
        "outbox_worker_enabled": False,
        "session_cookie_secure": False,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


class Harness:
    """Atalhos para simular mensagens e inspecionar o resultado."""

    def __init__(self, container: Container, clock: FixedClock) -> None:
        self.c = container
        self.clock = clock
        # Com gateway real (simulado por MockTransport), `gateway` não é o fake.
        self.gateway: FakeGateway = container.gateway  # type: ignore[assignment]

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

    async def q(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Executa um método do repositório numa transação própria."""
        async with self.c.db.transaction() as tx:
            return await getattr(tx, method)(*args, **kwargs)

    async def conversation(self, sender: str = SENDER) -> Conversation:
        conv = await self.q("get_conversation", sender)
        assert conv is not None
        return conv

    async def outbound(self, sender: str = SENDER) -> list[OutboundIntent]:
        return await self.q("list_outbound", sender)

    async def kinds(self, sender: str = SENDER) -> list[ReplyKind]:
        return [o.kind for o in await self.outbound(sender)]

    async def sent_kinds(self, sender: str = SENDER) -> list[ReplyKind]:
        return [o.kind for o in await self.outbound(sender) if o.status is OutboundStatus.SENT]

    async def drafts(self, sender: str = SENDER) -> list[OrderDraft]:
        return await self.q("list_drafts", sender)

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
async def harness_factory(clock: FixedClock, tmp_path: Path):
    containers: list[Container] = []

    async def factory(
        *, db_path: Path | None = None, gateway: Any = None, **store_overrides: Any
    ) -> Harness:
        path = db_path or tmp_path / f"db{len(containers)}.sqlite"
        url = sqlite_url(path)
        engine = create_engine(url)
        await create_schema(engine)
        container = build_container(
            make_settings(database_url=url),
            clock=clock,
            store=make_store(**store_overrides),
            engine=engine,
            gateway=gateway,
        )
        containers.append(container)
        return Harness(container, clock)

    yield factory
    for container in containers:
        await container.aclose()


@pytest.fixture
async def h(harness_factory) -> Harness:
    return await harness_factory()


class AppHandle:
    def __init__(self, client: TestClient, url: str) -> None:
        self.client = client
        self.url = url


@pytest.fixture
def app_factory(tmp_path: Path):
    """App completa sobre um banco criado pelas migrações (não por create_all)."""
    handles: list[AppHandle] = []

    def factory(app_env: str = "test", **overrides: Any) -> AppHandle:
        url = sqlite_url(tmp_path / f"app{len(handles)}.sqlite")
        command.upgrade(alembic_config(url), "head")
        settings = make_settings(
            app_env=app_env, database_url=url, require_migrated_db=True, **overrides
        )
        container = build_container(settings, store=make_store())
        client = TestClient(create_app(settings, container=container))
        client.__enter__()
        handle = AppHandle(client, url)
        handles.append(handle)
        return handle

    yield factory
    for handle in handles:
        handle.client.__exit__(None, None, None)
