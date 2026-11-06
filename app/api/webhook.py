"""Rotas do webhook da WhatsApp Cloud API.

GET  /webhook/whatsapp  — verificação da Meta (hub.mode / hub.verify_token / hub.challenge)
POST /webhook/whatsapp  — eventos assinados (X-Hub-Signature-256 sobre o corpo bruto)

Responde 200 só depois de gravar. Se algo falhar, responde 500 e a Meta reenvia; a
deduplicação por ID evita processamento duplo. O conteúdo das mensagens nunca vai para o log.
"""

import json
import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.core.container import Container
from app.core.logging import mask_id
from app.domain.models import InboundMessage
from app.integrations.whatsapp.webhook import parse_webhook, verify_signature

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])


def _container(request: Request) -> Container:
    container: Container = request.app.state.container
    if not container.settings.webhook_enabled:
        raise HTTPException(status_code=404)
    return container


@router.get("/whatsapp", response_class=PlainTextResponse)
async def verify(
    request: Request,
    mode: Annotated[str, Query(alias="hub.mode")] = "",
    token: Annotated[str, Query(alias="hub.verify_token", max_length=200)] = "",
    challenge: Annotated[str, Query(alias="hub.challenge", max_length=200)] = "",
) -> str:
    settings = _container(request).settings
    assert settings.whatsapp_verify_token is not None
    expected = settings.whatsapp_verify_token.get_secret_value()
    if mode != "subscribe" or not secrets.compare_digest(token.encode(), expected.encode()):
        logger.warning("verificação de webhook recusada")
        raise HTTPException(status_code=403)
    return challenge


@router.post("/whatsapp", response_class=PlainTextResponse)
async def receive(request: Request, background: BackgroundTasks) -> str:
    container = _container(request)
    settings = container.settings
    assert settings.whatsapp_app_secret is not None

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.webhook_max_body_bytes:
        raise HTTPException(status_code=413)
    body = await request.body()
    if len(body) > settings.webhook_max_body_bytes:
        raise HTTPException(status_code=413)

    # Assinatura ANTES de qualquer leitura do conteúdo.
    signature = request.headers.get("x-hub-signature-256")
    if not verify_signature(settings.whatsapp_app_secret.get_secret_value(), body, signature):
        logger.warning("webhook com assinatura inválida recusado")
        raise HTTPException(status_code=401)

    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400) from exc

    now = container.clock.now()
    parsed = parse_webhook(payload, phone_number_id=settings.whatsapp_phone_number_id, now=now)

    touched: set[str] = set()
    for message in parsed.messages:
        result = await container.conversations.handle_inbound(
            InboundMessage(
                provider_message_id=message.provider_message_id,
                conversation_id=message.wa_id,
                type=message.type,
                text=message.text,
                timestamp=message.timestamp,
                received_at=now,
                provider_user_id=message.provider_user_id,
            )
        )
        if result.outbound_ids:
            touched.add(message.wa_id)
    for status in parsed.statuses:
        await container.webhook_events.apply_status(status)
    if settings.pause_on_owner_echo:
        for echo in parsed.echoes:
            await container.webhook_events.apply_owner_echo(echo)

    if parsed.ignored:
        logger.info("webhook: itens ignorados=%s", sorted(set(parsed.ignored)))
    # Envio imediato após responder à Meta; a outbox cobre qualquer falha aqui.
    for conversation_id in touched:
        background.add_task(_dispatch, container, conversation_id)
    return "OK"


async def _dispatch(container: Container, conversation_id: str) -> None:
    try:
        await container.dispatcher.dispatch_pending(conversation_id)
    except Exception:
        logger.exception(
            "envio imediato falhou conversa=%s (a outbox tentará)", mask_id(conversation_id)
        )
