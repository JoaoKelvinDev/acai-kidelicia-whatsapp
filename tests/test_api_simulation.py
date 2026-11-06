import pytest

from app.core.config import Settings
from tests.conftest import SENDER, load_order


def test_health(app_factory):
    client = app_factory("production").client
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("app_env", ["production", "staging"])
def test_simulation_routes_and_docs_do_not_exist_outside_dev(app_factory, app_env):
    client = app_factory(app_env).client
    response = client.post("/dev/simulate/inbound", json={"from": SENDER, "text": "Oi"})
    assert response.status_code == 404
    assert client.get("/dev/store-settings").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_default_settings_disable_dev_tools():
    assert Settings(_env_file=None).dev_tools_enabled is False


def test_simulated_order_flow_end_to_end(app_factory):
    client = app_factory().client
    body = client.post(
        "/dev/simulate/inbound",
        json={"from": SENDER, "text": load_order("delivery_pix_valido"), "message_id": "m1"},
    ).json()
    assert body["result"]["intent"] == "site_order"
    assert [d["kind"] for d in body["dispatched"]] == ["confirmation"]
    assert [d["status"] for d in body["dispatched"]] == ["sent"]

    repeat = client.post(
        "/dev/simulate/inbound",
        json={"from": SENDER, "text": load_order("delivery_pix_valido"), "message_id": "m1"},
    )
    assert repeat.json()["result"]["duplicate"] is True

    view = client.get(f"/dev/conversations/{SENDER}").json()
    assert view["conversation"]["state"] == "HUMAN_PENDING"
    assert len(view["messages"]) == 1
    assert view["drafts"][0]["state"] == "RECEIVED"

    taken = client.post(f"/dev/conversations/{SENDER}/take_over", json={"actor": "joao"})
    assert taken.json()["state"] == "HUMAN_ACTIVE"
    assert len(client.get("/dev/sent").json()) == 1


def test_simulation_validates_input(app_factory):
    client = app_factory().client
    bad = client.post("/dev/simulate/inbound", json={"from": "abc", "text": "Oi"})
    assert bad.status_code == 422
    missing = client.post("/dev/conversations/5511000000001/pause", json={"actor": "joao"})
    assert missing.status_code == 404
    unknown_action = client.post(f"/dev/conversations/{SENDER}/delete", json={"actor": "j"})
    assert unknown_action.status_code == 422


def test_store_settings_persist_and_apply(app_factory):
    client = app_factory().client
    current = client.get("/dev/store-settings").json()
    current["status_override"] = "fechado"
    assert client.put("/dev/store-settings", json=current).status_code == 200
    response = client.post(
        "/dev/simulate/inbound",
        json={"from": SENDER, "text": load_order("delivery_pix_valido")},
    )
    assert [d["kind"] for d in response.json()["dispatched"]] == ["store_closed"]
