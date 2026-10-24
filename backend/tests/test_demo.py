"""The SwiftShip demo business (demo_business/app.py) and the demo seed script, wired to Sanctio in-process."""
import hashlib
import hmac
import importlib.util
import json
import re
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import connectors
from app.db import SessionLocal
from app.models import Conversation, Customer
from scripts.seed_demo import Settings, seed

_spec = importlib.util.spec_from_file_location(
    "swiftship_demo", Path(__file__).resolve().parents[2] / "demo_business" / "app.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)

SETTINGS = Settings(api_key="sk_live_demo_key_for_tests", webhook_secret="whsec_demo_secret_for_tests",
                    business_url="https://swiftship.test", admin_password="Passw0rd!23",
                    phones={"C-1001": "+2348030000001"})


def forward(test_client: TestClient) -> httpx.MockTransport:
    """Send httpx requests to an in-process app, as if it were on the network."""
    def handler(request: httpx.Request) -> httpx.Response:
        r = test_client.request(request.method, request.url.path, content=request.content,
                                headers={k: v for k, v in request.headers.items() if k.lower() != "content-length"})
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": r.headers["content-type"]})
    return httpx.MockTransport(handler)


@pytest.fixture()
def swiftship(client, monkeypatch):
    monkeypatch.setattr(demo, "WEBHOOK_SECRET", SETTINGS.webhook_secret)
    monkeypatch.setattr(demo, "API_KEY", SETTINGS.api_key)
    monkeypatch.setattr(demo, "RESET_TOKEN", "reset-me")
    monkeypatch.setattr(demo, "SANCTIO_URL", "http://sanctio.test")
    demo.store.reset()
    with SessionLocal() as db:
        seed(db, SETTINGS)
    site = TestClient(demo.app)
    connectors.transport = forward(site)                         # Sanctio -> SwiftShip action endpoint
    monkeypatch.setattr(demo, "sanctio_transport", forward(client))  # SwiftShip -> Sanctio sessions API
    return site


def signed(body: dict, secret: str = SETTINGS.webhook_secret, timestamp: int | None = None):
    raw = json.dumps(body).encode()
    ts = str(timestamp if timestamp is not None else int(time.time()))
    sig = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return raw, {"X-Sanctio-Timestamp": ts, "X-Sanctio-Signature": sig, "Content-Type": "application/json"}


def test_dm01_seed_creates_a_ready_business(client, swiftship):
    r = client.post("/api/auth/login", json={"email": "demo@swiftship.test", "password": "Passw0rd!23"})
    admin = {"Authorization": f"Bearer {r.json()['token']}"}
    assert [a["name"] for a in client.get("/api/admin/actions", headers=admin).json()][:2] == \
        ["list_shipments", "track_shipment"]
    assert len(client.get("/api/admin/knowledge", headers=admin).json()) == 4
    assert client.post("/api/v1/sessions", json={"customer_id": "C-1001"},
                       headers={"X-API-Key": SETTINGS.api_key}).status_code == 200


def test_dm02_customer_cancels_through_the_demo_site(client, swiftship):
    assert swiftship.post("/login", content="customer_id=C-1001",
                          headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 200
    page = swiftship.get("/account").text
    assert "http://sanctio.test/widget.js" in page and "Amina" in page
    token = re.search(r'sessionToken: "([^"]+)"', page).group(1)
    chat = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/v1/chat", json={"message": "Please cancel SHP-1002"}, headers=chat).json()
    assert r["action"]["decision"] == "awaiting_confirmation"
    assert client.post("/api/v1/chat", json={"message": "yes", "conversation_id": r["conversation_id"]},
                       headers=chat).json()["action"]["decision"] == "executed"
    shipments = {s["tracking_number"]: s["status"] for s in swiftship.get("/api/my-shipments").json()}
    assert shipments == {"SHP-1001": "in_transit", "SHP-1002": "cancelled", "SHP-1003": "delivered"}


def test_dm03_reseed_wipes_conversations_but_keeps_credentials(client, swiftship):
    token = client.post("/api/v1/sessions", json={"customer_id": "C-1001"},
                        headers={"X-API-Key": SETTINGS.api_key}).json()["session_token"]
    client.post("/api/v1/chat", json={"message": "Where is SHP-1001?"}, headers={"Authorization": f"Bearer {token}"})
    with SessionLocal() as db:
        assert db.query(Conversation).count() == 1
        seed(db, SETTINGS)
        assert db.query(Conversation).count() == 0
        assert db.query(Customer).filter_by(external_id="C-1001").one().phone == "+2348030000001"
    assert client.post("/api/v1/sessions", json={"customer_id": "C-1001"},
                       headers={"X-API-Key": SETTINGS.api_key}).status_code == 200


def test_dm04_action_endpoint_verifies_sanctio(swiftship):
    body = {"action": "cancel_shipment", "customer_id": "C-1001", "params": {"tracking_number": "SHP-1002"},
            "dry_run": False}
    raw, headers = signed(body, secret="wrong")
    assert swiftship.post("/sanctio", content=raw, headers=headers).status_code == 401
    raw, headers = signed(body, timestamp=int(time.time()) - 3600)  # replayed old request
    assert swiftship.post("/sanctio", content=raw, headers=headers).status_code == 401
    assert demo.store.shipments["SHP-1002"]["status"] == "pending_pickup"
    raw, headers = signed({**body, "customer_id": "C-1002"})  # someone else's shipment
    assert swiftship.post("/sanctio", content=raw, headers=headers).json()["ok"] is False


def test_dm05_reset_needs_the_token(swiftship):
    demo.store.shipments["SHP-1002"]["status"] = "cancelled"
    assert swiftship.post("/demo/reset", headers={"X-Demo-Token": "guess"}).status_code == 403
    assert swiftship.post("/demo/reset", headers={"X-Demo-Token": "reset-me"}).status_code == 200
    assert demo.store.shipments["SHP-1002"]["status"] == "pending_pickup"
