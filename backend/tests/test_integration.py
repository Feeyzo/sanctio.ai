"""Integration and system tests through the HTTP API."""
from app.db import SessionLocal
from app.models import Order

from .conftest import Chat


def order(ref):
    with SessionLocal() as db:
        return db.query(Order).filter_by(order_ref=ref).first()


# ---- authentication ----
def test_it01_chat_requires_api_key_and_session(client):
    assert client.post("/api/v1/chat", json={"message": "hi"}).status_code == 401
    assert client.post("/api/v1/chat", json={"message": "hi"}, headers={"X-API-Key": "wrong"}).status_code == 401


def test_it02_revoked_session_rejected(client, chat):
    chat.say("hi")
    client.delete("/api/v1/sessions", headers=chat.headers)
    r = client.post("/api/v1/chat", json={"message": "hi"}, headers=chat.headers)
    assert r.status_code == 401


# ---- order tracking & troubleshooting ----
def test_it03_track_order(chat):
    r = chat.say("Where is my order ORD-10021?")
    assert r["action"]["decision"] == "executed" and "processing" in r["reply"]


def test_it04_guided_troubleshooting(chat):
    r = chat.say("Money was deducted from my account but I have no order")
    assert r["action"]["name"] == "get_troubleshooting_steps" and "24 hours" in r["reply"]


# ---- verified action execution with confirmation ----
def test_it05_cancel_with_confirmation(chat):
    r = chat.say("Please cancel order ORD-10023")
    assert r["action"]["decision"] == "awaiting_confirmation"
    assert order("ORD-10023").status == "pending"  # nothing changed yet
    r = chat.say("yes")
    assert r["action"]["decision"] == "executed"
    assert order("ORD-10023").status == "cancelled"


def test_it06_customer_can_decline(chat):
    chat.say("cancel ORD-10023")
    r = chat.say("no")
    assert r["action"]["decision"] == "declined_by_customer" and order("ORD-10023").status == "pending"


def test_it07_address_change(chat):
    chat.say("Change the address for ORD-10021 to 4 Murtala Mohammed Way, Kano")
    chat.say("yes")
    assert order("ORD-10021").shipping_address == "4 Murtala Mohammed Way, Kano"


def test_it08_small_refund_executes(chat):
    chat.say("The earbuds in ORD-10022 arrived damaged, I want a refund")
    r = chat.say("confirm")
    assert r["action"]["decision"] == "executed" and order("ORD-10022").status == "refunded"


# ---- human handoff ----
def test_it09_large_refund_goes_to_human_and_admin_approves(client, admin):
    c = Chat(client, "C-1003")
    r = c.say("The office chair ORD-10041 is broken, refund me")
    assert r["action"]["decision"] == "pending_approval"
    assert "action_requires_human_approval" in r["handoff"]["reasons"]
    pending = client.get("/api/admin/approvals", headers=admin).json()
    assert len(pending) == 1
    client.post(f"/api/admin/approvals/{pending[0]['id']}/approve", headers=admin)
    assert order("ORD-10041").status == "refunded"


def test_it10_angry_customer_handed_off(chat):
    r = chat.say("This is TERRIBLE!!! You people are useless, I am so angry")
    assert r["handoff"] and "strong_negative_sentiment" in r["handoff"]["reasons"]
    assert r["status"] == "handed_off"
    # after handoff the AI no longer acts
    r = chat.say("cancel ORD-10023")
    assert r["action"] is None and order("ORD-10023").status == "pending"


def test_it11_explicit_human_request(chat):
    r = chat.say("I want to speak to a human")
    assert "customer_requested_human" in r["handoff"]["reasons"]


def test_it12_repeated_failure_handoff(chat):
    chat.say("My delivery is late")
    r = chat.say("That didn't help, still not working")
    assert r["handoff"] is None
    r = chat.say("Still not working, same problem")
    assert r["handoff"] and "unsuccessful_resolution" in r["handoff"]["reasons"]


def test_it13_handoff_summary_visible_to_admin(client, admin, chat):
    chat.say("I want to speak to a human")
    h = client.get("/api/admin/handoffs", headers=admin).json()[0]
    assert "Amina Yusuf" in h["summary"] and h["status"] == "open"


# ---- admin ----
def test_it14_admin_login_required(client):
    assert client.get("/api/admin/stats").status_code == 401
    assert client.post("/api/admin/login", json={"email": "admin@shopdemo.ng", "password": "bad"}).status_code == 401


def test_it15_dashboard_stats(client, admin, chat):
    chat.say("Where is ORD-10021")
    chat.say("thank you")
    s = client.get("/api/admin/stats", headers=admin).json()
    assert s["total_conversations"] == 1 and s["ai_resolution_rate"] == 100.0
