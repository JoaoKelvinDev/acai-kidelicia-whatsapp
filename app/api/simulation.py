"""Rotas de simulação local. Só existem com APP_ENV=local/test; nunca em produção.

Não têm autenticação porque não são registradas fora do ambiente de desenvolvimento; a
dependência abaixo é uma segunda barreira caso alguém as inclua por engano.
"""

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.container import Container
from app.domain.enums import MessageType
from app.domain.models import InboundMessage, new_id
from app.domain.store import StoreSettings
from app.integrations.whatsapp.fake import FakeGateway
from app.services.handoff import ConversationNotFoundError


def require_dev_tools(request: Request) -> Container:
    container: Container = request.app.state.container
    if not container.settings.dev_tools_enabled:
        raise HTTPException(status_code=404)
    return container


ContainerDep = Annotated[Container, Depends(require_dev_tools)]
router = APIRouter(prefix="/dev", tags=["simulação (somente local)"])


class SimulatedInbound(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sender: str = Field(alias="from", pattern=r"^\d{8,15}$")
    text: str | None = Field(default=None, max_length=4096)
    type: MessageType = MessageType.TEXT
    message_id: str | None = Field(default=None, max_length=128)
    timestamp: datetime | None = None


class ActorRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=80)


class GlobalPauseRequest(ActorRequest):
    paused: bool


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")


async def _conversation_view(container: Container, conversation_id: str) -> dict[str, Any]:
    async with container.db.transaction() as tx:
        conv = await tx.get_conversation(conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="conversa não encontrada")
        return {
            "conversation": _dump(conv),
            "messages": [_dump(m) for m in await tx.list_inbound(conversation_id)],
            "drafts": [_dump(d) for d in await tx.list_drafts(conversation_id)],
            "outbound": [_dump(o) for o in await tx.list_outbound(conversation_id)],
            "audit": [_dump(e) for e in await tx.list_audit(conversation_id)],
        }


@router.post("/simulate/inbound")
async def simulate_inbound(body: SimulatedInbound, container: ContainerDep) -> dict[str, Any]:
    now = container.clock.now()
    timestamp = body.timestamp or now
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    message = InboundMessage(
        provider_message_id=body.message_id or f"sim.{new_id()}",
        conversation_id=body.sender,
        type=body.type,
        text=body.text,
        timestamp=timestamp,
        received_at=now,
    )
    result = await container.conversations.handle_inbound(message)
    dispatched = await container.dispatcher.dispatch_pending(body.sender)
    return {
        "message_id": message.provider_message_id,
        "result": _dump(result),
        "dispatched": [_dump(i) for i in dispatched],
    }


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, container: ContainerDep) -> dict[str, Any]:
    return await _conversation_view(container, conversation_id)


@router.post("/conversations/{conversation_id}/{action}")
async def conversation_action(
    conversation_id: str,
    action: Literal["take_over", "pause", "resume", "close"],
    body: ActorRequest,
    container: ContainerDep,
) -> dict[str, Any]:
    handler = getattr(container.handoff, action)
    try:
        conv = await handler(conversation_id, body.actor)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="conversa não encontrada") from exc
    return _dump(conv)


@router.post("/automation-pause")
async def automation_pause(body: GlobalPauseRequest, container: ContainerDep) -> dict[str, Any]:
    await container.handoff.set_global_pause(body.paused, body.actor)
    return {"automation_paused": body.paused}


@router.get("/store-settings")
async def get_store_settings(container: ContainerDep) -> dict[str, Any]:
    async with container.db.transaction() as tx:
        return _dump(await tx.get_store_settings())


@router.put("/store-settings")
async def put_store_settings(body: StoreSettings, container: ContainerDep) -> dict[str, Any]:
    async with container.db.transaction() as tx:
        await tx.save_store_settings(body, container.clock.now())
    return _dump(body)


@router.post("/retention/purge")
async def purge(container: ContainerDep, dry_run: bool = True) -> dict[str, Any]:
    return asdict(await container.retention.purge(dry_run=dry_run))


@router.get("/sent")
async def sent_messages(container: ContainerDep) -> list[dict[str, str]]:
    gateway = container.gateway
    if not isinstance(gateway, FakeGateway):
        raise HTTPException(status_code=404)
    return [
        {"to": s.to, "text": s.text, "provider_message_id": s.provider_message_id}
        for s in gateway.sent
    ]
