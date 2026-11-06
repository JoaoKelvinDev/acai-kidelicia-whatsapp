"""Painel da equipe: login, permissões, CSRF, ações e telas."""

import io
import re

import pytest

from app import cli
from tests.conftest import SENDER, load_order

PASSWORD = "senha-segura-123"


@pytest.fixture
def panel(app_factory, monkeypatch):
    handle = app_factory()

    def run_cli(*args: str, stdin: str = "") -> int:
        monkeypatch.setenv("DATABASE_URL", handle.url)
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        return cli.main(list(args))

    assert (
        run_cli(
            "create-operator",
            "--username",
            "Joao",
            "--role",
            "admin",
            "--password-stdin",
            stdin=PASSWORD + "\n",
        )
        == 0
    )
    assert (
        run_cli(
            "create-operator",
            "--username",
            "maria",
            "--role",
            "atendente",
            "--password-stdin",
            stdin=PASSWORD + "\n",
        )
        == 0
    )
    handle.run_cli = run_cli
    return handle


def login(client, username: str, password: str = PASSWORD):
    return client.post(
        "/admin/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def csrf(client, path: str = "/admin") -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, "token CSRF ausente"
    return match.group(1)


def simulate(client, text: str, sender: str = SENDER) -> None:
    response = client.post("/dev/simulate/inbound", json={"from": sender, "text": text})
    assert response.status_code == 200


def test_panel_requires_login(panel):
    response = panel.client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_wrong_password_and_lockout(panel):
    client = panel.client
    response = login(client, "joao", "senha-errada-000")
    assert response.status_code == 401
    assert "inválidos" in response.text
    assert login(client, "ninguem", PASSWORD).status_code == 401  # mesma resposta
    for _ in range(4):
        login(client, "joao", "senha-errada-000")
    assert login(client, "joao", PASSWORD).status_code == 401  # bloqueado


def test_login_sets_secure_session_cookie(panel):
    response = login(panel.client, "JOAO")
    assert response.status_code == 303
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/admin" in cookie


def test_queue_shows_pending_order_and_detail_shows_organized_order(panel):
    client = panel.client
    simulate(client, load_order("delivery_pix_valido"))
    login(client, "maria")

    queue = client.get("/admin").text
    assert "Mariana Souza" in queue
    assert "(11) 97412-3058" in queue
    assert "Pedido recebido — montar e pesar" in queue

    detail = client.get(f"/admin/conversas/{SENDER}").text
    for expected in (
        "Copo 500ml",
        "Creme de Ninho, Creme de Cupuaçu",
        "Leite Condensado, Granola",
        "Rua das Acácias",
        "não verificada",
        "Pix",
        "Recebemos seu pedido!",
    ):
        assert expected in detail, expected


def test_customer_content_is_escaped(panel):
    client = panel.client
    simulate(client, "<script>alert('x')</script> quero falar com atendente")
    login(client, "maria")
    detail = client.get(f"/admin/conversas/{SENDER}").text
    assert "<script>alert" not in detail
    assert "&lt;script&gt;" in detail


def test_actions_require_valid_csrf_and_are_audited(panel):
    client = panel.client
    simulate(client, load_order("delivery_pix_valido"))
    login(client, "maria")
    url = f"/admin/conversas/{SENDER}/acao"

    assert client.post(url, data={"action": "take_over"}).status_code == 422
    forged = client.post(url, data={"action": "take_over", "csrf_token": "forjado"})
    assert forged.status_code == 403

    token = csrf(client, f"/admin/conversas/{SENDER}")
    ok = client.post(url, data={"action": "take_over", "csrf_token": token}, follow_redirects=False)
    assert ok.status_code == 303
    view = client.get(f"/dev/conversations/{SENDER}").json()
    assert view["conversation"]["state"] == "HUMAN_ACTIVE"
    assert view["conversation"]["assignee"] == "maria"
    assert view["audit"][-1]["actor"] == "maria"


def test_attendant_cannot_change_settings(panel):
    client = panel.client
    login(client, "maria")
    assert client.get("/admin/configuracoes").status_code == 403
    token = csrf(client)
    response = client.post("/admin/pausa-global", data={"paused": "1", "csrf_token": token})
    assert response.status_code == 403
    assert "Configurações" not in client.get("/admin").text


def test_admin_changes_store_status_hours_and_global_pause(panel):
    client = panel.client
    login(client, "joao")
    token = csrf(client, "/admin/configuracoes")
    response = client.post(
        "/admin/configuracoes",
        data={
            "csrf_token": token,
            "status": "auto",
            "open_4": "on",
            "start_4": "14:00",
            "end_4": "22:00",
            "website_url": "https://acaikideliciapl.com.br",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    store = client.get("/dev/store-settings").json()
    assert store["status_override"] is None
    assert store["opening_hours"] == [{"weekday": 4, "start": "14:00:00", "end": "22:00:00"}]

    paused = client.post(
        "/admin/pausa-global", data={"paused": "1", "csrf_token": token}, follow_redirects=False
    )
    assert paused.status_code == 303
    assert client.get("/dev/store-settings").json()["automation_paused"] is True
    assert "Automação pausada" in client.get("/admin").text


def test_invalid_hours_are_rejected(panel):
    client = panel.client
    login(client, "joao")
    token = csrf(client, "/admin/configuracoes")
    response = client.post(
        "/admin/configuracoes",
        data={
            "csrf_token": token,
            "status": "aberto",
            "open_0": "on",
            "start_0": "22:00",
            "end_0": "10:00",
        },
    )
    assert response.status_code == 400
    assert "Segunda: horário inválido" in response.text


def test_logout_invalidates_session(panel):
    client = panel.client
    login(client, "maria")
    old_cookie = client.cookies.get("acai_session")
    token = csrf(client)
    client.post("/admin/logout", data={"csrf_token": token}, follow_redirects=False)
    client.cookies.set("acai_session", old_cookie, path="/admin")
    assert client.get("/admin", follow_redirects=False).status_code == 303


def test_deactivated_operator_loses_access(panel):
    client = panel.client
    login(client, "maria")
    assert client.get("/admin").status_code == 200
    assert panel.run_cli("deactivate-operator", "--username", "maria") == 0
    assert client.get("/admin", follow_redirects=False).status_code == 303
    assert login(client, "maria").status_code == 401


def test_security_headers_on_panel(panel):
    response = panel.client.get("/admin/login")
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


def test_cli_rejects_weak_password_and_duplicate(panel, capsys):
    assert (
        panel.run_cli(
            "create-operator",
            "--username",
            "fraca",
            "--role",
            "atendente",
            "--password-stdin",
            stdin="curta\n",
        )
        == 1
    )
    assert (
        panel.run_cli(
            "create-operator",
            "--username",
            "joao",
            "--role",
            "admin",
            "--password-stdin",
            stdin=PASSWORD + "\n",
        )
        == 1
    )
    assert "já existe" in capsys.readouterr().err


def test_cli_purge_dry_run(panel, capsys):
    assert panel.run_cli("purge", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "dry_run: True" in out


def test_panel_can_be_restricted_to_local_hosts(app_factory):
    client = app_factory(admin_allowed_hosts="localhost,127.0.0.1").client
    via_tunnel = client.get("/admin/login", headers={"host": "algo.trycloudflare.com"})
    assert via_tunnel.status_code == 404
    assert (
        client.get("/admin/static/admin.css", headers={"host": "x.trycloudflare.com"}).status_code
        == 404
    )
    assert client.get("/admin/login", headers={"host": "localhost:8000"}).status_code == 200
    assert client.get("/health", headers={"host": "algo.trycloudflare.com"}).status_code == 200


def test_timeline_keeps_reply_after_message_despite_provider_clock(panel):
    """Caso real (06/11/2026): horário da Meta arredondado à frente do relógio local."""
    from datetime import UTC, datetime, timedelta

    client = panel.client
    ahead = (datetime.now(UTC) + timedelta(seconds=2)).isoformat()
    client.post("/dev/simulate/inbound", json={"from": SENDER, "text": "Oi", "timestamp": ahead})
    login(client, "maria")
    page = client.get(f"/admin/conversas/{SENDER}").text
    assert page.index("Cliente ·") < page.index("Assistente ·")
