"""Bella Wears, the WhatsApp shop demo (demo_business/shop.py), wired to Sanctio in-process."""
import pytest
from fastapi.testclient import TestClient

from app import connectors
from app.db import SessionLocal
from app.models import Business, Customer, WhatsAppNumber
from scripts.seed_demo import Settings, seed

from .test_demo import SETTINGS, demo, forward, signed
from .test_whatsapp import PNID, WhatsApp, graph  # noqa: F401  (graph is a fixture)

SHOP = demo.shop.shop
BUYER, OTHER = "2348031112222", "2348033334444"
WA_SETTINGS = Settings(**{**SETTINGS.__dict__, "whatsapp_phone_number_id": PNID})


@pytest.fixture()
def bella(client, monkeypatch, graph):  # noqa: F811
    monkeypatch.setattr(demo, "WEBHOOK_SECRET", SETTINGS.webhook_secret)
    monkeypatch.setattr(demo.shop, "DEMO_WEBHOOK_SECRET", SETTINGS.webhook_secret)
    demo.store.reset()
    SHOP.reset()
    with SessionLocal() as db:
        seed(db, WA_SETTINGS)
    site = TestClient(demo.app)
    connectors.transport = forward(site)
    return WhatsApp(client, graph)


def order(customer: str, **params) -> dict:
    p = {"product": "BW-101", "size": "L", "quantity": 2, "delivery_address": "12 Zoo Road, Kano", **params}
    return SHOP.run("place_order", customer, p, dry_run=False)


# ---- the shop's own rules ----

def test_sh01_order_dry_run_changes_nothing_and_quotes_the_total():
    SHOP.reset()
    r = SHOP.run("place_order", "WA-1", {"product": "black kaftan", "size": "l", "quantity": 2,
                                         "delivery_address": "12 Zoo Road, Kano"}, dry_run=True)
    assert r["ok"] and r["amount"] == 2 * 18500 + 2500
    assert SHOP.orders == {} and SHOP.stock["BW-101"] == 6


def test_sh02_order_checks_size_stock_and_ambiguous_names():
    SHOP.reset()
    assert "comes in M, L, XL" in order("WA-1", size="S")["error"]
    assert "out of stock" in order("WA-1", product="fila cap", size="")["error"]
    assert "only 3" in order("WA-1", product="BW-102", size="XL", quantity=4)["error"]
    assert "Which one" in order("WA-1", product="black")["error"]  # black kaftan or black abaya
    placed = order("WA-1")
    assert placed["data"]["order_number"] == "ORD-1001" and SHOP.stock["BW-101"] == 4


def test_sh03_customers_only_see_their_own_orders():
    SHOP.reset()
    order("WA-1")
    assert SHOP.run("track_order", "WA-2", {"order_number": "ORD-1001"}, False)["ok"] is False
    assert SHOP.run("cancel_order", "WA-2", {"order_number": "ORD-1001"}, False)["ok"] is False
    assert SHOP.orders["ORD-1001"]["status"] == "processing"


def test_sh04_cancel_only_before_dispatch_and_return_only_after_delivery():
    SHOP.reset()
    order("WA-1")
    assert SHOP.run("request_return", "WA-1", {"order_number": "ORD-1001"}, True)["ok"] is False
    SHOP.advance("ORD-1001")  # owner dispatches
    assert "can't be cancelled" in SHOP.run("cancel_order", "WA-1", {"order_number": "ORD-1001"}, True)["error"]
    SHOP.advance("ORD-1001")  # delivered
    r = SHOP.run("request_return", "WA-1", {"order_number": "ORD-1001", "reason": "too small"}, False)
    assert r["ok"] and r["amount"] == 37000 and SHOP.orders["ORD-1001"]["status"] == "returned"


def test_sh05_shop_endpoint_needs_the_shop_signature(bella):
    site = TestClient(demo.app)
    body = {"action": "list_products", "customer_id": "WA-1", "params": {}, "dry_run": True}
    raw, headers = signed(body)  # SwiftShip's secret is not the shop's
    assert site.post("/shop/sanctio", content=raw, headers=headers).status_code == 401
    raw, headers = signed(body, secret=demo.shop.shop_secret(SETTINGS.webhook_secret))
    assert site.post("/shop/sanctio", content=raw, headers=headers).json()["ok"] is True


# ---- seeding ----

def test_sh06_seed_creates_the_shop_and_connects_whatsapp_to_it(client, bella):
    r = client.post("/api/auth/login", json={"email": "owner@bellawears.test", "password": SETTINGS.admin_password})
    owner = {"Authorization": f"Bearer {r.json()['token']}"}
    names = [a["name"] for a in client.get("/api/admin/actions", headers=owner).json()]
    assert "place_order" in names and "track_shipment" not in names
    status = client.get("/api/admin/whatsapp/status", headers=owner).json()
    assert status["open_to_new_customers"] is True
    assert [n["phone_number_id"] for n in status["numbers"]] == [PNID]


def test_sh07_reset_keeps_numbers_and_phones_linked_on_the_dashboard(client, bella):
    r = client.post("/api/auth/login", json={"email": "demo@swiftship.test", "password": SETTINGS.admin_password})
    admin = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.post("/api/admin/whatsapp/link", headers=admin,
                       json={"customer_id": "C-1002", "phone": "+2348030000002"}).status_code == 200
    assert client.post("/api/admin/whatsapp/numbers", headers=admin,
                       json={"phone_number_id": "200000000000002"}).status_code == 200
    with SessionLocal() as db:
        seed(db, WA_SETTINGS)
        swiftship = db.query(Business).filter_by(name="SwiftShip Logistics").one()
        assert db.query(Customer).filter_by(business_id=swiftship.id, external_id="C-1002").one().phone == "+2348030000002"
        assert db.query(WhatsAppNumber).filter_by(phone_number_id="200000000000002").one().business_id == swiftship.id


# ---- over WhatsApp ----

def test_sh08_new_number_is_registered_and_can_cancel_its_order(bella):
    bella.send(BUYER, "hello")
    with SessionLocal() as db:
        customer = db.query(Customer).filter_by(external_id="WA-" + BUYER).one()
        assert customer.phone == "+" + BUYER and customer.name == "Test"
    order("WA-" + BUYER)
    assert "processing" in bella.send(BUYER, "where is ORD-1001?")
    bella.send(BUYER, "please cancel ORD-1001")
    bella.tap(BUYER, bella.buttons(BUYER)["Confirm"])
    assert SHOP.orders["ORD-1001"]["status"] == "cancelled" and SHOP.stock["BW-101"] == 6


def test_sh09_another_number_cannot_touch_the_order(bella):
    order("WA-" + BUYER)
    reply = bella.send(OTHER, "cancel ORD-1001")
    assert SHOP.orders["ORD-1001"]["status"] == "processing"
    assert "Order not found for this WhatsApp number" in reply


def test_sh10_closed_business_still_ignores_unknown_numbers(client, bella):
    r = client.post("/api/auth/login", json={"email": "owner@bellawears.test", "password": SETTINGS.admin_password})
    owner = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.put("/api/admin/whatsapp/settings", headers=owner,
                      json={"open_to_new_customers": False}).json() == {"open_to_new_customers": False}
    bella.send(BUYER, "hello")
    with SessionLocal() as db:
        assert db.query(Customer).filter_by(external_id="WA-" + BUYER).first() is None
