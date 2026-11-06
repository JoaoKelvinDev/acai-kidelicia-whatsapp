"""Payloads no formato do webhook da Cloud API, com dados fictícios.

Estrutura baseada num evento real recebido do painel de teste da Meta em 06/11/2026
(status "failed" com errors[]), com todos os identificadores substituídos.
"""

import hashlib
import hmac
import json
import time
from typing import Any

PHONE_NUMBER_ID = "100000000000001"
BUSINESS_NUMBER = "15550000001"
WABA_ID = "200000000000002"
APP_SECRET = "segredo-de-teste-do-app"
VERIFY_TOKEN = "token-de-verificacao-teste"
# Horário atual: o servidor de teste usa relógio real e aplica a janela de 24 h.
EPOCH = int(time.time())


def sign(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def encode(payload: Any) -> bytes:
    # A Meta envia JSON com unicode escapado; a assinatura vale para os bytes exatos.
    return json.dumps(payload).encode()


def envelope(*changes: dict[str, Any], entries: int = 1) -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": WABA_ID, "changes": list(changes)} for _ in range(entries)],
    }


def value(
    *,
    messages: list[dict[str, Any]] | None = None,
    statuses: list[dict[str, Any]] | None = None,
    contacts: list[dict[str, Any]] | None = None,
    phone_number_id: str = PHONE_NUMBER_ID,
) -> dict[str, Any]:
    v: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": BUSINESS_NUMBER,
            "phone_number_id": phone_number_id,
        },
    }
    if contacts is not None:
        v["contacts"] = contacts
    if messages is not None:
        v["messages"] = messages
    if statuses is not None:
        v["statuses"] = statuses
    return v


def change(v: dict[str, Any], field: str = "messages") -> dict[str, Any]:
    return {"value": v, "field": field}


def text_message(wa_id: str, body: str, msg_id: str, ts: int = EPOCH) -> dict[str, Any]:
    return {
        "from": wa_id,
        "id": msg_id,
        "timestamp": str(ts),
        "type": "text",
        "text": {"body": body},
    }


def media_message(wa_id: str, kind: str, msg_id: str) -> dict[str, Any]:
    return {"from": wa_id, "id": msg_id, "timestamp": str(EPOCH), "type": kind, kind: {"id": "m1"}}


def contact(wa_id: str, user_id: str = "BR.1000000000000001") -> dict[str, Any]:
    return {"wa_id": wa_id, "user_id": user_id, "profile": {"name": "Cliente Teste"}}


def status(
    msg_id: str, state: str, recipient: str, ts: int = EPOCH, error_code: int | None = None
) -> dict[str, Any]:
    s: dict[str, Any] = {
        "id": msg_id,
        "status": state,
        "timestamp": str(ts),
        "recipient_id": recipient,
    }
    if error_code is not None:
        s["errors"] = [{"code": error_code, "title": "Erro de teste", "message": "Erro de teste"}]
    return s


def echo(to: str, msg_id: str) -> dict[str, Any]:
    return change(
        {
            "messaging_product": "whatsapp",
            "metadata": {
                "display_phone_number": BUSINESS_NUMBER,
                "phone_number_id": PHONE_NUMBER_ID,
            },
            "message_echoes": [
                {
                    "from": BUSINESS_NUMBER,
                    "to": to,
                    "id": msg_id,
                    "timestamp": str(EPOCH),
                    "type": "text",
                    "text": {"body": "Oi! Aqui é da loja."},
                }
            ],
        },
        field="smb_message_echoes",
    )
