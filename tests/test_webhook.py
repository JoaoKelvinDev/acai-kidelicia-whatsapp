"""Webhook da Cloud API: verificação, assinatura, leitura completa, status e eco."""

from datetime import UTC, datetime

import pytest

from app.integrations.whatsapp.webhook import parse_webhook, verify_signature
from tests import meta_payloads as mp
from tests.conftest import OTHER_SENDER, SENDER, load_order

WEBHOOK_SETTINGS = {
    "whatsapp_app_secret": mp.APP_SECRET,
    "whatsapp_verify_token": mp.VERIFY_TOKEN,
    "whatsapp_phone_number_id": mp.PHONE_NUMBER_ID,
}


@pytest.fixture
def client(app_factory):
    return app_factory(**WEBHOOK_SETTINGS).client


def post(client, payload, *, signature: str | None = "auto", body: bytes | None = None):
    raw = body if body is not None else mp.encode(payload)
    headers = {"Content-Type": "application/json"}
    if signature == "auto":
        headers["X-Hub-Signature-256"] = mp.sign(raw)
    elif signature is not None:
        headers["X-Hub-Signature-256"] = signature
    return client.post("/webhook/whatsapp", content=raw, headers=headers)


def conversation(client, wa_id: str = SENDER):
    response = client.get(f"/dev/conversations/{wa_id}")
    return response.json() if response.status_code == 200 else None


def sent(client) -> list[dict]:
    return client.get("/dev/sent").json()


def say(client, text: str, msg_id: str, wa_id: str = SENDER):
    payload = mp.envelope(
        mp.change(
            mp.value(contacts=[mp.contact(wa_id)], messages=[mp.text_message(wa_id, text, msg_id)])
        )
    )
    return post(client, payload)


# ── verificação (GET) ───────────────────────────────────────────────────────


def test_verification_returns_challenge(client):
    response = client.get(
        "/webhook/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": mp.VERIFY_TOKEN,
            "hub.challenge": "42",
        },
    )
    assert response.status_code == 200
    assert response.text == "42"


@pytest.mark.parametrize(
    "params",
    [
        {"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "42"},
        {"hub.mode": "unsubscribe", "hub.verify_token": mp.VERIFY_TOKEN, "hub.challenge": "42"},
        {},
    ],
)
def test_verification_rejects_wrong_token_or_mode(client, params):
    assert client.get("/webhook/whatsapp", params=params).status_code == 403


def test_webhook_disabled_without_secrets(app_factory):
    client = app_factory().client
    assert client.get("/webhook/whatsapp").status_code == 404
    assert client.post("/webhook/whatsapp", content=b"{}").status_code == 404


# ── assinatura (POST) ───────────────────────────────────────────────────────


@pytest.mark.parametrize("signature", [None, "sha256=" + "0" * 64, "md5=abc", "sha256="])
def test_invalid_signature_is_rejected_before_processing(client, signature):
    payload = mp.envelope(mp.change(mp.value(messages=[mp.text_message(SENDER, "Oi", "w1")])))
    assert post(client, payload, signature=signature).status_code == 401
    assert conversation(client) is None


def test_tampered_body_is_rejected(client):
    original = mp.encode(
        mp.envelope(mp.change(mp.value(messages=[mp.text_message(SENDER, "Oi", "w1")])))
    )
    tampered = original.replace(b"Oi", b"Ol")
    response = post(client, None, signature=mp.sign(original), body=tampered)
    assert response.status_code == 401
    assert conversation(client) is None


def test_signature_is_checked_on_raw_bytes():
    body = b'{"a":"\\u00e7"}'
    assert verify_signature(mp.APP_SECRET, body, mp.sign(body))
    assert not verify_signature(mp.APP_SECRET, '{"a":"ç"}'.encode(), mp.sign(body))
    assert not verify_signature("outro-segredo", body, mp.sign(body))


def test_malformed_json_with_valid_signature(client):
    assert post(client, None, body=b"{nao-e-json").status_code == 400


def test_oversized_body_is_rejected(app_factory):
    client = app_factory(webhook_max_body_bytes=2048, **WEBHOOK_SETTINGS).client
    big = mp.envelope(mp.change(mp.value(messages=[mp.text_message(SENDER, "x" * 5000, "w1")])))
    assert post(client, big).status_code == 413


# ── mensagens ───────────────────────────────────────────────────────────────


def test_text_message_is_processed_and_answered(client):
    assert say(client, "Oi", "wamid.1").status_code == 200
    view = conversation(client)
    assert view["conversation"]["state"] == "AUTO_ACTIVE"
    assert view["conversation"]["provider_user_id"] == "BR.1000000000000001"
    assert [m["provider_message_id"] for m in view["messages"]] == ["wamid.1"]
    assert [s["to"] for s in sent(client)] == [SENDER]


def test_site_order_through_webhook_confirms(client):
    say(client, load_order("delivery_pix_valido"), "wamid.order")
    view = conversation(client)
    assert view["conversation"]["state"] == "HUMAN_PENDING"
    assert [o["kind"] for o in view["outbound"]] == ["confirmation"]  # loja aberta no teste


def test_every_entry_change_and_message_is_processed(client):
    payload = mp.envelope(
        mp.change(
            mp.value(
                messages=[
                    mp.text_message(SENDER, "Oi", "wamid.a"),
                    mp.text_message(OTHER_SENDER, "Bom dia", "wamid.b"),
                ]
            )
        ),
        mp.change(mp.value(messages=[mp.text_message("5511955554444", "Olá", "wamid.c")])),
    )
    payload["entry"].append(
        {
            "id": mp.WABA_ID,
            "changes": [
                mp.change(mp.value(messages=[mp.text_message("5511944443333", "Oi", "wamid.d")]))
            ],
        }
    )
    assert post(client, payload).status_code == 200
    assert {s["to"] for s in sent(client)} == {
        SENDER,
        OTHER_SENDER,
        "5511955554444",
        "5511944443333",
    }


def test_repeated_delivery_is_processed_once(client):
    for _ in range(3):
        assert say(client, "Oi", "wamid.same").status_code == 200
    assert len(sent(client)) == 1
    assert len(conversation(client)["messages"]) == 1


def test_other_phone_number_and_own_number_are_ignored(client):
    other = mp.envelope(
        mp.change(mp.value(messages=[mp.text_message(SENDER, "Oi", "w1")], phone_number_id="999"))
    )
    own = mp.envelope(
        mp.change(mp.value(messages=[mp.text_message(mp.BUSINESS_NUMBER, "Oi", "w2")]))
    )
    assert post(client, other).status_code == 200
    assert post(client, own).status_code == 200
    assert conversation(client) is None
    assert conversation(client, mp.BUSINESS_NUMBER) is None
    assert sent(client) == []


@pytest.mark.parametrize("kind", ["audio", "image", "document", "location", "video", "sticker"])
def test_media_is_forwarded_not_read(client, kind):
    post(client, mp.envelope(mp.change(mp.value(messages=[mp.media_message(SENDER, kind, "w1")]))))
    view = conversation(client)
    assert view["messages"][0]["type"] == kind
    assert view["messages"][0]["text"] is None
    assert [o["kind"] for o in view["outbound"]] == ["media"]


def test_reaction_is_ignored_and_button_reply_is_text(client):
    reaction = {
        "from": SENDER,
        "id": "w1",
        "timestamp": str(mp.EPOCH),
        "type": "reaction",
        "reaction": {"message_id": "x", "emoji": "👍"},
    }
    button = {
        "from": SENDER,
        "id": "w2",
        "timestamp": str(mp.EPOCH),
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": "b", "title": "Oi"}},
    }
    post(client, mp.envelope(mp.change(mp.value(messages=[reaction, button]))))
    view = conversation(client)
    assert [m["provider_message_id"] for m in view["messages"]] == ["w2"]
    assert view["messages"][0]["text"] == "Oi"


# ── status de entrega ───────────────────────────────────────────────────────


def _greet_and_get_reply_id(client) -> str:
    say(client, "Oi", "wamid.1")
    [reply] = conversation(client)["outbound"]
    assert reply["status"] == "sent"
    return reply["provider_message_id"]


def test_statuses_update_reply_without_regressing(client):
    reply_id = _greet_and_get_reply_id(client)
    for state, ts in (("sent", 1), ("read", 3), ("delivered", 2), ("read", 3)):
        payload = mp.envelope(
            mp.change(mp.value(statuses=[mp.status(reply_id, state, SENDER, mp.EPOCH + ts)]))
        )
        assert post(client, payload).status_code == 200
    [reply] = conversation(client)["outbound"]
    assert reply["delivery_status"] == "read"
    assert reply["delivered_at"] is not None and reply["read_at"] is not None
    assert len(sent(client)) == 1  # status nunca gera resposta
    assert len(conversation(client)["messages"]) == 1  # nem vira mensagem


def test_failed_status_records_error_code(client):
    reply_id = _greet_and_get_reply_id(client)
    payload = mp.envelope(
        mp.change(mp.value(statuses=[mp.status(reply_id, "failed", SENDER, error_code=131047)]))
    )
    post(client, payload)
    [reply] = conversation(client)["outbound"]
    assert reply["delivery_status"] == "failed"
    assert reply["delivery_error_code"] == 131047
    assert reply["status"] == "sent"  # aceita pela API; falhou na entrega; sem reenvio


def test_status_for_unknown_message_is_harmless(client):
    payload = mp.envelope(
        mp.change(
            mp.value(statuses=[mp.status("wamid.de-fora", "failed", SENDER, error_code=131031)])
        )
    )
    assert post(client, payload).status_code == 200
    assert conversation(client) is None


# ── eco do app do celular (coexistência) ────────────────────────────────────


def test_owner_echo_pauses_automation(client):
    say(client, "Oi", "wamid.1")
    assert post(client, mp.envelope(mp.echo(SENDER, "wamid.eco"))).status_code == 200
    view = conversation(client)
    assert view["conversation"]["state"] == "HUMAN_ACTIVE"
    assert view["conversation"]["assignee"] == "app_whatsapp"
    say(client, "quero um açaí", "wamid.2")
    assert len(sent(client)) == 1  # só a saudação inicial


def test_owner_echo_for_new_contact_creates_paused_conversation(client):
    post(client, mp.envelope(mp.echo(OTHER_SENDER, "wamid.eco")))
    assert conversation(client, OTHER_SENDER)["conversation"]["state"] == "HUMAN_ACTIVE"


def test_owner_echo_can_be_disabled(app_factory):
    client = app_factory(pause_on_owner_echo=False, **WEBHOOK_SETTINGS).client
    say(client, "Oi", "wamid.1")
    post(client, mp.envelope(mp.echo(SENDER, "wamid.eco")))
    assert conversation(client)["conversation"]["state"] == "AUTO_ACTIVE"


# ── robustez do parser ──────────────────────────────────────────────────────


NOW = datetime(2026, 11, 6, tzinfo=UTC)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "texto",
        {"object": "page"},
        {"object": "whatsapp_business_account", "entry": "x"},
        {"object": "whatsapp_business_account", "entry": [{"changes": "abc"}]},
        {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": None}]}]},
        mp.envelope(mp.change({"metadata": {}, "messages": {"from": "1"}})),
        mp.envelope(mp.change(mp.value(messages=[{"id": "x"}], statuses=[{"status": "read"}]))),
        mp.envelope(
            mp.change(mp.value(statuses=[{"id": "x", "status": "deleted", "timestamp": "1"}]))
        ),
        mp.envelope(
            mp.change(mp.value(statuses=[{"id": "x", "status": "read", "timestamp": "abc"}]))
        ),
        mp.envelope(mp.change(mp.value(), field="account_update")),
    ],
)
def test_parser_never_raises_on_odd_payloads(payload):
    parsed = parse_webhook(payload, phone_number_id=mp.PHONE_NUMBER_ID, now=NOW)
    assert parsed.messages == [] and parsed.statuses == []
    assert parsed.ignored


def test_parser_without_configured_phone_number_id_accepts_any():
    payload = mp.envelope(
        mp.change(mp.value(messages=[mp.text_message(SENDER, "Oi", "w1")], phone_number_id="7"))
    )
    assert len(parse_webhook(payload, phone_number_id=None, now=NOW).messages) == 1
