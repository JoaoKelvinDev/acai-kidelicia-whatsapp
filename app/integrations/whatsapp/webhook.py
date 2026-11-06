"""Webhook da WhatsApp Cloud API: assinatura e leitura do payload.

- A assinatura (X-Hub-Signature-256) é conferida sobre o corpo BRUTO, antes de qualquer parse.
- Todos os itens de entry[] → changes[] → messages[]/statuses[] são lidos, não só o primeiro.
- Payload malformado nunca derruba o processamento: o item é ignorado e o motivo registrado.
- Eventos de outro número (phone_number_id) e mensagens do próprio número são ignorados.
"""

import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.domain.enums import DeliveryStatus, MessageType

_TYPE_MAP = {
    "text": MessageType.TEXT,
    "image": MessageType.IMAGE,
    "audio": MessageType.AUDIO,
    "voice": MessageType.AUDIO,
    "video": MessageType.VIDEO,
    "document": MessageType.DOCUMENT,
    "location": MessageType.LOCATION,
    "sticker": MessageType.STICKER,
    "contacts": MessageType.CONTACTS,
}
_IGNORED_TYPES = frozenset({"reaction", "system", "request_welcome"})


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256=").strip().lower())


@dataclass(frozen=True)
class IncomingMessage:
    provider_message_id: str
    wa_id: str
    type: MessageType
    text: str | None
    timestamp: datetime
    provider_user_id: str | None = None


@dataclass(frozen=True)
class StatusUpdate:
    provider_message_id: str
    status: DeliveryStatus
    timestamp: datetime
    recipient_id: str | None
    error_code: int | None = None
    error_title: str | None = None


@dataclass(frozen=True)
class OwnerEcho:
    """Mensagem enviada pelo app do celular da loja (coexistência). Não validado com evento real."""

    provider_message_id: str
    to_wa_id: str
    timestamp: datetime


@dataclass
class ParsedWebhook:
    messages: list[IncomingMessage] = field(default_factory=list)
    statuses: list[StatusUpdate] = field(default_factory=list)
    echoes: list[OwnerEcho] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)


def _ts(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _text_of(message: dict[str, Any]) -> str | None:
    kind = message.get("type")
    if kind == "text":
        return (message.get("text") or {}).get("body")
    if kind == "button":
        return (message.get("button") or {}).get("text")
    if kind == "interactive":
        interactive = message.get("interactive") or {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return reply.get("title")
    return None


def _message_type(kind: Any) -> MessageType:
    if kind in ("text", "button", "interactive"):
        return MessageType.TEXT
    return _TYPE_MAP.get(kind, MessageType.OTHER)


def parse_webhook(payload: Any, *, phone_number_id: str | None, now: datetime) -> ParsedWebhook:
    parsed = ParsedWebhook()
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        parsed.ignored.append("objeto_desconhecido")
        return parsed

    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            parsed.ignored.append("entry_invalido")
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict) or not isinstance(change.get("value"), dict):
                parsed.ignored.append("change_invalido")
                continue
            _parse_change(change, parsed, phone_number_id=phone_number_id, now=now)
    return parsed


def _parse_change(
    change: dict[str, Any], parsed: ParsedWebhook, *, phone_number_id: str | None, now: datetime
) -> None:
    value: dict[str, Any] = change["value"]
    metadata = value.get("metadata") or {}
    if phone_number_id and str(metadata.get("phone_number_id")) != phone_number_id:
        parsed.ignored.append("outro_numero")
        return
    business_number = _digits(metadata.get("display_phone_number"))
    field_name = change.get("field")

    if field_name == "smb_message_echoes":
        for echo in value.get("message_echoes") or []:
            if isinstance(echo, dict) and echo.get("id") and echo.get("to"):
                parsed.echoes.append(
                    OwnerEcho(
                        provider_message_id=str(echo["id"]),
                        to_wa_id=_digits(echo["to"]),
                        timestamp=_ts(echo.get("timestamp")) or now,
                    )
                )
            else:
                parsed.ignored.append("eco_invalido")
        return

    if field_name != "messages":
        parsed.ignored.append(f"campo_{field_name}")
        return

    user_ids = {
        _digits(c.get("wa_id")): c.get("user_id")
        for c in value.get("contacts") or []
        if isinstance(c, dict)
    }
    for message in value.get("messages") or []:
        _parse_message(message, parsed, business_number, user_ids, now)
    for status in value.get("statuses") or []:
        _parse_status(status, parsed)


def _parse_message(
    message: Any,
    parsed: ParsedWebhook,
    business_number: str,
    user_ids: dict[str, Any],
    now: datetime,
) -> None:
    if not isinstance(message, dict) or not message.get("id") or not message.get("from"):
        parsed.ignored.append("mensagem_invalida")
        return
    wa_id = _digits(message["from"])
    if not wa_id or (business_number and wa_id == business_number):
        parsed.ignored.append("mensagem_do_proprio_numero")
        return
    kind = message.get("type")
    if kind in _IGNORED_TYPES:
        parsed.ignored.append(f"tipo_{kind}")
        return
    user_id = user_ids.get(wa_id)
    parsed.messages.append(
        IncomingMessage(
            provider_message_id=str(message["id"]),
            wa_id=wa_id,
            type=_message_type(kind),
            text=_text_of(message),
            timestamp=_ts(message.get("timestamp")) or now,
            provider_user_id=str(user_id) if user_id else None,
        )
    )


def _parse_status(status: Any, parsed: ParsedWebhook) -> None:
    if not isinstance(status, dict) or not status.get("id"):
        parsed.ignored.append("status_invalido")
        return
    try:
        value = DeliveryStatus(status.get("status"))
    except ValueError:
        parsed.ignored.append(f"status_{status.get('status')}")
        return
    timestamp = _ts(status.get("timestamp"))
    if timestamp is None:
        parsed.ignored.append("status_sem_horario")
        return
    errors = status.get("errors") or []
    first_error = errors[0] if errors and isinstance(errors[0], dict) else {}
    code = first_error.get("code")
    parsed.statuses.append(
        StatusUpdate(
            provider_message_id=str(status["id"]),
            status=value,
            timestamp=timestamp,
            recipient_id=_digits(status.get("recipient_id")) or None,
            error_code=code if isinstance(code, int) else None,
            error_title=str(first_error["title"])[:200] if first_error.get("title") else None,
        )
    )
