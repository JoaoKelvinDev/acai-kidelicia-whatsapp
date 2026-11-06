"""Gateway real da Cloud API (sem rede: httpx.MockTransport) e travas de configuração."""

import json
import logging

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.domain.enums import OutboundStatus, ReplyKind
from app.integrations.whatsapp.cloud import CloudApiGateway
from app.integrations.whatsapp.gateway import GatewayError
from tests import meta_payloads as mp
from tests.conftest import SENDER, load_order

TOKEN = "token-ficticio-NAO-REAL-123"
ALLOWED = frozenset({"5511974123058"})


def gateway(handler, allowed: frozenset[str] = ALLOWED) -> CloudApiGateway:
    return CloudApiGateway(
        access_token=TOKEN,
        phone_number_id=mp.PHONE_NUMBER_ID,
        api_version="v25.0",
        allowed_recipients=allowed,
        timeout_seconds=5,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def meta_error(status: int, code: int | None):
    body = {"error": {"message": "erro", "code": code}} if code is not None else {}
    return lambda request: httpx.Response(status, json=body)


async def test_sends_text_with_expected_request():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.OK"}]})

    result = await gateway(handler).send_text(SENDER, "Olá")
    assert result.provider_message_id == "wamid.OK"
    [request] = seen
    assert str(request.url) == f"https://graph.facebook.com/v25.0/{mp.PHONE_NUMBER_ID}/messages"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": SENDER,
        "type": "text",
        "text": {"preview_url": False, "body": "Olá"},
    }


async def test_recipient_outside_allowlist_never_reaches_meta():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"messages": [{"id": "x"}]})

    with pytest.raises(GatewayError) as exc:
        await gateway(handler).send_text("5511963217045", "Olá")
    assert exc.value.code == "destinatario_fora_da_lista_autorizada"
    assert not exc.value.retryable
    assert calls == 0


async def test_allowlist_sends_in_registered_format_when_wa_id_lacks_ninth_digit():
    # Caso real (06/11/2026): wa_id sem o 9, lista da Meta com o 9 → erro 131030.
    seen: list[dict] = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "x"}]})

    assert (await gateway(handler).send_text("551174123058", "Olá")).provider_message_id == "x"
    assert seen[0]["to"] == "5511974123058"


async def test_without_allowlist_sends_to_wa_id_as_given():
    seen: list[dict] = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "x"}]})

    await gateway(handler, allowed=frozenset()).send_text("551174123058", "Olá")
    assert seen[0]["to"] == "551174123058"


@pytest.mark.parametrize(
    ("status", "code", "name", "retryable"),
    [
        (429, None, "http_429", True),
        (400, 130429, "limite_de_envio", True),
        (400, 131056, "limite_por_destinatario", True),
        (500, None, "http_500", True),
        (503, 2, "meta_2", True),
        (400, 131047, "fora_da_janela_24h", False),
        (401, 190, "token_invalido", False),
        (400, 131031, "conta_restrita", False),
        (400, 131030, "destinatario_nao_permitido_pela_meta", False),
        (400, 100, "parametro_invalido", False),
        (400, 999999, "meta_999999", False),
    ],
)
async def test_meta_errors_are_classified(status, code, name, retryable):
    with pytest.raises(GatewayError) as exc:
        await gateway(meta_error(status, code)).send_text(SENDER, "Olá")
    assert exc.value.code == name
    assert exc.value.retryable is retryable
    assert exc.value.outcome_unknown is False


async def test_non_json_error_body():
    with pytest.raises(GatewayError) as exc:
        await gateway(lambda r: httpx.Response(502, text="<html>")).send_text(SENDER, "Olá")
    assert exc.value.code == "http_502" and exc.value.retryable


async def test_connection_failure_is_retryable_but_timeout_is_unknown():
    def refuse(request):
        raise httpx.ConnectError("recusado", request=request)

    def slow(request):
        raise httpx.ReadTimeout("demorou", request=request)

    with pytest.raises(GatewayError) as exc:
        await gateway(refuse).send_text(SENDER, "Olá")
    assert exc.value.retryable and not exc.value.outcome_unknown

    with pytest.raises(GatewayError) as exc:
        await gateway(slow).send_text(SENDER, "Olá")
    assert exc.value.outcome_unknown and not exc.value.retryable


async def test_unexpected_error_shapes():
    for body in ([1, 2], {"error": "texto"}, {"error": {"code": "x"}}):
        with pytest.raises(GatewayError) as exc:
            await gateway(lambda r, b=body: httpx.Response(400, json=b)).send_text(SENDER, "Olá")
        assert exc.value.code == "http_400" and not exc.value.retryable


async def test_success_without_id_is_unknown():
    with pytest.raises(GatewayError) as exc:
        await gateway(lambda r: httpx.Response(200, json={})).send_text(SENDER, "Olá")
    assert exc.value.outcome_unknown


async def test_token_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(GatewayError):
        await gateway(meta_error(401, 190)).send_text(SENDER, "Olá")
    assert TOKEN not in caplog.text
    assert "token da Cloud API inválido" in caplog.text


async def test_end_to_end_with_cloud_gateway(harness_factory):
    sent: list[dict] = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": f"wamid.out{len(sent)}"}]})

    h = await harness_factory(gateway=gateway(handler))
    await h.receive(load_order("delivery_pix_valido"))
    [reply] = await h.outbound()
    assert reply.kind is ReplyKind.CONFIRMATION
    assert reply.status is OutboundStatus.SENT
    assert reply.provider_message_id == "wamid.out1"
    assert sent[0]["to"] == SENDER


# ── travas de configuração ──────────────────────────────────────────────────

CLOUD = {
    "whatsapp_gateway": "cloud",
    "whatsapp_access_token": TOKEN,
    "whatsapp_phone_number_id": mp.PHONE_NUMBER_ID,
    "whatsapp_app_secret": mp.APP_SECRET,
    "whatsapp_verify_token": mp.VERIFY_TOKEN,
}


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_cloud_requires_all_credentials():
    with pytest.raises(ValidationError, match="WHATSAPP_ACCESS_TOKEN"):
        settings(app_env="staging", whatsapp_gateway="cloud")


def test_cloud_is_refused_with_local_env():
    with pytest.raises(ValidationError, match="APP_ENV=local"):
        settings(app_env="local", whatsapp_allowed_recipients=SENDER, **CLOUD)


def test_cloud_outside_production_requires_allowlist():
    with pytest.raises(ValidationError, match="WHATSAPP_ALLOWED_RECIPIENTS"):
        settings(app_env="staging", **CLOUD)
    ok = settings(
        app_env="staging", whatsapp_allowed_recipients="+55 (11) 97412-3058, 5511963217045", **CLOUD
    )
    assert ok.allowed_recipients == {"5511974123058", "5511963217045"}
    assert settings(app_env="production", **CLOUD).allowed_recipients == frozenset()


def test_secrets_are_hidden_in_repr():
    s = settings(app_env="staging", whatsapp_allowed_recipients=SENDER, **CLOUD)
    assert TOKEN not in repr(s) and mp.APP_SECRET not in repr(s)


def test_warning_when_webhook_runs_with_dev_routes(app_factory, caplog):
    caplog.set_level(logging.WARNING)
    app_factory(whatsapp_app_secret=mp.APP_SECRET, whatsapp_verify_token=mp.VERIFY_TOKEN)
    assert "rotas /dev (sem login) estão ativas" in caplog.text


def test_blank_secrets_count_as_missing():
    s = settings(whatsapp_app_secret="", whatsapp_verify_token="  ", whatsapp_access_token="")
    assert s.whatsapp_app_secret is None and s.whatsapp_verify_token is None
    assert not s.webhook_enabled
    with pytest.raises(ValidationError, match="WHATSAPP_APP_SECRET"):
        settings(
            app_env="staging",
            whatsapp_allowed_recipients=SENDER,
            **{**CLOUD, "whatsapp_app_secret": ""},
        )


def test_env_example_is_safe_by_default(monkeypatch):
    from pathlib import Path

    for key in list(__import__("os").environ):
        if key.startswith(("WHATSAPP_", "APP_ENV")):
            monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=Path(__file__).parents[1] / ".env.example")
    assert s.whatsapp_gateway == "fake"
    assert not s.webhook_enabled
